# Browser Control V8-A Product Truth Audit

Generated from `scripts/verify/browser_control_truth_audit.py`.
This report is a local repository audit; it does not start QwenPaw, open Chrome, call network, or inspect a user profile.

## Capability Matrix

| Capability | Gap Status | Isolated | User | Follow-Up |
|---|---|---|---|---|
| navigation.open | supported | supported | supported | none |
| navigation.history | supported | supported | supported | none |
| observation.snapshot | supported | supported | supported | none |
| observation.screenshot | supported | supported | supported | none |
| extraction.structured | partial | partial | partial | V8-B |
| forms.type | supported | supported | supported | none |
| forms.select | supported | supported | supported | none |
| forms.submit_guard | partial | partial | partial | V8-D |
| dialogs.confirm | supported | supported | supported | none |
| dom.iframe | partial | partial | partial | V8-E |
| dom.shadow | partial | partial | partial | V8-E |
| tabs.multi_tab | supported | supported | supported | none |
| files.download_read | supported | supported | supported | none |
| files.upload_select | supported | supported | supported | none |
| lifecycle.cleanup | supported | supported | supported | V8-C |
| routing.context_resolution | supported | supported | supported | none |
| policy.approval | partial | partial | supported | V8-D |
| trace.evidence | supported | supported | supported | none |
| ux.readiness | partial | partial | supported | V8-D |

## Confirmed Support

| Capability | Product Task | Public API |
|---|---|---|
| navigation.open | Open or navigate a browser tab to a URL. | Browser.tabs.open(url), Tab.actions.navigate(url) |
| navigation.history | Move backward, forward, or reload in tab history. | Tab.actions.back(), Tab.actions.forward(), Tab.actions.reload() |
| observation.snapshot | Read a structured accessibility/text snapshot. | Tab.snapshot() |
| observation.screenshot | Capture a screenshot artifact for visual evidence. | Tab.screenshot() |
| forms.type | Type or fill text into form fields. | Tab.actions.type(target, text), Tab.actions.press(key) |
| forms.select | Select an option in a native select control. | Tab.actions.select(target, value) |
| dialogs.confirm | Handle confirmation, alert, and prompt dialogs. | Tab.actions.dialog(accept=True), Tab.actions.dialog(accept=False) |
| tabs.multi_tab | List, open, select, and close multiple tabs. | Browser.tabs.list(), Browser.tabs.open(), Browser.tabs.select(), Tab.close() |
| files.download_read | Read files downloaded by browser interactions. | Tab.actions.download(target) |
| files.upload_select | Select local files for file upload controls. | Tab.actions.upload(target, file_path) |
| lifecycle.cleanup | Release owned and borrowed tabs at request boundaries. | Browser.close(), Tab.close() |
| routing.context_resolution | Route public tasks to isolated and user-state tasks to user. | Browser.connect(context=...) |
| trace.evidence | Emit backend, context, action, and status evidence. | BrowserTraceEvent, get_browser_trace_events() |

## Capability Gaps

Gap categories covered here: `missing`, `partial`, `internal_only`.

| Capability | Gap Status | Route | Current Evidence |
|---|---|---|---|
| extraction.structured | partial | V8-B | src/qwenpaw/browser_sdk/extract.py, src/qwenpaw/browser_sdk/extract.py, complex-isolated, complex-user |
| forms.submit_guard | partial | V8-D | src/qwenpaw/browser_sdk/policy.py, src/qwenpaw/browser_sdk/backends/user.py:action, src/qwenpaw/browser/approval_policy.py, fixture, taobao-live:safety-gated |
| dom.iframe | partial | V8-E | scripts/verify/browser_control_v8_capability_fixture.html:capability-frame, scripts/verify/browser_control_v8_capability_fixture.html:capability-frame, v8-capability-isolated, v8-capability-user |
| dom.shadow | partial | V8-E | scripts/verify/browser_control_v8_capability_fixture.html:capability-shadow-host, scripts/verify/browser_control_v8_capability_fixture.html:capability-shadow-host, v8-capability-isolated, v8-capability-user |
| policy.approval | partial | V8-D | src/qwenpaw/browser_sdk/policy.py, src/qwenpaw/browser_sdk/backends/user.py:action, src/qwenpaw/browser/approval_policy.py, fixture, taobao-live:safety-gated |
| ux.readiness | partial | V8-D | src/qwenpaw/browser_sdk/browser.py:diagnostics, console/src/pages/Settings/browserControlReadiness.tsx, plugins/bundle/browser-control/routes.py:/extension/status, bridge-disconnected, frontend focused tests |

## Entropy Findings

- `clean` `model_visible_and_verifier` : No Browser Control hot-path legacy instructions found.

## Legacy Evidence Policy

Old `browser_use` local tests and samples are historical capability evidence only. They map to product capability IDs and do not define Browser SDK public API names.

- Classified legacy evidence files: `35`
- Public API names are sourced from `product_matrix.py`.
- Removal candidates and compatibility cleanup belong to V8-C.

- Legacy evidence maps to: `extraction.structured`, `forms.select`, `forms.submit_guard`, `lifecycle.cleanup`, `navigation.history`, `navigation.open`, `observation.snapshot`, `routing.context_resolution`, `tabs.multi_tab`, `trace.evidence`

## V8 Follow-Up Routing

| Spec | Scope |
|---|---|
| `V8-B` | SDK capability gaps |
| `V8-C` | lifecycle and hard cleanup |
| `V8-D` | product UX readiness |
| `V8-E` | deterministic and live verification |
