# DSH Runtime Integration Options

## Status: NO DECISION YET

Phase 5 deliberately does not choose the application-facing
Gateway-to-DSH session transport. The Phase 5 Gateway only exposes its own
bootstrap health and readiness. A Phase 6 ADR must evaluate and decide the
seam before a session or chat API is implemented.

The DSH Web application is not a product runtime interface. In rc.6 its
network binding is intentionally safety-restricted; BeyondQuant must not
work around that restriction with a proxy, redirect, host networking, source
patch, or equivalent mechanism. Phase 5 uses container-local `127.0.0.1` only
to start and verify DSH.

## Options for Phase 6

### Option A: Official DeepSeek Harness Python SDK (highest priority)

The official Python SDK is documented as the programmatic alternative to the
Web UI. Evaluate the following application-facing shape:

```text
Gateway
  → dedicated DSH Runtime Adapter
  → official DeepSeek Harness Python SDK
  → bundled DSH runtime
```

The Phase 5 implementation must not install or integrate this SDK. Phase 6
must first query the current PyPI release, verify SDK/runtime version mapping,
prototype lifecycle behavior, and record the result in ADR-0003.

Evaluate:

- session lifecycle
- streaming
- cancellation
- notifications
- durable session
- MCP composition
- model configuration
- subprocess lifecycle
- failure isolation
- authentication
- observability

### Option B: Dedicated BYQ DSH Runtime Adapter using another official seam

Evaluate another official application-facing DSH seam, if one exists, behind
a dedicated adapter owned by the BYQ integration boundary. The same lifecycle,
streaming, cancellation, authentication, isolation, and observability criteria
apply.

### Option C: Official future remote runtime interface

Evaluate an official future remote runtime interface if upstream introduces
one with a stable application-facing contract.

Direct network exposure of `dsh web` is not an acceptable production option.

## Evaluation matrix

Phase 6 must compare each option on:

- process boundary
- streaming
- session lifecycle
- cancellation
- WorkflowTrace translation
- upgrades
- Python Gateway compatibility
- failure isolation
- authentication
- observability

No temporary Chat API, SSE normalization, Python SDK installation, DSH SDK
adapter, or internal event schema translation is introduced in Phase 5.
