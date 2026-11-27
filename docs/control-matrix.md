# Control Matrix

Fictional control set modelled on common SOX ITGC "logical access" controls. Thresholds are set in
`soxreview/controls.py` and are typical values. A real program takes them from its own control narratives.

## AC-01: Access provisioning

| | |
|---|---|
| **Risk** | Unauthorised access to financially significant systems leads to unauthorised or erroneous transactions |
| **Control statement** | Access to in-scope applications and privileged groups is granted only after documented approval by the user's manager or the group owner. The approver is neither the recipient nor the person who grants the access |
| **Frequency** | Per event (tested monthly, full population) |
| **Population** | Directory audit events `add_member` to groups flagged `sox_in_scope = true`, in the period, not linked to an incident |
| **Evidence** | Audit event (who, what, when) · ServiceNow RITM (requested for, group, approval, approver, approval time, fulfiller, notes) · manager and group owner of record |

| Attribute | Test | Exception example |
|---|---|---|
| A1 | The change references a request ticket that exists | Change made with no ticket |
| A2 | The ticket's requested-for user and group match the change | Ticket raised for someone else |
| A3 | The ticket's approval is `approved` with a timestamp. If not, the notes are reviewed (see below) | `not requested` |
| A4 | Approval time ≤ provisioning time | Approved the day after access was granted |
| A5 | Approver ≠ recipient and approver ≠ fulfiller | Self-approval |
| A6 | Approver is the recipient's manager or the group owner | A peer manager approved |
| L1-L3 | (Notes path) Quote found verbatim · approver authorised · approval dated before provisioning | Verbal approval only; e-mail dated after the change |

## AC-02: Terminations

| | |
|---|---|
| **Risk** | Former employees keep access and can make or hide transactions |
| **Control statement** | Accounts of terminated users are disabled within 24 hours of the termination time (4 hours for involuntary terminations), tracked on a leaver ticket |
| **Population** | Users with status `terminated` and a termination time in the period (HR source of truth) |

| Attribute | Test |
|---|---|
| B1 | A `disable_account` event exists |
| B2 | First disable ≤ termination + 24 h (voluntary) or + 4 h (involuntary) |
| B3 | A *Leaver Offboarding* RITM exists for the user |

## AC-03: Emergency (break-glass) access

| | |
|---|---|
| **Risk** | Emergency privileged access is abused or never removed |
| **Control statement** | Emergency access to privileged groups is used only for P1/P2 incidents, approved by the group owner within 48 hours, and removed within 7 days |
| **Population** | `add_member` events whose source ticket is an incident |

| Attribute | Test |
|---|---|
| C1 | Linked incident exists with priority 1 or 2 |
| C2 | Retrospective approval by the group owner ≤ 48 h after the grant |
| C3 | Matching `remove_member` event ≤ 7 days after the grant |

## Deficiency handling

Each proposed exception goes to the tester on `review_queue.csv`. The tester confirms the exception, or overturns it with a
reason, in the workpaper's `tester_conclusion` column. Confirmed exceptions are raised with the control owner for remediation
(remove access, obtain approval, root cause). They are then assessed for severity (deficiency, significant deficiency, material weakness),
considering compensating controls.
