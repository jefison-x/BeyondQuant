#!/usr/bin/env node
/**
 * 0.9 strict-order step-5 B1 capability discovery: `subagent-child-crash` owner
 * `d15-4-child-provider-remediation`.
 *
 * Read-only discovery against the actual DSH `0.1.5-rc.1` candidate. It answers
 * exactly one question and nothing else:
 *
 *   Does an OUT-OF-PROCESS continuable provider exist that
 *   (a) implements `SubagentProvider.prepareContinuable`,
 *   (b) can have its child independently killed/restarted, and
 *   (c) has a native resume surface?
 *
 * Method (all isolated, no production runtime, no DSH fork/patch):
 *   * boot the real candidate cordis context + the real `SubagentRuntime`;
 *   * register the real candidate providers (`spawn`, `fork` in-process;
 *     `acp`, `codex`, `claude-code` out-of-process; optional `dsh-sdk`);
 *   * for each provider record `prepareContinuable` presence + real capabilities;
 *   * exercise the REAL native capability gate `SubagentRuntime.prepareContinuable`
 *     and capture the typed rejection for providers without the capability;
 *   * optionally verify the candidate source archive sha256 and scan the upstream
 *     `packages/subagent/<package>/src/index.ts` for `prepareContinuable` (source-level
 *     provenance, no install required for that part).
 *
 * This probe never SIGKILLs a child, never fakes an owning-process crash, never
 * substitutes a BYQ child-resume bridge and never mutates a provider. A `PASS`
 * for B1 would require an out-of-process provider with the capability; when none
 * exists the honest result is BLOCKED (see the observer).
 *
 * Usage:
 *   node child_provider_discovery.mjs run [--out <path>] [--source-archive <tar.gz>]
 */

import { createHash } from 'node:crypto'
import { readFileSync, writeFileSync, mkdirSync, existsSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { spawnSync } from 'node:child_process'
import { Context } from '@deepseek-ai/cordis'
import SubagentRuntime from '@deepseek-ai/dsh-subagent'
import { mountAgentLoopTestDependencies } from '@deepseek-ai/dsh-agent-loop-testkit'
import * as Spawn from '@deepseek-ai/dsh-subagent-spawn-in-process'
import * as Fork from '@deepseek-ai/dsh-subagent-fork-in-process'
import * as Acp from '@deepseek-ai/dsh-subagent-acp'
import * as Codex from '@deepseek-ai/dsh-subagent-codex'
import * as ClaudeCode from '@deepseek-ai/dsh-subagent-claude-code'

const HERE = dirname(fileURLToPath(import.meta.url))
const ROOT = resolve(HERE, '..', '..', '..')
const CANDIDATE_DECLARATION = join(ROOT, 'config/dsh/candidates/dsh-0.1.5rc1/candidate.json')

// Candidate-bundled subagent providers. `boundary` is the transport the provider
// owns; the in-process pair shares the executor OS process, the rest spawn a
// separate child process. `required_in_bundle` records candidate membership.
const PROVIDERS = [
  {
    name: 'spawn', package: '@deepseek-ai/dsh-subagent-spawn-in-process', module: Spawn,
    boundary: 'in-process', in_candidate_bundle: true,
    config: { providerName: 'spawn' },
  },
  {
    name: 'fork', package: '@deepseek-ai/dsh-subagent-fork-in-process', module: Fork,
    boundary: 'in-process', in_candidate_bundle: true,
    config: { providerName: 'fork' },
  },
  {
    name: 'acp', package: '@deepseek-ai/dsh-subagent-acp', module: Acp,
    boundary: 'out-of-process', in_candidate_bundle: true,
    config: { providerName: 'acp', command: 'true', args: [], disposeEofGraceMs: 5000, disposeGraceMs: 5000 },
  },
  {
    name: 'codex', package: '@deepseek-ai/dsh-subagent-codex', module: Codex,
    boundary: 'out-of-process', in_candidate_bundle: true,
    config: { providerName: 'codex', env: {}, permissionMode: 'never', disposeGraceMs: 5000 },
  },
  {
    name: 'claude-code', package: '@deepseek-ai/dsh-subagent-claude-code', module: ClaudeCode,
    boundary: 'out-of-process', in_candidate_bundle: true,
    config: { providerName: 'claude-code', env: {}, permissionMode: 'dontAsk', disposeGraceMs: 5000 },
  },
  {
    // Published at 0.1.5-rc.1 but NOT part of the candidate bundled runtime list
    // (see docs/evidence/d15/d15-4/routing.v1.json). Included only to record that
    // it too has no prepareContinuable; its absence from the bundle is reported.
    name: 'dsh-sdk', package: '@deepseek-ai/dsh-subagent-dsh-sdk', module: null,
    boundary: 'out-of-process', in_candidate_bundle: false,
    config: { providerName: 'dsh-sdk', dshHome: '/tmp/byq-d15-probe-dsh-home', patches: [], shutdownTimeoutMs: 5000, disposeEofGraceMs: 5000, disposeGraceMs: 5000 },
  },
]

async function loadOptionalModule(packageName) {
  try {
    return await import(packageName)
  } catch (error) {
    return { __importError: String(error?.message ?? error) }
  }
}

function sha256File(path) {
  const hash = createHash('sha256')
  hash.update(readFileSync(path))
  return hash.digest('hex')
}

function tarList(archive) {
  const result = spawnSync('tar', ['tzf', archive], { encoding: 'utf8', maxBuffer: 64 * 1024 * 1024 })
  if (result.status !== 0) return null
  return result.stdout.split('\n').filter(Boolean)
}

function tarRead(archive, member) {
  const result = spawnSync('tar', ['xzOf', archive, member], { encoding: 'utf8', maxBuffer: 16 * 1024 * 1024 })
  return result.status === 0 ? result.stdout : null
}

function scanSourceArchive(archive, declaration) {
  const entries = tarList(archive)
  if (entries === null) return { available: false, reason: 'tar listing failed' }
  const prefix = entries.find((item) => /^deepseek-harness-[0-9a-f]+\/packages\/subagent\//.test(item))
  const root = prefix ? prefix.slice(0, prefix.indexOf('/packages/')) : null
  if (root === null) return { available: false, reason: 'candidate source tree not found in archive' }
  const packages = []
  for (const provider of PROVIDERS) {
    const member = `${root}/packages/subagent/${provider.package.replace('@deepseek-ai/dsh-subagent-', 'subagent-')}/src/index.ts`
    const content = tarRead(archive, member)
    packages.push({
      provider: provider.name,
      package: provider.package,
      source_member: member,
      source_found: content !== null,
      source_has_prepare_continuable: content !== null && content.includes('prepareContinuable'),
      source_advertises_no_start_capabilities: content !== null && content.includes('NO_START_CAPABILITIES'),
    })
  }
  return { available: true, root, packages }
}

function installedVersion(packageName) {
  try {
    const manifest = join(HERE, 'node_modules', ...packageName.split('/'), 'package.json')
    return JSON.parse(readFileSync(manifest, 'utf8')).version
  } catch {
    return null
  }
}

async function collectProvider(ctx, provider) {
  const record = {
    name: provider.name,
    package: provider.package,
    boundary: provider.boundary,
    in_candidate_bundle: provider.in_candidate_bundle,
    import_ok: true,
    version: installedVersion(provider.package),
    prepare_continuable_present: false,
    capabilities: null,
    inherits_parent_context: null,
    gate: { ok: null, kind: 'not-called' },
  }
  const module = provider.module ?? await loadOptionalModule(provider.package)
  if (module?.__importError) {
    record.import_ok = false
    record.import_error = module.__importError
    return record
  }
  try {
    module.apply(ctx, provider.config)
  } catch (error) {
    record.register_error = { name: error?.constructor?.name ?? 'Error', message: String(error?.message ?? error).slice(0, 300) }
    return record
  }
  const instance = ctx.subagents.getProvider(provider.name)
  if (instance === undefined) {
    record.register_error = { name: 'Error', message: 'provider was not registered' }
    return record
  }
  record.prepare_continuable_present = typeof instance.prepareContinuable === 'function'
  record.capabilities = instance.capabilities ?? null
  record.inherits_parent_context = instance.inheritsParentContext ?? null
  // Exercise the REAL native capability gate. `fork` needs a live parent log; a
  // zero-event stub is a valid empty prefix, so the capability is still measured.
  const parent = provider.name === 'fork'
    ? { session: { snapshotEvents: () => [] } }
    : null
  try {
    const spec = await ctx.subagents.prepareContinuable(provider.name, {
      sessionId: 'discovery-child', parent, signal: new AbortController().signal,
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

async function run(outPath, sourceArchive) {
  const declaration = JSON.parse(readFileSync(CANDIDATE_DECLARATION, 'utf8'))
  const providerRecords = []
  let bootError = null
  let sourceScan = { available: false, reason: 'no --source-archive provided' }
  let archiveReport = null

  if (sourceArchive) {
    const observed = sha256File(sourceArchive)
    const expected = declaration.upstream.source_archive_sha256
    archiveReport = {
      path: sourceArchive,
      observed_sha256: observed,
      expected_sha256: expected,
      matches_declaration: observed === expected,
    }
    sourceScan = scanSourceArchive(sourceArchive, declaration)
  }

  try {
    const ctx = new Context()
    await mountAgentLoopTestDependencies(ctx)
    await ctx.plugin(SubagentRuntime)
    for (const provider of PROVIDERS) {
      providerRecords.push(await collectProvider(ctx, provider))
    }
  } catch (error) {
    bootError = { name: error?.constructor?.name ?? 'Error', message: String(error?.message ?? error).slice(0, 400) }
  }

  const outOfProcessWithCapability = providerRecords.filter(
    (item) => item.boundary === 'out-of-process' && item.prepare_continuable_present === true)
  const inProcessWithCapability = providerRecords.filter(
    (item) => item.boundary === 'in-process' && item.prepare_continuable_present === true)
  const outOfProcessRejected = providerRecords.filter(
    (item) => item.boundary === 'out-of-process'
      && item.prepare_continuable_present === false
      && item.gate.kind === 'unsupported-capability')

  const payload = {
    schema_version: 'byq-v090-d15-child-provider-discovery.v1',
    generated_at: new Date().toISOString(),
    candidate: {
      release: 'dsh-0.1.5rc1',
      npm: declaration.target_npm_version,
      python_sdk: declaration.python.sdk,
    },
    provenance: {
      candidate_declaration: 'config/dsh/candidates/dsh-0.1.5rc1/candidate.json',
      source_tag: declaration.upstream.source_tag,
      source_commit: declaration.upstream.source_commit,
      source_archive_sha256: declaration.upstream.source_archive_sha256,
      archive: archiveReport,
    },
    evidence_class: 'native-runtime-isolated',
    llm: { class: 'no-llm', real_llm_quality: false, note: 'capability discovery makes no LLM call' },
    boot_error: bootError,
    providers: providerRecords,
    source_archive_scan: sourceScan,
    conclusions: {
      // Decisive answer to the B1 capability question.
      out_of_process_continuable_provider_available: outOfProcessWithCapability.length > 0,
      independently_killable_child_available: outOfProcessWithCapability.length > 0,
      native_resume_surface_for_out_of_process_child: outOfProcessWithCapability.length > 0,
      in_process_continuable_provider_available: inProcessWithCapability.length > 0,
      out_of_process_provider_without_prepare_continuable_rejected: outOfProcessRejected.length > 0,
      out_of_process_continuable_providers: outOfProcessWithCapability.map((item) => item.name),
      in_process_continuable_providers: inProcessWithCapability.map((item) => item.name),
    },
    substitutions_rejected: [
      'a BYQ child-resume bridge (ADR-0082 Option 2, rejected) is not a provider capability',
      'a same-process in-process provider is not an independently killable child',
      'an owning-process SIGKILL is not a child-only crash',
      'a label-only PASS without a real out-of-process prepareContinuable provider is not evidence',
    ],
    child_crash_qualification: null,
    child_crash_qualification_reason:
      'no out-of-process continuable provider exists to kill; an in-process child cannot be independently SIGKILLed, '
      + 'and killing the owning process is explicitly not a child crash',
    production_unchanged: {
      selector: 'config/dsh/deployment.json default_release=dsh-0.1.2rc1',
      note: 'probe boots only an isolated in-memory cordis context; no DSH fork/patch, no production file written',
    },
  }

  const text = JSON.stringify(payload, null, 2) + '\n'
  if (outPath) {
    mkdirSync(dirname(outPath), { recursive: true })
    writeFileSync(outPath, text)
  }
  process.stdout.write(text)
}

function main(argv) {
  const [mode, ...rest] = argv
  if (mode !== 'run') {
    process.stderr.write('usage: child_provider_discovery.mjs run [--out path] [--source-archive tar.gz]\n')
    process.exitCode = 2
    return
  }
  const outIndex = rest.indexOf('--out')
  const out = outIndex !== -1 ? rest[outIndex + 1] : null
  const archiveIndex = rest.indexOf('--source-archive')
  const archive = archiveIndex !== -1 ? rest[archiveIndex + 1] : null
  if (archive && !existsSync(archive)) {
    process.stderr.write(`source archive not found: ${archive}\n`)
    process.exitCode = 2
    return
  }
  run(out, archive).catch((error) => {
    process.stderr.write(String(error?.stack ?? error) + '\n')
    process.exitCode = 1
  })
}

main(process.argv.slice(2))
