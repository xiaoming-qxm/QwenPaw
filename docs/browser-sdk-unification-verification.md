# Browser SDK Unification Verification

Generated: 2026-07-03

## Scenario Matrix

| Scenario | Expected route | Policy checkpoints | Forbidden calls | Evidence |
| --- | --- | --- | --- | --- |
| Public web research: search for Loop Engineering blog | `browser(code=...)` -> `Browser.connect(context="auto")` -> `isolated.playwright_legacy` | Fresh observation after open before extraction | `DesktopScreenShot`, `ViewVideo`, visible legacy browser entry | Functional contract `test_public_research_flow_routes_to_isolated_backend` |
| User login-state shopping/cart task | `browser(code=...)` -> `Browser.connect(context="user")` -> `user.chrome_extension` | Sensitive action policy can block clear/delete/purchase-like actions before bridge mutation | Isolated fallback when bridge is missing | Functional contract `test_user_state_flow_routes_to_chrome_extension_policy_gate` |
| Disconnected bridge for user-state task | `browser(code=...)` or legacy control shim -> `context="user"` -> explicit block | Context acquisition must fail before browser mutation | Isolated fallback | Functional contract `test_disconnected_bridge_flow_blocks_explicitly` |
| Unsupported legacy action | Explicit direct `browser_use` call -> SDK shim -> fail closed | No legacy dispatcher fallback | Old dispatcher execution after SDK gap | Functional contract `test_unsupported_legacy_action_reports_sdk_gap` |
| Default tool surface | Runtime tool registry -> workspace list | N/A | `browser_use`, `python_repl`, `python_repl_reset` as normal entries | Functional contract `test_default_runtime_tool_surface_has_single_browser_entry` |

## Expected Backend Routes

- Public web route: `context="auto"` with no user-state requirement selects `isolated.playwright_legacy` when available.
- User-state route: `context="user"` or `context="auto"` with `requires_user_state=True` selects `user.chrome_extension`.
- Disconnected user bridge route: `user.chrome_extension` returns `browser_bridge_disconnected`; no Playwright fallback is allowed.

## Policy Checkpoints

- Browser context acquisition: `BrowserPolicy.allow_context_acquisition`.
- Sensitive browser actions: `BrowserPolicy.allow_action` before bridge execution for submit, purchase, delete, clear, upload, download, or private-data actions.

## Forbidden Tool Calls

- `DesktopScreenShot`
- `ViewVideo`
- model-visible `browser_use`
- model-visible `python_repl`
- direct Playwright routing for user-state tasks
- repeated no-progress browser loops without a fresh observation

## Log Patterns That Prove Success

- `browser` is the only default browser automation tool in the runtime surface.
- Public research flow logs include `browser(code=...)`, `Browser.connect(context="auto")`, and `isolated.playwright_legacy`.
- User-state flow logs include `browser(code=...)`, `Browser.connect(context="user")`, `user.chrome_extension`, and policy evaluation before sensitive mutations.
- Disconnected bridge logs include `browser_bridge_disconnected`.
- Unsupported legacy calls include `sdk_gap=true`.

## Observed Automated Evidence

- `uv run python -m pytest tests/local/functional/test_browser_sdk_unified_flows.py tests/local/functional/test_browser_sdk_tool_surface.py -v`
- Result: 5 passed.
- `uv run qwenpaw app`
- Result: startup reached application startup, then failed to bind because
  `127.0.0.1:8088` was already in use.
- `uv run qwenpaw app --port 8099`
- Result: server reached Ready at `http://127.0.0.1:8099`; smoke server was
  stopped with normal shutdown.

## Manual Acceptance Status

Manual live prompts that operate on real user Chrome and Taobao remain gated by a live Chrome Extension bridge and explicit user approval for destructive or purchase-like actions. Automated contracts prove routing, fail-closed behavior, and tool-surface constraints without modifying a real user account.
