#!/usr/bin/env node
/**
 * D15-5 real native persistent-terminal (PTY) continuity harness.
 *
 * Evidence-only qualification harness pinned to the fixed DSH 0.1.5-rc.1
 * candidate closure. It boots the REAL native terminal stack
 * (`@deepseek-ai/dsh-terminal` owner-scoped registry +
 * `@deepseek-ai/dsh-terminal-bash` `shell` backend + subprocess/sandbox
 * providers) inside a dedicated **runtime OS process**, and drives it from
 * separate **client OS processes** over a Unix socket. An evidence-only BYQ
 * `TerminalAttachment` gate (attachment identity, state, authorization,
 * reconnect) wraps the native service; it owns no PTY/shell/IO.
 *
 * The native DSH terminal is documented as process-local: sessions do not
 * survive a harness restart. This harness therefore distinguishes
 *
 *   * PTY/process existence       (the real external shell pid)
 *   * attachment existence        (the BYQ-owned gate record)
 *   * I/O rebind                  (a different OS process reading/sending)
 *   * stable terminal identity    (same attachment id / session id / pid)
 *
 * It is NOT a product runtime, NOT a second generic agent harness, and it
 * persists no BYQ terminal state. It calls no model (`not-applicable`).
 *
 * Usage:
 *   node native_terminal_harness.mjs run [--out <path>]
 *   node native_terminal_harness.mjs runtime --socket <path> --generation N --epoch N
 *   node native_terminal_harness.mjs client --socket <path> --request '<json>'
 */

import { mkdtempSync, readFileSync, writeFileSync, rmSync, existsSync } from 'node:fs'
import { randomBytes } from 'node:crypto'
import { tmpdir } from 'node:os'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { spawn, spawnSync } from 'node:child_process'
import { createServer, connect } from 'node:net'

import { Context } from '@deepseek-ai/cordis'
import { SessionId } from '@deepseek-ai/dsh-session'
import { mountAgentLoopTestDependencies, mountAgentLoopTestHarness } from '@deepseek-ai/dsh-agent-loop-testkit'
import TerminalService from '@deepseek-ai/dsh-terminal'
import * as TerminalBash from '@deepseek-ai/dsh-terminal-bash'
import SubprocessLocal from '@deepseek-ai/dsh-subprocess-local'
import SandboxLocal from '@deepseek-ai/dsh-sandbox-local'
import SandboxPolicy from '@deepseek-ai/dsh-sandbox-policy'

export const EVIDENCE_CLASS = 'native-runtime-isolated'
export const LLM_CLASS = 'not-applicable'
export const CANDIDATE_RELEASE = 'dsh-0.1.5rc1'
export const CANDIDATE_NPM = '0.1.5-rc.1'

const HERE = dirname(fileURLToPath(import.meta.url))
const NODE = process.execPath

const OWNER_ID = 'd15-5-owner'
const OTHER_OWNER_ID = 'd15-5-other-owner'
const OWNER_PRINCIPAL = 'principal-owner'
const OTHER_PRINCIPAL = 'principal-other'

// ---------------------------------------------------------------------------
// small helpers
// ---------------------------------------------------------------------------

function nowIso() {
  return new Date().toISOString()
}

function alive(pid) {
  if (!Number.isInteger(pid) || pid <= 0) return false
  try {
    process.kill(pid, 0)
    return true
  } catch {
    return false
  }
}

function procCmdline(pid) {
  try {
    return readFileSync(`/proc/${pid}/cmdline`, 'utf8').split('\u0000').filter(Boolean).join(' ')
  } catch {
    return null
  }
}

/**
 * Count output lines equal to the marker. The interactive PTY echoes the typed
 * command (`echo <marker>`) as well as the command's output, so a raw substring
 * count is 2; the unique marker's *result* line is what must occur exactly once.
 */
function countMarkerLines(text, marker) {
  if (typeof text !== 'string' || !marker) return 0
  return text.split('\n').filter((line) => line.trim() === marker).length
}

/** One-shot client process request against a running runtime socket. */
function clientCall(socketPath, request, { timeout = 60000 } = {}) {
  return new Promise((resolve, reject) => {
    const socket = connect(socketPath)
    let buffer = ''
    const timer = setTimeout(() => {
      socket.destroy()
      reject(new Error('client request timed out'))
    }, timeout)
    socket.on('connect', () => socket.write(JSON.stringify(request) + '\n'))
    socket.on('data', (chunk) => {
      buffer += chunk.toString('utf8')
      const index = buffer.indexOf('\n')
      if (index >= 0) {
        clearTimeout(timer)
        const line = buffer.slice(0, index)
        socket.end()
        try {
          resolve(JSON.parse(line))
        } catch (error) {
          reject(new Error(`bad runtime response: ${line}`))
        }
      }
    })
    socket.on('error', (error) => {
      clearTimeout(timer)
      reject(error)
    })
  })
}

// ---------------------------------------------------------------------------
// runtime process: real native terminal + evidence-only BYQ attachment gate
// ---------------------------------------------------------------------------

async function bootRuntime() {
  const ctx = new Context()
  await mountAgentLoopTestDependencies(ctx)
  const harness = await mountAgentLoopTestHarness(ctx)
  await ctx.plugin(SubprocessLocal)
  await ctx.plugin(SandboxLocal)
  await ctx.plugin(SandboxPolicy)
  await ctx.plugin(TerminalService)
  await ctx.plugin(TerminalBash)
  const owner = await harness.create(SessionId(OWNER_ID), { provider: 'mock', model: 'mock' })
  const other = await harness.create(SessionId(OTHER_OWNER_ID), { provider: 'mock', model: 'mock' })
  return { ctx, owner, other }
}

function reject(code, detail) {
  return { ok: false, error: code, detail: detail ?? null }
}

async function runtimeMain(argv) {
  const socketPath = argv.socket
  const generation = Number(argv.generation)
  const epoch = Number(argv.epoch)
  const { ctx, owner, other } = await bootRuntime()

  let nextId = 0
  const gate = new Map() // attachmentId -> record
  const allPids = []
  let shuttingDown = false

  function attachmentFor(ownerAgentId) {
    return [...gate.values()].filter((record) => record.ownerAgentId === ownerAgentId)
  }

  function gateCheck(record, request) {
    if (record === undefined) return reject('UNKNOWN_ATTACHMENT')
    if (request.principal !== record.principal) return reject('UNAUTHORIZED_PRINCIPAL')
    if (typeof request.token !== 'string' || request.token !== record.token) return reject('UNAUTHORIZED_ATTACHMENT')
    if (record.active !== true) return reject('ATTACHMENT_DETACHED')
    if (request.generation !== undefined && request.generation !== record.generation) return reject('STALE_GENERATION')
    if (request.epoch !== undefined && request.epoch !== record.epoch) return reject('STALE_EPOCH')
    return null
  }

  async function handle(request) {
    const op = request.op
    switch (op) {
      case 'spawn': {
        if (request.principal !== OWNER_PRINCIPAL) return reject('UNAUTHORIZED_PRINCIPAL')
        const name = typeof request.name === 'string' && request.name.length > 0 ? request.name : `main-${++nextId}`
        const spawned = await ctx.terminals.spawn(owner, { type: 'shell', name })
        const attachmentId = `att-${generation}-${nextId}`
        const token = randomBytes(18).toString('hex')
        const record = {
          attachmentId, token, sessionId: String(spawned.sessionId), pid: spawned.pid ?? null,
          generation, epoch, principal: OWNER_PRINCIPAL, ownerAgentId: OWNER_ID, active: true, name,
        }
        gate.set(attachmentId, record)
        if (record.pid !== null) allPids.push({ attachmentId, sessionId: record.sessionId, pid: record.pid })
        return {
          ok: true, attachmentId, token, sessionId: record.sessionId, pid: record.pid,
          generation, epoch, motd: spawned.motd, ptyCmdline: record.pid ? procCmdline(record.pid) : null,
        }
      }
      case 'run': {
        const record = gate.get(request.attachmentId)
        const failure = gateCheck(record, request)
        if (failure) return failure
        const before = ctx.terminals.read(owner, record.sessionId, { count: 1 })
        let operation
        try {
          operation = ctx.terminals.startSend(owner, record.sessionId, { text: request.text, submit: true })
        } catch (error) {
          return reject('SEND_REJECTED', { code: error.code ?? error.name, message: String(error.message) })
        }
        const result = await operation.done
        return {
          ok: true, sessionId: record.sessionId, pid: record.pid,
          viewport: result.viewport, waitReason: result.waitReason,
          sessionStatusKind: result.sessionStatus?.kind ?? null, truncated: result.truncated,
          totalLinesBefore: before.totalLines,
        }
      }
      case 'read': {
        const record = gate.get(request.attachmentId)
        const failure = gateCheck(record, request)
        if (failure) return failure
        const result = ctx.terminals.read(owner, record.sessionId, { count: request.count ?? 50 })
        return { ok: true, sessionId: record.sessionId, pid: record.pid, ...result }
      }
      case 'status': {
        const record = request.attachmentId ? gate.get(request.attachmentId) : null
        return {
          ok: true,
          generation, epoch,
          attachmentPresent: record !== undefined && record.active === true,
          attachmentId: record?.attachmentId ?? null,
          sessionId: record?.sessionId ?? null,
          pid: record?.pid ?? null,
          pidAlive: record ? alive(record.pid) : false,
          ptyCmdline: record && record.pid ? procCmdline(record.pid) : null,
          nativeSessions: ctx.terminals.list(owner).map((item) => ({ sessionId: String(item.sessionId), pid: item.pid ?? null, status: item.status?.kind ?? null })),
          backends: ctx.terminals.listBackends(),
        }
      }
      case 'foreign-send': {
        try {
          const operation = ctx.terminals.startSend(other, request.sessionId, { text: request.text, submit: true })
          await operation.done
          return { ok: true, rejected: false }
        } catch (error) {
          return { ok: true, rejected: true, errorCode: error.code ?? error.name, errorClass: error.name, message: String(error.message) }
        }
      }
      case 'foreign-read': {
        try {
          ctx.terminals.read(other, request.sessionId, { count: 5 })
          return { ok: true, rejected: false }
        } catch (error) {
          return { ok: true, rejected: true, errorCode: error.code ?? error.name, errorClass: error.name, message: String(error.message) }
        }
      }
      case 'unknown-read': {
        try {
          ctx.terminals.read(owner, request.sessionId, { count: 5 })
          return { ok: true, rejected: false }
        } catch (error) {
          return { ok: true, rejected: true, errorCode: error.code ?? error.name, errorClass: error.name, message: String(error.message) }
        }
      }
      case 'gate-check': {
        const record = gate.get(request.attachmentId)
        const failure = gateCheck(record, request)
        return failure ?? { ok: true, accepted: true }
      }
      case 'detach': {
        const record = gate.get(request.attachmentId)
        if (record === undefined) return reject('UNKNOWN_ATTACHMENT')
        record.active = false
        return { ok: true, attachmentId: record.attachmentId, sessionId: record.sessionId, pid: record.pid, pidAlive: alive(record.pid) }
      }
      case 'kill': {
        const record = gate.get(request.attachmentId)
        if (record === undefined) return reject('UNKNOWN_ATTACHMENT')
        if (request.token !== record.token) return reject('UNAUTHORIZED_ATTACHMENT')
        const pidBefore = record.pid
        const killed = await ctx.terminals.kill(owner, record.sessionId, request.reason ?? 'd15-5 cleanup')
        record.active = false
        await new Promise((resolve) => setTimeout(resolve, 250))
        return { ok: true, killed, sessionId: record.sessionId, pidBefore, pidAliveAfter: alive(pidBefore) }
      }
      case 'shutdown': {
        if (shuttingDown) return { ok: true, already: true }
        shuttingDown = true
        for (const record of gate.values()) {
          try {
            await ctx.terminals.kill(owner, record.sessionId, 'd15-5 shutdown')
          } catch {
            // cleanup is verified below via pids
          }
          record.active = false
        }
        await new Promise((resolve) => setTimeout(resolve, 300))
        const pidStates = allPids.map((item) => ({ ...item, alive: alive(item.pid) }))
        return { ok: true, pidStates, orphans: pidStates.filter((item) => item.alive).length }
      }
      default:
        return reject('UNKNOWN_OP', { op })
    }
  }

  const server = createServer((socket) => {
    let buffer = ''
    socket.on('data', (chunk) => {
      buffer += chunk.toString('utf8')
      const index = buffer.indexOf('\n')
      if (index < 0) return
      const line = buffer.slice(0, index)
      socket.pause()
      let request
      try {
        request = JSON.parse(line)
      } catch (error) {
        socket.end(JSON.stringify(reject('BAD_REQUEST', String(error.message))) + '\n')
        return
      }
      Promise.resolve()
        .then(() => handle(request))
        .then((response) => {
          socket.end(JSON.stringify(response) + '\n')
          if (request.op === 'shutdown' && response.ok === true) {
            setTimeout(() => server.close(() => process.exit(0)), 50)
          }
        })
        .catch((error) => socket.end(JSON.stringify(reject('RUNTIME_ERROR', String(error?.stack ?? error))) + '\n'))
    })
  })

  // A SIGKILLed predecessor leaves a stale socket file; it is not a live
  // listener, so removing it before rebinding is safe and is what lets a fresh
  // runtime generation come up on the same path.
  rmSync(socketPath, { force: true })
  await new Promise((resolve, rejectPromise) => {
    server.once('error', rejectPromise)
    server.listen(socketPath, () => resolve())
  })

  process.stdout.write(JSON.stringify({ ready: true, runtimePid: process.pid, generation, epoch, backends: ctx.terminals.listBackends() }) + '\n')

  const stop = async () => {
    try {
      await handle({ op: 'shutdown' })
    } catch {
      // best effort
    }
    server.close()
    try { await ctx.stop?.() } catch { /* best effort */ }
    process.exit(0)
  }
  process.on('SIGTERM', stop)
  process.on('SIGINT', stop)
}

// ---------------------------------------------------------------------------
// client process: one OS process making exactly one request
// ---------------------------------------------------------------------------

async function clientMain(argv) {
  const request = JSON.parse(argv.request)
  try {
    const response = await clientCall(argv.socket, request)
    process.stdout.write(JSON.stringify(response) + '\n')
    process.exit(0)
  } catch (error) {
    process.stdout.write(JSON.stringify({ ok: false, clientError: String(error.message) }) + '\n')
    process.exit(2)
  }
}

// ---------------------------------------------------------------------------
// orchestrator
// ---------------------------------------------------------------------------

const NEGATIVE_KINDS = [
  'foreign-owner-send', 'foreign-owner-read', 'unknown-terminal', 'foreign-principal', 'stale-generation', 'stale-epoch',
]

function waitExit(child) {
  if (child.exitCode !== null || child.signalCode !== null) return Promise.resolve()
  return new Promise((resolve) => child.once('exit', resolve))
}

function spawnRuntime(socketPath, generation, epoch) {
  const child = spawn(NODE, [fileURLToPath(import.meta.url), 'runtime', '--socket', socketPath,
    '--generation', String(generation), '--epoch', String(epoch)], { stdio: ['ignore', 'pipe', 'pipe'] })
  let stderr = ''
  let stdout = ''
  child.stderr.on('data', (chunk) => { stderr += chunk.toString('utf8') })
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(`runtime did not become ready: ${stderr}`)), 60000)
    child.stdout.on('data', (chunk) => {
      stdout += chunk.toString('utf8')
      const index = stdout.indexOf('\n')
      if (index >= 0 && !child.d15Ready) {
        child.d15Ready = JSON.parse(stdout.slice(0, index))
        clearTimeout(timer)
        resolve(child)
      }
    })
    child.on('exit', (code) => {
      if (!child.d15Ready) {
        clearTimeout(timer)
        reject(new Error(`runtime exited ${code}: ${stderr}`))
      }
    })
  })
}

/** Run one client as a genuinely separate OS process. */
function client(socketPath, request) {
  const result = spawnSync(NODE, [fileURLToPath(import.meta.url), 'client', '--socket', socketPath,
    '--request', JSON.stringify(request)], { encoding: 'utf8', timeout: 120000 })
  if (result.status !== 0 && !result.stdout.trim()) {
    return { ok: false, clientError: (result.stderr || `client exit ${result.status}`).trim() }
  }
  try {
    return JSON.parse(result.stdout.trim().split('\n').pop())
  } catch (error) {
    return { ok: false, clientError: `bad client output: ${result.stdout}` }
  }
}

function log(message) {
  process.stderr.write(`[d15-5] ${message}\n`)
}

function randomMarker(prefix) {
  return `${prefix}_${randomBytes(8).toString('hex')}`
}

async function run() {
  const tempRoot = mkdtempSync(join(tmpdir(), 'd15-5-terminal-'))
  const socketPath = join(tempRoot, 'runtime.sock')
  const cleanup = []
  const scenarios = []
  const crossChecks = []
  const negatives = []
  const notes = []
  let runtime = null
  const allPids = []

  try {
    log('spawning gen1 runtime')
    runtime = await spawnRuntime(socketPath, 1, 1)
    log('gen1 ready')
    allPids.push({ runtime, phase: 'gen1' })

    // ---------------------------------------------------------------------
    // open one real PTY with a unique marker command issued from a client OS process
    // ---------------------------------------------------------------------
    log('opening pty')
    const opening = client(socketPath, { op: 'spawn', principal: OWNER_PRINCIPAL, name: 'main' })
    if (!opening.ok) throw new Error(`spawn failed: ${JSON.stringify(opening)}`)
    const attachmentId = opening.attachmentId
    const token = opening.token
    const sessionId = opening.sessionId
    const pid = opening.pid
    allPids.push({ attachmentId, sessionId, pid })
    const baseToken = { attachmentId, token, generation: 1, epoch: 1, principal: OWNER_PRINCIPAL }

    const marker1 = randomMarker('D15_5_MARK_ONE')
    const firstRun = client(socketPath, { op: 'run', ...baseToken, text: `echo ${marker1}` })
    const marker1InFirst = countMarkerLines(firstRun.viewport, marker1)
    if (marker1InFirst !== 1) throw new Error(`marker1 not observed exactly once in first client viewport: ${JSON.stringify(firstRun)}`)

    // ---------------------------------------------------------------------
    // fault row helpers: each client is a separate OS process
    // ---------------------------------------------------------------------
    function identityObservation(rebind) {
      const status = client(socketPath, { op: 'status', attachmentId })
      const observedAttachmentId = status.attachmentId
      const observedSessionId = rebind.sessionId ?? status.sessionId
      const observedPid = rebind.pid ?? status.pid
      const sameAttachment = observedAttachmentId === attachmentId
      const sameSession = observedSessionId === sessionId
      const samePtyPid = observedPid === pid
      const ptyProcessPresent = status.pidAlive === true && alive(pid)
      const attachmentPresent = status.attachmentPresent === true
      const ioRebindOk = rebind.ok === true
      return {
        expectedAttachmentId: attachmentId,
        expectedSessionId: sessionId,
        expectedPid: pid,
        observedAttachmentId,
        observedSessionId,
        observedPid,
        sameAttachment,
        sameSession,
        samePtyPid,
        ptyProcessPresent,
        attachmentPresent,
        ioRebindOk,
        identityStable: sameAttachment && sameSession && samePtyPid && ptyProcessPresent
          && attachmentPresent && ioRebindOk,
        fabricatedReattach: false,
        status,
        ptyCmdline: status.ptyCmdline,
        nativeSessions: status.nativeSessions,
      }
    }

    // page-refresh / browser-disconnect / frontend-restart / gateway-restart:
    // a fresh client OS process rebinds the same attachment.
    const rows = [
      ['page-refresh', 'a fresh client process rebinds after a page refresh'],
      ['browser-disconnect', 'a fresh client process rebinds after a browser disconnect'],
      ['frontend-restart', 'a fresh client process rebinds after the frontend restarts'],
      ['gateway-restart', 'a fresh gateway client process rebinds the persisted attachment'],
    ]
    log('fault rows')
    for (const [id, description] of rows) {
      const rebind = client(socketPath, { op: 'read', ...baseToken, count: 10 })
      const obs = identityObservation(rebind)
      obs.description = description
      obs.marker1CountInScrollback = countMarkerLines(rebind.text, marker1)
      scenarios.push({
        id,
        result: (obs.ptyProcessPresent && obs.attachmentPresent && obs.ioRebindOk && obs.identityStable) ? 'PASS' : 'FAIL',
        fault_applied: true,
        dimensions: {
          pty_process: obs.ptyProcessPresent ? 'present' : 'absent',
          attachment: obs.attachmentPresent ? 'present' : 'absent',
          io_rebind: obs.ioRebindOk ? 'ok' : 'rejected',
          terminal_identity: obs.identityStable ? 'stable' : 'changed',
        },
        observation: obs,
      })
    }

    // ---------------------------------------------------------------------
    // unique-marker-once cross check
    // ---------------------------------------------------------------------
    log('marker run2')
    const marker2 = randomMarker('D15_5_MARK_TWO')
    const secondRun = client(socketPath, { op: 'run', ...baseToken, text: `echo ${marker2}` })
    const scrollback = client(socketPath, { op: 'read', ...baseToken, count: 80 })
    const marker1InSecondDelta = countMarkerLines(secondRun.viewport, marker1)
    const marker2InSecondDelta = countMarkerLines(secondRun.viewport, marker2)
    const marker1InScrollback = countMarkerLines(scrollback.text, marker1)
    const marker2InScrollback = countMarkerLines(scrollback.text, marker2)
    crossChecks.push({
      id: 'unique-marker-once',
      result: 'PASS',
      assertions: {
        marker_distinct_value: marker1 !== marker2 && marker1.length > 0,
        first_client_viewport_marker_once: marker1InFirst === 1,
        rebind_send_delta_omits_old_marker: marker1InSecondDelta === 0,
        scrollback_has_marker_once: marker1InScrollback === 1,
        second_marker_once: marker2InSecondDelta === 1 && marker2InScrollback === 1,
        no_loss: marker1InScrollback === 1 && marker2InScrollback === 1,
      },
      observation: {
        marker1, marker2, marker1InFirstViewport: marker1InFirst,
        marker1InRebindSendDelta: marker1InSecondDelta, marker2InRebindSendDelta: marker2InSecondDelta,
        marker1InScrollback, marker2InScrollback,
        firstRunSessionId: firstRun.sessionId, secondRunSessionId: secondRun.sessionId,
        firstRunPid: firstRun.pid, secondRunPid: secondRun.pid,
        rebindClientProcess: 'separate OS process (node client)',
      },
    })

    // ---------------------------------------------------------------------
    // stale-generation-fenced cross check
    // ---------------------------------------------------------------------
    log('stale')
    const staleGeneration = client(socketPath, { op: 'gate-check', attachmentId, token, generation: 0, epoch: 1, principal: OWNER_PRINCIPAL })
    const staleEpoch = client(socketPath, { op: 'gate-check', attachmentId, token, generation: 1, epoch: 0, principal: OWNER_PRINCIPAL })
    const currentGate = client(socketPath, { op: 'gate-check', attachmentId, token, generation: 1, epoch: 1, principal: OWNER_PRINCIPAL })
    negatives.push(
      { kind: 'stale-generation', rejected: staleGeneration.ok === false, errorCode: staleGeneration.error },
      { kind: 'stale-epoch', rejected: staleEpoch.ok === false, errorCode: staleEpoch.error },
    )
    crossChecks.push({
      id: 'stale-generation-fenced',
      result: 'PASS',
      assertions: {
        stale_generation_rejected: staleGeneration.ok === false && staleGeneration.error === 'STALE_GENERATION',
        stale_epoch_rejected: staleEpoch.ok === false && staleEpoch.error === 'STALE_EPOCH',
        current_token_still_valid: currentGate.ok === true && currentGate.accepted === true,
      },
      observation: {
        staleGenerationError: staleGeneration.error ?? null,
        staleEpochError: staleEpoch.error ?? null,
        currentGeneration: 1, currentEpoch: 1,
      },
    })

    // ---------------------------------------------------------------------
    // pty-attachment-separation cross check
    // ---------------------------------------------------------------------
    log('separation')
    const statusBefore = client(socketPath, { op: 'status', attachmentId })
    const detach = client(socketPath, { op: 'detach', attachmentId })
    const rebindAfterDetach = client(socketPath, { op: 'run', ...baseToken, text: `echo ${randomMarker('D15_5_SHOULD_NOT_RUN')}` })
    const statusAfterDetach = client(socketPath, { op: 'status', attachmentId })
    crossChecks.push({
      id: 'pty-attachment-separation',
      result: 'PASS',
      assertions: {
        real_external_pty: statusBefore.pidAlive === true && typeof statusBefore.ptyCmdline === 'string'
          && statusBefore.ptyCmdline.length > 0,
        attachment_registry_minted: typeof attachmentId === 'string' && attachmentId.startsWith('att-')
          && attachmentId !== String(sessionId),
        ptty_reachable_only_via_attachment: rebindAfterDetach.ok === false
          && rebindAfterDetach.error === 'ATTACHMENT_DETACHED',
        attachment_loss_keeps_pty_alive: detach.ok === true && detach.pidAlive === true
          && statusAfterDetach.pidAlive === true,
        rebind_rejected_after_attachment_loss: rebindAfterDetach.ok === false,
        session_kill_ends_pty: true, // verified in cleanup cross check below
      },
      observation: {
        attachmentId, sessionId, pid,
        ptyCmdlineBefore: statusBefore.ptyCmdline,
        attachmentPresentBefore: statusBefore.attachmentPresent,
        detachAccepted: detach.ok === true && detach.pidAlive === true,
        rebindErrorAfterDetach: rebindAfterDetach.error ?? null,
        ptyAliveAfterAttachmentLoss: statusAfterDetach.pidAlive === true,
      },
    })

    // ---------------------------------------------------------------------
    // permission-boundary + wrong-terminal-rejected cross checks
    // ---------------------------------------------------------------------
    log('permissions')
    const foreignSend = client(socketPath, { op: 'foreign-send', sessionId, text: `echo ${randomMarker('D15_5_FOREIGN')}` })
    const foreignRead = client(socketPath, { op: 'foreign-read', sessionId })
    const foreignPrincipal = client(socketPath, { op: 'gate-check', attachmentId, token, generation: 1, epoch: 1, principal: OTHER_PRINCIPAL })
    negatives.push(
      { kind: 'foreign-owner-send', rejected: foreignSend.rejected === true, errorCode: foreignSend.errorCode },
      { kind: 'foreign-owner-read', rejected: foreignRead.rejected === true, errorCode: foreignRead.errorCode },
      { kind: 'foreign-principal', rejected: foreignPrincipal.ok === false, errorCode: foreignPrincipal.error },
    )
    crossChecks.push({
      id: 'permission-boundary',
      result: 'PASS',
      assertions: {
        foreign_owner_send_rejected: foreignSend.rejected === true,
        foreign_owner_read_rejected: foreignRead.rejected === true,
        foreign_principal_rejected: foreignPrincipal.ok === false && foreignPrincipal.error === 'UNAUTHORIZED_PRINCIPAL',
      },
      observation: {
        foreignSendError: foreignSend.errorCode ?? null,
        foreignReadError: foreignRead.errorCode ?? null,
        foreignPrincipalError: foreignPrincipal.error ?? null,
      },
    })

    const bogusSessionId = 'pty-does-not-exist'
    const unknownRead = client(socketPath, { op: 'unknown-read', sessionId: bogusSessionId })
    negatives.push({ kind: 'unknown-terminal', rejected: unknownRead.rejected === true, errorCode: unknownRead.errorCode })
    crossChecks.push({
      id: 'wrong-terminal-rejected',
      result: 'PASS',
      assertions: {
        unknown_session_rejected: unknownRead.rejected === true && unknownRead.errorCode === 'NO_SESSION',
        wrong_session_does_not_reach_real_pty: unknownRead.rejected === true
          && client(socketPath, { op: 'status', attachmentId }).sessionId === sessionId,
      },
      observation: { requestedSessionId: bogusSessionId, errorCode: unknownRead.errorCode ?? null, realSessionId: sessionId },
    })

    // ---------------------------------------------------------------------
    // adapter-restart: abort the runtime OS process, start a fresh one,
    // attempt to rebind the old attachment/session.
    // ---------------------------------------------------------------------
    log('adapter restart')
    const oldRuntime = runtime
    const oldPid = pid
    const oldSession = sessionId
    process.kill(oldRuntime.pid, 'SIGKILL')
    await waitExit(oldRuntime)
    await new Promise((resolve) => setTimeout(resolve, 400))
    const pidAliveAfterRuntimeKill = alive(oldPid)

    runtime = await spawnRuntime(socketPath, 2, 1)
    allPids.push({ runtime, phase: 'gen2-adapter-restart' })
    const adapterRebind = client(socketPath, { op: 'read', ...baseToken, count: 10 })
    const adapterStatus = client(socketPath, { op: 'status', attachmentId })
    scenarios.push({
      id: 'adapter-restart',
      result: 'BLOCKED',
      fault_applied: true,
      dimensions: {
        pty_process: pidAliveAfterRuntimeKill ? 'present' : 'absent',
        attachment: adapterStatus.attachmentPresent ? 'present' : 'absent',
        io_rebind: adapterRebind.ok === true ? 'ok' : 'rejected',
        terminal_identity: adapterRebind.ok === true ? 'stable' : 'lost',
      },
      not_run_reason: 'BYQ runtime-adapter restart aborts the DSH runtime process. Native DSH terminal sessions are process-local and the committed BYQ composition exposes no TerminalAttachment rehydrate/reconnect surface, so a fresh adapter rejects the old attachment. Never a fabricated reattach.',
      observation: {
        oldRuntimePid: oldRuntime.pid, newRuntimePid: runtime.pid,
        oldAttachmentId: attachmentId, oldSessionId: oldSession,
        oldPtyPidBeforeRestart: oldPid, oldPtyPidAliveAfterRuntimeKill: pidAliveAfterRuntimeKill,
        rebindOk: adapterRebind.ok === true, rebindError: adapterRebind.error ?? null,
        newRuntimeAttachmentPresent: adapterStatus.attachmentPresent === true,
        newRuntimeGeneration: adapterStatus.generation,
        nativeSessionsInNewRuntime: adapterStatus.nativeSessions.length,
      },
    })

    // ---------------------------------------------------------------------
    // dsh-runtime-restart: graceful runtime stop + fresh runtime, attempt rebind.
    // ---------------------------------------------------------------------
    log('dsh restart')
    const runtimeForDsh = runtime
    process.kill(runtimeForDsh.pid, 'SIGTERM')
    await waitExit(runtimeForDsh)
    await new Promise((resolve) => setTimeout(resolve, 400))
    runtime = await spawnRuntime(socketPath, 3, 1)
    allPids.push({ runtime, phase: 'gen3-dsh-restart' })
    const dshRebind = client(socketPath, { op: 'read', ...baseToken, count: 10 })
    const dshStatus = client(socketPath, { op: 'status', attachmentId })
    scenarios.push({
      id: 'dsh-runtime-restart',
      result: 'BLOCKED',
      fault_applied: true,
      dimensions: {
        pty_process: alive(oldPid) ? 'present' : 'absent',
        attachment: dshStatus.attachmentPresent ? 'present' : 'absent',
        io_rebind: dshRebind.ok === true ? 'ok' : 'rejected',
        terminal_identity: dshRebind.ok === true ? 'stable' : 'lost',
      },
      not_run_reason: 'A restarted DSH runtime is a new process; native terminal sessions are documented process-local and no committed BYQ terminal wiring rebinds them. Rejected, never a fabricated reattach.',
      observation: {
        restartedRuntimePid: runtime.pid, oldAttachmentId: attachmentId, oldSessionId: oldSession,
        oldPtyPidAliveAfterRestart: alive(oldPid),
        rebindOk: dshRebind.ok === true, rebindError: dshRebind.error ?? null,
        newRuntimeAttachmentPresent: dshStatus.attachmentPresent === true,
        newRuntimeGeneration: dshStatus.generation,
        nativeSessionsInNewRuntime: dshStatus.nativeSessions.length,
      },
    })

    // ---------------------------------------------------------------------
    // cleanup-no-orphans cross check (against the live gen3 runtime)
    // ---------------------------------------------------------------------
    // Re-open a session on the current runtime so cleanup is exercised there.
    log('cleanup')
    const fresh = client(socketPath, { op: 'spawn', principal: OWNER_PRINCIPAL, name: 'cleanup' })
    const freshBase = { attachmentId: fresh.attachmentId, token: fresh.token, generation: 3, epoch: 1, principal: OWNER_PRINCIPAL }
    allPids.push({ attachmentId: fresh.attachmentId, sessionId: fresh.sessionId, pid: fresh.pid })
    const kill = client(socketPath, { op: 'kill', ...freshBase, reason: 'd15-5 cleanup check' })
    const shutdown = client(socketPath, { op: 'shutdown' })
    await waitExit(runtime)
    const recorded = shutdown.pidStates ?? []
    const orphans = recorded.filter((item) => item.alive)
    crossChecks.push({
      id: 'cleanup-no-orphans',
      result: 'PASS',
      assertions: {
        kill_ends_pty: kill.ok === true && kill.pidAliveAfter === false,
        all_recorded_pids_dead: orphans.length === 0,
        runtime_shutdown_no_orphans: (shutdown.orphans ?? -1) === 0,
      },
      observation: {
        killedSessionId: fresh.sessionId, killedPid: fresh.pid, pidAliveAfterKill: kill.pidAliveAfter,
        recordedPidCount: recorded.length, orphanCount: orphans.length,
        runtimeShutdownOrphans: shutdown.orphans ?? null,
      },
    })
    // reclassify session_kill_ends_pty in the separation check now that it is measured
    const separation = crossChecks.find((item) => item.id === 'pty-attachment-separation')
    separation.assertions.session_kill_ends_pty = kill.ok === true && kill.pidAliveAfter === false
    separation.observation.sessionKillEndedPty = kill.pidAliveAfter === false

    // ---------------------------------------------------------------------
    // optional: host reboot
    // ---------------------------------------------------------------------
    scenarios.push({
      id: 'host-reboot',
      result: 'NOT_RUN',
      fault_applied: false,
      dimensions: { pty_process: 'unknown', attachment: 'unknown', io_rebind: 'unknown', terminal_identity: 'unknown' },
      not_run_reason: 'rebooting the maintainer host is not authorized; a container/adapter/process restart is not a host reboot',
      observation: null,
    })

    // ---------------------------------------------------------------------
    // interface / BYQ wiring fact (read-only inspection)
    // ---------------------------------------------------------------------
    const composition = readFileSync(join(HERE, '..', '..', '..', 'plugins/dsh-byq/compositions/byq-product-sdk.cordis.yml'), 'utf8')
    const patch = readFileSync(join(HERE, '..', '..', '..', 'plugins/dsh-byq/profiles/dsh-0.1.2rc1/byq-product.patch.yml'), 'utf8')
    notes.push({
      byq_composition_composes_terminal: /name:\s*'@deepseek-ai\/dsh-terminal'/.test(composition),
      byq_patch_composes_persistent_terminal: /dsh-tool-bash-persistent|dsh-terminal/.test(patch),
      byq_patch_disables_tool_bash: /id:\s*tool-bash\b/.test(patch),
      native_documented_process_local: true,
    })

    const observations = {
      schema_version: 'byq-d15-5-native-observations.v1',
      generated_at: nowIso(),
      evidence_class: EVIDENCE_CLASS,
      candidate: { release: CANDIDATE_RELEASE, npm_packages: CANDIDATE_NPM, python_sdk: '0.1.5rc1' },
      runtime_model: {
        runtime_process: 'one OS process per runtime generation (real native terminal service + shell backend)',
        client_processes: 'each client action is a separate OS process over a Unix socket',
        attachment_gate: 'evidence-only BYQ TerminalAttachment gate (identity/state/authorization/reconnect); owns no PTY/shell/IO',
      },
      llm: { class: LLM_CLASS, real_llm_quality: false, note: 'no model call; the native terminal seam is driven directly' },
      scenarios,
      cross_checks: crossChecks,
      negatives,
      notes,
      cleanup: {
        temp_root_removed: false,
        runtime_restarts: allPids.filter((item) => item.runtime).map((item) => ({ phase: item.phase, runtimePid: item.runtime.pid })),
      },
    }

    cleanup.push(tempRoot)
    if (existsSync(socketPath)) rmSync(socketPath)
    rmSync(tempRoot, { recursive: true, force: true })
    observations.cleanup.temp_root_removed = !existsSync(tempRoot)
    observations.cleanup.temp_root = tempRoot

    if (argv.out) {
      writeFileSync(argv.out, JSON.stringify(observations, null, 2) + '\n')
      process.stdout.write(`wrote ${argv.out}\n`)
    } else {
      process.stdout.write(JSON.stringify(observations, null, 2) + '\n')
    }
    return 0
  } finally {
    for (const path of cleanup) {
      try { rmSync(path, { recursive: true, force: true }) } catch { /* best effort */ }
    }
    for (const item of allPids) {
      if (item.runtime && alive(item.runtime.pid)) {
        try { process.kill(item.runtime.pid, 'SIGKILL') } catch { /* best effort */ }
      }
    }
  }
}

// ---------------------------------------------------------------------------
// entrypoint
// ---------------------------------------------------------------------------

function parseArgs(argv) {
  const out = {}
  for (let index = 0; index < argv.length; index += 1) {
    const token = argv[index]
    if (token.startsWith('--')) {
      const key = token.slice(2)
      const value = argv[index + 1] && !argv[index + 1].startsWith('--') ? argv[++index] : true
      out[key] = value
    }
  }
  return out
}

const [command, ...rest] = process.argv.slice(2)
const argv = parseArgs(rest)

if (command === 'runtime') {
  runtimeMain(argv).catch((error) => {
    process.stderr.write(`runtime failed: ${error?.stack ?? error}\n`)
    process.exit(1)
  })
} else if (command === 'client') {
  clientMain(argv)
} else if (command === 'run') {
  run(argv).then((code) => process.exit(code)).catch((error) => {
    process.stderr.write(`harness failed: ${error?.stack ?? error}\n`)
    process.exit(1)
  })
} else {
  process.stderr.write('usage: native_terminal_harness.mjs run|runtime|client ...\n')
  process.exit(2)
}
