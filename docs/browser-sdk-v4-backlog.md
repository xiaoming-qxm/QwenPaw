# Browser SDK V4 Backlog

V3 unified the backend package shape under the Browser SDK:
`qwenpaw.browser_sdk.backends.isolated` owns `isolated.playwright`, and
`qwenpaw.browser_sdk.backends.user` owns `user.chrome_extension`.

The old implementation paths were removed without compatibility re-export
modules. V4 work should build on the new package shape instead of restoring
`qwenpaw.browser_sdk.isolated_backend` or
`plugins/bundle/browser-control/user_backend.py`.

## Deferred Work

- Add richer backend health telemetry for both `isolated.playwright` and
  `user.chrome_extension`, including bridge availability, runtime startup
  failures, and policy-denial metadata.
- Define a stable backend diagnostics API that can be consumed by the console,
  plugin status pages, and acceptance logs without importing backend
  implementation modules directly.
- Expand user-state acceptance coverage around approval-gated sensitive actions
  once a live Chrome Extension bridge and explicit account-operation approval
  are available.
- Unify the Browser Control REPL/OOP SDK package shape, including
  `plugins/bundle/browser-control/sdk/browser.py` and
  `plugins/bundle/browser-control/sdk/tab.py`. This is V4 scope, not V3 scope:
  V3 intentionally migrates backend package shape only, and must not move or
  redesign the plugin REPL/OOP SDK facade.
