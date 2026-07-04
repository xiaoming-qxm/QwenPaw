# Browser SDK Unification Verification

Generated: 2026-07-03

## Scenario Matrix

| Scenario | Expected route | Policy checkpoints | Forbidden calls | Evidence |
| --- | --- | --- | --- | --- |
| Public web research: search for Loop Engineering blog | `browser(code=...)` -> `Browser.connect(context="auto")` -> `isolated.playwright` | Fresh observation after open before extraction | `DesktopScreenShot`, `ViewVideo`, visible legacy browser entry | Functional contract `test_public_research_flow_routes_to_isolated_backend` |
| User login-state shopping/cart task | `browser(code=...)` -> `Browser.connect(context="user")` -> `user.chrome_extension` | Sensitive action policy can block clear/delete/purchase-like actions before bridge mutation | Isolated fallback when bridge is missing | Functional contract `test_user_state_flow_routes_to_chrome_extension_policy_gate` |
| Disconnected bridge for user-state task | `browser(code=...)` -> `context="user"` -> explicit block | Context acquisition must fail before browser mutation | Isolated fallback | Functional contract `test_disconnected_bridge_flow_blocks_explicitly` |
| Removed legacy browser action surface | Legacy browser action imports/tool lookup -> absent | No legacy dispatcher fallback | Old dispatcher execution after SDK gap | Legacy browser removal contract |
| Default tool surface | Runtime tool registry -> workspace list | N/A | legacy browser tool or legacy REPL tools as normal entries | Functional contract `test_default_runtime_tool_surface_has_single_browser_entry` |
| V4 hard removal | Runtime source scan and import checks | `/ws/nm-bridge` remains the Chrome Extension bridge route | old plugin SDK, old remote bridge class, and old SDK websocket route | Contract `test_browser_sdk_v4_legacy_removal` |

## Expected Backend Routes

- Public web route: `context="auto"` with no user-state requirement selects `isolated.playwright` when available.
- User-state route: `context="user"` or `context="auto"` with `requires_user_state=True` selects `user.chrome_extension`.
- Disconnected user bridge route: `user.chrome_extension` returns `browser_bridge_disconnected`; no Playwright fallback is allowed.

## Policy Checkpoints

- Browser context acquisition: `BrowserPolicy.allow_context_acquisition`.
- Sensitive browser actions: `BrowserPolicy.allow_action` before bridge execution for submit, purchase, delete, clear, upload, download, or private-data actions.

## Forbidden Tool Calls

- `DesktopScreenShot`
- `ViewVideo`
- model-visible legacy browser tool
- model-visible legacy REPL tools
- direct Playwright routing for user-state tasks
- repeated no-progress browser loops without a fresh observation

## Log Patterns That Prove Success

- `browser` is the only default browser automation tool in the runtime surface.
- Public research flow logs include `browser(code=...)`, `Browser.connect(context="auto")`, and `isolated.playwright`.
- User-state flow logs include `browser(code=...)`, `Browser.connect(context="user")`, `user.chrome_extension`, and policy evaluation before sensitive mutations.
- Disconnected bridge logs include `browser_bridge_disconnected`.
- Legacy browser action imports/tool lookup are absent; there is no SDK shim.
- V4 hard removal leaves `/ws/nm-bridge` as the Chrome Extension bridge route
  and removes the old plugin SDK, old remote bridge class, and old SDK
  websocket route.

## V4 Public SDK Contract

```python
browser = await Browser.connect(context="auto")
tab = await browser.tabs.active()
await tab.actions.navigate("https://example.com")
snapshot = await tab.snapshot()
info = await tab.page_info()
diagnostics = await Browser.diagnostics(context="auto")
```

Use `context="user"` for user Chrome state and `context="isolated"` for
public isolated work. After `tab.actions.click(...)`, navigation, typing,
selection, scroll, reload, or wait transitions, take a fresh observation before
the next mutation.

## Observed Automated Evidence

- `uv run python -m pytest tests/local/unit/browser_sdk/test_browser_sdk_skill_docs.py -v`
- Result: 7 passed. This covers all built-in model-visible skills,
  Browser Control plugin skills, plugin manifest tool metadata, SDK reference
  text, guard text, and user-facing runtime payload names.
- `uv run python -m pytest tests/local/functional/test_browser_sdk_unified_flows.py tests/local/functional/test_browser_sdk_tool_surface.py -v`
- Result: 5 passed.
- `uv run qwenpaw app`
- Result: startup reached application startup, then failed to bind because
  `127.0.0.1:8088` was already in use.
- `uv run qwenpaw app --port 8099`
- Result: server reached Ready at `http://127.0.0.1:8099`; smoke server was
  stopped with normal shutdown.

## Manual Acceptance Status

| Acceptance item | Status | Evidence / reason |
| --- | --- | --- |
| Latest backend/frontend deployment smoke | PASS | `uv run qwenpaw app --port 8099` reached Ready at `http://127.0.0.1:8099` from latest local code and stopped cleanly. |
| Public research prompt: Loop Engineering blog | ROUTE-PASS / LIVE-CONTENT BLOCKED | A direct `browser(code=...)` acceptance probe printed `backend=isolated.playwright`, then timed out after 30000 ms while opening/snapshotting the public search page. Route arbitration is correct; live content extraction is blocked by the current browser/network environment and is not marked PASS. |
| User-state Taobao cart prompt | SAFETY-GATED BLOCKED | With Browser Control user backend registered, a safe non-mutating `Browser.connect(context="user")` probe returned `browser_bridge_disconnected` with `backend_id=user.chrome_extension`. No isolated fallback occurred. Real Taobao cart mutation is blocked until the Chrome Extension bridge is live and the user explicitly approves account-mutating actions. |
| Destructive/purchase-like Taobao actions | SAFETY-GATED BLOCKED unless explicitly approved | Add-to-cart, clear cart, checkout-like, delete, submit, purchase, or account-changing actions require approval before bridge mutation. |

Manual live prompts that operate on real user Chrome and Taobao remain gated
by a live Chrome Extension bridge and explicit user approval for destructive
or purchase-like actions. Automated contracts prove routing, fail-closed
behavior, and tool-surface constraints without modifying a real user account.
