# Browser SDK Operation Notes

## API Surface

- Use `browser(code=...)` and Browser SDK calls for Chrome work.
- Connect to user Chrome state with
  `Browser.connect(context="user", requires_user_state=True)`.
- Use `Browser.connect(context="isolated")` for public pages that do not need
  profile cookies, extensions, or existing tabs.
- `browser.tabs.open(...)`, `browser.tabs.active()`, `browser.tabs.select(...)`,
  `tab.snapshot()`, `tab.screenshot()`, `tab.page_info()`, and `tab.extract(...)`
  are the primary observation and tab primitives.
- `tab.evaluate(..., read_only=True)` is a read helper. Mutating evaluation and
  action calls are recorded as Browser SDK action traces.

Common calls inside `browser(code=...)`:

```python
browser = await Browser.connect(context="user", requires_user_state=True)
tab = await browser.tabs.active()
snapshot = await tab.snapshot()
info = await tab.page_info()
```

## Context And Bridge

- User-state work depends on the Chrome Extension bridge.
- Bridge availability is reported through
  `await Browser.diagnostics(context="user")`.
- Explicit `context="user"` and `context="isolated"` requests are hard
  constraints. `context="auto"` may select an available backend from request
  metadata.
- Approval decisions for sensitive actions are surfaced through Browser SDK
  policy metadata and Browser trace events.

## Observation Primitives

- `tab.snapshot()` returns structured page text, refs, URL, and title.
- `tab.screenshot()` records visual state when text observation is unavailable
  or incomplete.
- Browser SDK traces record tab lifecycle, observation, action, extraction,
  approval, and cleanup events for recovery decisions.
- BrowserGate owns stale-observation, no-progress, context-upgrade, approval,
  and blocker recovery decisions.

## Visual Fallback

- Prefer `snapshot` for structured state.
- Use `screenshot` when the page is visual, canvas based, or missing important
  state from the text observation.
- Screenshot artifacts are Browser SDK observations; local file/media tools are
  outside the Browser SDK control path.
