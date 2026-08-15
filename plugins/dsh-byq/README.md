# dsh-byq

This is the Phase 5 DSH configuration bundle. It only adds the BeyondQuant
MCP Streamable HTTP client and exposes the MCP tool namespace `byq`.

It intentionally contains no personas, skills, subagents, prompts, or strategy
agents. The bundle is installed into the `byq` profile by the official
`dsh plugin --profile byq add ...` mechanism.

The bundle also owns the only Product preset root. `byq-product` is the
default and only selectable Product preset; its composition is intentionally
empty so Product DSH does not expose shipped coding presets or source-editing
capabilities. User preset roots are disabled for Product DSH.
