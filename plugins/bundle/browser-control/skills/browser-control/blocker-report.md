# Blocker Reporting

## What Counts As A Blocker

Report a blocker only when browser evidence shows authentication, CAPTCHA,
risk check, automation block, denied approval, payment/checkout/final
purchase, irreversible account/security change, unrelated sensitive data,
an unverifiable exact user constraint, or a destructive action that the user
did not explicitly request or authorize.

A stale ref, failed click, missing element, slow load, unclear state, or
unchanged badge is recoverable. Re-observe and try another visible route.

## Reporting Rules

- Do not invent page contents or relax constraints.
- Do not mark near matches, cheaper substitutes, or unverified results as
  complete.
- If blocked, keep the story incomplete and record `blocked_reason`.
- Tell the user exactly what action is needed.

## Goal Completion Protocol

- Before calling `update_goal(status="complete")`:
  1. Execute a final verification snapshot (`await tab.snapshot()`).
  2. Confirm the objective is fully met from browser evidence.
  3. If any aspect is uncertain, continue working -- do not mark complete.
- If blocked by login, CAPTCHA, payment, or other safety/auth barriers:
  - Call `update_goal(status="blocked")` immediately.
  - Report the exact blocker and what user action is needed.
- Do not mark near-matches or unverified results as complete.
