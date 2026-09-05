# DSH 0.1.2rc1 upstream artifact record

Date: 2026-09-06 (Asia/Shanghai)

Scope: U0 read-only upstream inspection and isolated downloads. This record does not qualify a
candidate image or change the deployed/default DSH release.

## Exact release

- Official source tag: [`dsh-v0.1.2-rc.1`](https://github.com/deepseek-ai/DeepSeek-Harness/tree/dsh-v0.1.2-rc.1)
- Tag commit: `a66e4702047846cdaa10c66c9d3df3951f5ea70d`
- Commit date/subject: `2026-09-03T02:27:19+08:00`, `release(dsh): 0.1.2-rc.1`
- Python SDK: [`deepseek-harness-sdk==0.1.2rc1`](https://pypi.org/project/deepseek-harness-sdk/0.1.2rc1/)
- Python runtime: [`deepseek-harness-runtime-bin==0.1.2rc1`](https://pypi.org/project/deepseek-harness-runtime-bin/0.1.2rc1/)
- Optional npm carrier: [`@deepseek-ai/dsh@0.1.2-rc.1`](https://www.npmjs.com/package/@deepseek-ai/dsh/v/0.1.2-rc.1)

The SDK metadata requires Python `>=3.10`, `pydantic>=2.12,<3`, and the exact
`deepseek-harness-runtime-bin==0.1.2rc1`. No floating `latest` or mixed prerelease was used.

## Published file identity

| File | SHA-256 | Bytes | Uploaded (UTC) |
|---|---|---:|---|
| `deepseek_harness_sdk-0.1.2rc1-py3-none-any.whl` | `24689eec01e95233feb75ca08a0fe748b491e71682f80d2c04e6f9485f20488a` | 13,692 | 2026-09-04 03:16:35 |
| `deepseek_harness_runtime_bin-0.1.2rc1-py3-none-manylinux_2_28_x86_64.whl` | `670d8af06845cc2fc16738f1b030375321f3f8268837152aa3100e14a7b9887d` | 77,713,295 | 2026-09-04 03:14:46 |
| `deepseek_harness_runtime_bin-0.1.2rc1-py3-none-manylinux_2_28_aarch64.whl` | `5052ca9fea2304e28d82a71012a32e7d2399322e1884a065cb08cf5bc57f017f` | 77,218,739 | 2026-09-04 03:14:42 |
| `deepseek_harness_runtime_bin-0.1.2rc1-py3-none-macosx_14_0_arm64.whl` | `2cac2256cdebfda726c3378e24f4be31c0847aece7f2a7eb5a8523559f6b5894` | 72,523,836 | 2026-09-04 03:14:39 |
| `deepseek_harness_runtime_bin-0.1.2rc1-py3-none-win_amd64.whl` | `390bd8cd5f8700fc609c58e1ccb78091d5c8c6e11c21656e284e0f68da0e148f` | 69,024,367 | 2026-09-04 03:14:50 |

The Linux x86-64 SDK/runtime wheels were downloaded into an isolated temporary directory and
locally re-hashed; both hashes matched PyPI. The target host is Linux x86-64 and therefore has an
exact published wheel. The runtime wheel exposes console command `dsh` and contains the standalone
`deepseek-harness-sdk-runtime-linux-x64` executable; it does not require a system Node executable.
The executable reports `0.1.2-rc.1`.

The source `python/sdk-runtime/package.json` has 123 direct bundled packages: 116 `dsh*` packages
and seven supporting `@deepseek-ai` packages (Cordis/group/include/loader/timer, CosmoKit and
Schemastery). Package presence is an installed closure, not an enabled Product capability. U1 must
capture the build/SBOM relationship and installed metadata; the embedded runtime JSON currently
contains a `0.0.0-dev` build placeholder, so it must not be used as release authority.

The optional npm CLI publishes `bin.dsh=lib/bin.js`, SHA-1
`fef213043313affc36ca2226d2637ad483b5e3f6` and integrity
`sha512-RPq48TzxvwpdT9/7W1tbhZDBMmeK+bxDrX9cqQC27Wx/LqtgJF8PSa3b3xriU8oxtvhwYmk21w2cej3uMQrnVA==`.
It remains a documented fallback, not a second selected carrier.

## Negative compatibility finding

An isolated npm resolution using the old BYQ package list and the exact new target failed with
`ERESOLVE`: the retained Cordis `4.0.1` does not satisfy new `@deepseek-ai/dsh-agent` peer
`@deepseek-ai/cordis@^4.0.2`. The install was not forced. This is expected evidence that the old
78-package manifest cannot be mechanically version-replaced; U1 must create an audited release
closure and U4 must generate the new profile/patch.

Host `python3 -m venv` was unavailable because the host lacks `ensurepip`/the Python 3.14 venv
package. U0 therefore extracted the exact downloaded wheels into its temporary directory and ran
the bundled executable there. No system package was installed. This host limitation is not a DSH
compatibility failure.
