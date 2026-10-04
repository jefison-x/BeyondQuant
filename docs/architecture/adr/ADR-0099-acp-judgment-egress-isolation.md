# ADR-0099 — Isolate dedicated ACP judgment provider egress

- Status: **Proposed** (2026-10-04). Maintainer acceptance is required before
  changing the candidate process and network boundary.
- Scope: the dedicated Product ACP research-judgment root in ADR-0097 at
  official `dsh-v0.2.0-rc.2` commit
  `639ed015397290b3745d163aafe02ffee4aa3f84`. Ordinary Product sessions
  and the retained `0.1.5rc1` image/configuration keep their existing route.
- No paid provider test, default promotion, merge or deployment follows from
  accepting this design.

## Observed gap

The candidate currently changes the one `runtime-adapter` service's image and
environment. That service also hosts ordinary Product conversations. Its
`byq_product` bridge gives Adapter and the official DSH child the same
external network path; both run as UID 10002. DSH can bypass its configured
local provider URL and the per-root budget proxy with a direct connection.
Disabling DSH tools does not change that network fact.

Moving that whole service to an internal-only network would break ordinary
Product model calls. It would also leave the single Gateway/Backend runtime
authority ambiguous if a second full Adapter claimed the same boot/epoch.
Therefore the isolation boundary must be the **dedicated judgment DSH
execution**, not the existing Product Adapter or its global authority.

## Decision proposed

1. Keep the existing Adapter and Gateway authority owner on their current
   network. The trusted Adapter remains the sole owner of judgment admission,
   Backend root lifecycle, model resolution, journal, provider budget proxy,
   result settlement and exact terminal ACK. Do not run a second full Adapter
   or grant a new global runtime authority.
2. Execute only the official DSH ACP judgment process in a separate, narrowly
   scoped runner container on an **internal-only network**. It has no ordinary
   bridge, host network, Docker socket, provider credential, or external proxy.
   The runner forwards ACP bytes and owns process start/stop/reap; it makes no
   Agent, business, model-routing or budget decisions and is not another
   generic harness. A runner process serves one exact admitted root at a time.
3. Attach the existing Adapter and the isolated five-read MCP service to the
   runner's internal control network. The Adapter's existing per-root provider
   proxy listens on that internal interface for the runner, authenticates the
   distinct root-local token, enforces the frozen route/budget and writes the
   durable attempt marker before its own HTTPS worker sends anything outward.
   This amends ADR-0097's proposed **loopback** proxy transport for this
   isolated process only; the proxy's decision and journal ownership stay in
   Adapter. The proxy listener is not exposed on the Product bridge or host.
4. The runner accepts control only for the exact admitted task/call/root and
   Adapter authority, with one active process, bounded frame sizes, deadlines,
   process-group cleanup and no replay after uncertain dispatch. Its control
   channel must not accept model-supplied commands. DSH receives only its
   contained session directory, immutable composition, root MCP environment
   and local proxy token. The current child also receives
   `BYQ_MCP_ACP_JUDGMENT_SIGNING_KEY`; container isolation does not hide a
   secret passed to DSH. Prove that key and direct MCP access cannot authorize
   another task/call/root/AgentRun, or replace it with a narrower capability.
5. The Adapter fails closed before prompt if the runner network, provider
   proxy binding, process identity, AgentRun binding or terminal cleanup cannot
   be proven. A lost worker/runner response stays outcome-unknown and must not
   be replayed or reported as no external call. ADR-0098's proposed Backend
   settlement is a separate prerequisite for closing such a root.

The actual runner control framing, authentication and startup must be reviewed
with an isolated implementation. A tunnel alone is not proof: a compromised
runner could send arbitrary ACP bytes, so the Adapter must continue treating
all ACP output as untrusted and preserve Backend admission/terminal checks.
Docker's internal network prevents direct external routing from that
container; it does not restrict access to every listener of a service attached
to the same network. Audit the Adapter and MCP listeners for generic CONNECT,
reverse-proxy or forwarding routes. Use narrower facades if any can relay
arbitrary egress. No current candidate deployment is claimed to meet this ADR.

## Proof before promotion

1. Inspect resolved Compose and actual container attachments: the runner has
   only internal networks; the existing Product Adapter retains its normal
   route and readiness, and the retained SDK rollback still selects its exact
   old image/configuration. Verify Gateway/Backend authority remains single.
2. From the real DSH process namespace, test direct DNS/TCP to every supported
   provider origin, alternate IP and IPv6, and any proxy environment path.
   Direct egress must fail. Enumerate all reachable Adapter/MCP ports and test
   CONNECT, reverse-proxy and forwarding behavior. The authenticated local
   provider proxy and five read tools must still work.
3. Prove that another root, another caller and the DSH process cannot start,
   replace or control a runner process; the control channel cannot be forged
   through the root MCP signing key. Prove prompt timeout, cancellation and
   runner death leave no orphan and no replay. Keep unknown provider outcomes
   unknown until exact reconciliation.
4. Pair the network proof with the separate provider budget, Backend terminal
   ACK and Product API qualification. A keyless network probe is not Product
   acceptance.

## Alternatives considered

- Trust DSH tool configuration and provider `baseURL` on the current bridge:
  no direct-network bypass prevention.
- Make the entire current Adapter internal-only: breaks ordinary Product model
  routing; a second full Adapter also conflicts with the singleton
  Gateway/Backend boot authority without further design.
- Keep the current container and install UID-specific firewall rules: needs a
  privileged setup, a safe one-way child UID drop, exact destination updates
  and platform support. None has been qualified for this candidate.
- Add an external worker to an internal-only Adapter: still breaks ordinary
  sessions unless their whole provider routing is redesigned, and DSH access
  to the worker must be separately prevented.

## Source and local evidence

- `compose.yml` and `compose.dsh-acp-rc2-candidate.yml` show one shared
  Adapter on `byq_product`; the candidate Dockerfile has one UID.
- `services/runtime-adapter/app/compat/dsh_acp.py` starts DSH as a child;
  `services/runtime-adapter/app/research_judgment_acp_provider_proxy.py`
  currently binds loopback.
- Docker's [Compose networking documentation](https://docs.docker.com/compose/how-tos/networking/)
  states that an internal network has no external gateway and that a
  dual-network service can still reach the internet.
