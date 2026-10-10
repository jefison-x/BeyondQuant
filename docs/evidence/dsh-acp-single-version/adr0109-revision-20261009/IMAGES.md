# Matched local candidate images — 2026-10-09

Unqualified local candidates; not release/promote/deploy artifacts.

| Service | Exact local image ID | Source files matched |
| --- | --- | --- |
| backend | `sha256:753662c496721f9cb3b411850351ba1ddfb08ec6661e7fe8716710c33661b281` | 236/236 |
| mcp | `sha256:0980003d2c9c632598e51434257f7c631ddcd3bb11d8ddbd915b3a84fe577b8b` | 31/31 |
| product-runner | `sha256:6ddceb4fd7a65ac5dabe57d87ba7b7710e3d60d0d27bafad6a7c91371fd7743a` | 25/25 |
| adapter | `sha256:0effdb8bae2b27c06e127185016bc97c34eb494ae8c1990872e7785abac80b8c` | 80/80 |

Backend and MCP built with normal repository Dockerfiles, cached dependencies and network=none.
The runner standard offline build failed in the final stage: missing cache made apt need network,
which was deliberately disabled (DNS failure; exit100). It was not silently called PASS.

Runner and Adapter local candidates inherit precise previously verified ACP baseline image IDs.
Runner official commit marker is 639ed015397290b3745d163aafe02ffee4aa3f84 and pnpm lock hash
80fe05eae33582ae26839afd05f1965f9b0e4be11034ddf9797af6085d5ba9b1; complete CLI output exists.
Adapter lock hash 53592f4ad247cff51dd7deff6f8ca1b6230257848a5b1917db2cab9e34d49f3e equals current checkout.
No DSH runtime/source/dependency changes were made in the derived layers. BYQ source/profile/skills
are copied with exact current hashes; runner permissions and Adapter USER byq are preserved.
No shipped source deletions appear in the bounded revision; directory COPY stale-file limitation is
retained and must not be used for future deletion/cutover without a clean build.

The first readback script failed after Backend/MCP hash checks because Docker omits the empty
default-root User property. Only that metadata parser was repaired; the completed read-only check
matched all 372 selected files (no model, domain or process work). Scripts and logs are preserved.

Current byq-acpf6 containers were not replaced, restarted or supplied new prompts. Old unknown
root and rollback containers/volumes remain. Trusted-main Release Images Full, hosted CI, exact
tested digest promotion and production acceptance remain NOT_RUN.

## Independent artifact gates

Tester executed the packaged MCP bridge test from the actual new image once: PASS. It used
network=none, read-only root and tmpfs /tmp, with no build/download/model call. Independent
metadata check confirms MCP USER=node, Adapter USER=byq, and runner fixed official commit/profile
identity. Reviewer Functional/Architecture/Integrity PASS for the local no-deletion candidate,
with clean full build failure and all production/publication limits preserved. Root admits
these exact artifacts only for new isolated candidate qualification, not deployment/promotion.
