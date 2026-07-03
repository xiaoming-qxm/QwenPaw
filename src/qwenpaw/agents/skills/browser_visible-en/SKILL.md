---
name: browser_visible
description: "Use when the user asks about visible browser behavior. Execution still goes through browser(code=...) and Browser SDK contexts."
metadata:
  builtin_skill_version: "2.0"
  qwenpaw:
    emoji: "🖥️"
    requires: {}
---

# Browser Visibility

The execution entry remains `browser(code=...)`.

Use `Browser.connect(context="user")` when the user needs their real Chrome
profile, visible session, login state, cart, account page, or existing tabs.
This requires the Chrome Extension bridge and must block when the bridge is not
connected.

Use `Browser.connect(context="isolated")` or `context="auto"` for public web
work that does not need user state. The isolated backend may be headless or
managed by runtime configuration; do not ask for visibility unless the user
explicitly needs to watch or assist.

Do not foreground, focus, or activate the user's Chrome unless they ask to
watch. Browser SDK actions should work silently by default.
