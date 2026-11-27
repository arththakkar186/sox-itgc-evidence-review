# ServiceNow Integration (read-only)

## Calls

| Purpose | Request |
|---|---|
| Rows | `GET /api/now/table/sc_req_item?sysparm_query=<period>&sysparm_fields=<allow-list>&sysparm_display_value=true&sysparm_exclude_reference_link=true&sysparm_limit=500&sysparm_offset=N` |
| Expected count | `GET /api/now/stats/sc_req_item?sysparm_query=<same>&sysparm_count=true` |

- **GET only.** A unit test fails if any other HTTP method is used.
- **Field allow-list** (`sysparm_fields`): only the columns the controls need, so work notes on unrelated tables are never pulled.
- **Pagination** by `sysparm_offset` until a short page comes back.
- **Auth**: OAuth bearer token (`SN_TOKEN`) for a dedicated integration user with read roles only.

## The completeness check, and why it exists

The Table API returns only rows the calling user may read. Row-level ACLs (for example on HR-restricted catalog
items) silently remove rows. The Aggregate (stats) API can still count them. A population that is quietly
incomplete is a serious audit problem, so `ServiceNowSource.load()` compares the two numbers and writes a warning into the
summary when they differ:

```
sc_req_item: Table API returned 412 rows but Aggregate API counts 415. Check row-level ACLs for the
integration user before relying on this population.
```

(Illustrative numbers.) Investigation order when the counts differ:

1. Same query string on both calls? (filters, date boundaries, time zone)
2. Duplicates or deletions between the two calls? (re-run both back to back)
3. Row-level ACLs: impersonate the integration user and compare with an admin view on the missing range.

## Field mapping

| ServiceNow field | Tool column |
|---|---|
| `number` | `number` |
| `cat_item.name` | `catalog_item` |
| `request.requested_for` | `requested_for` |
| `approval` | `approval` (lower-cased) |
| `u_group`, `u_approver`, `u_approved_at`, `u_fulfilled_by` | Custom fields on the access catalog item (names vary by instance) |
| `work_notes` | `work_notes` (minimised before any model call) |

Approval history normally lives in `sysapproval_approver`. The custom fields above stand in for a join that each instance
models differently. Adjust `RITM_FIELDS` and `_map_ritm` per instance.
