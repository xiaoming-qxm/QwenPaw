---
name: browser
description: "Use browser(code=...) with the Browser SDK for web research, tab work, and user Chrome tasks."
metadata:
  builtin_skill_version: "13.1"
  qwenpaw:
    emoji: ""
    requires: {}
---

# Browser

Use `browser(code=...)` as the normal browser automation entry. Inside that
code, `Browser`, `VisualRegion`, `Grounding`, and `TargetQuery` are already injected: do not import
`browser_use`, `Browser`, or any legacy browser package. VisualRegion and Grounding are already injected; TargetQuery is already injected; never write
`from browser_sdk import VisualRegion, Grounding`, because it is rejected
before execution. Connect with the Canonical Browser SDK:

```python
browser = await Browser.connect(context="auto")
open_result = await browser.tabs.open("https://example.com")
if (
    open_result.status in {"SUCCEEDED", "PARTIAL"}
    and open_result.opened_tabs
):
    tab = await browser.tabs.select(open_result.opened_tabs[0])
    snapshot = await tab.snapshot()
```

Action-First, Controlled Primitive:

- Use primitives for tab lifecycle, observation, page metadata, extraction,
  waiting, and close/release.
- Use `actions.*` for page interaction and state changes.
- After any state-changing action, observe again with `tab.snapshot()` or
  `tab.screenshot()` before the next mutation.

Canonical values are Runtime-issued. An item in `opened_tabs` or the result of
`tabs.list()` is itself a `TabSummary` selection token: pass it directly to
`browser.tabs.select(summary)`. Do **not** access `summary.ref` or create a
replacement token. To inspect its safe metadata use `summary.title`,
`summary.url`, or `summary.to_dict()`; if you open a tab for the task, select
`open_result.opened_tabs[0]` directly instead of listing and rediscovering it.
The selected `Tab` is an operation receiver, not a metadata record: it has no
`.url` or `.title`. Keep URL/title checks on the `TabSummary`, then call
`snapshot()` on the selected `Tab` for page evidence.
Use the `TargetRef` from fresh evidence. Every potentially state-changing click
must carry a typed postcondition constructed from the **pre-action** snapshot;
do not call `click(target)` without one:

```python
snapshot = await tab.snapshot(limit=50)
target = snapshot.targets[0]
before = snapshot.observation.context
expect = ActionExpectation.transition(
    BrowserCondition.all(PageCondition.document_changed(before))
)
terminal = await tab.actions.click(target.ref, expect=expect)
```

For a link with an observed destination, verify that destination instead of
guessing page text:

```python
link = None
for item in snapshot.targets:
    if item.observed_url:
        link = item
        break
if link is not None:
    expect = ActionExpectation.transition(
        BrowserCondition.all(PageCondition.url(link.observed_url, match="prefix"))
    )
    terminal = await tab.actions.click(link.ref, expect=expect)
```

For text entry into an editable control, use controlled `paste`, which
verifies the target value. Take a fresh snapshot before the next mutation:

```python
search_box = None
for item in snapshot.targets:
    if "editable" in item.states:
        search_box = item
        break
if search_box is not None:
    terminal = await tab.actions.paste(search_box.ref, "quiet keyboard")
    snapshot = await tab.snapshot()
```

For virtualized lists, use the public Canonical scroll action—not legacy
helpers such as `scroll_down`. Observe again after every page scroll:

```python
terminal = await tab.actions.scroll(direction="down", amount="page")
snapshot = await tab.snapshot()
```

For product/result pages where header targets crowd out ordinary semantic links,
use the injected `TargetQuery` first. It performs bounded semantic discovery but
delivers only the matching targets, so do not broaden screenshots or
`VisualRegion` just to find an ordinary link:

```python
product_links = await tab.snapshot(
    query=TargetQuery(
        role="link",
        name="quiet keyboard",
        match="contains",
    ),
    limit=10,
)
product_links
```

If a mutation returns `UNCERTAIN`, `BLOCKED`, or `FAILED`, do not blindly
retry a write. Observe the current state first and use the returned `problem`
and `retry` for safe recovery.

`tab.wait_for(...)` is not active in the current Canonical surface. Do not
call it or use fixed sleeps; **never import asyncio or call
`asyncio.sleep` (or another fixed wait).** To observe a page after it changes
or loads, take a fresh `tab.snapshot()` instead.

Before a viewport `tab.screenshot()`, take a fresh `tab.snapshot()` on that
selected tab; the snapshot supplies the evidence context that binds the image.
`ScreenshotResult` has a task-owned `image` `ResourceHandle`, never a local
`.path`. Do not inspect a screenshot's undocumented fields; leave `screenshot`
as the final expression to deliver it.

When a product card or button is inside closed shadow DOM and the ordinary
snapshot has no usable semantic target, do not guess CSS, JavaScript, or raw
click coordinates. First establish context with a small `snapshot(limit=50)`,
then take **one** viewport screenshot. After inspecting the image, use its
`visual_context` and the target's normalized image rectangle (0 through 1) to
ground the visual region into a semantic `TargetRef`:

```python
snapshot = await tab.snapshot(limit=50)
visual = await tab.screenshot()
visual
```

In the next Browser call, while the screenshot remains fresh:

```python
region = VisualRegion(
    visual.visual_context,
    x=0.10, y=0.25, width=0.30, height=0.35,
)
ground = await tab.snapshot(scope=region)
if ground.grounding is Grounding.EXACT:
    target = ground.targets[0]
```

Only `Grounding.EXACT` yields an actionable target. For `MULTIPLE`, narrow the
region and ground again; for `NO_MATCH`, `STALE`, or `UNAVAILABLE`, observe
again or stop. Never turn image coordinates into a direct click. To avoid
exhausting model context, reuse the current observation and screenshot for one
page state—do not repeatedly screenshot or take full snapshots for the same
target.

Leave a result object such as `snapshot` or `terminal` as the final
expression when it needs to be reported. Do not access undocumented fields
such as `snapshot.observation.title` or print a raw snapshot; use
`snapshot.targets` only to select fresh Runtime-issued targets in code.
Each item in `snapshot.targets` is a `TargetSummary`: read its direct
`.role`, `.name`, `.states`, `.observed_url`, and `.ref` fields. The Browser
code sandbox does not expose Python introspection helpers such as `hasattr`,
so do not probe for optional fields; use the documented fields directly.
There is no `target.observation` object. Do not use desktop screenshot tools:
after a fresh snapshot, leave `await tab.screenshot()` as the final expression
when visual context is needed.

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
dispatchers. Recover with fresh observations and the documented Canonical
APIs.
