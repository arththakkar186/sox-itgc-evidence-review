from __future__ import annotations

import copy
import hashlib
import io
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import generate_synthetic  # noqa: E402
from soxreview.controls import reconcile_llm, run_all, test_ac01, test_ac02  # noqa: E402
from soxreview.evidence import write_pack  # noqa: E402
from soxreview.ingest import CsvSource, ServiceNowSource  # noqa: E402
from soxreview.llm import ClaudeReviewer, OfflineReviewer  # noqa: E402
from soxreview.minimize import Pseudonymizer  # noqa: E402
from soxreview.models import EXCEPTION, NEEDS_REVIEW, PASS, LLMFinding, TestResult, parse_ts  # noqa: E402
from soxreview.pilot import cohen_kappa, compare, load_manual  # noqa: E402

PERIOD = "2026-10"


class Fixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.data = Path(cls.tmp.name) / "data"
        generate_synthetic.generate(cls.data, PERIOD, seed=7)
        cls.pop = CsvSource(cls.data).load()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def fresh(self):
        return copy.deepcopy(self.pop)


class TestEndToEnd(Fixture):
    def test_offline_pipeline_matches_manual_review(self):
        results, log, _ = run_all(self.pop, PERIOD, OfflineReviewer(), "test-salt")
        pilot = compare(results, load_manual(self.data / "manual_review.csv"))
        self.assertEqual(pilot["missing_in_tool"], 0)
        self.assertEqual(pilot["missing_in_manual"], 0)
        self.assertEqual(pilot["disagreements"], [], "\n".join(pilot["disagreements"]))
        self.assertEqual(len(log), 6, "only tickets without a structured approval go to the reviewer")

    def test_out_of_scope_groups_ignored(self):
        results, _, _ = run_all(self.pop, PERIOD, OfflineReviewer(), "s")
        groups = self.pop.groups_by_id
        events = {e["event_id"]: e for e in self.pop.access_events}
        for r in results:
            if r.control_id in ("AC-01", "AC-03"):
                self.assertEqual(groups[events[r.item_id]["group_id"]]["sox_in_scope"], "true")

    def test_without_reviewer_notes_items_go_to_tester(self):
        results, log, _ = run_all(self.pop, PERIOD, None, "s")
        self.assertEqual(log, [])
        self.assertEqual(sum(1 for r in results if r.result == NEEDS_REVIEW), 6)

    def test_generator_is_deterministic(self):
        with tempfile.TemporaryDirectory() as d:
            generate_synthetic.generate(Path(d), PERIOD, seed=7)
            for name in ("access_events.csv", "ritms.csv", "manual_review.csv"):
                a = hashlib.sha256((Path(d) / name).read_bytes()).hexdigest()
                b = hashlib.sha256((self.data / name).read_bytes()).hexdigest()
                self.assertEqual(a, b, name)


class TestControls(Fixture):
    def _first_clean_ac01(self, pop):
        results = test_ac01(pop, PERIOD, None, Pseudonymizer("s", pop.users_by_id), [])
        return next(r for r in results if r.result == PASS)

    def _event_and_ritm(self, pop, event_id):
        ev = next(e for e in pop.access_events if e["event_id"] == event_id)
        return ev, pop.ritms_by_number[ev["source_ticket"]]

    def test_approval_after_grant_is_exception(self):
        pop = self.fresh()
        clean = self._first_clean_ac01(pop)
        ev, ritm = self._event_and_ritm(pop, clean.item_id)
        ritm["approved_at"] = "2026-10-31 23:59"
        r = next(x for x in test_ac01(pop, PERIOD, None, Pseudonymizer("s", pop.users_by_id), []) if x.item_id == ev["event_id"])
        self.assertEqual(r.result, EXCEPTION)
        self.assertIn("A4", r.rationale)

    def test_fulfiller_approving_is_sod_exception(self):
        pop = self.fresh()
        clean = self._first_clean_ac01(pop)
        ev, ritm = self._event_and_ritm(pop, clean.item_id)
        ritm["approver_id"] = ev["performed_by"]
        r = next(x for x in test_ac01(pop, PERIOD, None, Pseudonymizer("s", pop.users_by_id), []) if x.item_id == ev["event_id"])
        self.assertIn("fulfiller", r.rationale)

    def test_involuntary_leaver_has_4h_limit(self):
        pop = self.fresh()
        u = next(x for x in pop.users if x["status"] == "terminated" and x["termination_type"] == "voluntary"
                 and next(r for r in test_ac02(pop, PERIOD) if r.item_id == x["user_id"]).result == PASS)
        dis = next(e for e in pop.access_events if e["action"] == "disable_account" and e["target_user_id"] == u["user_id"])
        lag_h = (parse_ts(dis["timestamp"]) - parse_ts(u["termination_at"])).total_seconds() / 3600
        u["termination_type"] = "involuntary"
        r = next(x for x in test_ac02(pop, PERIOD) if x.item_id == u["user_id"])
        self.assertEqual(r.result, PASS if lag_h <= 4 else EXCEPTION)


class TestReconcile(unittest.TestCase):
    payload = {"notes": "P-AAAAAA (manager) approved by email on 2026-10-01 09:00; email attached.",
               "access_granted": {"granted_at": "2026-10-02 09:00"}}

    def _run(self, finding):
        finding.quote_verified = bool(finding.quote) and finding.quote in self.payload["notes"]
        return reconcile_llm(TestResult("AC-01", "X"), finding, self.payload, parse_ts("2026-10-02 09:00"), {"P-AAAAAA"})

    def test_valid_evidence_recommends_pass_but_needs_tester(self):
        f = LLMFinding(True, "P-AAAAAA", "manager", "2026-10-01 09:00",
                       "P-AAAAAA (manager) approved by email on 2026-10-01 09:00", "high", "ok", "m")
        r = self._run(f)
        self.assertEqual((r.result, r.recommendation), (NEEDS_REVIEW, PASS))

    def test_invented_quote_is_rejected(self):
        f = LLMFinding(True, "P-AAAAAA", "manager", "2026-10-01 09:00", "Approved in writing by the CFO", "high", "ok", "m")
        self.assertEqual(self._run(f).recommendation, EXCEPTION)

    def test_unauthorised_approver_is_rejected(self):
        f = LLMFinding(True, "P-BBBBBB", "other", "2026-10-01 09:00",
                       "P-AAAAAA (manager) approved by email on 2026-10-01 09:00", "high", "ok", "m")
        self.assertEqual(self._run(f).recommendation, EXCEPTION)

    def test_never_auto_passes(self):
        f = LLMFinding(True, "P-AAAAAA", "manager", "2026-10-01 09:00",
                       "P-AAAAAA (manager) approved by email on 2026-10-01 09:00", "high", "ok", "m")
        self.assertNotEqual(self._run(f).result, PASS, "a model finding must never produce a final PASS")


class TestMinimize(Fixture):
    def test_scrub_removes_direct_identifiers(self):
        pz = Pseudonymizer("s", self.pop.users_by_id)
        u = self.pop.users[50]
        text = f"{u['display_name']} wrote from {u['email']} at 905-555-0199 via 10.20.30.40, see https://intranet.example/x"
        out = pz.scrub(text)
        for leak in (u["display_name"], u["email"], "905-555-0199", "10.20.30.40", "https://"):
            self.assertNotIn(leak, out)
        self.assertIn(pz.pid(u["user_id"]), out)

    def test_payloads_contain_no_names_ids_or_emails(self):
        _, log, _ = run_all(self.pop, PERIOD, OfflineReviewer(), "s")
        blob = json.dumps([e["payload"] for e in log])
        for u in self.pop.users:
            self.assertNotIn(u["display_name"], blob)
            self.assertNotIn(u["email"], blob)
            self.assertNotIn(f'"{u["user_id"]}"', blob)

    def test_salt_changes_pseudonyms(self):
        a = Pseudonymizer("cycle-1", self.pop.users_by_id).pid("U0100")
        b = Pseudonymizer("cycle-2", self.pop.users_by_id).pid("U0100")
        self.assertNotEqual(a, b)


class TestPilot(unittest.TestCase):
    def test_kappa(self):
        self.assertAlmostEqual(cohen_kappa([("PASS", "PASS"), ("EXCEPTION", "EXCEPTION")]), 1.0)
        self.assertAlmostEqual(cohen_kappa([("PASS", "EXCEPTION"), ("EXCEPTION", "PASS")]), -1.0)


class TestEvidencePack(Fixture):
    def test_manifest_hashes_match(self):
        results, log, pz = run_all(self.pop, PERIOD, OfflineReviewer(), "s")
        with tempfile.TemporaryDirectory() as d:
            out = write_pack(Path(d), PERIOD, self.pop, results, log, "offline-rules", pz.redactions)
            m = json.loads((out / "manifest.json").read_text())
            for name, digest in m["outputs"].items():
                self.assertEqual(hashlib.sha256((out / name).read_bytes()).hexdigest(), digest)
            self.assertEqual(set(m["inputs"]), {f"{t}.csv" for t in ("users", "groups", "access_events", "ritms", "incidents")})


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class TestServiceNow(Fixture):
    def test_read_only_pagination_and_acl_gap_warning(self):
        rows = [{"number": f"RITM{i:07d}", "cat_item.name": "Access Request", "approval": "Approved"} for i in range(5)]
        seen = []

        def opener(req):
            seen.append(req)
            if "/stats/" in req.full_url:
                return FakeResponse(json.dumps({"result": {"stats": {"count": "6"}}}).encode())
            offset = int(req.full_url.split("sysparm_offset=")[1].split("&")[0])
            return FakeResponse(json.dumps({"result": rows[offset:offset + 2]}).encode())

        src = ServiceNowSource("example", self.data, PERIOD, token="t", opener=opener, page_size=2)
        pop = src.load()
        self.assertEqual(len(pop.ritms), 5)
        self.assertTrue(all(r.get_method() == "GET" for r in seen), "ServiceNow access must be read-only")
        self.assertTrue(any("Aggregate API counts 6" in w for w in pop.warnings))
        self.assertEqual(pop.ritms[0]["approval"], "approved")


class TestClaudeReviewer(unittest.TestCase):
    """Exercises the request/response handling with a fake SDK client (no network)."""

    def setUp(self):
        sys.modules.setdefault("anthropic", types.SimpleNamespace(Anthropic=lambda: None))

    def _client(self, stop_reason, text):
        captured = {}

        class Messages:
            def create(self, **kw):
                captured.update(kw)
                return types.SimpleNamespace(stop_reason=stop_reason, model=kw["model"],
                                             content=[types.SimpleNamespace(type="text", text=text)])

        return types.SimpleNamespace(beta=types.SimpleNamespace(messages=Messages())), captured

    def test_parses_structured_output_and_sends_schema(self):
        body = json.dumps({"approval_evidence_found": True, "approver": "P-AAAAAA", "approver_role": "manager",
                           "approval_time": "2026-10-01 09:00", "quote": "q", "confidence": "high", "rationale": "r"})
        client, captured = self._client("end_turn", body)
        f = ClaudeReviewer(client=client).review({"notes": "q"})
        self.assertTrue(f.approval_evidence_found)
        self.assertEqual(captured["model"], "claude-opus-5-5")
        self.assertEqual(captured["output_config"]["format"]["type"], "json_schema")
        self.assertEqual(captured["fallbacks"], "default")

    def test_refusal_routes_to_manual(self):
        client, _ = self._client("refusal", "")
        f = ClaudeReviewer(client=client).review({"notes": "x"})
        self.assertFalse(f.approval_evidence_found)
        self.assertIn("manual review", f.rationale)


if __name__ == "__main__":
    unittest.main()
