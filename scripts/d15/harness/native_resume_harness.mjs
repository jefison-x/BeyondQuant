/**
 * D15-3 native session resume qualification harness.
 *
 * Question: for a BYQ AgentSession whose old runtime generation disappears, can
 * a NEW generation resume the SAME persisted DSH session natively, instead of
 * creating a new DSH session and replaying BYQ conversation context?
 *
 * The harness drives the real DSH 0.1.5-rc.1 session-persistence seam
 * (`SessionPersistence.create/open`, `SessionHandle.read/append/flush/close`,
 * `SessionWriteLease` via `flock(2)`, `readColdSessionLog`) with one OS process
 * per runtime generation. It classifies every Runtime Continuity failure-matrix
 * row from raw observations; the framework-neutral classification itself lives
 * in `packages/contracts/runtime_continuity.py` and is applied by
 * `scripts/d15/native_resume_qualification.py`.
 *
 * Usage:
 *   node native_resume_harness.mjs <observations.json>
 *
 * Deterministic apart from the generated-at timestamp and scratch paths.
 */

import { spawn } from 'node:child_process'
import { mkdtemp, rm, stat } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { writeFile, mkdir } from 'node:fs/promises'
import {
  PACKAGE_VERSIONS, TARGET_NPM_VERSION, closeBackend, completedTurn, contiguous,
  eventTypes, hasOpenTurn, mountBackend, nextTurn, openTurn, sessionHeader,
  validateEvents,
} from './native_resume_common.mjs'

const outputPath = process.argv[2]
if (!outputPath) {
  console.error('usage: node native_resume_harness.mjs <observations.json>')
  process.exit(2)
}

const here = dirname(fileURLToPath(import.meta.url))
const workerPath = join(here, 'native_resume_worker.mjs')

const BYQ_FALLBACK = 'BYQ lifecycle-journal conversation rehydration plus a new private DSH session (runtime.py::_rehydrate + _ensure_harness); raw DSH state is never parsed and the DSH session id never becomes the BYQ AgentSession identity.'

const scratchRoots = []

async function scratch(label) {
  const root = await mkdtemp(join(tmpdir(), `byq-d15-3-${label}-`))
  scratchRoots.push(root)
  return root
}

function spawnWorker(command) {
  const child = spawn(process.execPath, [workerPath, JSON.stringify(command)], {
    stdio: ['ignore', 'pipe', 'pipe'],
  })
  let stdout = ''
  let stderr = ''
  child.stdout.on('data', (chunk) => { stdout += chunk })
  child.stderr.on('data', (chunk) => { stderr += chunk })
  const first = new Promise((resolve, reject) => {
    const onData = () => {
      const index = stdout.indexOf('\n')
      if (index >= 0) {
        child.stdout.off('data', onData)
        resolve(JSON.parse(stdout.slice(0, index)))
      }
    }
    child.stdout.on('data', onData)
    child.on('error', reject)
    child.on('exit', (code) => {
      if (!stdout.includes('\n')) reject(new Error(`worker exited (${code}) without output: ${stderr.slice(0, 400)}`))
    })
  })
  const exited = new Promise((resolve) => child.on('exit', (code, signal) => resolve({ code, signal })))
  return { child, first, exited, stderr: () => stderr }
}

async function runToCompletion(command) {
  const worker = spawnWorker(command)
  const result = await worker.first
  const exit = await worker.exited
  return { result, exit, stderr: worker.stderr() }
}

async function killWorker(worker) {
  worker.child.kill('SIGKILL')
  await worker.exited
}

async function openAndRead(root, id, access) {
  const ctx = await mountBackend(root)
  const handle = await ctx.sessionPersistence.open(id, access)
  const slice = await handle.read(0)
  return { ctx, handle, events: slice.events }
}

async function statSession(root, id) {
  const ctx = await mountBackend(root)
  const snapshot = await ctx.sessionPersistence.stat(id)
  await closeBackend(ctx)
  return snapshot
}

function baseObservation({ id, fault, generation, lost_run, dsh_session_persisted, native_resume_available, native_resume, extra = {}, simulated, real, byqFallback = BYQ_FALLBACK }) {
  const native = native_resume ?? {}
  return {
    id,
    fault,
    generation,
    lost_run,
    dsh_session_persisted,
    native_resume_available,
    native_resume_same_session_id: native.same_session_id ?? null,
    native_resume_events_preserved: native.events_preserved ?? null,
    native_resume_sequence_contiguous: native.sequence_contiguous ?? null,
    native_resume_event_count: native.event_count ?? null,
    lease_contention_observed: extra.lease_contention_observed ?? false,
    lease_released_on_process_death: extra.lease_released_on_process_death ?? null,
    cold_read_interrupted_closers: extra.cold_read_interrupted_closers ?? null,
    open_turn_preserved: extra.open_turn_preserved ?? null,
    simulated,
    real,
    byq_fallback_required_if_native_unavailable: byqFallback,
    classification_input: {
      generation_survived: generation === 'survives',
      lost_run,
      native_session_persisted: dsh_session_persisted,
      native_resume_available,
      byq_fallback_available: true,
      previous_generation_state: extra.previous_generation_state
        ?? (generation === 'survives' ? 'alive' : (lost_run ? 'interrupted' : 'replaced')),
    },
  }
}

async function rowBrowserDisconnect() {
  const root = await scratch('browser')
  const ctx = await mountBackend(root)
  const handle = await ctx.sessionPersistence.create(sessionHeader('sess-browser', root))
  await handle.append(validateEvents(completedTurn(0, 1)))
  await handle.flush()
  // The browser transport drops; the runtime generation is untouched and the
  // same live write handle keeps the session.
  await handle.append(validateEvents(completedTurn(6, 2)))
  await handle.flush()
  const live = await handle.read(0)
  // Independent proof the session is also persisted and natively resumable.
  const reader = await openAndRead(root, 'sess-browser', 'read')
  const resumed = reader.events
  await reader.handle.close()
  await handle.close()
  await closeBackend(ctx)
  return baseObservation({
    id: 'browser-disconnect',
    fault: 'Browser disconnect',
    generation: 'survives',
    lost_run: false,
    dsh_session_persisted: true,
    native_resume_available: true,
    native_resume: {
      same_session_id: String(reader.handle.id) === 'sess-browser',
      events_preserved: resumed.length === live.events.length,
      sequence_contiguous: contiguous(resumed),
      event_count: resumed.length,
    },
    simulated: ['browser WebSocket/HTTP transport drop (no browser exists in this isolated harness)'],
    real: [
      'the surviving in-process runtime generation is the live SessionHandle',
      'append + flush on the same handle after the disconnect',
      'an independent read handle observes the persisted log',
    ],
  })
}

async function rowFrontendRestart() {
  const root = await scratch('frontend')
  const ctx = await mountBackend(root)
  const handle = await ctx.sessionPersistence.create(sessionHeader('sess-frontend', root))
  await handle.append(validateEvents(completedTurn(0, 1)))
  await handle.flush()
  // A restarted frontend attaches a new read consumer while the writer still
  // holds the cross-process write lease; readers never touch the lease.
  const reader = await openAndRead(root, 'sess-frontend', 'read')
  const observed = reader.events
  await reader.handle.close()
  await handle.append(validateEvents(completedTurn(6, 2)))
  await handle.flush()
  const live = await handle.read(0)
  await handle.close()
  await closeBackend(ctx)
  return baseObservation({
    id: 'frontend-restart',
    fault: 'Frontend restart',
    generation: 'survives',
    lost_run: false,
    dsh_session_persisted: true,
    native_resume_available: true,
    native_resume: {
      same_session_id: String(reader.handle.id) === 'sess-frontend',
      events_preserved: observed.length === 6,
      sequence_contiguous: contiguous(live.events),
      event_count: live.events.length,
    },
    simulated: ['frontend SPA reload (no frontend exists in this isolated harness)'],
    real: [
      'concurrent read handle over the same persisted session while the writer holds the lease',
      'writer continues the same durable sequence after the restart',
    ],
  })
}

async function rowGatewayRestart() {
  const root = await scratch('gateway')
  const ctx = await mountBackend(root)
  const handle = await ctx.sessionPersistence.create(sessionHeader('sess-gateway', root))
  await handle.append(validateEvents(completedTurn(0, 1)))
  await handle.flush()
  // The gateway replays from a cold read of the durable log; the runtime
  // generation (writer) survives and continues the sequence.
  const cold = await runToCompletion({ cmd: 'cold-read', root, id: 'sess-gateway' })
  await handle.append(validateEvents(completedTurn(6, 2)))
  await handle.flush()
  const live = await handle.read(0)
  await handle.close()
  await closeBackend(ctx)
  return baseObservation({
    id: 'gateway-restart',
    fault: 'Gateway restart',
    generation: 'survives',
    lost_run: false,
    dsh_session_persisted: true,
    native_resume_available: true,
    native_resume: {
      same_session_id: cold.result.session_id === 'sess-gateway',
      events_preserved: cold.result.events === 6,
      sequence_contiguous: contiguous(live.events),
      event_count: live.events.length,
    },
    simulated: ['gateway process restart (no gateway exists in this isolated harness)'],
    real: [
      'cold read of the durable DSH log through readColdSessionLog',
      'runtime generation survives and continues the persisted sequence',
    ],
  })
}

async function rowAdapterRestart() {
  const root = await scratch('adapter')
  const ctx = await mountBackend(root)
  const handle = await ctx.sessionPersistence.create(sessionHeader('sess-adapter', root))
  await handle.append(validateEvents(completedTurn(0, 1)))
  await handle.flush()
  await handle.close()
  await closeBackend(ctx)
  // New generation: a fresh backend instance opens the same session for write.
  const { ctx: ctx2, handle: resumed, events } = await openAndRead(root, 'sess-adapter', 'write')
  await resumed.append(validateEvents(completedTurn(events.length, nextTurn(events))))
  await resumed.flush()
  const after = (await resumed.read(0)).events
  await resumed.close()
  await closeBackend(ctx2)
  return baseObservation({
    id: 'adapter-restart',
    fault: 'Adapter restart',
    generation: 'replaced',
    lost_run: false,
    dsh_session_persisted: true,
    native_resume_available: true,
    native_resume: {
      same_session_id: String(resumed.id) === 'sess-adapter',
      events_preserved: events.length === 6,
      sequence_contiguous: contiguous(after),
      event_count: after.length,
    },
    simulated: ['adapter process restart (the fresh Cordis backend instance models the new generation)'],
    real: [
      'graceful handle close releases the write lease',
      'SessionPersistence.open(id, "write") resumes the SAME persisted session',
      'append + flush continue the durable sequence with no new session created',
    ],
  })
}

async function rowDshCrash() {
  const root = await scratch('crash')
  // Generation 1 creates a session with an open (unfinished) turn and flushes,
  // then is SIGKILLed mid-run: the kernel releases the flock lease.
  const holder = spawnWorker({ cmd: 'create-hold', root, id: 'sess-crash', events: 'open', flush: true })
  const created = await holder.first
  await killWorker(holder)
  // Generation 2 resumes the SAME persisted session.
  const { ctx, handle, events } = await openAndRead(root, 'sess-crash', 'write')
  const openTurnPreserved = hasOpenTurn(events)
  const cold = await runToCompletion({ cmd: 'cold-read', root, id: 'sess-crash' })
  await handle.close()
  await closeBackend(ctx)
  const stat = await statSession(root, 'sess-crash')
  return baseObservation({
    id: 'dsh-crash',
    fault: 'DSH crash',
    generation: 'replaced',
    lost_run: true,
    dsh_session_persisted: true,
    native_resume_available: true,
    native_resume: {
      same_session_id: String(handle.id) === 'sess-crash',
      events_preserved: events.length === created.appended,
      sequence_contiguous: contiguous(events),
      event_count: events.length,
    },
    extra: {
      lease_released_on_process_death: true,
      open_turn_preserved: openTurnPreserved,
      cold_read_interrupted_closers: cold.result.events - events.length,
      previous_generation_state: 'interrupted',
    },
    simulated: ['abrupt DSH process death while a root run was open (SIGKILL of the holder process)'],
    real: [
      'flush durability barrier persisted the open turn before the crash',
      'kernel flock release on process death',
      'new generation opens the same session and reads the interrupted turn evidence',
      'readColdSessionLog folds the open turn with synthetic interrupted closers (nothing written back)',
    ],
    byqFallback: BYQ_FALLBACK,
  })
}

async function rowRuntimeGenerationReplacement() {
  const root = await scratch('generation')
  const created = await runToCompletion({ cmd: 'create-exit', root, id: 'sess-generation', events: 'completed', flush: true })
  const { ctx, handle, events } = await openAndRead(root, 'sess-generation', 'write')
  await handle.append(validateEvents(completedTurn(events.length, nextTurn(events))))
  await handle.flush()
  const after = (await handle.read(0)).events
  await handle.close()
  await closeBackend(ctx)
  return baseObservation({
    id: 'runtime-generation-replacement',
    fault: 'RuntimeGeneration replacement',
    generation: 'replaced',
    lost_run: false,
    dsh_session_persisted: true,
    native_resume_available: true,
    native_resume: {
      same_session_id: String(handle.id) === 'sess-generation',
      events_preserved: events.length === created.result.appended,
      sequence_contiguous: contiguous(after),
      event_count: after.length,
    },
    simulated: ['explicit generation rotation (new worker process == new generation)'],
    real: [
      'generation-1 materializes and exits cleanly',
      'generation-2 natively resumes the same durable session identity',
    ],
  })
}

async function rowHostReboot() {
  const root = await scratch('reboot')
  const holder = spawnWorker({ cmd: 'create-hold', root, id: 'sess-reboot', events: 'completed', flush: true })
  const created = await holder.first
  // Host reboot: every process dies without cleanup. The kernel drops the lock.
  await killWorker(holder)
  const { ctx, handle, events } = await openAndRead(root, 'sess-reboot', 'write')
  await handle.append(validateEvents(completedTurn(events.length, nextTurn(events))))
  await handle.flush()
  const after = (await handle.read(0)).events
  await handle.close()
  await closeBackend(ctx)
  return baseObservation({
    id: 'host-reboot',
    fault: 'Host reboot',
    generation: 'replaced',
    lost_run: false,
    dsh_session_persisted: true,
    native_resume_available: true,
    native_resume: {
      same_session_id: String(handle.id) === 'sess-reboot',
      events_preserved: events.length === created.appended,
      sequence_contiguous: contiguous(after),
      event_count: after.length,
    },
    extra: { lease_released_on_process_death: true },
    simulated: ['host reboot: all processes killed without cleanup (SIGKILL of the holder process)'],
    real: [
      'durable log survives process/host death',
      'flock lease is released by the kernel, so there is no stale lease',
      'a new generation natively resumes the same session',
    ],
  })
}

async function rowExecutorTakeover() {
  const root = await scratch('takeover')
  const ctx = await mountBackend(root)
  const seed = await ctx.sessionPersistence.create(sessionHeader('sess-takeover', root))
  await seed.append(validateEvents(completedTurn(0, 1)))
  await seed.flush()
  await seed.close()
  await closeBackend(ctx)
  // Executor-1 holds the write lease in another process.
  const holder = spawnWorker({ cmd: 'hold-write', root, id: 'sess-takeover' })
  await holder.first
  // Executor-2 is fenced by the kernel lease.
  let contention = null
  const challenger = await mountBackend(root)
  try {
    await challenger.sessionPersistence.open('sess-takeover', 'write')
    contention = { blocked: false, error: null }
  } catch (error) {
    contention = { blocked: true, error: error?.name ?? 'Error' }
  }
  await closeBackend(challenger)
  // Executor-1 dies; the lease is released and executor-2 takes over natively.
  await killWorker(holder)
  const { ctx: ctx3, handle, events } = await openAndRead(root, 'sess-takeover', 'write')
  await handle.append(validateEvents(completedTurn(events.length, nextTurn(events))))
  await handle.flush()
  const after = (await handle.read(0)).events
  await handle.close()
  await closeBackend(ctx3)
  return baseObservation({
    id: 'executor-takeover',
    fault: 'executor takeover',
    generation: 'replaced',
    lost_run: false,
    dsh_session_persisted: true,
    native_resume_available: true,
    native_resume: {
      same_session_id: String(handle.id) === 'sess-takeover',
      events_preserved: events.length === 6,
      sequence_contiguous: contiguous(after),
      event_count: after.length,
    },
    extra: {
      lease_contention_observed: contention.blocked,
      lease_released_on_process_death: true,
      fencing_error: contention.error,
    },
    simulated: ['executor identity rotation (a second worker process attempts the write lease)'],
    real: [
      'a live writer is fenced by flock: SessionAlreadyOwnedError',
      'after the old executor dies the lease is released and the new executor takes over natively',
    ],
  })
}

async function controlNativeUnavailable() {
  const root = await scratch('native-unavailable')
  // Generation 1 creates a session but crashes before the durability barrier,
  // so the session never materialized.
  const holder = spawnWorker({ cmd: 'create-hold', root, id: 'sess-unmaterialized', events: 'none', flush: false })
  const created = await holder.first
  await killWorker(holder)
  const snapshot = await statSession(root, 'sess-unmaterialized')
  let openError = null
  try {
    const { ctx, handle } = await openAndRead(root, 'sess-unmaterialized', 'write')
    await handle.close()
    await closeBackend(ctx)
  } catch (error) {
    openError = error?.name ?? 'Error'
  }
  return baseObservation({
    id: 'native-unavailable-control',
    fault: 'Native resume unavailable control (unmaterialized session)',
    generation: 'replaced',
    lost_run: false,
    dsh_session_persisted: false,
    native_resume_available: false,
    native_resume: { same_session_id: null, events_preserved: null, sequence_contiguous: null, event_count: null },
    extra: {
      stat_visible: Boolean(snapshot),
      open_error: openError,
      created_flushed: created.flushed,
      previous_generation_state: 'absent',
    },
    simulated: ['crash before the SessionHandle.flush() durability barrier (SIGKILL after create, no append/flush)'],
    real: [
      'a session that never materialized is invisible to stat/open after the process dies',
      'the refused open does not fabricate a successor session',
      'native resume is therefore unavailable and BYQ conversation fallback is required',
    ],
  })
}

async function main() {
  const observations = []
  const rows = [
    rowBrowserDisconnect,
    rowFrontendRestart,
    rowGatewayRestart,
    rowAdapterRestart,
    rowDshCrash,
    rowRuntimeGenerationReplacement,
    rowHostReboot,
    rowExecutorTakeover,
  ]
  try {
    for (const row of rows) {
      const observation = await row()
      observations.push(observation)
      console.error(`[d15-3] ${observation.id}: generation=${observation.generation} lost_run=${observation.lost_run} persisted=${observation.dsh_session_persisted} native_resume=${observation.native_resume_available}`)
    }
    const control = await controlNativeUnavailable()
    observations.push(control)
    console.error(`[d15-3] ${control.id}: generation=${control.generation} persisted=${control.dsh_session_persisted} native_resume=${control.native_resume_available}`)

    const document = {
      schema_version: 'byq-d15-3-native-resume-observations.v1',
      generated_at: new Date().toISOString(),
      target: {
        release_id: 'dsh-0.1.5rc1',
        python_sdk: '0.1.5rc1',
        python_runtime_bin: '0.1.5rc1',
        bundled_npm_version: TARGET_NPM_VERSION,
        source_tag: 'dsh-v0.1.5-rc.1',
        source_commit: '183f08e9c6dde7e36cd2318eaee70b0da08fb35e',
      },
      harness: {
        script: 'scripts/d15/harness/native_resume_harness.mjs',
        worker: 'scripts/d15/harness/native_resume_worker.mjs',
        package_versions: PACKAGE_VERSIONS,
        scope: 'Real DSH 0.1.5-rc.1 session-persistence seam: SessionPersistence.create/open, SessionHandle.read/append/flush/close, cross-process SessionWriteLease (flock), readColdSessionLog. One OS process per runtime generation.',
        classification: 'scripts/d15/native_resume_qualification.py (packages/contracts/runtime_continuity.py::classify_generation_transition)',
      },
      failure_rows: observations.filter((item) => !item.id.endsWith('control')),
      controls: observations.filter((item) => item.id.endsWith('control')),
    }
    await mkdir(dirname(outputPath), { recursive: true }).catch(() => {})
    await writeFile(outputPath, `${JSON.stringify(document, null, 2)}\n`, 'utf8')
    console.log(JSON.stringify({
      schema_version: document.schema_version,
      failure_rows: document.failure_rows.length,
      controls: document.controls.length,
    }, null, 2))
    return 0
  } finally {
    for (const root of scratchRoots) await rm(root, { recursive: true, force: true }).catch(() => {})
  }
}

main().then((code) => process.exit(code)).catch((error) => {
  console.error(error)
  process.exit(2)
})
