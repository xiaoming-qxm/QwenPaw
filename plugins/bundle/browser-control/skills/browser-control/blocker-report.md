# Browser Blocker Report

BrowserGate emits structured blocker output from Browser SDK trace, approval,
context, backend, and progress evidence. The browser-control skill only
documents the fields agents should preserve when reporting that output.

## Fields

- `blocked_reason`: machine-readable Browser SDK reason.
- `context`: selected Browser SDK context, such as `context="user"` or
  `context="isolated"`.
- `backend`: selected backend id.
- `approval_state`: approval metadata when a sensitive action requires or
  receives a user decision.
- `required_user_action`: concrete user-side action needed to unblock work.
- `status`: `blocked` or `failed`.

## Evidence Sources

- Authentication and CAPTCHA evidence comes from Browser SDK error taxonomy.
- Bridge availability comes from `Browser.diagnostics(context="user")` and
  backend trace metadata.
- Approval decisions come from QwenPaw approval metadata and Browser trace
  `approval_state`.
- Freshness and no-progress evidence comes from BrowserGate recovery decisions.
