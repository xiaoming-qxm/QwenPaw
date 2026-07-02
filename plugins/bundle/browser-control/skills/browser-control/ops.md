# Browser Operation Rules

## Observe, Act, Verify

- Use `python_repl` and the preloaded `browser` SDK for real Chrome work.
- Start with `await browser.tabs.list()` and `await browser.tabs.get(tab_id)`,
  then observe with `await tab.snapshot()`.
- If you are unsure about SDK signatures, call
  `print(await browser.documentation())` in `python_repl`; do not guess.
- Common calls:
  `tab = await browser.tabs.open(url)`,
  `snap = await tab.snapshot()`,
  `await tab.wait_for(2)`,
  `await tab.wait_for(wait_time=2)`,
  `await tab.scroll(direction="down", amount="page")`.
- `snapshot()` takes no arguments. Do not call `snapshot(full=True)`.
- `scroll` only accepts keyword arguments such as `direction` and `amount`.
- JavaScript evaluation is not available in control mode. Do not call
  `tab.evaluate` or `tab.action("evaluate", ...)`.
- After each navigation, click, type, selection, reload, or wait,
  observe again.
- Prefer refs or selectors from the latest snapshot; use visible text only
  as a fallback.
- If a click appears unchanged, re-observe or screenshot before trying
  another route.

## Read-After-Write Verification

- After submitting, saving, adding, removing, selecting, following, or
  updating settings, read the resulting state back.
- If async network activity happened but a badge, counter, button, or
  page fragment still shows the old value, treat the page as stale.
- Verification ladder: `wait_for` then `snapshot`; if stale, `reload` then
  `snapshot`; if needed, open the canonical list/detail/status/cart page.
- Never repeat the same state-changing click before authoritative read-back.

## Tab And Navigation Rules

- A successful `claim_tab` response means the tab is ready; observe it
  instead of opening duplicates.
- Keep one claimed tab per target unless the user asks for multiple tabs.
- Keep `allow_new_context` false unless a separate tab/window is required.

## Visual Fallback

- Use `snapshot` first. Use `screenshot` when snapshot is empty, generic,
  visual/canvas based, or misses key state. Trust the freshest observation.
- Do not inspect screenshot file paths with local file/media tools. If the
  Browser SDK observations are insufficient, report a blocker instead of
  leaving the SDK loop.
- If a web search result page returns a degraded snapshot after one
  wait/reload, switch to another browser-accessible web UI route, such as a
  different search provider or the site's own search page. Do not repeat the
  same degraded snapshot loop.

## Supported Actions

Use SDK methods such as `browser.tabs.list()`, `browser.tabs.get(tab_id)`,
`tab.snapshot()`, `tab.click(...)`, `tab.type(...)`, `tab.press_key(...)`,
`tab.navigate(...)`, `tab.hover(...)`, `tab.scroll(...)`,
`tab.select_option(...)`, `tab.wait_for(...)`, and `browser.close()`.
