# Current-source ACP archive review

**Functional: limited PASS. Tests: limited PASS. Clean Break Architecture: limited PASS.** No blocking issue found in the saved execution evidence.

The executed script SHA-256 is `1c775ba1dedd2c6a372e039e815e9b5911130085b5dd1797b42bc82fc3f5b89b`; `scripts/release/images.py` remained at `dc68c24fd4436b0ddeee89b7e7486e8ec1894d3bcc2fb5faee37a9e257f6b783`. The real Docker save produced 806,272,000 bytes with SHA-256 `e435117fad3db1b7d65d116a9156cf533a506952aeb5465b20eb0dac3117b37f`. All three exact aliases resolved to manifest ID `15cdf5…`, config ID `a2ba7f…`, linux/amd64 and the same 28 ordered layers and diffIDs. The final parser and source-image binding checks passed. The 91 captured image input hashes matched before and after.

The pre-cleanup receipt contains the archive size and hash. The executed script flushed and fsynced that file and its directory before unlinking the tar. Three exact aliases were removed non-force with verified absence and no cleanup error. All 26 preexisting containers, including 8 running, and all 15 preserved image tags retained exact before/after identities. The stopped frontend was already in the pre-execution baseline.

Evidence: [result.json](../result.json), [proof-before-cleanup.json](../proof-before-cleanup.json), [independent-audit.json](../tester/independent-audit.json), and [execution-tool-result.json](../tester/execution-tool-result.json). The saved original tool result has chunk `58911a`, exit code 0, and stdout fields matching the final receipt.

This establishes the current local containerd image's real three-alias archive shape and parser/source binding. Full 17-service `images.export`, cross-store load, hosted runner qualification, registry publication and attestation remain **NOT_RUN**. I did not rerun Docker or reread the deleted tar.
