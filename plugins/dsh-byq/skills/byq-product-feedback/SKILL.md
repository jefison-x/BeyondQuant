---
name: byq-product-feedback
description: Help a user report a BeyondQuant bug, performance problem, usability issue, or feature request in the conversation, with one confirmation in the global approval center.
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
   content and disclosure in the conversation.
4. In the same turn, use the current orchestrator run to request exactly one
   global approval with action `byq_feedback_submit`, resource type
   `product_feedback`, and the exact feedback id. The approval reason must name
   the previewed title and explain that the privacy-reviewed snapshot will be
   sent to the official central Feedback Hub and may become a public GitHub
   Issue. Tell the user to approve or reject it from the header approval bell,
   then stop. Do not ask them to visit the feedback page and do not submit yet.
5. After the approval center resumes this original conversation, read that exact
   approval. If it is approved and authorized, submit the exact preview hash and
   current version once, including its `agent_approval_id`. If rejected, explain
   that nothing was submitted. If the draft version or preview changed, generate
   a new preview and request a new exact approval. Never fabricate a confirmation
   flag, approval id, resource binding, or approval outcome.

Submitting durably queues the privacy-safe snapshot for the official central
Feedback Hub. Central anti-abuse checks and moderation remain independent from
the local approval; approval does not promise publication. A local installation
with no Hub relay configuration retains the queue and reports `unconfigured`
instead of losing the feedback. Normal users never configure GitHub or Hub
credentials. Only report a GitHub Issue link when BYQ returns one.

Credential-shaped text, email addresses, external URLs, unsupported markup, and
suspected security reports are rejected. For a suspected vulnerability, do not
save or submit it; direct the user to the project's private security channel.
Read lists in bounded pages and stop when the requested item is found; never
exhaust `has_more` without a specific user need.
