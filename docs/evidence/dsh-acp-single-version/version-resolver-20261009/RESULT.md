# Single authoritative DSH selection preparation — 2026-10-09

Tester / independent Reviewer / Root PASS for preparation only. The strict resolver loads the single manifest, validates roles/version/source/lock and profile/identity hashes, refuses escaping/symlink paths and online SDK rollback, and emits the explicit release-to-ACP-family mapping. Both Worker and independent Tester passed seven targeted offline tests and the current-manifest CLI. No profile hash drift was found.

`sdk_online_fallback=false` is the resolver's selection output; it does not claim current runtime/Compose/CI/Release consumers have already removed SDK. Consumers remain unwired and default promotion remains gated by live qualification. Capabilities evidence strings are not a promotion authorization.
