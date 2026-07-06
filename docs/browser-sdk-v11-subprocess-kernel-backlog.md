# Browser SDK V11 Subprocess Kernel Backlog

## Goal

V11 should replace `InProcessBrowserCodeExecutor` with a
`SubprocessBrowserCodeExecutor` behind the existing `BrowserCodeExecutor`
protocol. The public `browser(code=...)` tool, `BrowserKernelRuntime`, and
`qwenpaw.browser.sdk` import shape should stay stable.

## Process Boundary

Browser objects created inside the subprocess are proxy facades. They should
send JSON-safe requests to the main process rather than owning browser
backends directly.

The main process remains responsible for:

- Approval policy and approval UI state.
- Browser trace and progress metadata.
- Recovery classification and runtime outcome metadata.
- Backend registry selection.
- Browser bridge and Chrome extension runtime ownership.

## Reused V10 Contract

The subprocess executor must reuse the V10 runtime boundary:

- `BrowserCodeExecutor.execute`, `reset`, `reset_all`, `sweep_idle`, and
  `diagnostics`.
- `CapabilityGuard` policy for rejected imports and builtins.
- JSON-safe execution context and result metadata.
- `BrowserKernelResult` output, return value, error, and artifact schema.
- Runtime-owned TTL sweep after 300 seconds of idle time.
- Runtime-owned reset and reset-all semantics.
- Runtime-owned cancellation trace events.

## Open Work

- Define the subprocess request/response transport.
- Implement proxy Browser/Tab facades that call back into the main process.
- Add process startup, health check, and teardown diagnostics.
- Add artifact transfer for screenshots, downloads, and generated files.
- Add failure taxonomy for subprocess launch, IPC timeout, and worker crash.
