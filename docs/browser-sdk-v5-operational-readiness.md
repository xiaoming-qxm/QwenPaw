# Browser SDK V5 Operational Readiness

Generated: 2026-07-04

V5 closes the operational readiness gaps around diagnostics, user Chrome
approval, status surfaces, and model-facing error recovery for the unified
`browser(code=...)` Browser SDK route.

## Automated Contract Scenarios

| Scenario | Expected signal | Coverage |
| --- | --- | --- |
| Public research route for Loop Engineering | `browser(code=...)` with `Browser.connect(context="auto")` selects `isolated.playwright` when isolated is available. | Browser SDK unified flow and diagnostics contracts. |
| User Chrome route for Taobao-style user state | `browser(code=...)` with `Browser.connect(context="user")` selects `user.chrome_extension`; there is no isolated fallback for explicit user context. | User backend resolver, status, and policy registration contracts. |
| Bridge disconnected | A user-context operation fails closed with `chrome_disconnected` and an actionable diagnostic hint. | Backend diagnostics, status payload, console rendering, and tool error text contracts. |
| Sensitive action risk classification | Delete, clear, purchase, checkout, pay, submit, upload, download, and credential actions are classified as sensitive. | V5 risk classifier contract. |
| Browser tool error recovery | Visible text includes code, message, hint, and diagnostics summary while full traceback remains in metadata only. | `test_browser_tool_v5_errors`. |

## Manual Live Acceptance

Manual live acceptance is not an automated CI test because it may depend on a
real Chrome profile, logged-in Taobao state, and user approval for account
changes.

| Live scenario | Required result |
| --- | --- |
| Loop Engineering public blog research | Confirm the live prompt routes through `browser(code=...)`, `context="auto"`, and `isolated.playwright`; record live network/content blockers separately from route success. |
| Taobao user Chrome read-only state | Confirm the live prompt routes through `browser(code=...)`, `context="user"`, and `user.chrome_extension`; bridge disconnected is a safety-gated block, not a PASS. |
| Taobao account mutation | Add-to-cart, clear-cart, delete, checkout, purchase, submit, payment, and account-changing actions require explicit approval before bridge mutation. |

## Failure Diagnostics

- Bridge disconnected: show `chrome_disconnected`, selected backend
  `user.chrome_extension` when known, and the hint to reload the extension or
  reopen the target browser tab.
- Backend unavailable: show `browser_backend_unavailable` or
  `isolated_backend_unavailable` with backend availability checks.
- Browser Control engine missing: show `browser_control_engine_missing` and
  ask the user to restart QwenPaw or reload the Browser Control plugin.
- Tool errors: keep traceback in metadata; visible text stays concise and
  actionable.

## Forbidden Execution Paths

- User Chrome tasks must not fall back to isolated Playwright when the request
  explicitly uses `context="user"` or requires user state.
- User Chrome tasks must not be inspected with desktop/media/file inspection
  tools outside the Browser SDK.
- Normal model-facing browser work must not use legacy browser entries,
  legacy plugin REPL entries, removed Browser Control SDK modules, or the old
  SDK websocket route.
- Repeated no-progress clicks without a fresh `tab.snapshot(limit=...)` or
  `tab.screenshot()` are forbidden.

## Approval Expectations

- approval approved: one approved sensitive action may be cached only for the
  same root session, domain, risk kind, and normalized action within the
  policy TTL.
- approval denied: the browser action is blocked before bridge mutation and
  returns a denied policy decision.
- approval timeout: the browser action is blocked before bridge mutation and
  returns an approval-timeout policy decision.
- Non-sensitive read actions such as snapshot, screenshot, page info,
  evaluate read-only extraction, list tabs, and active tab must not create
  approval requests.
