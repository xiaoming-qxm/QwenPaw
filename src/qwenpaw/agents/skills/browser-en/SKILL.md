---
name: browser
description: "Use browser(code=...) with the Browser SDK for web research, tab work, user Chrome tasks, and advanced browser diagnostics."
metadata:
  builtin_skill_version: "12.0"
  qwenpaw:
    emoji: ""
    requires: {}
---

# Browser

Use `browser(code=...)` as the normal browser automation entry. Inside that
code, connect with the Browser SDK:

```python
browser = await Browser.connect(context="auto")
tab = await browser.tabs.open("https://example.com")
snapshot = await tab.snapshot()
```

Action-First, Controlled Primitive:

- Use primitives for tab lifecycle, observation, page metadata, extraction,
  waiting, and close/release.
- Use `actions.*` for page interaction and state changes.
- After any state-changing action, observe again with `tab.snapshot()` or
  `tab.screenshot()` before the next mutation.

Use generated discovery for API details:

```python
Browser.capabilities(scope="actions")
Browser.help(api_id="tab.actions.click")
```

Normal rhythm:

```python
browser = await Browser.connect(context="auto")
tab = await browser.tabs.open("https://example.com")
snapshot = await tab.snapshot()
await tab.actions.click({"ref": "r1_e3"})
snapshot = await tab.snapshot()
```

- `context="auto"` is the default and chooses the best available backend.
- `context="user"` requires the user's Chrome bridge; report the block if it
  is unavailable.
- `context="isolated"` is for deterministic work that must not use the user's
  Chrome state.
- Pass `requires_user_state=True` when login state, carts, accounts, or
  existing user tabs are required; such requests fail closed if user Chrome is
  unavailable.

Check backend availability without opening a browser:

```python
diagnostics = await Browser.diagnostics(context="auto")
```

Do not use fixed sleeps, private backend objects, JavaScript execution,
CSS-target shortcuts, low-level protocol escape hatches, or direct backend
dispatchers. Recover with `tab.wait_for(...)`, fresh observations, and
generated `Browser.help(...)`.
