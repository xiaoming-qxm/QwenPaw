---
name: browser-control
description: Use Browser Control Python REPL to operate Chrome through the QwenPaw Browser SDK.
activation:
  when_tools_available: ["python_repl"]
---

# Browser Control Skill

## Overview

Use this skill when a worker has the Browser Control Python REPL and needs to
operate a user's Chrome session through QwenPaw Browser Control.

Use the `python_repl` tool and the Browser Control SDK. The REPL preloads a
`browser` variable. If the environment was reset, recreate it inside
`python_repl` with:

```python
from sdk import Browser
browser = await Browser.connect()
```

If a browser call raises `BridgeDisconnected`, refresh the preloaded object
once before reporting a blocker:

```python
browser = await browser.connect()
```

Do not instantiate `Browser()` directly. If reconnecting still fails, stop
and report the bridge as blocked instead of repeating the same operation.

Common hot-path calls are:

```python
# Open a fresh SDK-owned tab for a new task.
tab = await browser.tabs.open("https://example.com")

# Inspect tabs only when the task asks for existing browser state.
owned_infos = await browser.tabs.list()
all_infos = await browser.tabs.list(all=True)
for info in all_infos:
    print(info.id, info.title, info.url)

# Attach to an existing tab only when you need Tab methods.
tab = await browser.tabs.get(tab_id)

# Observe, read metadata, and close.
snap = await tab.snapshot()
info = await tab.page_info()
await tab.close()
```

Do not call `browser.tabs()` or private attributes such as `browser._state`.
If a common API is unclear, run `print(await browser.documentation())` once
instead of probing private state or guessing method names.

Use SDK code inside `python_repl` to inspect tabs, take snapshots, act on refs,
and verify the result. Call `await browser.documentation()` when you need the
API reference.

Browser Control is an observe-act-verify loop over the real browser: observe
the current page, perform one browser action, then verify the visible result
before continuing or reporting completion. Apply read-after-write discipline:
after a state-changing action, verify from a fresh observation or an
authoritative state view before declaring success, failure, or retrying the
same side effect.

## Includes

- [ops.md](ops.md): browser operation rules and read-after-write verification.
- [blocker-report.md](blocker-report.md): blocker detection and reporting.
- [control-mode.md](control-mode.md): control-mode constraints and bridge rules.
