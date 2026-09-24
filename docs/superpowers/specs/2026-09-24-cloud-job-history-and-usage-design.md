# Cloud Job History and Usage Design

## Goal

Correct the Cloud Queue's Recent Jobs display and turn the existing **Utilities → Cloud Jobs** navigation item into a complete, API-backed job history. Users with the existing `jobs` cloud-workflow permission can inspect their own jobs or all jobs recorded by Atelier, including real RunningHub task IDs and actual RH coin consumption.

## Placement and Access

- The existing **Utilities → Cloud Jobs** button opens the job-history view in the center Cloud Studio workspace.
- The left Cloud Workflows navigation remains visible.
- The right Cloud Queue and Cloud Usage rail remains visible.
- The existing `jobs` permission remains the only access gate. Administrators already control this permission per user; no new role or permission is introduced.
- Users without `jobs` permission cannot open the page or call its API.

## Data Source and Accuracy

Atelier's persisted RunningHub job ledger is the source for listing jobs created through Atelier. RunningHub's documented task query response is the source for final usage:

- `taskId`: the real RunningHub task identifier.
- `usage.consumeCoins`: actual RH coins consumed.
- `usage.taskCostTime`: workflow runtime, displayed as runtime and never as credits.

The application already polls RunningHub by task ID while a job is active. It will normalize and persist the final usage values so completed rows remain accurate after reloads and service restarts. Missing or not-yet-reported usage displays as `—`; it is never replaced by an estimate.

RunningHub does not document a stable API for listing every account billing record. Therefore **All Jobs** means every job recorded by Atelier, including jobs from other Atelier users sharing the configured RunningHub credentials. Jobs submitted outside Atelier are outside this feature's scope.

## Recent Jobs Rail

The right rail stays compact and continues to show active work plus the five most recent terminal jobs.

Each recent row shows:

- Media thumbnail when available.
- Workflow name, such as `Krea2 Image HQ`, `Scail 2 Motion`, or `MiniMax H3 Ref2V`.
- Clearly labelled status.
- A compact metadata line containing a shortened RunningHub task ID, formatted runtime, and actual coin usage, for example: `Task 201350… · 71 sec · 8 RH coins`.

No unexplained bare number is shown. If a task ID, runtime, or coin value is unavailable, that part is omitted or shown as `—` where necessary.

The **View All →** action and **Cloud Jobs** navigation item open the same full history view.

## Full Cloud Jobs View

The center workspace contains:

- Page title: `Cloud Jobs`.
- Scope filter: `My Jobs` and `All Jobs`.
- Workflow filter: all available workflow types.
- Status filter: active, completed, failed, and cancelled states.
- Search by full or partial Atelier job ID, RunningHub task ID, or creator.
- Summary showing the number of matching jobs and sum of known actual RH coins.
- Paginated job table.

Table columns:

1. Created
2. Workflow
3. Creator
4. Atelier ID
5. RunningHub Task ID
6. Status
7. Runtime
8. RH Coins

The default scope is **My Jobs**. Filters and search operate server-side so the full persisted history can be inspected without loading every row into the browser at once. The table defaults to newest first.

## API Design

Extend `GET /api/runninghub/jobs` with optional query parameters while preserving the current response for existing callers:

- `scope=my|all`, default `my`.
- `workflow=<workflow_key>`.
- `status=<normalized_status>`.
- `q=<search text>`.
- `page=<positive integer>`, default `1`.
- `per_page=<bounded integer>`, default `20`.
- `view=rail|history`, default `rail` for backward compatibility.

`view=rail` returns every active job plus the five most recent terminal jobs, matching current queue behavior. `view=history` returns the full filtered history page and metadata:

- `jobs`
- `page`
- `per_page`
- `total`
- `total_pages`
- `known_coin_total`

Public job records expose normalized `task_id`, `runtime`, and `rh_coins` fields but continue excluding encrypted credentials, fingerprints, concurrency controls, and local upload paths.

## Usage Refresh

- Active tasks continue to receive usage values during normal polling.
- When a task reaches a terminal state, Atelier stores the final usage returned in that response.
- The history endpoint does not repeatedly call RunningHub for every completed job on each page load.
- For legacy completed records with a task ID but missing usage, the server schedules a bounded background backfill using the job's stored encrypted credential. It refreshes the visible page first and persists every successful result. Backfill failures leave `—` and do not prevent the history page from loading.
- Backfill calls are rate-limited and never resubmit or mutate a RunningHub task.

## Error Handling

- Invalid filters return HTTP 400 with a concise error.
- Page numbers beyond the available range return an empty page with valid pagination metadata.
- A RunningHub usage lookup failure does not hide the job.
- Unknown usage remains visibly unknown rather than being estimated.
- Users lacking `jobs` permission continue to receive HTTP 403.

## Testing

Backend tests cover:

- Default rail compatibility.
- `my` versus `all` scope.
- Workflow, status, and search filtering.
- Pagination and totals.
- Actual `consumeCoins` and `taskCostTime` persistence.
- Secret and local-path exclusion.
- Permission enforcement.
- Legacy records with missing usage.

UI tests cover:

- Cloud Jobs navigation opening the central history view.
- View All opening the same view.
- Correct workflow labels and labelled recent-job metadata.
- Scope, workflow, status, search, and pagination controls.
- Runtime and RH Coins rendering in separate columns.
- Empty, loading, active, failed, and incomplete-usage states.

## Out of Scope

- Estimated credits.
- Scraping RunningHub's billing dashboard.
- Discovering tasks submitted outside Atelier.
- Changing the existing per-user Cloud Jobs permission model.
