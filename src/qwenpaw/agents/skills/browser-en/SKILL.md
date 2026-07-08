---
name: browser
description: "Use browser(code=...) with the Browser SDK for web research, tab work, user Chrome tasks, and advanced browser diagnostics."
metadata:
  builtin_skill_version: "11.0"
  qwenpaw:
    emoji: ""
    requires: {}
---

# Browser

Use `browser(code=...)` as the only normal browser automation entry.
Inside that code, connect with the Browser SDK:

```python
browser = await Browser.connect(context="auto")
tab = await browser.tabs.open("https://example.com")
snapshot = await tab.snapshot()
```

Long-running browser work may continue until it reaches a real terminal
outcome. Stop it with task cancellation when the user asks to cancel or when
the outer runtime is stopped.

V13 routing, workspace, and Protocol v2 ownership contract:

In short: auto prefers user Chrome.

- `context="auto"`: default. `auto` prefers user Chrome through
  `user.chrome_extension` when the Chrome Extension is available. Public or
  ambiguous work may use a degraded isolated fallback only when user Chrome is
  unavailable; traces and diagnostics mark `selected_backend_degraded` and
  `fallback_reason`.
- `context="user"`: explicitly use the user's Chrome profile through the
  Chrome Extension bridge. If the bridge is disconnected, stop and report the
  block.
- `context="isolated"`: explicitly use the isolated backend for deterministic
  tests or tasks that must not touch user Chrome. It never routes to user
  Chrome.

When the task needs visible session state, login state, a cart, an account
page, or existing tabs, pass `requires_user_state=True`. User-state requests
fail closed with `user_browser_unavailable` if user Chrome is unavailable;
they do not fall back to isolated. Do not foreground, focus, or activate the
user's Chrome unless the user asks to watch.

Primitive operations and structured actions are peer capabilities:

```python
browser = await Browser.connect(context="auto")
tab = await browser.tabs.open("https://example.com")
snapshot = await tab.snapshot()
info = await tab.page_info()
await tab.actions.click({"ref": "r1_e3"})
```

Browser Ownership Protocol v2 tab semantics:

- `browser.tabs.open(url)` is the normal page-entry API. `url` is required; it
  reuses the current request workspace tab and navigates it to the target URL.
  Normal tasks do not create a blank page first.
- `browser.tabs.new(url)` is only for an explicit additional tab. `url` is
  required; do not call URL-less new.
- `browser.tabs.active()` only returns an existing tab controlled by the
  current request. It never creates a tab and is not a normal task starting
  point.
- `Browser.diagnostics(context="auto")` checks connected, routable,
  actionable, and cleanup_verified health, not only bridge connectivity.

Generic product capabilities use structured actions:

```python
await tab.actions.upload({"selector": "input[type=file]"}, "/tmp/input.txt")
download = await tab.actions.download({"selector": "[data-testid=export]"})
await tab.actions.dialog(accept=True)
```

After a state-changing operation, take a fresh `tab.snapshot()` or
`tab.screenshot()` before the next mutation. `tab.evaluate(...,
read_only=True)` is a read helper and does not satisfy that observation
requirement. `tab.page_info()` is metadata only; it does not satisfy the
observation requirement either.

Browser approval modes use QwenPaw's shared vocabulary:
`OFF, AUTO, SMART, STRICT`. Read-only observation stays operational.
Sensitive boundaries follow the active mode and evidence confidence. Critical
known boundaries require approval in every mode. Critical unknown boundaries
block and require user intervention.

Check backend availability without opening a browser:

```python
diagnostics = await Browser.diagnostics(context="auto")
```

Use light extraction for compact reads:

```python
result = await tab.extract("Summarize the visible article", format="text")
data = await tab.extract("Return title and price as JSON", format="json")
```

Raw CDP and remote browser attachment are blocked coming-soon capabilities
with no public callable entrypoint. Normal browser work goes through the
Browser SDK.
