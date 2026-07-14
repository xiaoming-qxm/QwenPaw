---
name: browser
description: "Use browser(code=...) with the Browser SDK for web research, tab work, and user Chrome tasks."
metadata:
  builtin_skill_version: "12.2"
  qwenpaw:
    emoji: ""
    requires: {}
---

# Browser

Use `browser(code=...)` as the normal browser automation entry. Inside that
code, connect with the Canonical Browser SDK:

```python
browser = await Browser.connect(context="auto")
open_result = await browser.tabs.open("https://example.com")
if (
    open_result.status in {"SUCCEEDED", "PARTIAL"}
    and open_result.opened_tabs
):
    tabs: list[TabSummary] = await browser.tabs.list()
    tab = await browser.tabs.select(open_result.opened_tabs[0])
    snapshot = await tab.snapshot()
```

Action-First, Controlled Primitive:

- Use primitives for tab lifecycle, observation, page metadata, extraction,
  waiting, and close/release.
- Use `actions.*` for page interaction and state changes.
- After any state-changing action, observe again with `tab.snapshot()` or
  `tab.screenshot()` before the next mutation.

Canonical values are Runtime-issued. Select a `TabSummary`, use the
`TargetRef` from fresh evidence, and inspect rich terminal truth:

```python
read_result = await tab.read(limit=100)
snapshot = await tab.snapshot(limit=50)
target: TargetRef = snapshot.targets[0].ref
terminal = await tab.actions.click(target)
terminal
```

Waits use a typed `BrowserCondition`, never natural-language guessing:

```python
condition = BrowserCondition.all(PageCondition.ready("load"))
terminal = await tab.wait_for(condition, timeout_ms=10_000)
```

Convert a workspace path once, then pass the task-owned `ResourceHandle`:

```python
resource: ResourceHandle = browser.resources.from_workspace("report.pdf")
terminal = await tab.actions.upload_file(target, (resource,))
```

- `context="auto"` is the default and chooses the best available backend.
- `context="user"` requires the user's Chrome bridge; report the block if it
  is unavailable.
- `context="isolated"` is for deterministic work that must not use the user's
  Chrome state.
- Use `context="user"` when login state, carts, accounts, or existing user
  tabs are required; that request fails closed if user Chrome is unavailable.

`browser(code=...)` runs module-level async Python. Do not use `return` in
its code; assign the SDK result to a variable or leave it as the final
expression. Canonical results are recorded by the tool automatically.

Do not use fixed sleeps, private backend objects, JavaScript execution,
CSS-target shortcuts, low-level protocol escape hatches, or direct backend
dispatchers. Recover with typed `tab.wait_for(...)`, fresh observations, and
the documented Canonical APIs.
