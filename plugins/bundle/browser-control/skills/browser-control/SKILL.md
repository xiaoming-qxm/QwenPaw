---
name: browser-control
description: Use the Chrome Extension bridge through the core Browser SDK.
activation:
  when_tools_available: ["browser"]
---

# Browser Control Skill

Browser Control is now reached through the core Browser SDK. Use
`browser(code=...)` and connect to the user's Chrome session with
`Browser.connect(context="user", requires_user_state=True)`.

```python
browser = await Browser.connect(context="user", requires_user_state=True)
tab = await browser.tabs.active()
await tab.actions.navigate("https://example.com")
snapshot = await tab.snapshot()
info = await tab.page_info()
```

Generic user-browser capabilities stay on the Browser SDK action surface:

```python
await tab.actions.upload({"selector": "input[type=file]"}, "/tmp/input.txt")
download = await tab.actions.download({"selector": "[data-testid=export]"})
await tab.actions.dialog(accept=True)
```

Use `Browser.connect(context="isolated")` only for public, read-only work that
does not need the user's Chrome profile. Logged-in pages, existing tabs, and
user-state tasks require `context="user"` and the Chrome Extension bridge.

Use `await Browser.diagnostics(context="user")` to report bridge availability
without opening or mutating a page.

Sensitive user-browser actions use the QwenPaw approval service. Approval
state, bridge availability, stale observations, and blocker details are
recorded by Browser SDK trace metadata and handled by BrowserGate.

Observation primitives are `tab.snapshot()` for structured page state and
`tab.screenshot()` for visual state when text observations are insufficient.

## Includes

- [ops.md](ops.md): Browser SDK API, context, approval, and observation notes.
- [blocker-report.md](blocker-report.md): structured blocker report fields.
- [control-mode.md](control-mode.md): Chrome Extension bridge constraints.
