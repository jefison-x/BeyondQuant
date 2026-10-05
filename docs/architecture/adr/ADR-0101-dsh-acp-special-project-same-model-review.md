# ADR-0101 — DSH ACP special project: same-model independent review sessions

- Status: **Accepted** (2026-10-05). The maintainer explicitly accepted the
  exact decision below for the DSH ACP special project. Acceptance is scoped to
  the role arrangement only; it does not accept any other part of the draft and
  does not reduce the test, security, merge or deployment gates.
- Scope: the BYQ DSH ACP upgrade special project on branch
  `codex/dsh-acp-upgrade`, fixed official `dsh-v0.2.0-rc.2`
  (`639ed015397290b3745d163aafe02ffee4aa3f84`). Does not change the Clean Break
  default role models, any other project, or the human merge/deployment gates.
- Does not reduce evidence requirements: it changes who may fill the Tester and
  Reviewer roles for this project, not what they must verify.

## Context

`docs/clean-break/development-agent-mode.md` assigns Tester to `gpt-6-luna` /
max and Reviewer to `gpt-6-sol` / medium. This host exposes the OpenCode
session on a single model, so the maintainer explicitly authorized, for this
special project only, that OpenCode may run the Tester and Reviewer as **new,
independent same-model sessions**, with the main session acting as Root instead
of `gpt-6-sol` / medium. The maintainer's instruction: use two fresh sessions
on the current model for auxiliary verification and code review, give them the
task scope, Accepted ADRs, exact HEAD and evidence paths, do not seed the
implementer's conclusions, and do not let the implementer session self-review.

## Decision

For the DSH ACP special project only:

1. The implementer (main session) performs the code changes.
2. Tester and Reviewer are **separate fresh sessions on the same model**, each
   with an independent context and no implementer conclusions injected. Each
   receives the task scope, Accepted ADRs, the exact frozen HEAD and evidence
   paths.
3. The main session acts as Root and synthesizes both reports into an explicit,
   scope-limited PASS/FAIL conclusion.
4. Same model is not same session self-review: the Reviewer must not modify
   implementation; identified fixes return to the implementer, after which only
   the affected parts are re-verified.
5. A session may not simulate an independent session or fabricate a role report.
   If an independent session cannot be started, that is reported as NOT_RUN.

## Required evidence

- Both fresh-session reports are retained separately in the special-project
  evidence, labeled as same-model independent auxiliary review and citing this
  authorization.
- Each report states the exact HEAD, commands, results, evidence paths and
  NOT_RUN items it inspected.
- The Root conclusion states which items are PASS for the ordinary ACP session
  scope, which are FAIL/NOT_RUN, and that formal role checks do not by
  themselves constitute Product promotion or production acceptance.

## Boundaries

- No push, PR, merge, deployment or release is authorized by this ADR.
- F6 and the dedicated judgment `/acp-root/run` remain deferred and disabled.
- This exception must not be generalized to other projects; a different project
  needs its own authorization.

## Authorization reference

Maintainer instruction in the DSH ACP special-project session, 2026-10-05:
"本专项明确允许 OpenCode 使用当前同一个模型，在独立新会话中分别担任 Tester
和 Reviewer，由主会话担任 Root，替代仓库指定的 Luna max Tester / Sol medium
Reviewer 模型要求。这是本专项的流程例外，不改变其他项目的规则。"

## Acceptance record (2026-10-05)

The maintainer explicitly accepted exactly this decision: OpenCode may use the
current same model in two new independent sessions as Tester and Reviewer, with
the main session as Root, replacing the special-project Luna/Sol model
requirement. Acceptance is limited to that role arrangement and does not lower
the testing, security, merge or deployment gates. The draft contains no decision
beyond that arrangement; no other part is accepted by this record.
