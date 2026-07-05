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
