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

## Mission Progress

- Set a story's `passes` field to true only from browser evidence.
- Add discovered required stories when needed; do not delete existing ones.
- Answer only after all stories pass or an explicit blocker appears.
