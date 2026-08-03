# Rubric: Data Modelling & Privacy (CTL-0400, 0402)

Judgment review. Advisory. Owned by senior-data.

## For every new field
| Question | Required answer |
|---|---|
| Is it personal data? | yes/no — if unsure, treat as yes |
| Purpose | what it is for, specifically |
| Lawful basis (if personal) | consent / contract / legitimate interest / legal obligation |
| Retention | a duration, not "indefinite" |
| Who can read it | roles and systems |
| Processors | any third party that will receive it |

This accumulates into a GDPR Art. 30 record. Fill it at write time — reconstructing it
later under a legal deadline is an archaeology project.

## Deletion trace
For any new personal data, list EVERY location it will come to rest:
primary DB, replicas, backups, warehouse, search index, cache, event stream, logs,
analytics, third-party processors, support tooling.

A deletion story that stops at the primary database is not a deletion story.

## Schema compatibility (CTL-0402)
- [ ] Additive only, OR expand-migrate-contract across three deploys
- [ ] Old code can still read the new schema (deploy ordering)
- [ ] New code can read old data still in flight
- [ ] Reversible, or explicitly marked irreversible with a written reason
- [ ] Batched if the table is large; lock duration estimated
- [ ] Verified backup taken immediately before
- [ ] Dry-run performed against a production-sized copy
- [ ] Rollback procedure written as an actual command

## Logging
- [ ] No object logged whose serialisation has not been inspected
- [ ] No raw identifiers in analytics events (use pseudonymous ids)
- [ ] Log retention no longer than the deletion promise made to users
