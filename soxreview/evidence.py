"""Write the audit evidence pack for one test cycle.

out/<period>/
  workpaper.csv        one row per tested item: attributes, result, recommendation, rationale, evidence refs
  exceptions.csv       items the tool proposes as exceptions
  review_queue.csv     items a tester must look at (all NEEDS_REVIEW, plus all exceptions)
  llm_log.jsonl        exactly what was sent to the reviewer (minimised) and what came back
  summary.md           population counts, results by control, pilot comparison if available
  manifest.json        SHA-256 of every input and output file, tool version, reviewer, run time
"""
from __future__ import annotations

import csv
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .ingest import Population, sha256_file
from .models import EXCEPTION, NEEDS_REVIEW, TestResult

CONTROL_NAMES = {
    "AC-01": "Access provisioning is approved by an authorised person before access is granted",
    "AC-02": "Terminated users are disabled within the required time, with a leaver ticket",
    "AC-03": "Emergency (break-glass) access is justified, approved after the fact and removed",
}


def _row(r: TestResult) -> dict:
    return {
        "control_id": r.control_id, "item_id": r.item_id, "result": r.result, "recommendation": r.recommendation,
        "attributes": " | ".join(f"{a.name}={'Y' if a.passed else ('N' if a.passed is False else '?')}" for a in r.attributes),
        "rationale": r.rationale, "evidence_refs": " ".join(r.evidence_refs),
        "reviewer": r.llm.reviewer if r.llm else "rules",
        "tester_conclusion": "", "tester_initials": "", "tester_date": "",
    }


def _write_csv(path: Path, rows: list[dict], fields: list[str]):
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def write_pack(out: Path, period: str, pop: Population, results: list[TestResult], llm_log: list[dict],
               reviewer_name: str, redactions: dict, pilot: dict | None = None) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    rows = [_row(r) for r in results]
    fields = list(rows[0].keys()) if rows else ["control_id"]
    _write_csv(out / "workpaper.csv", rows, fields)
    _write_csv(out / "exceptions.csv", [x for x in rows if x["recommendation"] == EXCEPTION], fields)
    _write_csv(out / "review_queue.csv",
               [x for x in rows if x["result"] == NEEDS_REVIEW or x["recommendation"] == EXCEPTION], fields)
    with (out / "llm_log.jsonl").open("w") as fh:
        for entry in llm_log:
            fh.write(json.dumps(entry, sort_keys=True) + "\n")

    by = Counter((r.control_id, r.result) for r in results)
    rec = Counter((r.control_id, r.recommendation) for r in results)
    lines = [f"# SOX ITGC access-control test: {period}", "",
             f"Tool version {__version__} · reviewer `{reviewer_name}` · generated {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC", "",
             "| Control | Description | Tested | Pass | Exception | Needs review | Proposed exceptions |",
             "|---|---|---:|---:|---:|---:|---:|"]
    for cid, desc in CONTROL_NAMES.items():
        n = sum(1 for r in results if r.control_id == cid)
        lines.append(f"| {cid} | {desc} | {n} | {by[(cid, 'PASS')]} | {by[(cid, 'EXCEPTION')]} | {by[(cid, 'NEEDS_REVIEW')]} | {rec[(cid, 'EXCEPTION')]} |")
    lines += ["", "## Proposed exceptions", ""]
    for r in results:
        if r.recommendation == EXCEPTION:
            lines.append(f"- **{r.control_id} {r.item_id}**: {r.rationale}")
    lines += ["", "## Items routed to a tester because the notes were read by the reviewer", ""]
    for r in results:
        if r.result == NEEDS_REVIEW:
            lines.append(f"- **{r.item_id}** recommended **{r.recommendation}**: {r.rationale}")
    lines += ["", "## Privacy", "",
              f"{len(llm_log)} items were sent to the reviewer, minimised to 6 fields with pseudonymised people. "
              f"Redactions in free text: " + ", ".join(f"{k} {v}" for k, v in redactions.items()) + "."]
    if pop.warnings:
        lines += ["", "## Population warnings", ""] + [f"- {w}" for w in pop.warnings]
    if pilot:
        lines += ["", "## Pilot: tool vs manual review", "",
                  f"- Items compared: {pilot['compared']}",
                  f"- Agreement (tool recommendation vs manual conclusion): **{pilot['agreement_pct']:.1f}%** "
                  f"({pilot['agree']}/{pilot['compared']})",
                  f"- Cohen's kappa: {pilot['kappa']:.3f}",
                  f"- Confusion (manual → tool): {pilot['confusion']}",
                  f"- Manual items with no tool result: {pilot['missing_in_tool']}; tool items not in manual review: {pilot['missing_in_manual']}"]
        if pilot["disagreements"]:
            lines += ["", "Disagreements:"] + [f"- {d}" for d in pilot["disagreements"]]
    (out / "summary.md").write_text("\n".join(lines) + "\n")

    manifest = {
        "tool": "soxreview", "version": __version__, "period": period, "reviewer": reviewer_name,
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "inputs": pop.checksums,
        "outputs": {p.name: sha256_file(p) for p in sorted(out.iterdir()) if p.is_file() and p.name != "manifest.json"},
        "counts": {"tested": len(results), "llm_reviewed": len(llm_log)},
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return out
