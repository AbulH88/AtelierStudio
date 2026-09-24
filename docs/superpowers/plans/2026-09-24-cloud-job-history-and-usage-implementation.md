# Cloud Job History and Usage Implementation Plan

## Objective

Implement the approved Cloud Jobs history view, correct Recent Jobs metadata, and expose actual RunningHub coin usage without estimates.

## Work Items

1. Add backend tests for rail compatibility, history scope, filters, search, pagination, totals, and secret exclusion.
2. Normalize RunningHub usage fields when polling so `consumeCoins` and `taskCostTime` are persisted as public job data.
3. Extend `GET /api/runninghub/jobs` with `view=history`, `scope`, filters, search, and bounded pagination while keeping the default rail response unchanged.
4. Add the central Cloud Jobs panel, filters, summary, responsive table, loading/empty/error states, and pagination.
5. Wire Utilities → Cloud Jobs and View All to the new center panel without removing either sidebar.
6. Correct Recent Jobs rows to show workflow name, labelled status, shortened task ID, formatted runtime, and actual RH coins.
7. Add UI contract tests and run focused backend/UI tests, JavaScript syntax validation, Python compilation, and the full suite.
8. Commit, push, deploy, and verify the live page.

## Compatibility and Safety

- The endpoint defaults to the existing compact rail behavior.
- Only users with the existing `jobs` cloud permission can query either view.
- API credentials and local upload paths remain excluded.
- Unknown usage is displayed as `—`; no credit estimate is generated.
- All Jobs reads Atelier's persisted ledger and does not scrape RunningHub.
