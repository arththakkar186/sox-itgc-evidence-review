"""Compare the tool's recommendations with an independent manual review.

The pilot question is: if a tester had used the tool's recommendation, would
they have reached the same conclusion as the manual review? Items the tool
routes to NEEDS_REVIEW are compared on their recommendation, because the tester
still makes the final call on those.
"""
from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path

from .models import TestResult

LABELS = ("PASS", "EXCEPTION")


def load_manual(path: Path) -> dict[tuple[str, str], dict]:
    with Path(path).open(newline="") as fh:
        return {(r["control_id"], r["item_id"]): r for r in csv.DictReader(fh)}


def cohen_kappa(pairs: list[tuple[str, str]]) -> float:
    n = len(pairs)
    if not n:
        return 0.0
    po = sum(1 for a, b in pairs if a == b) / n
    ca, cb = Counter(a for a, _ in pairs), Counter(b for _, b in pairs)
    pe = sum((ca[l] / n) * (cb[l] / n) for l in LABELS)
    return 1.0 if pe == 1 else (po - pe) / (1 - pe)


def compare(results: list[TestResult], manual: dict[tuple[str, str], dict]) -> dict:
    tool = {(r.control_id, r.item_id): r for r in results}
    keys = sorted(set(tool) & set(manual))
    pairs = [(manual[k]["conclusion"], tool[k].recommendation) for k in keys]
    agree = sum(1 for a, b in pairs if a == b)
    confusion = Counter(f"{a}→{b}" for a, b in pairs)
    disagreements = [f"{k[0]} {k[1]}: manual {manual[k]['conclusion']} ({manual[k]['tester_note']}), "
                     f"tool {tool[k].recommendation} ({tool[k].rationale})" for k in keys
                     if manual[k]["conclusion"] != tool[k].recommendation]
    return {
        "compared": len(keys), "agree": agree,
        "agreement_pct": 100.0 * agree / len(keys) if keys else 0.0,
        "kappa": cohen_kappa(pairs), "confusion": dict(sorted(confusion.items())),
        "missing_in_tool": len(set(manual) - set(tool)), "missing_in_manual": len(set(tool) - set(manual)),
        "disagreements": disagreements,
    }
