# Judgment runner derived image: review-only build input

Base image: `sha256:6592810009079dff51f42bf87f56076e84ae665eaf5a2f722b1b57ccb4b7666c`.

The Dockerfile copies only the current BYQ judgment runner, profile, identity, and runtime files from the pinned worktree. It does not clone or rebuild DSH. Build-time assertions retain official DSH commit `639ed015397290b3745d163aafe02ffee4aa3f84`, official lock SHA256 `80fe05eae33582ae26839afd05f1965f9b0e4be11034ddf9797af6085d5ba9b1`, and the expected DSH CLI artifact. All BYQ and DSH runtime files are root-owned and non-writable in the resulting image; the inherited entrypoint is retained.

Root may perform the bounded local offline build after reviewing this file. This task did not build or start the image.

Suggested Root command (run from the pinned worktree):

```sh
docker build --pull=false --network=none \
  -f /tmp/byq-adr0109-qual-20261009-c89ff732f2/Dockerfile.judgment-runner-derived \
  -t byq-adr0109-judgment-runner-derived:20261009 .
```
