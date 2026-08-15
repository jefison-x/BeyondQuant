# Contracts

Reserved for framework-neutral BYQ integration contracts. `WorkflowTraceEvent`
is the Phase 6 minimum internal envelope. DSH notifications are translated at
the Runtime Adapter boundary; no DSH internal event schema is promoted into a
Gateway or frontend contract.

See [`workflow_trace.py`](workflow_trace.py) for the typed envelope factory.
