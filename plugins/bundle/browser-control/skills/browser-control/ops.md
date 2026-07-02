# Browser Operation Rules

## Observe, Act, Verify

- Use `python_repl` and the preloaded `browser` SDK for real Chrome work.
- For a new user task, start with
  `tab = await browser.tabs.open(url_or_search_page)` and then observe with
  `await tab.snapshot()`.
- Use `await browser.tabs.list()` and `await browser.tabs.get(tab_id)` only
  when the user asks you to use, inspect, clean up, or continue work in a
  specific existing tab. Do not reuse unrelated old tabs to answer a new task.
- If you are unsure about SDK signatures, call
  `print(await browser.documentation())` in `python_repl`; do not guess.
- Common calls:
  `tab = await browser.tabs.open(url)`,
  `snap = await tab.snapshot()`,
  `await tab.scroll(direction="down", amount="page")`,
  `await tab.wait_for(2)`,
  `snap = await tab.snapshot()`.
- Prefer a direct, browser-visible URL when the user intent can be expressed
  as a page route, search URL, list URL, detail URL, cart URL, or status URL.
  Do not start from a homepage and type into a search box when an equivalent
  URL route is available.
- `snapshot()` takes no arguments. Do not call `snapshot(full=True)`.
- `scroll` only accepts keyword arguments such as `direction` and `amount`.
- JavaScript evaluation is not available in control mode. Do not call
  `tab.evaluate` or `tab.action("evaluate", ...)`.
- `wait_for` is a synchronization action. It may follow a click, navigation,
  type, or scroll without another snapshot first, but it makes previous
  observations stale. Always observe after `wait_for` before the next
  mutating action.
- After each navigation, click, type, selection, reload, scroll, or wait,
  observe again before the next mutating action.
- Prefer refs or selectors from the latest snapshot; use visible text only
  as a fallback.
- If a click appears unchanged, re-observe or screenshot before trying
  another route.
- Keep each `python_repl` browser cell narrow: perform at most one mutating
  browser action, optionally wait for it to settle, then take a fresh
  snapshot. Do not batch click/type/click sequences in one cell.
- If a click, type, selection, or form-submit action times out or leaves the
  page unchanged, retry that exact action sequence at most once after a fresh
  snapshot. On the next failure, change route: use a direct URL, a canonical
  list/detail/status page, a different visible control, or report a real
  blocker when the page evidence requires it.

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
  instead of opening duplicates when the user explicitly selected that tab.
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
