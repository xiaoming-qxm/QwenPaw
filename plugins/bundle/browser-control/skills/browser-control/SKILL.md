---
name: browser-control
description: Use the Chrome Extension bridge through the core Browser SDK.
activation:
  when_tools_available: ["browser"]
---

# Browser Control Skill

Browser Control is now reached through the core Browser SDK. Use
`browser(code=...)` and connect to the user's Chrome session with
`Browser.connect(context="user")`.

```python
browser = await Browser.connect(context="user")
tab = await browser.tabs.open("https://example.com")
snapshot = await tab.snapshot()
```

The Chrome Extension bridge is required for user-state work. If the bridge is
disconnected, stop and ask the user to enable or refresh the extension. Do not
reroute logged-in or existing-tab tasks to the isolated backend.

Use observe-act-verify discipline: after each navigation, click, type,
selection, scroll, or destructive action, take a fresh `tab.snapshot()` or
`tab.screenshot()` before the next mutation.

## Includes

- [ops.md](ops.md): browser operation rules and read-after-write verification.
- [blocker-report.md](blocker-report.md): blocker detection and reporting.
- [control-mode.md](control-mode.md): Chrome Extension bridge constraints.
