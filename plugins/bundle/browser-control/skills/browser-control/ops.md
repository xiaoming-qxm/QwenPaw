# Browser Operation Rules

## Observe, Act, Verify

- Use `python_repl` and the preloaded `browser` SDK for real Chrome work.
- For a new user task, start with
  `tab = await browser.tabs.open(url_or_search_page)` and then observe with
  `await tab.snapshot()`.
- Opening a new tab is not an observation. After
  `browser.tabs.open(...)`, call `await tab.snapshot()` before scrolling,
  clicking, typing, or selecting.
- `await browser.tabs.list()` returns tabs already managed by this SDK
  session. Use `await browser.tabs.list(all=True)` and
  `await browser.tabs.get(tab_id)` only when the user asks you to use,
  inspect, clean up, or continue work in a specific existing tab. Do not reuse
  unrelated old tabs to answer a new task.
- If you are unsure about SDK signatures, call
  `print(await browser.documentation())` in `python_repl`; do not guess.
- Common calls:
  `tab = await browser.tabs.open(url)`,
  `snap = await tab.snapshot()`,
  `await tab.click(ref="r1_e22")`,
  `await tab.scroll(direction="down", amount="page")`,
  `await tab.scroll(direction="up", amount="top")`,
  `await tab.wait_for(2)`,
  `snap = await tab.snapshot()`.
- Prefer a direct, browser-visible URL when the user intent can be expressed
  as a page route, search URL, list URL, detail URL, cart URL, or status URL.
  Do not start from a homepage and type into a search box when an equivalent
  URL route is available.
- `snapshot()` takes no arguments. Do not call `snapshot(full=True)`.
- `scroll` only accepts keyword arguments such as `direction` and `amount`.
  Use `amount="top"` or `amount="bottom"` for absolute page jumps when the
  needed control is expected near the start or end of a long page.
- JavaScript evaluation is not available in control mode. Do not call
  `tab.evaluate` or `tab.action("evaluate", ...)`.
- `wait_for` is a synchronization action. It may follow a click, navigation,
  type, or scroll without another snapshot first, but it makes previous
  observations stale. Always observe after `wait_for` before the next
  mutating action.
- After each navigation, click, type, selection, reload, scroll, or wait,
  observe again before the next mutating action.
- Prefer refs from the latest snapshot. If the target label is known but
  missing because the snapshot is truncated, generic, or AX-only, use
  `await tab.click(text="visible label")`; the SDK can locate visible DOM
  text and scroll offscreen controls into view. Use CSS selectors only for
  stable semantic selectors, not guessed class names.
- Snapshot refs are snapshot-scoped string identifiers. Use the complete
  quoted ref exactly as shown in the latest snapshot, such as
  `await tab.click(ref="r3_e22")`; do not strip the `r3_` prefix, invent
  shorter `e22` refs, or reuse refs copied from older snapshots.
- Link refs may include an `href`; clicking that ref uses SDK-managed
  same-tab navigation when possible, so prefer the fresh ref over coordinate
  clicks for search results and product links.
- `action_target` lines summarize visible controls that modern pages expose
  poorly through accessibility trees. If an action target has a `[ref=...]`
  value such as `[ref=r4_e17]`, click that complete quoted ref first. If it
  has no ref, prefer
  `tab.click(text="...")`; use x/y coordinates only when ref and text
  targeting both fail.
- Icon-only controls may appear with synthesized labels such as `add cart`,
  `cart`, or `buy` when the DOM exposes that semantic through stable
  attributes. Prefer those refs over visual coordinate guesses. If a
  synthesized icon label appears without a ref, use text targeting such as
  `await tab.click(text="add cart")`; the SDK resolves that label from stable
  element attributes instead of guessed coordinates.
- Use an action candidate budget: once the current page exposes a plausible
  next action such as add-to-cart, buy, checkout, confirm, delete, or search,
  try the strongest ref/text candidate within the next browser action. If it
  fails after one fresh observation, try a different real candidate or route.
  Do not keep inspecting listings, screenshots, or broad page snapshots while
  a page-level action target already matches the task.
- Use coordinates only after SDK evidence identifies the target's position;
  do not guess page coordinates from a generic layout.
- Do not convert screenshots into coordinates for state-changing actions such
  as add-to-cart, checkout, confirm, delete, or select-all. Treat screenshots
  as observation only, then return to a ref/text/semantic action target or
  report a blocker if the SDK cannot expose a real target.
- If a click appears unchanged, re-observe or screenshot before trying
  another route.
- Snapshot output starts with `page_state` when scroll metrics are available.
  Use `at_top`, `at_bottom`, and `scroll_percent` to decide whether another
  scroll is meaningful; do not repeat page scrolls once the expected boundary is
  reached.
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
- Treat an authoritative state page as a subtask boundary. For example, if a
  cart/status/list page shows an item or setting that satisfies the user's
  requested quantity/category, advance to the next requested subtask; do not
  add another item, repeat the same write, or return to search unless the user
  explicitly asked for more.
- Treat a single requested write, such as adding one product, selecting one
  option, deleting one matching row, or saving one setting, as complete after
  the first authoritative read-back proves the requested item/category/count is
  present; adding another matching item is incorrect unless the user
  explicitly asked for multiple items or a different item.
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

Use SDK methods such as `browser.tabs.list()`, `browser.tabs.list(all=True)`,
`browser.tabs.get(tab_id)`,
`tab.snapshot()`, `tab.click(...)`, `tab.type(...)`, `tab.press_key(...)`,
`tab.navigate(...)`, `tab.hover(...)`, `tab.scroll(...)`,
`tab.select_option(...)`, `tab.wait_for(...)`, `tab.close()`,
`browser.tabs.close(tab_id)`, and `browser.close()`.
