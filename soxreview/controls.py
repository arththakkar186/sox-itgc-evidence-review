"""Deterministic control tests. Every attribute is a plain, explainable check.

AC-01  Access provisioning       in-scope grants are approved by an authorised person before provisioning
AC-02  Terminations              leavers are disabled within the time limit, with a leaver ticket
AC-03  Emergency access          break-glass grants have a P1/P2 incident, retro approval <= 48h, removal <= 7 days
"""
from __future__ import annotations

from datetime import timedelta

from .ingest import Population
from .llm import Reviewer
from .minimize import Pseudonymizer, approval_question
from .models import EXCEPTION, NEEDS_REVIEW, PASS, Attribute, TestResult, parse_ts

DISABLE_LIMIT = {"voluntary": timedelta(hours=24), "involuntary": timedelta(hours=4)}
RETRO_APPROVAL_LIMIT = timedelta(hours=48)
EMERGENCY_REMOVAL_LIMIT = timedelta(days=7)


def in_period(ts: str, period: str) -> bool:
    return (ts or "").startswith(period)


def finish(r: TestResult) -> TestResult:
    """Set result from attributes unless an LLM step already routed it."""
    if r.result == NEEDS_REVIEW:
        return r
    failed = r.failed()
    r.result = r.recommendation = EXCEPTION if failed else PASS
    r.rationale = "; ".join(f"{a.name}: {a.detail}" for a in failed) if failed else "All attributes met."
    return r


# --------------------------------------------------------------------------- AC-01

def test_ac01(pop: Population, period: str, reviewer: Reviewer | None, pz: Pseudonymizer,
              llm_log: list[dict]) -> list[TestResult]:
    users, groups, ritms = pop.users_by_id, pop.groups_by_id, pop.ritms_by_number
    out = []
    for ev in pop.access_events:
        g = groups.get(ev["group_id"])
        if ev["action"] != "add_member" or not g or g["sox_in_scope"] != "true" or not in_period(ev["timestamp"], period):
            continue
        if ev["source_ticket"].startswith("INC"):
            continue  # emergency access is tested by AC-03
        r = TestResult("AC-01", ev["event_id"], evidence_refs=[f"audit:{ev['event_id']}"])
        grant = parse_ts(ev["timestamp"])
        ritm = ritms.get(ev["source_ticket"])
        r.attributes.append(Attribute("A1 request ticket exists", ritm is not None,
                                      ritm["number"] if ritm else "no ticket referenced by the change"))
        if not ritm:
            out.append(finish(r))
            continue
        r.evidence_refs.append(f"servicenow:{ritm['number']}")
        match = ritm["requested_for"] == ev["target_user_id"] and ritm["group_id"] == ev["group_id"]
        r.attributes.append(Attribute("A2 ticket matches the change", match,
                                      "user and group match" if match else
                                      f"ticket is for {ritm['requested_for']}/{ritm['group_id']}, change was {ev['target_user_id']}/{ev['group_id']}"))
        authorized = {users.get(ev["target_user_id"], {}).get("manager_id"), g["owner_id"]} - {"", None}

        if ritm["approval"] == "approved" and ritm["approved_at"]:
            approved = parse_ts(ritm["approved_at"])
            approver = ritm["approver_id"]
            r.attributes += [
                Attribute("A3 approval recorded", True, f"approved by {approver} at {ritm['approved_at']}"),
                Attribute("A4 approved before provisioning", approved <= grant,
                          f"approved {ritm['approved_at']}, granted {ev['timestamp']}"),
                Attribute("A5 segregation of duties", approver not in (ev["target_user_id"], ev["performed_by"]),
                          "approver is neither the recipient nor the fulfiller" if approver not in (ev["target_user_id"], ev["performed_by"])
                          else f"approver {approver} is also the {'recipient' if approver == ev['target_user_id'] else 'fulfiller'}"),
                Attribute("A6 approver is authorised", approver in authorized,
                          "manager or group owner" if approver in authorized else f"{approver} is not the manager or the group owner"),
            ]
            out.append(finish(r))
            continue

        # Structured approval missing: read the notes.
        r.attributes.append(Attribute("A3 approval recorded", None,
                                      f"structured approval field is '{ritm['approval']}'; notes reviewed"))
        if reviewer is None:
            r.result, r.recommendation = NEEDS_REVIEW, EXCEPTION
            r.rationale = "Structured approval missing and no reviewer configured; tester must read the notes."
            out.append(r)
            continue
        payload = approval_question(ev["event_id"], ritm, ev, g, users, pz)
        f = reviewer.review(payload)
        f.quote_verified = bool(f.quote) and f.quote in payload["notes"]
        llm_log.append({"item_id": ev["event_id"], "reviewer": f.reviewer, "payload": payload, "finding": f.__dict__})
        r.llm = f
        r.evidence_refs.append(f"llm:{ev['event_id']}")
        out.append(reconcile_llm(r, f, payload, grant, {pz.pid(a) for a in authorized}))
    return out


def reconcile_llm(r: TestResult, f, payload: dict, grant, authorized_pids: set[str]) -> TestResult:
    """Turn extracted facts into a recommendation. A person always confirms."""
    checks = []
    if f.approval_evidence_found:
        t = parse_ts(f.approval_time) if f.approval_time else None
        checks = [
            Attribute("L1 quote found verbatim in notes", f.quote_verified, "quote verified" if f.quote_verified else "quote not found in notes"),
            Attribute("L2 approver is authorised", f.approver in authorized_pids, f"{f.approver} ({f.approver_role})"),
            Attribute("L3 approval dated before provisioning", t is not None and t <= grant,
                      f"approval {f.approval_time}, granted {payload['access_granted']['granted_at']}"),
        ]
    r.attributes += checks
    recommend_pass = f.approval_evidence_found and all(c.passed for c in checks)
    r.result = NEEDS_REVIEW
    r.recommendation = PASS if recommend_pass else EXCEPTION
    r.rationale = (f"Notes evidence approval ({f.reviewer}): {f.rationale} Tester to confirm against the attachment."
                   if recommend_pass else
                   f"No acceptable approval evidence ({f.reviewer}): {f.rationale}"
                   + ("" if not checks else " Failed: " + ", ".join(c.name for c in checks if not c.passed)))
    return r


# --------------------------------------------------------------------------- AC-02

def test_ac02(pop: Population, period: str) -> list[TestResult]:
    out = []
    leaver_tickets = {r["requested_for"]: r for r in pop.ritms if r["catalog_item"] == "Leaver Offboarding"}
    disables = {}
    for ev in pop.access_events:
        if ev["action"] == "disable_account":
            disables.setdefault(ev["target_user_id"], []).append(ev)
    for u in pop.users:
        if u["status"] != "terminated" or not in_period(u["termination_at"], period):
            continue
        r = TestResult("AC-02", u["user_id"], evidence_refs=[f"hr:{u['user_id']}"])
        term = parse_ts(u["termination_at"])
        limit = DISABLE_LIMIT.get(u["termination_type"], timedelta(hours=24))
        evs = sorted(disables.get(u["user_id"], []), key=lambda e: e["timestamp"])
        first = evs[0] if evs else None
        r.attributes.append(Attribute("B1 account disabled", first is not None,
                                      first["timestamp"] if first else "no disable event"))
        if first:
            r.evidence_refs.append(f"audit:{first['event_id']}")
            lag = parse_ts(first["timestamp"]) - term
            hours = lag.total_seconds() / 3600
            r.attributes.append(Attribute("B2 disabled within limit", lag <= limit,
                                          f"{hours:.1f}h after termination (limit {limit.total_seconds() / 3600:.0f}h, {u['termination_type']})"))
        t = leaver_tickets.get(u["user_id"])
        r.attributes.append(Attribute("B3 leaver ticket", t is not None, t["number"] if t else "no leaver ticket"))
        if t:
            r.evidence_refs.append(f"servicenow:{t['number']}")
        out.append(finish(r))
    return out


# --------------------------------------------------------------------------- AC-03

def test_ac03(pop: Population, period: str) -> list[TestResult]:
    out = []
    groups, incs = pop.groups_by_id, pop.incidents_by_number
    removals = [e for e in pop.access_events if e["action"] == "remove_member"]
    for ev in pop.access_events:
        if ev["action"] != "add_member" or not ev["source_ticket"].startswith("INC") or not in_period(ev["timestamp"], period):
            continue
        g = groups.get(ev["group_id"], {})
        r = TestResult("AC-03", ev["event_id"], evidence_refs=[f"audit:{ev['event_id']}"])
        grant = parse_ts(ev["timestamp"])
        inc = incs.get(ev["source_ticket"])
        ok = inc is not None and inc["priority"][:1] in ("1", "2")
        r.attributes.append(Attribute("C1 P1/P2 incident", ok, f"{inc['number']} priority {inc['priority']}" if inc else "incident not found"))
        if inc:
            r.evidence_refs.append(f"servicenow:{inc['number']}")
            ra = parse_ts(inc["retro_approved_at"]) if inc["retro_approved_at"] else None
            good = ra is not None and ra - grant <= RETRO_APPROVAL_LIMIT and inc["retro_approver_id"] == g.get("owner_id")
            r.attributes.append(Attribute("C2 retrospective owner approval <= 48h", good,
                                          f"approved by {inc['retro_approver_id']} at {inc['retro_approved_at']}" if ra else "no retrospective approval"))
        rem = next((e for e in sorted(removals, key=lambda e: e["timestamp"])
                    if e["target_user_id"] == ev["target_user_id"] and e["group_id"] == ev["group_id"]
                    and parse_ts(e["timestamp"]) >= grant), None)
        removed_ok = rem is not None and parse_ts(rem["timestamp"]) - grant <= EMERGENCY_REMOVAL_LIMIT
        r.attributes.append(Attribute("C3 access removed <= 7 days", removed_ok,
                                      f"removed {rem['timestamp']}" if rem else "no removal event"))
        out.append(finish(r))
    return out


def run_all(pop: Population, period: str, reviewer: Reviewer | None, salt: str) -> tuple[list[TestResult], list[dict], Pseudonymizer]:
    pz = Pseudonymizer(salt, pop.users_by_id)
    llm_log: list[dict] = []
    results = test_ac01(pop, period, reviewer, pz, llm_log) + test_ac02(pop, period) + test_ac03(pop, period)
    return results, llm_log, pz
