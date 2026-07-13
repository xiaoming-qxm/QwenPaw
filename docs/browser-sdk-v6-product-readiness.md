# Browser SDK V6 Product Readiness

Generated: 2026-07-05

V6-A adds an operational evidence loop for Browser Control. The goal is to
prove that browser work uses `browser(code=...)`, runs against fresh backend
and frontend code, and produces trace evidence that can be reviewed after each
scenario.

## Verification Commands

Run the local deterministic suite:

```bash
python scripts/verify/browser_control_verify.py preflight
python scripts/verify/browser_control_verify.py fixture
python scripts/verify/browser_control_verify.py public-search
python scripts/verify/browser_control_verify.py bridge-disconnected
```

The deterministic cart fixture is
`scripts/verify/browser_control_cart_fixture.html`. It has no external network
dependencies and stores cart state only in localStorage.

## Scenario Matrix

| ID | Scenario | Expected route | Required evidence | Outcome rules |
| --- | --- | --- | --- | --- |
| A1 | Preflight freshness | running service matches local `HEAD` | `/api/version` freshness gates: `git_commit`, `repo_dirty`, `frontend_fingerprint` | `failed` for stale service, `blocked` for unreachable service unless `--start-if-missing` is used. |
| A2 | Deterministic fixture cart | `browser(code=...)` -> `context="user"` -> Chrome Extension backend | `/extension/traces` includes user backend route, action events, and no forbidden tools | `passed` only when trace evidence proves user backend execution. |
| A3 | Deterministic public read-only | `browser(code=...)` -> `context="auto"` -> isolated backend when available | trace events include connect, observe/page-info, and backend route for `https://example.com/` | `passed` only when the task completes with `V6_PUBLIC_SEARCH_PASS` and isolated trace evidence. |
| A4 | Bridge disconnected | `browser(code=...)` -> `context="user"` -> fail closed | status diagnostics include disconnected bridge status and no isolated fallback | `passed` when user-state work blocks before mutation. |
| A5 | Approval gate | sensitive fixture action with approval required | approval denied/timeout blocks before bridge mutation; approval_level OFF policy bypass is explicit in report | `blocked` when approval is unavailable; never call purchase, payment, or order submission flows. |
| A6 | live Taobao opt-in | real user Chrome profile only when explicitly authorized | command includes `--live-taobao`, report records account-safety guardrails | not part of CI and must not run by default. Requires explicit user authorization. |

## Report Fields

Each verifier scenario writes a JSON-compatible report with:

- `scenario`
- `status`: `passed`, `blocked`, or `failed`
- `duration_ms`
- `browser_tool_calls`
- `backend_route`
- `forbidden_tools`
- `trace_event_count`
- `error_code`
- `blocked_reason`
- `failure_reason`
- `artifact_paths`

`blocked` means the harness reached a safety or environment gate without
proving the scenario. It is not a pass. `failed` means a required invariant was
violated, such as stale service code, forbidden tools in evidence, or user
state routed to isolated backend.

## Closeout Evidence

The V6 closeout verifier runs the Browser Control scenarios through the
QwenPaw chat/task API, then validates `/api/extension/traces` for backend
route evidence:

- `preflight`: `passed`, route
  `browser(code=...) -> context="user" -> user.chrome_extension`.
- `fixture`: `passed`, one browser tool call, route
  `browser(code=...) -> context="user" -> user.chrome_extension`, eight trace
  events, and no forbidden tools.
- `public-search`: `passed`, one browser tool call, route
  `browser(code=...) -> context="isolated" -> isolated.playwright`, two trace
  events, and no forbidden tools.

The fixture scenario opens the local deterministic cart page, executes
Browser SDK selector clicks through the Chrome Extension user backend, verifies
`V6_FIXTURE_PASS`, and fails if user-state work routes to the isolated backend.
The public scenario name is historical; it uses `https://example.com/` as a
stable read-only public page rather than a search engine.

V6-C requires every `blocked` report to include `blocked_reason` and every
`failed` report to include `failure_reason`. A blocked live condition must not
be rewritten as `passed` merely because automation stopped safely.

## Runtime Stability Contract

Browser SDK runtime failures use the shared `BrowserErrorCode` taxonomy for
model-visible recovery and verifier classification:

- `bridge_disconnected`: Chrome Extension bridge is unavailable or closed.
- `approval_denied`: user or policy denied a sensitive browser action.
- `approval_required`: sensitive browser action is waiting on approval.
- `login_required`: authenticated user state is missing.
- `captcha_or_risk_control`: CAPTCHA, verification, or risk-control gate.
- `network_timeout`: backend, bridge, kernel, or page operation timed out.
- `observation_stale`: mutating action was attempted without a fresh
  observation.
- `capability_missing`: the requested behavior is a generic SDK capability
  gap, not a reason for site-specific patches.

Legacy exception codes may remain on exception objects for compatibility, but
`browser(code=...)` tool output and verifier reports must expose the V6 code,
`recovery_hint`, and trace event id where available.

## Bridge Lifecycle Evidence

`/api/extension/status` exposes bridge lifecycle metadata from the shared
Native Messaging route state:

- `connected_since`
- `last_connected_at`
- `last_disconnected_at`
- `last_disconnect_reason`
- `last_error_code`
- `last_error_message`
- `last_request_timeout_at`
- `reconnect_count`

`NMBridge` records trace events for connect, reconnect, disconnect, request
timeout, and close. Disconnects and request timeouts must leave pending
requests failed fast, not unresolved.

## No-Progress Rule

The browser tool includes `progress_decision` metadata from
`detect_no_progress()`. The detector blocks only repeated failed action traces
with the same structural signature: action, tab id, URL, error code, action
kwargs digest, and `observation_digest`. Changed URL or changed observation
digest means the page state moved and no no-progress hint is emitted.

When `progress_decision.blocked` is true, model-visible text includes a
`No progress:` recovery hint before another retry. Successful repeated
read-only observations must not be blocked.

## Capability Gap Rule

When Browser SDK reports `capability_missing`, the repair path is to add or use
a generic Browser SDK capability. Site-specific patches are not the default
answer and must not be used to bypass SDK ownership boundaries.

## Forbidden Tool Rules

The verifier fails any report evidence containing forbidden tools such as
legacy browser entries, removed Browser Control SDK entries, removed remote
bridge references, old SDK websocket routes, or desktop/media inspection
surfaces outside the Browser SDK.

Normal browser work must stay on `browser(code=...)` and Browser SDK APIs. The
only Chrome Extension bridge route for user browser state is the current native
messaging route.

## Freshness Gates

`/api/version` must expose:

- `version`: existing application version
- `git_commit`: short commit of the running backend
- `repo_dirty`: whether the running repo has local changes
- `frontend_fingerprint`: built frontend asset fingerprint or index fallback

The verifier compares `git_commit` with local `HEAD`. A mismatch is a stale
service failure. Missing frontend fingerprint is a repair signal to rebuild or
restart the frontend/backend service before accepting browser evidence.

## Approval Policy

Sensitive actions include destructive, purchase, payment, submission, upload,
download, and credential-like operations. The default path requires approval
before bridge mutation. `approval_level OFF` may be used only as an explicit
operator choice for deterministic local fixture validation, and the report must
record that bypass.

Live Taobao validation must not automate purchase, payment, or order submission.
Add-to-cart, clear-cart, checkout-like, delete, submit, purchase, payment, and
account-changing actions remain safety gated.

## Live Taobao Guardrails

The `taobao-live` scenario is opt-in:

```bash
python scripts/verify/browser_control_verify.py taobao-live --live-taobao
```

It is not part of CI, must not run by default, and requires explicit user
authorization. If the bridge is disconnected, if account state is missing, or
if the requested operation would mutate a real account without approval, the
correct outcome is `blocked`.

## Repair Guidance

- Stale service: stop the server on port 8088 and restart from current local
  code, or run the verifier with `--start-if-missing` when no service is
  present.
- Disconnected bridge: reload the Browser Control Chrome Extension, reopen the
  target tab, and re-check `/api/extension/status`.
- Missing trace evidence: inspect `/api/extension/traces?session_id=<id>` and
  rerun the scenario from `browser(code=...)`.
- Forbidden tools: discard the run and rerun through Browser SDK only.

## Final Verification

Run the V6-C focused gates and repository gates before closeout:

```bash
python -m pytest tests/local/unit/browser_sdk/test_browser_sdk_v6_error_taxonomy.py -v
python -m pytest tests/local/unit/plugins/browser_control/test_nm_bridge_v6_lifecycle.py -v
python -m pytest tests/local/unit/browser_sdk/test_browser_sdk_v6_action_failures.py -v
python -m pytest tests/local/unit/browser_sdk/test_browser_sdk_v6_no_progress.py -v
python -m pytest tests/local/functional/test_browser_control_v6_verify_outcomes.py -v
python -m pytest tests/local/unit/browser_sdk/test_browser_sdk_v6_hardening_docs.py -v
mypy --ignore-missing-imports src/qwenpaw/browser_sdk src/qwenpaw/browser plugins/bundle/browser-control
make quick
pre-commit run --all-files
pre-commit run --all-files
make quick
```
