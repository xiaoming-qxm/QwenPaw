---
name: browser_cdp
description: "Advanced reference for explicit CDP topics. Normal browser work uses browser(code=...) and Browser.connect(...)."
metadata:
  builtin_skill_version: "2.0"
  qwenpaw:
    emoji: "🔌"
    requires: {}
---

# Browser CDP Reference

For normal browser work, use `browser(code=...)` with the Browser SDK:

```python
browser = await Browser.connect(context="auto")
```

Only enter this CDP reference when the user explicitly asks about debug ports,
attaching external tooling, or sharing a browser through CDP. Treat CDP as an
advanced backend detail, not the primary automation path.

When the task needs the user's logged-in Chrome state, use:

```python
browser = await Browser.connect(context="user")
```

That path requires the Chrome Extension bridge. If it is disconnected, stop and
ask the user to enable or refresh the extension. Do not reroute a user-state
task to the isolated backend.

When the task is public web research without user state, use:

```python
browser = await Browser.connect(context="isolated")
```

The SDK arbitrates backend selection independently of whether you use
primitives such as `tab.snapshot()` or structured actions such as
`tab.actions.click(...)`.
