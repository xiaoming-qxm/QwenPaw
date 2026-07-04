# Browser Operation Rules

## Observe, Act, Verify

- Use `browser(code=...)` and Browser SDK calls for Chrome work.
- For a new user task, connect with
  `Browser.connect(context="user", requires_user_state=True)`, open or select
  the relevant tab, then observe with `await tab.snapshot()`.
- Opening a tab is not an observation. After `browser.tabs.open(...)`, call
  `await tab.snapshot()` before scrolling, clicking, typing, or selecting.
- Prefer refs from the latest snapshot. Snapshot refs are scoped to the
  observation that produced them; do not reuse refs from older snapshots.
- Use semantic targets before coordinates: refs, visible text, stable
  selectors, then coordinates only when SDK evidence identifies the target.
- Do not convert screenshots into coordinates for state-changing actions such
  as add-to-cart, checkout, confirm, delete, or select-all.
- `tab.evaluate(..., read_only=True)` is a read helper. It does not satisfy
  the observe-before-act guard and must not mutate page state.
- After each navigation, click, type, selection, reload, scroll, or wait,
  observe again before the next mutating action.

Common calls inside `browser(code=...)`:

```python
browser = await Browser.connect(context="user", requires_user_state=True)
tab = await browser.tabs.active()
await tab.actions.navigate("https://example.com")
snapshot = await tab.snapshot()
await tab.actions.click({"ref": "r1_e22"})
snapshot = await tab.snapshot()
```

## Read-After-Write Verification

- After submitting, saving, adding, removing, selecting, or updating settings,
  read the resulting state back.
- If an authoritative cart, list, status, or detail page already proves the
  requested state, advance to the next subtask instead of repeating the write.
- Never repeat the same state-changing click before authoritative read-back.

## Tab And Navigation Rules

- Keep one claimed or opened tab per target unless the user asks for multiple
  tabs.
- Use existing tabs only when the user asks to inspect, clean up, or continue
  work in a specific user browser state.
- Do not reuse unrelated old tabs to answer a new task.

## Visual Fallback

- Use `snapshot` first. Use `screenshot` when the snapshot is empty, generic,
  visual/canvas based, or misses key state.
- Do not inspect screenshot file paths with local file/media tools.
- If Browser SDK observations are insufficient, report a blocker instead of
  leaving the SDK loop.

## Completion Rules

- Do not stop with a text-only response while a browser task is active.
- Verify the final state with a fresh `tab.snapshot()` before reporting.
- If stuck after two fresh observations with no progress, change approach or
  report a blocker.
