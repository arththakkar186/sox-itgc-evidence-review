#!/usr/bin/env python3
"""Generate a fictional, seeded dataset for one monthly SOX ITGC access-control test cycle.

Nothing here comes from a real company. Names are built from generic word lists,
e-mail addresses use example.com, and the "known exceptions" are injected on
purpose so the pipeline's results can be checked against a ground truth.

    python3 scripts/generate_synthetic.py --out data/synthetic --period 2026-10 --seed 7

Outputs (CSV): users, groups, access_events, ritms, incidents, manual_review
"""
from __future__ import annotations

import argparse
import csv
import random
from datetime import datetime, timedelta
from pathlib import Path

FIRST = ["Avery", "Blake", "Casey", "Devon", "Emery", "Finley", "Harper", "Jordan", "Kendall", "Logan",
         "Morgan", "Noel", "Parker", "Quinn", "Reese", "Rowan", "Sage", "Taylor", "Val", "Wren",
         "Alex", "Billie", "Cameron", "Drew", "Elliot", "Frankie", "Hayden", "Jesse", "Kai", "Lane"]
LAST = ["Abbott", "Barlow", "Carver", "Dalton", "Ellis", "Fenwick", "Garrow", "Hollis", "Ingram", "Jarvis",
        "Keeling", "Lowry", "Marsh", "Norwood", "Oakes", "Pryor", "Quarles", "Radley", "Sutter", "Thorne",
        "Upton", "Vance", "Whitlock", "Yardley", "Ashby", "Brook", "Colby", "Darrow", "Easton", "Fairley"]
DEPTS = ["Finance", "Accounting", "Payroll", "IT Operations", "Engineering", "Sales", "HR", "Procurement"]

GROUPS = [
    # group_id, name, application, privileged, sox_in_scope
    ("G01", "ERP-GL-Posting", "ERP (General Ledger)", False, True),
    ("G02", "ERP-Journal-Approver", "ERP (General Ledger)", True, True),
    ("G03", "ERP-AP-Payments", "ERP (Accounts Payable)", False, True),
    ("G04", "ERP-Vendor-Master", "ERP (Accounts Payable)", True, True),
    ("G05", "Payroll-Admin", "Payroll", True, True),
    ("G06", "Payroll-Viewer", "Payroll", False, True),
    ("G07", "AD-Domain-Admins", "Active Directory", True, True),
    ("G08", "Entra-Privileged-Role-Admin", "Microsoft Entra ID", True, True),
    ("G09", "DB-Finance-DBA", "Finance database", True, True),
    ("G10", "Teams-Marketing", "Microsoft 365", False, False),
    ("G11", "SharePoint-Sales", "Microsoft 365", False, False),
]


def iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M")


def write(path: Path, rows: list[dict]):
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def generate(out: Path, period: str, seed: int) -> dict:
    rnd = random.Random(seed)
    year, month = map(int, period.split("-"))
    start = datetime(year, month, 1, 8, 0)
    days_in_month = ((datetime(year + (month == 12), month % 12 + 1, 1) - datetime(year, month, 1)).days)

    def when(day_lo=1, day_hi=None) -> datetime:
        day_hi = day_hi or days_in_month - 2
        return start + timedelta(days=rnd.randint(day_lo - 1, day_hi - 1), hours=rnd.randint(0, 9), minutes=rnd.randint(0, 59))

    # ---------------------------------------------------------------- users
    users, used = [], set()
    for i in range(1, 301):
        while True:
            name = f"{rnd.choice(FIRST)} {rnd.choice(LAST)}"
            if name not in used:
                used.add(name)
                break
        users.append({"user_id": f"U{i:04d}", "display_name": name,
                      "email": name.lower().replace(" ", ".") + "@example.com",
                      "department": rnd.choice(DEPTS), "manager_id": "", "status": "active",
                      "termination_at": "", "termination_type": ""})
    managers = users[:25]
    for u in users[25:]:
        u["manager_id"] = rnd.choice(managers)["user_id"]
    for m in managers:
        m["manager_id"] = "U0001" if m["user_id"] != "U0001" else ""
    by_id = {u["user_id"]: u for u in users}
    it_staff = [u["user_id"] for u in users[25:45]]          # fulfillers
    for uid in it_staff:
        by_id[uid]["department"] = "IT Operations"

    groups = []
    for gid, name, app, priv, scope in GROUPS:
        groups.append({"group_id": gid, "name": name, "application": app, "privileged": str(priv).lower(),
                       "sox_in_scope": str(scope).lower(), "owner_id": rnd.choice(managers)["user_id"]})
    gby = {g["group_id"]: g for g in groups}
    in_scope = [g["group_id"] for g in groups if g["sox_in_scope"] == "true"]

    events, ritms, incidents, manual = [], [], [], []
    ev_n, ritm_n, inc_n = [0], [1000], [5000]

    def new_event(**kw):
        ev_n[0] += 1
        e = {"event_id": f"EV{ev_n[0]:05d}", "timestamp": "", "action": "", "target_user_id": "",
             "group_id": "", "performed_by": "", "source_ticket": ""}
        e.update(kw)
        events.append(e)
        return e

    def new_ritm(**kw):
        ritm_n[0] += 1
        r = {"number": f"RITM{ritm_n[0]:07d}", "catalog_item": "Access Request", "opened_at": "",
             "requested_by": "", "requested_for": "", "group_id": "", "approval": "approved",
             "approver_id": "", "approved_at": "", "fulfilled_by": "", "closed_at": "",
             "state": "Closed Complete", "work_notes": ""}
        r.update(kw)
        ritms.append(r)
        return r

    def name(uid):
        return by_id[uid]["display_name"]

    # ---------------------------------------------------------------- AC-01 access grants
    scenarios = (["clean"] * 118 + ["no_ticket"] * 3 + ["approved_after"] * 2 + ["self_approved"] * 2
                 + ["unauthorized_approver"] * 2 + ["wrong_user_on_ticket"] * 1
                 + ["notes_valid"] * 4 + ["notes_verbal"] * 1 + ["notes_after_grant"] * 1)
    rnd.shuffle(scenarios)
    for sc in scenarios:
        target = rnd.choice(users[45:])["user_id"]
        gid = rnd.choice(in_scope)
        fulfiller = rnd.choice(it_staff)
        opened = when(1, days_in_month - 4)
        approved = opened + timedelta(hours=rnd.randint(1, 20))
        grant = approved + timedelta(hours=rnd.randint(1, 30))
        approver = rnd.choice([by_id[target]["manager_id"], gby[gid]["owner_id"]])
        r = dict(opened_at=iso(opened), requested_by=target, requested_for=target, group_id=gid,
                 approver_id=approver, approved_at=iso(approved), fulfilled_by=fulfiller,
                 closed_at=iso(grant + timedelta(minutes=20)),
                 work_notes=f"Access added to {gby[gid]['name']} by {name(fulfiller)}. Closing.")
        truth, note = "PASS", "Approved by authorized approver before provisioning"
        if sc == "approved_after":
            r["approved_at"] = iso(grant + timedelta(hours=rnd.randint(2, 30)))
            truth, note = "EXCEPTION", "Approval recorded after access was granted"
        elif sc == "self_approved":
            r["approver_id"] = target
            truth, note = "EXCEPTION", "Requester approved their own access (SoD)"
        elif sc == "unauthorized_approver":
            others = [m["user_id"] for m in managers if m["user_id"] not in (by_id[target]["manager_id"], gby[gid]["owner_id"])]
            r["approver_id"] = rnd.choice(others)
            truth, note = "EXCEPTION", "Approver is neither the user's manager nor the group owner"
        elif sc.startswith("notes_"):
            mgr = by_id[target]["manager_id"]
            r.update(approval="not requested", approver_id="", approved_at="")
            if sc == "notes_valid":
                t = opened + timedelta(hours=rnd.randint(1, 5))
                grant = max(grant, t + timedelta(hours=2))
                r["work_notes"] = (f"Catalog approval step skipped (form error). {name(mgr)} (manager) approved by email "
                                   f"on {iso(t)}; email attached to this RITM. Access added to {gby[gid]['name']} by "
                                   f"{name(fulfiller)} after approval. Contact {by_id[mgr]['email']} with questions.")
                truth, note = "PASS", "Approval evidenced by attached manager e-mail dated before provisioning"
            elif sc == "notes_verbal":
                r["work_notes"] = (f"{name(mgr)} said it was fine on a call, no written approval. "
                                   f"Added to {gby[gid]['name']}. Call 905-555-0142 if issues.")
                truth, note = "EXCEPTION", "Verbal approval only; no documented approval"
            else:
                t = grant + timedelta(hours=rnd.randint(3, 24))
                r["work_notes"] = (f"Access added to {gby[gid]['name']} urgently. {name(mgr)} (manager) approved by email "
                                   f"on {iso(t)}; email attached.")
                truth, note = "EXCEPTION", "Documented approval is dated after provisioning"
        r["closed_at"] = iso(grant + timedelta(minutes=20))
        ticket = new_ritm(**r)
        if sc == "wrong_user_on_ticket":
            other = rnd.choice(users[45:])["user_id"]
            ticket["requested_for"] = other
            ticket["requested_by"] = other
            truth, note = "EXCEPTION", "Ticket was raised for a different user than the one granted access"
        src = "" if sc == "no_ticket" else ticket["number"]
        if sc == "no_ticket":
            ritms.remove(ticket)
            truth, note = "EXCEPTION", "No request ticket for the access change"
        e = new_event(timestamp=iso(grant), action="add_member", target_user_id=target, group_id=gid,
                      performed_by=fulfiller, source_ticket=src)
        manual.append({"control_id": "AC-01", "item_id": e["event_id"], "conclusion": truth, "tester_note": note})

    # out-of-scope noise (must be ignored by the population filter)
    for _ in range(40):
        target = rnd.choice(users[45:])["user_id"]
        new_event(timestamp=iso(when()), action="add_member", target_user_id=target,
                  group_id=rnd.choice(["G10", "G11"]), performed_by=rnd.choice(it_staff), source_ticket="")

    # ---------------------------------------------------------------- AC-02 terminations
    leavers = rnd.sample(users[45:], 36)
    late = set(u["user_id"] for u in leavers[:3])
    no_ticket = leavers[3]["user_id"]
    for u in leavers:
        ttype = rnd.choice(["voluntary"] * 4 + ["involuntary"])
        term = when(1, days_in_month - 3).replace(hour=17, minute=0) if ttype == "voluntary" else when(1, days_in_month - 3)
        u.update(status="terminated", termination_at=iso(term), termination_type=ttype)
        limit = timedelta(hours=24 if ttype == "voluntary" else 4)
        delay = timedelta(hours=rnd.randint(30, 96)) if u["user_id"] in late else timedelta(minutes=rnd.randint(5, int(limit.total_seconds() // 60) - 30))
        fulfiller = rnd.choice(it_staff)
        lt = None
        if u["user_id"] != no_ticket:
            lt = new_ritm(catalog_item="Leaver Offboarding", opened_at=iso(term - timedelta(days=rnd.randint(0, 5))),
                          requested_by=u["manager_id"], requested_for=u["user_id"], approval="not required",
                          fulfilled_by=fulfiller, closed_at=iso(term + delay + timedelta(minutes=15)),
                          work_notes="Account disabled, sessions revoked, groups removed, manager notified.")
        new_event(timestamp=iso(term + delay), action="disable_account", target_user_id=u["user_id"],
                  performed_by=fulfiller, source_ticket=lt["number"] if lt else "")
        if u["user_id"] in late:
            truth, note = "EXCEPTION", f"Account disabled {int(delay.total_seconds() // 3600)}h after termination (limit {int(limit.total_seconds() // 3600)}h)"
        elif u["user_id"] == no_ticket:
            truth, note = "EXCEPTION", "Account disabled on time but no leaver ticket documents the removal"
        else:
            truth, note = "PASS", "Disabled within the required window with a leaver ticket"
        manual.append({"control_id": "AC-02", "item_id": u["user_id"], "conclusion": truth, "tester_note": note})

    # ---------------------------------------------------------------- AC-03 emergency access
    emerg = ["clean"] * 4 + ["no_retro"] + ["not_revoked"]
    for sc in emerg:
        target = rnd.choice(it_staff)
        gid = rnd.choice(["G07", "G08", "G09"])
        opened = when(1, days_in_month - 10)
        grant = opened + timedelta(minutes=rnd.randint(10, 60))
        inc_n[0] += 1
        inc = {"number": f"INC{inc_n[0]:07d}", "opened_at": iso(opened), "priority": rnd.choice(["1 - Critical", "2 - High"]),
               "caller_id": target, "short_description": f"Production outage requiring {gby[gid]['name']} break-glass access",
               "retro_approver_id": gby[gid]["owner_id"], "retro_approved_at": iso(grant + timedelta(hours=rnd.randint(2, 30))),
               "closed_at": iso(grant + timedelta(hours=6)), "work_notes": "Emergency access used to restore service."}
        truth, note = "PASS", "P1/P2 incident, owner approved within 48h, access removed within 7 days"
        if sc == "no_retro":
            inc.update(retro_approver_id="", retro_approved_at="")
            truth, note = "EXCEPTION", "No retrospective approval recorded for emergency access"
        incidents.append(inc)
        helper = rnd.choice(it_staff)
        e = new_event(timestamp=iso(grant), action="add_member", target_user_id=target, group_id=gid,
                      performed_by=helper, source_ticket=inc["number"])
        if sc != "not_revoked":
            new_event(timestamp=iso(grant + timedelta(hours=rnd.randint(4, 72))), action="remove_member",
                      target_user_id=target, group_id=gid, performed_by=helper, source_ticket=inc["number"])
        else:
            truth, note = "EXCEPTION", "Emergency access still active after 7 days"
        manual.append({"control_id": "AC-03", "item_id": e["event_id"], "conclusion": truth, "tester_note": note})

    events.sort(key=lambda e: e["timestamp"])
    out.mkdir(parents=True, exist_ok=True)
    write(out / "users.csv", users)
    write(out / "groups.csv", groups)
    write(out / "access_events.csv", events)
    write(out / "ritms.csv", ritms)
    write(out / "incidents.csv", incidents)
    write(out / "manual_review.csv", manual)
    return {"users": len(users), "events": len(events), "ritms": len(ritms), "incidents": len(incidents),
            "manual_conclusions": len(manual),
            "manual_exceptions": sum(1 for m in manual if m["conclusion"] == "EXCEPTION")}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--out", default="data/synthetic")
    p.add_argument("--period", default="2026-10")
    p.add_argument("--seed", type=int, default=7)
    a = p.parse_args(argv)
    stats = generate(Path(a.out), a.period, a.seed)
    for k, v in stats.items():
        print(f"{k:>20}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
