# Browser SDK Unification Verification

Generated: 2026-07-03

## V6 Product Readiness

See `docs/browser-sdk-v6-product-readiness.md` for the current V6 evidence
harness, freshness gates, deterministic fixture, report fields, blocked
outcome semantics, and opt-in live acceptance policy.

## V12 Browser Routing And Permission Contract

V12 makes `context="auto"` user-Chrome-first. When the Chrome Extension is
available, `auto` selects `user.chrome_extension`. Public or ambiguous tasks
may use a degraded isolated fallback only when user Chrome is unavailable, and
that choice is visible through diagnostics and trace metadata. Tasks that need
login state, existing tabs, carts, account pages, or other user state must pass
`requires_user_state=True`; those requests fail closed with
`user_browser_unavailable` and do not use isolated fallback.

Browser permission decisions use QwenPaw approval modes
`OFF`, `AUTO`, `SMART`, and `STRICT`. Operational observations are allowed.
Sensitive boundaries follow the active mode and evidence confidence. Critical
known boundaries require approval in every mode, and critical unknown
boundaries block with `boundary_user_intervention_required`.
In short: critical unknown boundaries block.

## V5 Operational Readiness

See `docs/browser-sdk-v5-operational-readiness.md` for the current V5
acceptance matrix covering diagnostics, approval, user Chrome status,
model-facing error recovery, and manual live acceptance gates.

## Scenario Matrix

| Scenario | Expected route | Policy checkpoints | Forbidden calls | Evidence |
| --- | --- | --- | --- | --- |
| Public web research: search for Loop Engineering blog | `browser(code=...)` -> `Browser.connect(context="auto")` -> `user.chrome_extension` when connected, otherwise degraded isolated fallback with metadata | Fresh observation after open before extraction | desktop/media inspection tools, visible legacy browser entry, silent fallback for user-state tasks | V12 route contract `test_v12_auto_routing.py` |
| User login-state shopping/cart task | `browser(code=...)` -> `Browser.connect(context="auto", requires_user_state=True)` or explicit `context="user"` -> `user.chrome_extension` | Sensitive action policy can block clear/delete/purchase-like actions before bridge mutation | Isolated fallback when bridge is missing | V12 route and policy contracts |
| Disconnected bridge for user-state task | `browser(code=...)` -> `context="user"` -> explicit block | Context acquisition must fail before browser mutation | Isolated fallback | Functional contract `test_disconnected_bridge_flow_blocks_explicitly` |
| Removed legacy browser action surface | Legacy browser action imports/tool lookup -> absent | No legacy dispatcher fallback | Old dispatcher execution after SDK gap | Legacy browser removal contract |
| Default tool surface | Runtime tool registry -> workspace list | N/A | legacy browser tool or legacy REPL tools as normal entries | Functional contract `test_default_runtime_tool_surface_has_single_browser_entry` |
| V4 hard removal | Runtime source scan and import checks | `/ws/nm-bridge` remains the Chrome Extension bridge route | old plugin SDK, old remote bridge class, and old SDK websocket route | Contract `test_browser_sdk_v4_legacy_removal` |

## Expected Backend Routes

- Auto route: `context="auto"` prefers `user.chrome_extension` when user Chrome is available.
- Degraded isolated fallback: public or ambiguous `auto` can select `isolated.playwright` only when user Chrome is unavailable, with `selected_backend_degraded=True`.
- User-state route: `context="user"` or `context="auto"` with `requires_user_state=True` selects `user.chrome_extension` or blocks with `user_browser_unavailable`.
- Disconnected user bridge route: `user.chrome_extension` returns `browser_bridge_disconnected`; no Playwright fallback is allowed.

## Policy Checkpoints

- Browser context acquisition: `BrowserPolicy.allow_context_acquisition`.
- Browser boundary actions: `BrowserPolicy.allow_action` before bridge execution, with approval metadata for approval level, source, capability class, boundary severity, risk kind, evidence, decision reason, and consequence summary.

## Forbidden Tool Calls

- desktop/media inspection tools outside the Browser SDK
- model-visible legacy browser tool
- model-visible legacy REPL tools
- direct Playwright routing for user-state tasks
- repeated no-progress browser loops without a fresh observation

## Log Patterns That Prove Success

- `browser` is the only default browser automation tool in the runtime surface.
- Auto route logs include `browser(code=...)`, `Browser.connect(context="auto")`, `auto_user_chrome_first`, and either `user.chrome_extension` or degraded isolated fallback metadata.
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
snapshot = await tab.snapshot(limit=100)
info = await tab.page_info()
diagnostics = await Browser.diagnostics(context="auto")
```

Use `context="auto"` for normal Browser work; it prefers user Chrome.
Use `requires_user_state=True` when logged-in state or existing tabs are part
of the task. Use `context="isolated"` only as an explicit deterministic path
or when degraded isolated fallback is reported for public or ambiguous work.
After `tab.actions.click(...)`, navigation, typing, selection, scroll, reload,
or wait transitions, take a fresh observation before the next mutation.

Raw CDP and remote browser attachment have no public callable entrypoint.

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
| Public research prompt: Loop Engineering blog | ROUTE-PASS / LIVE-CONTENT BLOCKED | V12 expects `auto_user_chrome_first`; if user Chrome is unavailable, degraded isolated fallback is acceptable only with explicit fallback metadata. Live content extraction may still be blocked by the current browser/network environment and is not marked PASS. |
| User-state Taobao cart prompt | SAFETY-GATED BLOCKED | With Browser Control user backend registered, a safe non-mutating `Browser.connect(context="user")` probe returned `browser_bridge_disconnected` with `backend_id=user.chrome_extension`. No isolated fallback occurred. Real Taobao cart mutation is blocked until the Chrome Extension bridge is live and the user explicitly approves account-mutating actions. |
| Destructive/purchase-like Taobao actions | SAFETY-GATED BLOCKED unless explicitly approved | Add-to-cart, clear cart, checkout-like, delete, submit, purchase, or account-changing actions require approval before bridge mutation. |

Manual live prompts that operate on real user Chrome and Taobao remain gated
by a live Chrome Extension bridge and explicit user approval for destructive
or purchase-like actions. Automated contracts prove routing, fail-closed
behavior, and tool-surface constraints without modifying a real user account.
