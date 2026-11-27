"""Command line:

    python3 -m soxreview run   --data data/synthetic --period 2026-10 --out out/2026-10 [--reviewer offline|claude]
                               [--manual data/synthetic/manual_review.csv]
    python3 -m soxreview pull  --instance <name> --directory data/synthetic --period 2026-10 ...   (ServiceNow, read-only)
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from pathlib import Path

from .controls import run_all
from .evidence import write_pack
from .ingest import CsvSource, ServiceNowSource
from .llm import make_reviewer
from .pilot import compare, load_manual


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="soxreview", description="SOX ITGC access-control evidence review")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("run", "pull"):
        s = sub.add_parser(name)
        s.add_argument("--period", required=True, help="YYYY-MM")
        s.add_argument("--out", required=True)
        s.add_argument("--reviewer", choices=["offline", "claude", "none"], default="offline")
        s.add_argument("--model", default="claude-opus-5-5")
        s.add_argument("--manual", help="manual review CSV for the pilot comparison")
        s.add_argument("--salt", default=os.environ.get("SOXREVIEW_SALT", "change-me-per-cycle"),
                       help="pseudonymisation salt (set SOXREVIEW_SALT; rotate each cycle)")
        if name == "run":
            s.add_argument("--data", required=True, help="folder with the CSV exports")
        else:
            s.add_argument("--instance", required=True, help="ServiceNow instance name (<name>.service-now.com)")
            s.add_argument("--directory", required=True, help="folder with users/groups/access_events CSV exports")
    a = p.parse_args(argv)

    if a.cmd == "run":
        pop = CsvSource(Path(a.data)).load()
    else:
        pop = ServiceNowSource(a.instance, Path(a.directory), a.period).load()

    reviewer = None if a.reviewer == "none" else make_reviewer(a.reviewer, a.model)
    results, llm_log, pz = run_all(pop, a.period, reviewer, a.salt)
    pilot = compare(results, load_manual(Path(a.manual))) if a.manual else None
    out = write_pack(Path(a.out), a.period, pop, results, llm_log,
                     reviewer.name if reviewer else "none", pz.redactions, pilot)

    c = Counter((r.control_id, r.result) for r in results)
    print(f"Tested {len(results)} items for {a.period}; {len(llm_log)} sent to reviewer '{reviewer.name if reviewer else 'none'}'.")
    for cid in ("AC-01", "AC-02", "AC-03"):
        print(f"  {cid}: PASS {c[(cid, 'PASS')]:>3}  EXCEPTION {c[(cid, 'EXCEPTION')]:>3}  NEEDS_REVIEW {c[(cid, 'NEEDS_REVIEW')]:>3}")
    for w in pop.warnings:
        print(f"  WARNING: {w}")
    if pilot:
        print(f"Pilot: {pilot['agree']}/{pilot['compared']} agree with manual review "
              f"({pilot['agreement_pct']:.1f}%, kappa {pilot['kappa']:.3f}).")
    print(f"Evidence pack: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
