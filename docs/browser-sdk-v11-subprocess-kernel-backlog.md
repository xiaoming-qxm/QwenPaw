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

## Deferred V10 Review Items

These items were found during V10 SPEC execution review and are intentionally
deferred to V11 planning. They should be converted into explicit V11 SPEC
requirements before implementation.

### Broad App Type-Check Gate

V10-C's original final verification includes:

```bash
mypy --ignore-missing-imports src/qwenpaw/browser src/qwenpaw/app src/qwenpaw/hooks
```

The command still fails because of existing `src/qwenpaw/app` type debt outside
the Browser Bridge migration surface. V11 should either fix the broad app mypy
debt or define a repository-approved scoped type-check policy for Browser
features so SPEC final verification is enforceable and unambiguous.

### Product Readiness Field Gate

The V10 product verifier is now evidence-driven and blocks instead of reporting
false success when the service, Browser Bridge extension, or scenario runners
are not ready. V11 should finish the remaining product-readiness field gate:

- Start latest service and verify matching backend commit, frontend
  fingerprint, plugin fingerprint, extension version, and native host version.
- Require Browser Bridge to be connected for user-context scenarios.
- Require default product scenarios, including complex isolated/user fixtures
  and bridge reconnect evidence, to pass before publishing a green readiness
  report.
- Keep blocked reports explicit when external product setup is incomplete.

### Legacy Skill Migration Residue

The skill registry still needs the legacy `browser-control` skill name for
one-time workspace migration into canonical `browser`. V11 should decide the
long-term policy:

- Keep the compatibility token as an approved migration-only exception, with
  residue scans scoped to runtime hot paths.
- Or remove the token after the migration window and require a dedicated
  migration-version marker so old workspace manifests are not reprocessed.

### Tracked Unit Test Policy Cleanup

The V10 branch still changes tracked `tests/unit/...` files, while current
repository policy says non-integration tests for PR development should live
under `tests/local/...`. V11 should either migrate the Browser-related unit
coverage to `tests/local/...` or document an explicit exception for tests that
must remain tracked because CI depends on them.
