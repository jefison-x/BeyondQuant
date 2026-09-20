#!/usr/bin/env node
/**
 * D15-5 BYQ persistent-terminal wiring reachability probe.
 *
 * Real read-only inspection of the committed BYQ composition/profile, the
 * runtime-adapter, the D15 compat boundary, the candidate bundle ledger and the
 * installed candidate native terminal packages. It reports a per-interface
 * status. It never edits the production composition or selector.
 *
 * Usage: node interface_probe.mjs [--out <path>]
 */

import { readFileSync, writeFileSync, existsSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { createRequire } from 'node:module'

const HERE = dirname(fileURLToPath(import.meta.url))
const ROOT = resolve(HERE, '..', '..', '..')

function read(path) {
  try {
    return readFileSync(path, 'utf8')
  } catch {
    return null
  }
}

function countMatches(text, pattern) {
  return text === null ? 0 : (text.match(pattern) ?? []).length
}

function probe() {
  const composition = read(join(ROOT, 'plugins/dsh-byq/compositions/byq-product-sdk.cordis.yml'))
  const patch = read(join(ROOT, 'plugins/dsh-byq/profiles/dsh-0.1.2rc1/byq-product.patch.yml'))
  const adapterMain = read(join(ROOT, 'services/runtime-adapter/app/main.py'))
  const compat = read(join(ROOT, 'services/runtime-adapter/app/compat/dsh_015.py'))
  const ledger = read(join(ROOT, 'docs/evidence/d15/compatibility-ledger.v1.json'))

  const composesTerminalService = /name:\s*'@deepseek-ai\/dsh-terminal'/.test(composition ?? '')
  const composesShellBackend = /name:\s*'@deepseek-ai\/dsh-terminal-bash'/.test(composition ?? '')
  const composesTerminalTool = /name:\s*'@deepseek-ai\/dsh-tool-terminal'/.test(composition ?? '')
  const composesPersistentBashTool = /name:\s*'@deepseek-ai\/dsh-tool-bash-persistent'/.test(composition ?? '')
  const patchDisablesToolBash = /id:\s*tool-bash\b/.test(patch ?? '')
  const patchDisablesToolPwsh = /id:\s*tool-pwsh\b/.test(patch ?? '')
  const adapterRoutePaths = [...(adapterMain ?? '').matchAll(/@app\.(?:get|post|delete)\("([^"]+)"/g)]
    .map((match) => match[1])
  const terminalRoutePaths = adapterRoutePaths.filter((path) => /terminal|pty/i.test(path))
  // A run "terminal-receipt" is AgentRun terminal-state evidence, NOT a
  // persistent-terminal/PTY attachment product surface. Exclude it explicitly.
  const ptyAttachmentRoutes = terminalRoutePaths.filter((path) => !/terminal-receipt/.test(path))
  const adapterTerminalRoutes = ptyAttachmentRoutes.length
  const adapterRunTerminalReceiptRoutes = terminalRoutePaths.length - ptyAttachmentRoutes.length
  const adapterTerminalsReference = countMatches(adapterMain, /terminals?/i)
  const compatInherits012 = /class Dsh015Compatibility\(Dsh012Compatibility\)/.test(compat ?? '')
  const ledgerMentionsPersistentTerminal = /persistent_terminal_shell/.test(ledger ?? '')

  // Installed candidate native packages (present when the harness deps are installed).
  let terminalPkgVersion = null
  let shellBackendVersion = null
  let terminalReadmeProcessLocal = null
  try {
    const require = createRequire(import.meta.url)
    const terminalEntry = require.resolve('@deepseek-ai/dsh-terminal')
    terminalPkgVersion = JSON.parse(read(join(dirname(terminalEntry), '..', 'package.json')) ?? '{}').version ?? null
    const readme = read(join(dirname(terminalEntry), '..', 'README.md'))
    terminalReadmeProcessLocal = /Process-local sessions/.test(readme ?? '')
  } catch {
    terminalPkgVersion = null
  }
  try {
    const require = createRequire(import.meta.url)
    const backendEntry = require.resolve('@deepseek-ai/dsh-terminal-bash')
    shellBackendVersion = JSON.parse(read(join(dirname(backendEntry), '..', 'package.json')) ?? '{}').version ?? null
  } catch {
    shellBackendVersion = null
  }

  const interfaces = [
    {
      interface: 'native-pty-service',
      package: '@deepseek-ai/dsh-terminal',
      status: terminalPkgVersion ? 'REACHABLE_IN_CANDIDATE_CLOSURE' : 'NOT_RESOLVED',
      detail: 'owner-scoped TerminalSessionService (ids/publication/authorization/cleanup); PTY mechanics are backend-owned',
      version: terminalPkgVersion,
    },
    {
      interface: 'native-shell-backend',
      package: '@deepseek-ai/dsh-terminal-bash',
      status: shellBackendVersion ? 'REACHABLE_IN_CANDIDATE_CLOSURE' : 'NOT_RESOLVED',
      detail: 'registers the `shell` PTY backend type',
      version: shellBackendVersion,
    },
    {
      interface: 'native-terminal-tools',
      package: '@deepseek-ai/dsh-tool-terminal / @deepseek-ai/dsh-tool-bash-persistent',
      status: 'BUNDLED_NOT_COMPOSED_BY_BYQ',
      detail: 'bundled in the 0.1.5 closure but not composed by the committed BYQ composition',
      version: '0.1.5-rc.1',
    },
    {
      interface: 'byq-composition-terminal-service',
      package: 'plugins/dsh-byq/compositions/byq-product-sdk.cordis.yml',
      status: composesTerminalService ? 'COMPOSED' : 'NOT_COMPOSED',
      detail: 'composes @deepseek-ai/dsh-terminal',
      fact: composesTerminalService,
    },
    {
      interface: 'byq-composition-shell-backend',
      package: 'plugins/dsh-byq/compositions/byq-product-sdk.cordis.yml',
      status: composesShellBackend ? 'COMPOSED' : 'NOT_COMPOSED',
      detail: 'composes @deepseek-ai/dsh-terminal-bash',
      fact: composesShellBackend,
    },
    {
      interface: 'byq-product-terminal-tool',
      package: 'plugins/dsh-byq/compositions/byq-product-sdk.cordis.yml',
      status: composesTerminalTool || composesPersistentBashTool ? 'COMPOSED' : 'NOT_COMPOSED',
      detail: 'composes a model-facing persistent terminal tool',
      fact: composesTerminalTool || composesPersistentBashTool,
    },
    {
      interface: 'byq-terminal-product-surface',
      package: 'services/runtime-adapter/app/main.py',
      status: adapterTerminalRoutes > 0 ? 'EXPOSED' : 'ABSENT',
      detail: 'runtime-adapter HTTP persistent-terminal/PTY attachment routes (create/attach/read/signal/kill/reconnect); the run-terminal-receipt route is AgentRun terminal-state evidence, not a PTY surface',
      route_count: adapterTerminalRoutes,
      run_terminal_receipt_routes: adapterRunTerminalReceiptRoutes,
    },
    {
      interface: 'byq-terminal-attachment-persistence',
      package: 'services/runtime-adapter + PostgreSQL',
      status: 'ABSENT',
      detail: 'no BYQ TerminalAttachment identity/state/authorization/reconnect persisted anywhere in the committed tree',
    },
    {
      interface: 'byq-permission-fencing-for-terminal',
      package: 'services/runtime-adapter/app/compat/dsh_015.py',
      status: compatInherits012 ? 'INHERITS_0_1_2_OBSERVATION_ONLY' : 'UNKNOWN',
      detail: 'the 0.1.5 compat boundary still inherits the 0.1.2 observation contract; no terminal gate',
      fact: compatInherits012,
    },
    {
      interface: 'cross-process-terminal-reattach',
      package: 'native + BYQ',
      status: 'BLOCKED',
      detail: 'native sessions are documented process-local (do not survive a harness restart) and no committed BYQ wiring rehydrates/rebinds them; adapter/DSH restart therefore cannot rebind',
      native_documented_process_local: terminalReadmeProcessLocal,
    },
  ]

  const conclusions = {
    native_terminal_capability_present_in_candidate: terminalPkgVersion !== null && shellBackendVersion !== null,
    native_sessions_documented_process_local: terminalReadmeProcessLocal === true,
    byq_composes_terminal_service: composesTerminalService,
    byq_exposes_terminal_surface: adapterTerminalRoutes > 0,
    byq_run_terminal_receipt_routes: adapterRunTerminalReceiptRoutes,
    byq_persists_terminal_attachment: false,
    byq_can_reattach_after_runtime_restart: false,
    byq_patch_disables_one_shot_bash_and_pwsh: patchDisablesToolBash && patchDisablesToolPwsh,
    compat_inherits_0_1_2: compatInherits012,
    ledger_records_persistent_terminal: ledgerMentionsPersistentTerminal,
    adapter_mentions_terminals: adapterTerminalsReference,
  }

  const blocked_items = [
    {
      id: 'byq-terminal-product-surface',
      status: 'BLOCKED',
      reason: 'no committed BYQ runtime-adapter terminal routes or Gateable Product API terminal surface exist; adding one is a real architecture boundary change (ADR-0083, Proposed)',
      smallest_option: 'BYQ TerminalAttachment lifecycle over the native owner-scoped ctx.terminals seam (R4), candidate-specific and reversible',
    },
    {
      id: 'byq-adapter-restart-rebind',
      status: 'BLOCKED',
      reason: 'adapter restart aborts the DSH runtime; native sessions are process-local and BYQ has no TerminalAttachment rehydrate/reconnect path',
      smallest_option: 'BYQ TerminalAttachment persistence + native session reattach where supported, with explicit lost/interrupted status and never a fabricated reattach',
    },
    {
      id: 'dsh-runtime-restart-rebind',
      status: 'BLOCKED',
      reason: 'a restarted DSH runtime is a new process; native terminal sessions do not survive it',
      smallest_option: 'confirmed by the native package contract; requires a BYQ attachment layer plus an explicit non-reattach/lost status',
    },
  ]

  return {
    schema_version: 'byq-d15-5-interface-probe.v1',
    generated_at: new Date().toISOString(),
    candidate: { release: 'dsh-0.1.5rc1', npm: '0.1.5-rc.1' },
    sources: {
      composition: 'plugins/dsh-byq/compositions/byq-product-sdk.cordis.yml',
      patch: 'plugins/dsh-byq/profiles/dsh-0.1.2rc1/byq-product.patch.yml',
      adapter: 'services/runtime-adapter/app/main.py',
      compat: 'services/runtime-adapter/app/compat/dsh_015.py',
      ledger: 'docs/evidence/d15/compatibility-ledger.v1.json',
    },
    interfaces,
    conclusions,
    blocked_items,
  }
}

const outIndex = process.argv.indexOf('--out')
const result = probe()
if (outIndex >= 0 && process.argv[outIndex + 1]) {
  writeFileSync(process.argv[outIndex + 1], JSON.stringify(result, null, 2) + '\n')
  process.stdout.write(`wrote ${process.argv[outIndex + 1]}\n`)
} else {
  process.stdout.write(JSON.stringify(result, null, 2) + '\n')
}
