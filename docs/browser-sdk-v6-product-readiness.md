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
| A3 | Public search/read-only | `browser(code=...)` -> `context="auto"` -> isolated backend when available | trace events include connect, observe/extraction, and backend route | `blocked` for live network/content failure; route evidence can still be recorded separately. |
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
- `blocked_reason`
- `artifact_paths`

`blocked` means the harness reached a safety or environment gate without
proving the scenario. It is not a pass. `failed` means a required invariant was
violated, such as stale service code, forbidden tools in evidence, or user
state routed to isolated backend.

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

Live Taobao validation must not automate purchase, payment, or order
submission. Add-to-cart, clear-cart, checkout-like, delete, submit, purchase,
payment, and account-changing actions remain safety gated.

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
