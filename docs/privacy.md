# Privacy and Data Minimisation

Principle: **send the least data that can answer the question, and nothing that identifies a person.**

## What is sent (per notes-path item)

| Field | Example | Why it is needed |
|---|---|---|
| `item_id` | `EV00117` | Match the answer to the item (an internal event ID, not personal data) |
| `ticket` | `RITM0001117` | Context for the tester's log |
| `access_granted` | group name, application, recipient pseudonym, grant time | What was granted and when |
| `authorized_approvers` | two pseudonyms with roles `manager` / `group_owner` | Lets the model label the role without an org chart |
| `structured_approval_field` | `not requested` | Why the notes are being read |
| `notes` | redacted work notes | The evidence itself |

## What is never sent

Names, user IDs, e-mail addresses, phone numbers, IP addresses, URLs, department, manager chain, HR data, other tickets, or any item that passed on rules.

## Techniques

| Technique | Implementation |
|---|---|
| Allow-list | `minimize.approval_question` builds the payload field by field; nothing is copied wholesale |
| Pseudonyms | `P-` + first 6 hex characters of SHA-256(salt : user_id). Stable within a cycle, so the model can compare approver and authorised list |
| Salt rotation | `SOXREVIEW_SALT` set per cycle, so pseudonyms cannot be linked across months outside the boundary |
| Name replacement | Every directory display name found in free text is replaced by its pseudonym (longest first) |
| Pattern redaction | E-mail → `[EMAIL]`, URL → `[URL]`, IPv4 → `[IP]`, phone → `[PHONE]` |
| Redaction report | Counts per type are written to `summary.md` for the reviewer's sign-off |
| Audit trail | `llm_log.jsonl` stores the exact minimised payload and the response, so anyone can check what left the boundary |

## Tests that enforce it

`tests/test_pipeline.py::TestMinimize` fails the build if any payload contains a display name, an e-mail address or a raw user ID,
or if `scrub()` leaves a name, e-mail, phone, IP or URL behind.

## Residual risks

- A name that is **not** in the directory (an external person) may survive in notes. Mitigation: the tester reviews `llm_log.jsonl` for the first cycles, and a named-entity pass can be added if needed.
- Group and application names are sent; they are business context, not personal data.
- Provider data handling must be approved by the organisation's privacy and security review before any real data is processed.
