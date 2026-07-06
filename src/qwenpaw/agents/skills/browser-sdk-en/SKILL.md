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

Long-running browser work is allowed to continue until it reaches a real
terminal outcome. Stop it with task cancellation when the user asks to cancel
or when the outer runtime is stopped. The `timeout_ms` tool parameter is a
deprecated compatibility input and does not limit total Browser SDK execution;
do not tune it to manage long-running work.

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

Generic product capabilities use structured actions:

```python
await tab.actions.upload({"selector": "input[type=file]"}, "/tmp/input.txt")
download = await tab.actions.download({"selector": "[data-testid=export]"})
await tab.actions.dialog(accept=True)
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
