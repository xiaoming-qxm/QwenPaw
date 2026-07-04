# Control Mode Constraints

## Use The Chrome Extension Bridge

- Use `browser(code=...)` with
  `Browser.connect(context="user", requires_user_state=True)` for tasks that
  require the user's Chrome profile, login state, cart, account pages, or
  existing tabs.
- Do not use non-SDK browser tools, shell commands, HTTP clients, local files,
  desktop/media inspection tools, screenshots outside the SDK, or headless
  browser substitutes to inspect user browser state.
- If `tab.screenshot()` returns a file path, treat it as Browser SDK evidence
  only. Do not inspect that file through non-SDK tools.
- The Chrome Extension bridge must be connected. If it is disconnected, ask
  the user to enable or refresh the extension.

## Stay Silent By Default

- Work silently in the user's real Chrome session.
- Do not activate, focus, or foreground Chrome unless the user asks to watch.
- The user must be able to assist, pause, or stop without focus theft.

## Stop And Release

If the user asks to stop, cancel, end, or release Chrome control, run a
`browser(code=...)` call that connects with
`Browser.connect(context="user", requires_user_state=True)` and releases the
browser session, then report release.

## Goal Mode Execution

When operating under Goal mode:

- The current agent is the browser operator. Execute the task directly with
  `browser(code=...)` and Browser SDK calls.
- Do not dispatch workers, call `spawn_subagent`, delegate to other agents, or
  ask someone else to operate the browser.
- Follow observe-act-verify for each action.
- When the objective is verified complete, call `update_goal(status="complete")`.
- If blocked by auth, CAPTCHA, payment, or disconnected bridge, call
  `update_goal(status="blocked")` and report what the user needs to do.
