# Monthly Operating Procedure

| Step | Who | Action | Output |
|---|---|---|---|
| 1 | IAM analyst | After month end, export directory audit events (group adds/removes, disables) for in-scope groups, and the HR termination list | `access_events.csv`, `users.csv`, `groups.csv` |
| 2 | IAM analyst | Pull RITMs and incidents closed in the period (`soxreview pull`) or export them from ServiceNow | `ritms.csv`, `incidents.csv` |
| 3 | IAM analyst | Check the completeness warning: the Table API count must equal the Aggregate API count | No `Population warnings` in summary |
| 4 | IAM analyst | Set a new `SOXREVIEW_SALT`, then run `soxreview run` | `out/<period>/` evidence pack |
| 5 | Tester | Work `review_queue.csv`: for each `NEEDS_REVIEW` item, open the ticket attachment and confirm or overturn the recommendation; for each proposed exception, confirm it | `tester_conclusion`, initials, date filled in |
| 6 | Tester | Re-perform a sample of tool-passed items (for example 10 per control) directly in ServiceNow and the directory | Sample noted in workpaper |
| 7 | Control owner | Remediate confirmed exceptions: remove access, get approval, document root cause | Remediation tickets |
| 8 | IAM lead | Review and sign off the workpaper; archive the pack with its manifest | Signed workpaper, retained 7 years |

## Change management

Changes to controls, thresholds, prompts or the model are made by pull request, reviewed, tested in CI, and re-piloted
before the next cycle (see [pilot-methodology.md](pilot-methodology.md)).

## Access to the tool

- Read-only ServiceNow integration user, with only the roles needed to read `sc_req_item` and `incident`.
- API keys and tokens come from a secrets manager or an environment variable, never from the repository.
- Evidence packs are stored in the restricted audit evidence library, not on local disks.
