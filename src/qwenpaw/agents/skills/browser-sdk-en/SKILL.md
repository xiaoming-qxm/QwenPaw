---
name: browser-sdk
description: "Use the unified Browser SDK through browser(code=...) for web research, tab work, and user Chrome tasks."
metadata:
  builtin_skill_version: "1.0"
  qwenpaw:
    emoji: "🌐"
    requires: {}
---

# Browser SDK

Use `browser(code=...)` as the only normal browser automation entry.
Inside that code, connect with the SDK:

```python
browser = await Browser.connect(context="auto")
tab = await browser.tabs.open("https://example.com")
snapshot = await tab.snapshot()
```

Choose context by browser state, not by operation type:

- `context="auto"`: default. Public web work usually uses the isolated backend.
- `context="user"`: use the user's Chrome profile through the Chrome Extension bridge. If the bridge is disconnected, stop and report the block.
- `context="isolated"`: use the isolated backend for public web tasks that do not need user login state.

Primitive operations and structured actions are peer capabilities:

```python
browser = await Browser.connect(context="auto")
tab = await browser.tabs.active()
await tab.actions.navigate("https://example.com")
snapshot = await tab.snapshot()
info = await tab.page_info()
await tab.actions.click({"ref": "r1_e3"})
```

After a state-changing operation, take a fresh `tab.snapshot()` or
`tab.screenshot()` before the next mutation. `tab.evaluate(..., read_only=True)`
is a read helper and does not satisfy that observation requirement.
`tab.page_info()` is metadata only; it does not satisfy the observation
requirement either.

Check backend availability without opening a browser:

```python
diagnostics = await Browser.diagnostics(context="auto")
```

Use light extraction for compact reads:

```python
result = await tab.extract("Summarize the visible article", format="text")
data = await tab.extract("Return title and price as JSON", format="json")
```

Raw CDP is an advanced internal backend concern. Do not use raw CDP as the
primary path for ordinary browser tasks.
