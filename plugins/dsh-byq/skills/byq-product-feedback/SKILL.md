---
name: byq-product-feedback
description: Help a user report a BeyondQuant bug, performance problem, usability issue, or feature request as a private draft, privacy preview, and explicitly confirmed submission.
---

# BYQ product feedback

Use only the owner-scoped BYQ feedback tools. Never request a GitHub account,
token, repository, email address, workspace identifier, or internal deployment
detail. Never use Engineering Plane, filesystem, database, GitHub, admin
moderation, or publisher access.

Follow this boundary exactly:

1. Clarify only missing user-visible facts needed for a useful report. A normal
   report includes type, affected module, title, description, optional steps,
   expected and actual behaviour, severity, and explicitly selected diagnostic
   categories. Do not invent reproduction evidence.
2. Create or update a private draft. Tell the user it is still private.
3. Generate the server-owned public candidate preview and show its substantive
   content and disclosure to the user. Do not call submit in this turn.
4. Wait for an explicit confirmation that refers to that preview. “帮我反馈”、
   “提交一个问题” or agreement given before the preview is not confirmation.
5. Only after that later confirmation, submit the exact preview hash and current
   version once. If the version or preview changed, preview again and wait for a
   new confirmation. Never fabricate a confirmation flag.

Submitting creates a Product moderation item, not a GitHub Issue. Explain that
an administrator reviews it and an optional platform publisher may create the
Issue after acceptance. An unconfigured publisher is a useful queued state, not
a user error. Only report a GitHub Issue link when BYQ returns one.

Credential-shaped text, email addresses, external URLs, unsupported markup, and
suspected security reports are rejected. For a suspected vulnerability, do not
save or submit it; direct the user to the project's private security channel.
Read lists in bounded pages and stop when the requested item is found; never
exhaust `has_more` without a specific user need.
