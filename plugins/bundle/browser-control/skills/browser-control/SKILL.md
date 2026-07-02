# Browser Control Skill

activation:
  when_tools_available: ["python_repl"]

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
