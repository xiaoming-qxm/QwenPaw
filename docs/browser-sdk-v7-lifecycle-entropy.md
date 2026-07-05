# Browser SDK V7 Lifecycle Entropy

Generated: 2026-07-05

## V7-A Prompt And Skill Entropy Governance

V7-A keeps Browser Control guidance boring on purpose. The
model-visible browser skills must teach only generic Browser SDK guidance: use
`browser(code=...)`, connect with `Browser.connect`, choose `context="auto"`,
`context="user"`, or `context="isolated"` from browser state, observe after
mutations, and report blockers from diagnostics.

The skill layer is not a verifier harness. It must contain:

- No `browser_use`
- No `DesktopScreenshot`
- No `DesktopScreenShot`
- No `ViewVideo`
- no scenario markers such as fixture success tokens
- no named live-site task wording
- no desktop, media, or old websocket detours

## Verifier Harness Prompt Boundary

The Browser Control verifier may run deterministic scenarios, but
verifier harness prompts stay minimal. Scenario text should say what Browser SDK script
to run and what result to summarize. It should not teach forbidden tools,
legacy routes, exact tool-count policy, or backend fallback rules.

`scripts/verify/browser_control_verify.py` owns scenario checks through
`HarnessPromptSpec`. The spec separates:

- user-visible instruction text
- deterministic Browser SDK scenario code
- `required_success_marker`
- `required_context`
- `required_backend_id`
- user-backend requirements
- request context such as fixture approval policy
- forbidden-tool evidence policy

Verifier classification, not skill prose, decides whether a run passed. A
report passes only when task output, `/api/extension/traces`, backend route
evidence, and forbidden-tool evidence satisfy the scenario metadata.

## Removed Hook Residual Policy

The removed hook residual policy applies to
`plugins/bundle/browser-control/hooks`. The only source file expected in that
directory is `__init__.py`.

These removed modules must raise `ImportError`:

- `hooks.session_hook`
- `hooks.prompt`
- `hooks.context_handler`

The loader must not return stale `sys.modules` entries for removed hook modules,
and `__pycache__` must not contain stale bytecode for those removed modules.
If a removed hook is needed again, it must return as a new reviewed source file,
not through bytecode residue or implicit plugin loader behavior.

## V7-C Complex Deterministic Scenario Matrix

Deterministic acceptance comes from local complex fixtures, not live websites.
The verifier owns two local V7-C commands:

- `complex-isolated` runs `scripts/verify/browser_control_complex_fixture.html`
  through `browser(code=...)` and requires `isolated.playwright` trace
  evidence.
- `complex-user` runs the same local fixture through `browser(code=...)`,
  requires `user.chrome_extension` trace evidence, uses
  `approval_level=OFF` only for deterministic local fixture mutation, and
  requires user-backend cleanup evidence for QwenPaw-owned tabs.

The fixture covers async rendering, delayed content, scrollable lists,
duplicate labels, form validation, a confirmation dialog, navigation state,
and embedded iframe plus shadow DOM surfaces without external network access.
Complex verifier runs fail instead of passing when trace evidence shows stale
observation after mutation, forbidden tool usage, repeated no-progress action
failures, backend route mismatch, or residual QwenPaw-owned user tabs.

Live field tests are opt-in only. Live sites can still provide manual field
evidence, but they are not deterministic acceptance gates. Login, CAPTCHA,
risk control, and payment or order-submission flows must be classified as
blocked. The verifier must not automate purchase, payment, order submission,
or account-changing live-site actions without explicit approval.

## V7-D Coverage-Proven Compatibility Removal

V7-D removes compatibility remnants only after replacement behavior is covered
by focused tests. The Browser Control Native Host now requires the manifest
entry file `browser-bridge-hosts.json`. Setup writes that file, and status or
self-test checks report `native_host_repair_required` when a machine only has
the old single-config shape. The repair command is:

```bash
qwenpaw setup-extension --yes --reset
```

Browser SDK errors now expose the V6 error taxonomy directly. Tool results and
SDK exception payloads use `BrowserErrorCode` plus `code`, `outcome`,
`recovery_hint`, and trace event identifiers as the supported contract.

Browser Control runtime state uses `ControlState` as the internal contract. A
single explicit adapter boundary converts external workspace mappings through
`control_state_from_mapping` and writes results back through
`sync_control_state_to_mapping`. Engine helpers should use typed fields rather
than old dict-shaped state as their normal input.

The V7-D runtime residual scan covers Browser SDK runtime code, Browser runtime
code, the Browser Control plugin, and the verifier. It blocks removed hot-path
terms, removed websocket route names, removed remote bridge references, removed
error payload fields, and removed ControlState compatibility APIs from runtime
source.

## V7 Backlog

### isolated-backend capability-class backlog

The V7 backlog includes future isolated-backend capability-class validation.
Future V7 work should add an isolated-backend capability-class validation
matrix for `isolated.playwright`. That work should classify generic Browser SDK
capabilities such as navigation, observation, extraction, download-like reads,
form interaction, and unsupported operations. A `capability_missing` result
should point to a generic Browser SDK capability gap and must not encourage
site-specific patches.

This is not V7-A scope. V7-A only records the backlog item and preserves the
prompt boundary so future capability work does not drift into model-visible
site-specific instructions.
