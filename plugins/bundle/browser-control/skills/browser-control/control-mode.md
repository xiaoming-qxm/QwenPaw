# Control Mode Constraints

## Use The QwenPaw Chrome Bridge

- Browser Control uses the QwenPaw Chrome extension bridge through
  the `python_repl` Browser SDK.
- Do NOT use `browser_use`, `execute_shell_command`, shell commands,
  `curl`, HTTP clients/APIs, headless browsers, managed-CDP, JavaScript
  snippets, local files, or file-reading tools as substitutes for browser
  state.
- Do NOT use `read_file`, `grep_search`, `glob_search`, `view_image`,
  `view_video`, `desktop_screenshot`, `Read`, `Grep`, `Glob`,
  `ViewImage`, `ViewVideo`, or `DesktopScreenshot` to inspect browser
  pages or screenshots.
- The only browser-action entrypoint is `python_repl` with the preloaded
  Browser SDK (`browser.tabs`, `tab.navigate`, `tab.snapshot`, `tab.click`,
  `tab.type`, and related SDK calls).
- If `tab.screenshot()` returns a file path, treat it as an evidence
  artifact only. Do not read or view that file through non-SDK tools.
- `tab.click(x=..., y=...)` uses viewport CSS pixels. If you choose a point
  from a `tab.screenshot()` image, use its `coordinate_space` scale to
  convert screenshot pixels to viewport coordinates before clicking.
  Coordinates outside the current viewport are invalid.
- Do not repeat the same nearby coordinate after a fresh observation shows
  no page change. Switch to a semantic ref/text target, a direct route, or
  report the blocker.
- Snapshot refs are scoped to the observation that produced them. Copy the
  complete latest ref, for example `r3_e22`; do not strip the `r3_` prefix or
  reuse refs from older snapshots after the page changes.
- For product-selection or shopping tasks, treat each product/listing as a
  candidate. If the current candidate lacks the required action, return to
  the listing and try a bounded set of different real candidates or filters
  before declaring the task blocked. Use only real hrefs/refs observed from
  the page; do not invent item ids, API URLs, cart URLs, or mobile detail
  links.
- If a call raises `BridgeDisconnected`, run
  `browser = await browser.connect()` once and retry from a fresh SDK
  observation. If reconnecting still fails, ask the user to enable or refresh
  the extension.

## Stay Silent By Default

- Work silently in the user's real Chrome session.
- Do not activate, focus, or foreground Chrome unless the user asks to
  watch.
- The user must be able to assist, pause, or stop without focus theft.

## Stop And Release

- If the user asks to stop, cancel, end, or release Chrome control, call
  `await browser.close()` in `python_repl` immediately, then report release.

## Goal Mode Execution

When operating under Goal mode:
- The current agent is the browser operator. Execute the task directly with
  `python_repl` and the Browser SDK.
- Use python_repl + Browser SDK only for browser actions.
- Do NOT dispatch workers, call `spawn_subagent`, delegate to other
  agents, or ask someone else to operate the browser.
- Follow observe-act-verify for each action.
- When the objective is fully achieved (verified from browser evidence),
  call `update_goal(status="complete")`.
- If blocked (auth, CAPTCHA, payment, etc.), call
  `update_goal(status="blocked")` and report what the user needs to do.
