# Pilot Methodology

Before a tool's output is relied on for a SOX control, it has to be shown to reach the same conclusions as the
established manual procedure.

## Design

1. **Same population.** One closed month. The manual tester and the tool use identical extracts (checked by SHA-256 in the manifest).
2. **Independence.** The manual review is completed and saved (`manual_review.csv`: control, item, conclusion, note) **before** the tool's output is shared.
3. **Comparison unit.** The tool's *recommendation* for each item, including items routed to `NEEDS_REVIEW`, against the manual conclusion.
4. **Metrics** (`pilot.py`):
   - agreement % (recommendation = manual conclusion),
   - Cohen's kappa (agreement corrected for chance, which matters when most items pass),
   - confusion matrix (manual → tool),
   - coverage: items in one set but not the other (population completeness).
5. **Every disagreement is read** by the tester and the control owner, with both rationales side by side.

## Acceptance criteria (example)

| Criterion | Threshold |
|---|---|
| Population coverage | 100% (no missing items either way) |
| Agreement on exceptions | Every manual exception is also proposed by the tool (zero false negatives) |
| Overall agreement | ≥ 98%, with every false positive explained |
| Kappa | ≥ 0.90 |

False negatives (a missed exception) are the costly error in an audit, so the criteria are asymmetric.

## Result on the synthetic month

```text
Items compared: 176
Agreement: 100.0% (176/176)
Cohen's kappa: 1.000
Confusion (manual → tool): {'EXCEPTION→EXCEPTION': 18, 'PASS→PASS': 158}
```

The synthetic dataset is designed and labelled by the generator, so a perfect score here shows that the pipeline is
wired correctly. It is not evidence about real-world accuracy. That evidence comes from a pilot on real, independently reviewed data.

## After the pilot

- The tool becomes the first pass, and the tester reviews `review_queue.csv` plus a sample of tool-passed items each cycle.
- Any change to rules, prompt, model or effort is re-piloted on a labelled month before use.
- Version, reviewer model and input hashes are recorded in each cycle's manifest.
