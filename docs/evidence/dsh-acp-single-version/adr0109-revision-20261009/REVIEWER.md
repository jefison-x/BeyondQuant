# Independent revised-contract review — 2026-10-09

Functional / Tests / Clean Break Architecture: PASS for the bounded local revision.

Accepted ADR and internal contract align with unchanged runtime source. Only exact
role_tool_not_allowed proof receives the denied path. Policy refusals remain generic 403;
persisted unknown ingress blocks closure/new roots and cannot be rewritten. MCP may report
unknown after lost settlement response without replay or permission grant. Backend's durable
negative settlement can be authoritative for final root close under the accepted revision.

New tests prove root and child identities, exact durable settlements, private close ACK and
same-transaction terminal cursor hash/readback. ACK JSON carries lifecycle identity, while
cursor binding is in the authoritative Backend root record. Independent Backend 2/2 and
Adapter 2/2 logs were reviewed. Prior actual MCP bridge loss evidence was reused.

Real candidate process cleanup and Gateway/Product child acceptance remain NOT_RUN. The
Backend return is discarded to model lost response; Adapter slot tests use fake harnesses.
No old-root reconciliation, image deployment, hosted CI, push, merge or release PASS is granted.
Safe next stage: matched candidate images followed by necessary live candidate qualification.
