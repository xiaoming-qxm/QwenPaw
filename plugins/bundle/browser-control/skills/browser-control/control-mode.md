# Control Mode Constraints

## Use The QwenPaw Chrome Bridge

- Browser Control uses the QwenPaw Chrome extension bridge through
  the `python_repl` Browser SDK.
- Do NOT use `browser_use`, `execute_shell_command`, shell commands,
  `curl`, HTTP clients/APIs, headless browsers, managed-CDP, JavaScript
  snippets, or local files as substitutes for browser state.
- The only browser-action entrypoint is `python_repl` with the preloaded
  Browser SDK (`browser.tabs`, `tab.navigate`, `tab.snapshot`, `tab.click`,
  `tab.type`, and related SDK calls).
- If the bridge is disconnected, ask the user to enable the extension.

## Stay Silent By Default

- Work silently in the user's real Chrome session.
- Do not activate, focus, or foreground Chrome unless the user asks to
  watch.
- The user must be able to assist, pause, or stop without focus theft.

## Stop And Release

- If the user asks to stop, cancel, end, or release Chrome control, call
  `await browser.close()` in `python_repl` immediately, then report release.

## Mission Mode Auto-Execution

When operating under `/mission` mode:
- Browser-control missions override generic Mission Mode worker-dispatch
  guidance. The current agent is the browser operator for these stories.
- Do NOT dispatch workers, call `spawn_subagent`, delegate to other agents,
  or ask a worker to operate the browser.
- After writing prd.json, immediately update loop_config.json:
  set `current_phase` to `"execution_confirmed"`.
- Do NOT wait for user confirmation -- the user's /mission command
  already expresses clear intent.
- Continue executing stories using python_repl + Browser SDK only.
- After completing each story, update prd.json to set its `passes` to `true`.
