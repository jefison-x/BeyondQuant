#!/usr/bin/env node
/**
 * Independent DSH provider-qualification slice: native capability inventory.
 *
 * This probe answers one monitoring question for a published DSH release:
 *
 *   Does the release contain an actually registerable OUT-OF-PROCESS provider
 *   implementing `SubagentProvider.prepareContinuable`, with a real
 *   `SubagentRuntime.prepareContinuable` capability gate, a durable mailbox and a
 *   cross-process lease protocol?
 *
 * It boots the real `@deepseek-ai/cordis` context + real `SubagentRuntime` from an
 * isolated installation of the examined release (``--module-root``), registers the
 * real published providers and calls the real native capability gate for each.
 * Helper symbols for building an out-of-process ONE-SHOT backend
 * (`out-of-process.d.ts`, `subprocessRunHandle`, `NO_START_CAPABILITIES`, ...) are
 * recorded only to make explicit that their presence is NOT the capability.
 *
 * The probe is read-only, makes no LLM call and never forks/patches DSH. It does
 * not itself decide PASS/BLOCKED; the fail-able observer does. This probe only
 * records observations.
 *
 * Usage:
 *   node capability_inventory.mjs --module-root <dir> --npm-version <v> \
 *       --version-id <id> --out <inventory.json>
 */

import { createRequire } from 'node:module'
import { pathToFileURL } from 'node:url'
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'

function parseArgs(argv) {
  const args = {}
  for (let index = 0; index < argv.length; index += 1) {
    const token = argv[index]
    if (token.startsWith('--')) args[token.slice(2)] = argv[index + 1]
  }
  return args
}

const args = parseArgs(process.argv.slice(2))
if (!args['module-root'] || !args['npm-version'] || !args['version-id'] || !args.out) {
  process.stderr.write(
    'usage: capability_inventory.mjs --module-root <dir> --npm-version <v> '
    + '--version-id <id> --out <inventory.json>\n')
  process.exit(2)
}

const MODULE_ROOT = resolve(args['module-root'])
const NPM_VERSION = args['npm-version']
const VERSION_ID = args['version-id']
const OUT = resolve(args.out)
const requireFromRoot = createRequire(join(MODULE_ROOT, 'package.json'))

async function load(name) {
  return import(pathToFileURL(requireFromRoot.resolve(name)).href)
}

function packageVersion(name) {
  try {
    const manifest = JSON.parse(
      readFileSync(join(MODULE_ROOT, 'node_modules', ...name.split('/'), 'package.json'), 'utf8'))
    return manifest.version
  } catch {
    return null
  }
}

const PROVIDERS = [
  { name: 'spawn', package: '@deepseek-ai/dsh-subagent-spawn-in-process', boundary: 'in-process',
    config: { providerName: 'spawn' } },
  { name: 'fork', package: '@deepseek-ai/dsh-subagent-fork-in-process', boundary: 'in-process',
    config: { providerName: 'fork' } },
  { name: 'acp', package: '@deepseek-ai/dsh-subagent-acp', boundary: 'out-of-process',
    config: { providerName: 'acp', command: 'true', args: [], disposeEofGraceMs: 5000,
              disposeGraceMs: 5000 } },
  { name: 'codex', package: '@deepseek-ai/dsh-subagent-codex', boundary: 'out-of-process',
    config: { providerName: 'codex', env: {}, permissionMode: 'never', disposeGraceMs: 5000 } },
  { name: 'claude-code', package: '@deepseek-ai/dsh-subagent-claude-code', boundary: 'out-of-process',
    config: { providerName: 'claude-code', env: {}, permissionMode: 'dontAsk', disposeGraceMs: 5000 } },
  { name: 'dsh-sdk', package: '@deepseek-ai/dsh-subagent-dsh-sdk', boundary: 'out-of-process',
    config: { providerName: 'dsh-sdk', dshHome: '/tmp/byq-dsh-provider-qualification-home',
              patches: [], shutdownTimeoutMs: 5000, disposeEofGraceMs: 5000, disposeGraceMs: 5000 } },
]

const HELPER_SYMBOLS = [
  'NO_START_CAPABILITIES', 'subprocessRunHandle', 'settleRunResult', 'resolveChildCwd',
  'assertPositiveFinite', 'assertUsableCwd', 'validateConfiguredCwd',
]

function declaredLimitations() {
  let readme = ''
  try {
    readme = readFileSync(
      join(MODULE_ROOT, 'node_modules/@deepseek-ai/dsh-subagent/README.md'), 'utf8')
  } catch {
    return { available: false }
  }
  const has = (fragment) => readme.includes(fragment)
  return {
    available: true,
    process_local_residency: has('Process-local residency'),
    durable_mailbox_absent: has('No durable parent mailbox')
      || has('the service has no durable parent mailbox'),
    cross_process_lease_absent: has('durable mailbox and cross-process lease protocol')
      || has('durable mailbox and lease protocol'),
    cross_process_continuation_deferred: has('Cross-process continuation'),
    acp_one_shot: has('ACP children remain one-shot'),
    process_local_activation_quote: 'the Activation inbox and ownership graph do not coordinate '
      + 'two harness processes; concurrent access to one persistence store needs a durable mailbox '
      + 'and cross-process lease protocol',
  }
}

async function collectProvider(ctx, provider) {
  const record = {
    name: provider.name,
    package: provider.package,
    boundary: provider.boundary,
    version: packageVersion(provider.package),
    import_ok: true,
    prepare_continuable_present: false,
    capabilities: null,
    gate: { ok: null, kind: 'not-called' },
  }
  let module
  try {
    module = await load(provider.package)
  } catch (error) {
    record.import_ok = false
    record.import_error = String(error?.message ?? error).slice(0, 300)
    return record
  }
  try {
    module.apply(ctx, provider.config)
  } catch (error) {
    record.register_error = {
      name: error?.constructor?.name ?? 'Error',
      message: String(error?.message ?? error).slice(0, 300),
    }
    return record
  }
  const instance = ctx.subagents.getProvider(provider.name)
  if (instance === undefined) {
    record.register_error = { name: 'Error', message: 'provider was not registered' }
    return record
  }
  record.prepare_continuable_present = typeof instance.prepareContinuable === 'function'
  record.capabilities = instance.capabilities ?? null
  const parent = provider.name === 'fork'
    ? { session: { snapshotEvents: () => [] } }
    : null
  try {
    const spec = await ctx.subagents.prepareContinuable(provider.name, {
      sessionId: 'provider-qualification-child', parent, signal: new AbortController().signal,
    })
    record.gate = { ok: true, kind: 'capability-present', spec }
  } catch (error) {
    record.gate = {
      ok: false,
      kind: error?.code === 'UNSUPPORTED_CAPABILITY' ? 'unsupported-capability' : 'other-error',
      errorClass: error?.constructor?.name ?? 'Error',
      errorCode: error?.code ?? null,
      message: String(error?.message ?? error).slice(0, 300),
    }
  }
  return record
}

async function main() {
  const providerRecords = []
  let bootError = null
  let helpersPresent = []
  let subagentVersion = null

  try {
    const { Context } = await load('@deepseek-ai/cordis')
    const subagentModule = await load('@deepseek-ai/dsh-subagent')
    const SubagentRuntime = subagentModule.default ?? subagentModule.SubagentRuntime
    const { mountAgentLoopTestDependencies } = await load('@deepseek-ai/dsh-agent-loop-testkit')
    helpersPresent = HELPER_SYMBOLS.filter((name) => name in subagentModule)
    subagentVersion = packageVersion('@deepseek-ai/dsh-subagent')
    const ctx = new Context()
    await mountAgentLoopTestDependencies(ctx)
    await ctx.plugin(SubagentRuntime)
    for (const provider of PROVIDERS) {
      providerRecords.push(await collectProvider(ctx, provider))
    }
  } catch (error) {
    bootError = {
      name: error?.constructor?.name ?? 'Error',
      message: String(error?.message ?? error).slice(0, 400),
    }
  }

  const outOfProcessWithCapability = providerRecords.filter(
    (item) => item.boundary === 'out-of-process'
      && item.prepare_continuable_present === true
      && item.gate?.ok === true)
  const inProcessWithCapability = providerRecords.filter(
    (item) => item.boundary === 'in-process'
      && item.prepare_continuable_present === true
      && item.gate?.ok === true)

  const payload = {
    schema_version: 'byq-v090-dsh-provider-qualification-capability-inventory.v1',
    generated_at: new Date().toISOString(),
    examined_version: {
      id: VERSION_ID,
      npm: NPM_VERSION,
      channel: args.channel ?? null,
      subagent_package_version: subagentVersion,
    },
    evidence_class: 'native-runtime-isolated',
    llm: { class: 'no-llm', real_llm_quality: false,
           note: 'capability inventory makes no LLM call' },
    boot_error: bootError,
    providers: providerRecords,
    declared_limitations: declaredLimitations(),
    out_of_process_helpers: helpersPresent,
    helper_symbols_are_not_capability: true,
    cross_process_continuation_qualification: null,
    cross_process_continuation_qualification_reason:
      'no out-of-process continuable provider exists in the examined release to run a '
      + 'cross-process continuation, mailbox/lease, at-most-once settlement or orphan-cleanup '
      + 'qualification against',
    conclusions: {
      out_of_process_continuable_provider_available: outOfProcessWithCapability.length > 0,
      in_process_continuable_provider_available: inProcessWithCapability.length > 0,
      out_of_process_provider_without_prepare_continuable_rejected:
        providerRecords.some((item) => item.boundary === 'out-of-process'
          && item.prepare_continuable_present === false
          && item.gate?.kind === 'unsupported-capability'),
      cross_process_qualification_ok: false,
      out_of_process_continuable_providers: outOfProcessWithCapability.map((item) => item.name),
      in_process_continuable_providers: inProcessWithCapability.map((item) => item.name),
    },
    production_unchanged: {
      selector: 'config/dsh/deployment.json default_release=dsh-0.1.2rc1',
      note: 'probe boots only an isolated in-memory cordis context from a scratch install; '
        + 'no DSH fork/patch and no production file written',
    },
  }

  const text = JSON.stringify(payload, null, 2) + '\n'
  mkdirSync(dirname(OUT), { recursive: true })
  writeFileSync(OUT, text)
  process.stdout.write(text)
}

main().catch((error) => {
  process.stderr.write(String(error?.stack ?? error) + '\n')
  process.exit(1)
})
