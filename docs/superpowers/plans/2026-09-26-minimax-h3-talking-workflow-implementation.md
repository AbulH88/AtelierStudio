# MiniMax H3 Optimized for Talking Implementation Plan

> **Execution:** Implement inline with `executing-plans`, task by task, under strict TDD.

**Goal:** Add an independently permissioned Cloud Studio workflow that turns one portrait source image plus a structured, editable H3 prompt into a 720×1280 talking video through RunningHub workflow `2103082156684087297`.

**Architecture:** Extend the existing persisted RunningHub job system with a new `h3_talking` workflow key. A server-only OpenRouter endpoint generates the structured I2VA prompt from the image and user fields using one of two whitelisted models. A second endpoint validates and queues the final prompt, image, and 5–15 second duration; the existing dispatcher uploads media, submits nodes 9/14/20, polls, records real usage, imports the MP4 to Gallery, and cleans temporary files.

**Tech Stack:** Flask, vanilla JavaScript/HTML/CSS, pytest, requests, existing RunningHub queue and R2 Gallery integration.

**Spec:** `docs/superpowers/specs/2026-09-26-minimax-h3-talking-workflow-design.md`

## Global Constraints

- Keep existing H3 Ref2V behavior and routes unchanged.
- Use workflow key `h3_talking`, label `H3 Optimized for Talking`, and workflow ID `2103082156684087297`.
- OpenRouter API keys remain server-side; accept only `openai/gpt-6-luna` and `qwen/qwen3.8-27b`.
- Duration must be an integer from 5 through 15 inclusive on both prompt and video endpoints.
- The spoken script must be included verbatim in the generated prompt contract.
- Preserve unrelated untracked workspace files.
- Push the completed verified commits to the current `main` branch, as explicitly authorized by the user.

## Task 1: Backend prompt-builder contract

**Files:**
- Modify: `runpod-comfyui/webapp/test_runninghub_cloud.py`
- Modify: `runpod-comfyui/webapp/app.py`

**Produces:** `POST /api/runninghub/h3-talking/prompt` and a reusable strict prompt instruction/validation path.

**Step 1 — RED:** Add focused route tests that prove:

- `h3_talking` permission is required.
- missing image, unsupported model, fractional duration, and out-of-range duration return 400 without calling OpenRouter;
- the default/selected model is passed to OpenRouter;
- the instruction contains the exact first-line/section contract, duration, user description, audio/music direction, and verbatim script requirement;
- a structurally valid OpenRouter response containing the exact script is returned as `{prompt: ...}`;
- a malformed response or a response that omits/changes the exact script returns a safe 502.

Run:

```powershell
Set-Location runpod-comfyui/webapp
pytest -q test_runninghub_cloud.py -k "talking_prompt"
```

Expected: new tests fail because the route and helpers do not exist.

**Step 2 — GREEN:** In `app.py`:

- add the two-model allowlist with Luna as the default;
- add `_parse_h3_talking_duration` to reject missing, non-integer, fractional, or out-of-range values;
- add `_h3_talking_instruction(...)` embedding the approved I2VA structure and verbatim dialogue rules;
- call the existing `describe_image` OpenRouter boundary with the selected model and instruction;
- validate the returned first line, section ordering, and exact script presence;
- add the permission-gated multipart prompt route without persisting the image.

Run the same focused command.

Expected: all `talking_prompt` tests pass.

**Step 3 — Commit:**

```powershell
git add runpod-comfyui/webapp/app.py runpod-comfyui/webapp/test_runninghub_cloud.py
git commit -m "feat: add H3 talking prompt builder"
```

**Task verification:**

```powershell
Set-Location runpod-comfyui/webapp
pytest -q test_runninghub_cloud.py -k "talking_prompt or describe"
```

## Task 2: RunningHub job lifecycle and node submission

**Files:**
- Modify: `runpod-comfyui/webapp/test_runninghub_cloud.py`
- Modify: `runpod-comfyui/webapp/test_cloud_workflow_gates.py`
- Modify: `runpod-comfyui/webapp/app.py`

**Consumes:** The shared duration parser and `h3_talking` permission introduced by Task 1.

**Produces:** `POST /api/runninghub/h3-talking/jobs`, submission mapping for nodes 9/14/20, queue lifecycle support, cleanup, and history visibility.

**Step 1 — RED:** Add tests proving:

- `h3_talking` is a deny-by-default independent permission and appears for admins;
- job creation requires a supported image and non-empty final prompt;
- every integer duration 5–15 is accepted while missing/fractional/out-of-range values are rejected;
- a user can run one H3 Ref2V job and one Talking job independently, but cannot run two Talking jobs;
- `_runninghub_submit_h3_talking` posts to workflow `2103082156684087297`, instance `default`, with exactly node 9 `image`, node 14 `value`, and node 20 `value` overrides;
- dispatcher upload/submission and local talking-image cleanup use the existing lifecycle;
- public/history job data retains the separate workflow key and real usage fields.

Run:

```powershell
Set-Location runpod-comfyui/webapp
pytest -q test_runninghub_cloud.py test_cloud_workflow_gates.py -k "talking or cloud_workflows"
```

Expected: tests fail because `h3_talking` is not registered and no job route/submission branch exists.

**Step 2 — GREEN:** In `app.py`:

- add the workflow/instance/node constants and include `h3_talking` in `CLOUD_WORKFLOW_IDS`;
- implement `_runninghub_submit_h3_talking` with only the three approved node overrides;
- add `h3_talking` upload/submission handling to `_runninghub_run`;
- include `talking_image_path` in cleanup;
- implement the permission-gated job route with MIME/size, prompt, duration, credential, and independent active-job validation;
- persist only the fields needed for restart recovery and the existing history/usage flow.

Run the same focused command.

Expected: all focused lifecycle tests pass.

**Step 3 — Commit:**

```powershell
git add runpod-comfyui/webapp/app.py runpod-comfyui/webapp/test_runninghub_cloud.py runpod-comfyui/webapp/test_cloud_workflow_gates.py
git commit -m "feat: queue H3 optimized talking videos"
```

**Task verification:**

```powershell
Set-Location runpod-comfyui/webapp
pytest -q test_runninghub_cloud.py test_cloud_workflow_gates.py
```

## Task 3: Cloud Studio workflow interface

**Files:**
- Modify: `runpod-comfyui/tests/test_cloud_studio_shell.py`
- Modify: `runpod-comfyui/webapp/index.html`

**Consumes:** The prompt and job endpoints from Tasks 1–2 and the `h3_talking` permission/workflow key.

**Produces:** A complete separate Cloud Studio workflow panel, permission option, queue/history label, and submission UX.

**Step 1 — RED:** Add static UI contract tests proving the page contains:

- a separate Video navigation item and admin permission checkbox for `h3_talking`;
- one image input and 9:16 portrait preview;
- description, exact script, audio direction, music, and editable final-prompt fields;
- exactly the two approved model choices with Luna selected;
- `type=number min=5 max=15 step=1 value=10` duration input;
- Generate H3 Prompt and Generate Video buttons;
- calls to `/api/runninghub/h3-talking/prompt` and `/api/runninghub/h3-talking/jobs`;
- client validation that preserves prior prompt on generation failure and submits the final edited prompt;
- queue/history label `H3 Optimized for Talking` and filter option.

Run:

```powershell
Set-Location runpod-comfyui
pytest -q tests/test_cloud_studio_shell.py -k "talking"
```

Expected: new UI tests fail because the workflow panel does not exist.

**Step 2 — GREEN:** Update `index.html`:

- add the navigation, workflow panel, permission option, and Cloud Jobs filter;
- add compact CSS matching the current Cloud Studio visual language and a `9/16` image preview using `object-fit: cover`;
- wire image selection, model/duration/field validation, prompt generation, editable prompt, and video submission;
- do not clear user fields or an existing final prompt when prompt generation fails;
- extend workflow selection, permissions, queue rendering, job filters, and labels for `h3_talking`.

Run the same focused command.

Expected: all `talking` UI contract tests pass.

**Step 3 — Commit:**

```powershell
git add runpod-comfyui/webapp/index.html runpod-comfyui/tests/test_cloud_studio_shell.py
git commit -m "feat: add H3 talking cloud interface"
```

**Task verification:**

```powershell
Set-Location runpod-comfyui
pytest -q tests/test_cloud_studio_shell.py
```

## Task 4: Integrated verification, review, and push

**Files:** No planned product changes; fixes require their own RED→GREEN regression test.

**Consumes:** All backend and UI interfaces from Tasks 1–3.

**Step 1 — Focused integration verification:**

```powershell
Set-Location runpod-comfyui
pytest -q webapp/test_runninghub_cloud.py webapp/test_cloud_workflow_gates.py tests/test_cloud_studio_shell.py
```

Expected: all focused tests pass.

**Step 2 — Full regression verification:**

```powershell
Set-Location runpod-comfyui
pytest -q
```

Expected: no new failures. The known baseline may still report the three Gallery thumbnail tests and `webapp/test_cloud.py::test_cloud_status_endpoint_unconfigured`; compare by exact test name and do not hide unrelated failures.

**Step 3 — Whole-branch review:** Build the executing-plans review package and perform a separate whole-branch review against the spec and ledger. Because this session is prohibited from spawning subagents, perform the documented self-review and record that limitation. Any Critical/Important finding gets one TDD fix pass and a green focused/full suite.

**Step 4 — Push:**

```powershell
git status --short
git push origin main
```

Expected: only the intended tracked changes are committed; the push succeeds and the repository deployment workflow is triggered.

## Review Focus

- Exact preservation of non-English dialogue, punctuation, and line breaks.
- Fractional/missing duration bypasses across both endpoints.
- Permission leakage between `h3` and `h3_talking`.
- Temporary image cleanup on queue rejection, provider error, cancellation, and successful submission.
- No arbitrary OpenRouter model IDs or API credentials reaching the browser.
- No regression to existing H3 Ref2V controls or submission behavior.
- Node overrides must not accidentally change fixed resolution, FPS, latent-upscale, sampler, or audio nodes in the published Talking workflow.
