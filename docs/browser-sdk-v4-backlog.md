# Browser SDK V4 Backlog

V3 unified the backend package shape under the Browser SDK:
`qwenpaw.browser_sdk.backends.isolated` owns `isolated.playwright`, and
`qwenpaw.browser_sdk.backends.user` owns `user.chrome_extension`.

The old implementation paths were removed without compatibility re-export
modules. V4 work should build on the new package shape instead of restoring
`qwenpaw.browser_sdk.isolated_backend` or
`plugins/bundle/browser-control/user_backend.py`.

V4 hard-removes the obsolete plugin REPL/OOP execution world. The only normal
browser automation route is now the core `browser(code=...)` tool with
`qwenpaw.browser_sdk`.

## Deferred Work

- Add richer backend health telemetry for both `isolated.playwright` and
  `user.chrome_extension`, including bridge availability, runtime startup
  failures, and policy-denial metadata.
- Add a console and plugin-status presentation for `Browser.diagnostics` that
  can be read by users without inspecting logs.
- Document advanced CDP troubleshooting as backend/operator guidance, not as
  the main Browser SDK execution path.
- Expand user-state acceptance coverage around approval-gated sensitive actions
  once a live Chrome Extension bridge and explicit account-operation approval
  are available.
