#!/usr/bin/env node
/**
 * 0.9 strict-order step-5 B3 `terminal-adapter-restart` real native probe.
 *
 * Owner node: `d15-5-candidate-attachment-layer` (pre-gate; never post-GO R4).
 *
 * This probe implements and exercises the MINIMAL BYQ `TerminalAttachment`
 * lifecycle required by ADR-0083 on top of the REAL native DSH 0.1.5-rc.1
 * persistent terminal:
 *
 *   * DSH owns the PTY/shell/process/IO (`@deepseek-ai/dsh-terminal` owner-scoped
 *     registry + `@deepseek-ai/dsh-terminal-bash` `shell` backend), driven in a
 *     dedicated native runtime OS process.
 *   * BYQ owns ONLY a bounded, durable attachment record: a BYQ-minted
 *     attachment id (never a DSH session id or pid), the owner principal,
 *     authorization, runtime generation, executor epoch, state and an audit
 *     linkage. It is persisted to a BYQ-owned store and reloaded by a fresh
 *     adapter OS process.
 *
 * It is evidence-only, candidate-specific and reversible. It builds NO PTY
 * runtime, copies NO DSH terminal, builds NO second generic harness and never
 * persists or fabricates the native PTY. It calls no model (`not-applicable`).
 *
 * Two real scenarios:
 *   adapter-restart-native-survives  adapter restart with the native state still
 *                                     reachable -> rebind the SAME attachment.
 *   adapter-restart-native-lost      adapter restart that also takes the native
 *                                     runtime -> honest lost/interrupted.
 *
 * Modes:
 *   run [--out <path>]                       orchestrate both worlds
 *   runtime  --socket <p> --generation N --epoch N
 *   adapter  --socket <p> --runtime-socket <p> --store <dir> --generation N
 *            --epoch N --adapter-generation N --principal <p>
 *   client   --socket <p> --request '<json>'
 */

import { mkdtempSync, readFileSync, writeFileSync, renameSync, rmSync, existsSync, mkdirSync } from 'node:fs'
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

export const EVIDENCE_CLASS = 'native-runtime-isolated-b3'
export const LLM_CLASS = 'not-applicable'
export const CANDIDATE_RELEASE = 'dsh-0.1.5rc1'
export const CANDIDATE_NPM = '0.1.5-rc.1'
export const STORE_FILE = 'terminal-attachments.v1.json'

const HERE = dirname(fileURLToPath(import.meta.url))
const NODE = process.execPath

const OWNER_ID = 'd15-5-owner'
const OTHER_OWNER_ID = 'd15-5-other-owner'
const OWNER_PRINCIPAL = 'principal-owner'
const OTHER_PRINCIPAL = 'principal-other'

// ---------------------------------------------------------------------------
// helpers
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

function countMarkerLines(text, marker) {
  if (typeof text !== 'string' || !marker) return 0
  return text.split('\n').filter((line) => line.trim() === marker).length
}

function randomMarker(prefix) {
  return `${prefix}_${randomBytes(8).toString('hex')}`
}

function reject(code, detail) {
  return { ok: false, error: code, detail: detail ?? null }
}

/** One-shot request against a running socket server. */
function callSocket(socketPath, request, { timeout = 60000 } = {}) {
  return new Promise((resolve, rejectPromise) => {
    const socket = connect(socketPath)
    let buffer = ''
    const timer = setTimeout(() => {
      socket.destroy()
      rejectPromise(new Error('socket request timed out'))
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
          rejectPromise(new Error(`bad server response: ${line}`))
        }
      }
    })
    socket.on('error', (error) => {
      clearTimeout(timer)
      rejectPromise(error)
    })
  })
}

function serve(socketPath, handle, onShutdown) {
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
        .catch((error) => socket.end(JSON.stringify(reject('SERVER_ERROR', String(error?.stack ?? error))) + '\n'))
    })
  })
  rmSync(socketPath, { force: true })
  return new Promise((resolve, rejectPromise) => {
    server.once('error', rejectPromise)
    server.listen(socketPath, () => resolve(server))
  }).then(async (created) => {
    if (onShutdown) {
      const stop = async () => {
        try { await onShutdown() } catch { /* best effort */ }
        created.close()
        process.exit(0)
      }
      process.on('SIGTERM', stop)
      process.on('SIGINT', stop)
    }
    return created
  })
}

// ---------------------------------------------------------------------------
// native runtime OS process: DSH owns the PTY/shell/IO
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

async function runtimeMain(argv) {
  const socketPath = argv.socket
  const generation = Number(argv.generation)
  const epoch = Number(argv.epoch)
  const { ctx, owner, other } = await bootRuntime()
  const sessions = new Map()
  let shuttingDown = false

  async function handle(request) {
    switch (request.op) {
      case 'spawn': {
        const name = typeof request.name === 'string' && request.name.length > 0 ? request.name : 'main'
        const spawned = await ctx.terminals.spawn(owner, { type: 'shell', name })
        const record = { sessionId: String(spawned.sessionId), pid: spawned.pid ?? null, name }
        sessions.set(record.sessionId, record)
        return { ok: true, sessionId: record.sessionId, pid: record.pid, generation, epoch, motd: spawned.motd }
      }
      case 'run': {
        const record = sessions.get(request.sessionId)
        if (record === undefined) return reject('NO_SESSION')
        try {
          const operation = ctx.terminals.startSend(owner, record.sessionId, { text: request.text, submit: true })
          const result = await operation.done
          return { ok: true, sessionId: record.sessionId, pid: record.pid, viewport: result.viewport, waitReason: result.waitReason }
        } catch (error) {
          return reject('SEND_REJECTED', { code: error.code ?? error.name, message: String(error.message) })
        }
      }
      case 'read': {
        const record = sessions.get(request.sessionId)
        if (record === undefined) return reject('NO_SESSION')
        const result = ctx.terminals.read(owner, record.sessionId, { count: request.count ?? 50 })
        return { ok: true, sessionId: record.sessionId, pid: record.pid, ...result }
      }
      case 'status': {
        return {
          ok: true,
          role: 'runtime',
          generation,
          epoch,
          runtimePid: process.pid,
          sessions: ctx.terminals.list(owner).map((item) => ({
            sessionId: String(item.sessionId), pid: item.pid ?? null, status: item.status?.kind ?? null,
          })),
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
      case 'kill': {
        const record = sessions.get(request.sessionId)
        if (record === undefined) return reject('NO_SESSION')
        const pidBefore = record.pid
        const killed = await ctx.terminals.kill(owner, record.sessionId, request.reason ?? 'b3 cleanup')
        sessions.delete(record.sessionId)
        await new Promise((resolve) => setTimeout(resolve, 250))
        return { ok: true, killed, sessionId: record.sessionId, pidBefore, pidAliveAfter: alive(pidBefore) }
      }
      case 'shutdown': {
        if (shuttingDown) return { ok: true, already: true, orphans: 0, pidStates: [] }
        shuttingDown = true
        const recorded = [...sessions.values()].map((item) => ({ sessionId: item.sessionId, pid: item.pid }))
        for (const record of sessions.values()) {
          try { await ctx.terminals.kill(owner, record.sessionId, 'b3 shutdown') } catch { /* pids verified below */ }
        }
        sessions.clear()
        await new Promise((resolve) => setTimeout(resolve, 300))
        const pidStates = recorded.map((item) => ({ ...item, alive: alive(item.pid) }))
        return { ok: true, pidStates, orphans: pidStates.filter((item) => item.alive).length }
      }
      default:
        return reject('UNKNOWN_OP', { op: request.op })
    }
  }

  await serve(socketPath, handle, async () => { try { await handle({ op: 'shutdown' }) } catch { /* best effort */ } })
  process.stdout.write(JSON.stringify({ ready: true, role: 'runtime', runtimePid: process.pid, generation, epoch }) + '\n')
}

// ---------------------------------------------------------------------------
// BYQ adapter OS process: owns ONLY the durable TerminalAttachment lifecycle
// ---------------------------------------------------------------------------

function loadStore(storeDir) {
  const path = join(storeDir, STORE_FILE)
  if (!existsSync(path)) return { path, records: {} }
  try {
    const parsed = JSON.parse(readFileSync(path, 'utf8'))
    if (parsed && typeof parsed === 'object' && parsed.records && typeof parsed.records === 'object') {
      return { path, records: parsed.records }
    }
  } catch { /* fall through to empty */ }
  return { path, records: {} }
}

function saveStore(store) {
  mkdirSync(dirname(store.path), { recursive: true })
  const tmp = `${store.path}.${process.pid}.tmp`
  writeFileSync(tmp, JSON.stringify({ schema_version: 'byq-terminal-attachment-store.v1', records: store.records }, null, 2) + '\n')
  renameSync(tmp, store.path)
}

function audit(record, event, detail) {
  if (!Array.isArray(record.audit)) record.audit = []
  record.audit.push({ at: nowIso(), event, adapterGeneration: record.adapterGeneration, detail: detail ?? null })
}

async function adapterMain(argv) {
  const socketPath = argv.socket
  const runtimeSocket = argv['runtime-socket']
  const storeDir = argv.store
  const generation = Number(argv.generation)
  const epoch = Number(argv.epoch)
  const ownerPrincipal = argv.principal ?? OWNER_PRINCIPAL
  const store = loadStore(storeDir)

  async function runtimeCall(op) {
    try {
      return await callSocket(runtimeSocket, op, { timeout: 30000 })
    } catch (error) {
      return { ok: false, error: 'RUNTIME_UNAVAILABLE', detail: String(error.message) }
    }
  }

  function gate(record, request) {
    if (record === undefined) return reject('UNKNOWN_ATTACHMENT')
    if (request.principal !== record.ownerPrincipal) return reject('UNAUTHORIZED_PRINCIPAL')
    if (typeof request.token !== 'string' || request.token !== record.token) return reject('UNAUTHORIZED_ATTACHMENT')
    if (request.generation !== undefined && request.generation !== record.generation) return reject('STALE_GENERATION')
    if (request.epoch !== undefined && request.epoch !== record.executorEpoch) return reject('STALE_EPOCH')
    return null
  }

  async function handle(request) {
    switch (request.op) {
      case 'create': {
        if (request.principal !== ownerPrincipal) return reject('UNAUTHORIZED_PRINCIPAL')
        const spawned = await runtimeCall({ op: 'spawn', name: request.name })
        if (spawned.ok !== true) return reject('NATIVE_SPAWN_FAILED', spawned)
        const attachmentId = `byq-att-${randomBytes(9).toString('hex')}`
        const record = {
          attachmentId,
          token: randomBytes(18).toString('hex'),
          ownerPrincipal,
          ownerAgentId: OWNER_ID,
          generation,
          executorEpoch: epoch,
          status: 'attached',
          nativeSessionId: spawned.sessionId,
          nativePid: spawned.pid,
          nativeRuntimeGeneration: spawned.generation ?? generation,
          adapterGeneration: Number(argv['adapter-generation']) || 1,
          createdAt: nowIso(),
          audit: [],
        }
        audit(record, 'create', { nativeSessionId: record.nativeSessionId })
        store.records[attachmentId] = record
        saveStore(store)
        return {
          ok: true, attachmentId, token: record.token, sessionId: record.nativeSessionId,
          pid: record.nativePid, generation: record.generation, epoch: record.executorEpoch,
          nativeRuntimeGeneration: record.nativeRuntimeGeneration, byqMinted: true,
          attachmentIdIsNotNativeId: attachmentId !== record.nativeSessionId && attachmentId !== `pid-${record.nativePid}`,
          adapterGeneration: record.adapterGeneration, storePath: store.path,
        }
      }
      case 'reattach':
      case 'attach': {
        const record = store.records[request.attachmentId]
        const failure = gate(record, request)
        if (failure) return failure
        const native = await runtimeCall({ op: 'status' })
        const session = native.ok === true
          ? (native.sessions ?? []).find((item) => item.sessionId === record.nativeSessionId)
          : undefined
        const nativeReachable = native.ok === true
          && native.generation === record.nativeRuntimeGeneration
          && session !== undefined
          && alive(record.nativePid)
        if (!nativeReachable) {
          record.status = 'lost'
          record.adapterGeneration = Number(argv['adapter-generation']) || record.adapterGeneration
          record.nativeSessionPresent = false
          audit(record, 'lost', { reason: 'NATIVE_SESSION_UNAVAILABLE', runtimeGeneration: native.generation ?? null })
          store.records[record.attachmentId] = record
          saveStore(store)
          return {
            ok: false, status: record.status, attachmentId: record.attachmentId,
            reattachAttempted: true, rebindError: 'NATIVE_SESSION_UNAVAILABLE',
            nativeSessionPresent: false, nativeSessionId: record.nativeSessionId,
            nativePid: record.nativePid, oldPidAlive: alive(record.nativePid),
            runtimeGeneration: native.generation ?? null, adapterGeneration: record.adapterGeneration,
            nativeSessionCount: native.ok === true ? (native.sessions ?? []).length : null,
          }
        }
        record.status = 'reattached'
        record.adapterGeneration = Number(argv['adapter-generation']) || record.adapterGeneration
        record.nativeSessionPresent = true
        audit(record, 'reattach', { nativeSessionId: record.nativeSessionId })
        store.records[record.attachmentId] = record
        saveStore(store)
        return {
          ok: true, status: record.status, attachmentId: record.attachmentId, token: record.token,
          sessionId: record.nativeSessionId, pid: record.nativePid, generation: record.generation,
          epoch: record.executorEpoch, identityStable: true, adapterGeneration: record.adapterGeneration,
          nativeSessionCount: (native.sessions ?? []).length, runtimeGeneration: native.generation,
        }
      }
      case 'run':
      case 'signal': {
        const record = store.records[request.attachmentId]
        const failure = gate(record, request)
        if (failure) return failure
        if (record.status !== 'attached' && record.status !== 'reattached') return reject('ATTACHMENT_NOT_LIVE', { status: record.status })
        const result = await runtimeCall({ op: 'run', sessionId: record.nativeSessionId, text: request.text })
        if (result.ok === true) audit(record, 'signal', { marker: typeof request.text === 'string' ? request.text.slice(0, 64) : null })
        store.records[request.attachmentId] = record
        saveStore(store)
        return { ...result, attachmentId: record.attachmentId, status: record.status }
      }
      case 'read': {
        const record = store.records[request.attachmentId]
        const failure = gate(record, request)
        if (failure) return failure
        const result = await runtimeCall({ op: 'read', sessionId: record.nativeSessionId, count: request.count })
        return { ...result, attachmentId: record.attachmentId, status: record.status }
      }
      case 'status': {
        const record = request.attachmentId ? store.records[request.attachmentId] : null
        const native = await runtimeCall({ op: 'status' })
        return {
          ok: true, role: 'adapter', adapterPid: process.pid,
          adapterGeneration: Number(argv['adapter-generation']) || null,
          storePath: store.path,
          attachmentPresent: record !== undefined,
          attachmentId: record?.attachmentId ?? null,
          attachmentStatus: record?.status ?? null,
          sessionId: record?.nativeSessionId ?? null,
          pid: record?.nativePid ?? null,
          pidAlive: record?.nativePid ? alive(record.nativePid) : false,
          ptyCmdline: record?.nativePid ? procCmdline(record.nativePid) : null,
          nativeRuntimeGeneration: record?.nativeRuntimeGeneration ?? null,
          runtime: native,
          nativeSessions: native.ok === true ? native.sessions : [],
        }
      }
      case 'history': {
        const record = store.records[request.attachmentId]
        if (record === undefined) return reject('UNKNOWN_ATTACHMENT')
        return { ok: true, attachmentId: record.attachmentId, status: record.status, audit: record.audit ?? [] }
      }
      case 'foreign-principal': {
        return gate(store.records[request.attachmentId], request) ?? { ok: true, accepted: true }
      }
      case 'foreign-send':
        return runtimeCall({ op: 'foreign-send', sessionId: request.sessionId, text: request.text })
      case 'foreign-read':
        return runtimeCall({ op: 'foreign-read', sessionId: request.sessionId })
      case 'unknown-read':
        return runtimeCall({ op: 'unknown-read', sessionId: request.sessionId })
      case 'unknown-attachment': {
        const failure = gate(store.records[request.attachmentId], request)
        return failure ?? { ok: true, accepted: true }
      }
      case 'close': {
        const record = store.records[request.attachmentId]
        if (record === undefined) return reject('UNKNOWN_ATTACHMENT')
        if (request.token !== record.token) return reject('UNAUTHORIZED_ATTACHMENT')
        if (record.status === 'detached') {
          return { ok: true, alreadyClosed: true, attachmentId: record.attachmentId, status: record.status, killed: false }
        }
        let killed = false
        let pidAliveAfter = record.nativePid ? alive(record.nativePid) : false
        if (alive(record.nativePid)) {
          const result = await runtimeCall({ op: 'kill', sessionId: record.nativeSessionId, reason: 'b3 close' })
          killed = result.ok === true
          pidAliveAfter = result.ok === true ? result.pidAliveAfter === true : alive(record.nativePid)
        }
        record.status = 'detached'
        audit(record, 'close', { killed })
        store.records[record.attachmentId] = record
        saveStore(store)
        return { ok: true, alreadyClosed: false, killed, pidAliveAfter, attachmentId: record.attachmentId, status: record.status }
      }
      case 'shutdown': {
        return { ok: true, adapterPid: process.pid }
      }
      default:
        return reject('UNKNOWN_OP', { op: request.op })
    }
  }

  await serve(socketPath, handle)
  process.stdout.write(JSON.stringify({
    ready: true, role: 'adapter', adapterPid: process.pid,
    adapterGeneration: Number(argv['adapter-generation']) || null, storePath: store.path,
  }) + '\n')
}

// ---------------------------------------------------------------------------
// one-shot client process
// ---------------------------------------------------------------------------

async function clientMain(argv) {
  const request = JSON.parse(argv.request)
  try {
    const response = await callSocket(argv.socket, request)
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

function waitExit(child) {
  if (child.exitCode !== null || child.signalCode !== null) return Promise.resolve()
  return new Promise((resolve) => child.once('exit', resolve))
}

function spawnRole(mode, args) {
  const child = spawn(NODE, [fileURLToPath(import.meta.url), mode, ...args], { stdio: ['ignore', 'pipe', 'pipe'] })
  let stdout = ''
  let stderr = ''
  child.stderr.on('data', (chunk) => { stderr += chunk.toString('utf8') })
  return new Promise((resolve, rejectPromise) => {
    const timer = setTimeout(() => rejectPromise(new Error(`${mode} did not become ready: ${stderr}`)), 90000)
    child.stdout.on('data', (chunk) => {
      stdout += chunk.toString('utf8')
      const index = stdout.indexOf('\n')
      if (index >= 0 && !child.b3Ready) {
        child.b3Ready = JSON.parse(stdout.slice(0, index))
        clearTimeout(timer)
        resolve(child)
      }
    })
    child.on('exit', (code) => {
      if (!child.b3Ready) {
        clearTimeout(timer)
        rejectPromise(new Error(`${mode} exited ${code}: ${stderr}`))
      }
    })
  })
}

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
  process.stderr.write(`[b3] ${message}\n`)
}

async function readStore(storeDir) {
  const path = join(storeDir, STORE_FILE)
  if (!existsSync(path)) return { present: false, records: {} }
  try {
    const parsed = JSON.parse(readFileSync(path, 'utf8'))
    return { present: true, records: parsed.records ?? {} }
  } catch {
    return { present: false, records: {} }
  }
}

async function worldSurvives() {
  const root = mkdtempSync(join(tmpdir(), 'b3-adapter-survives-'))
  const storeDir = join(root, 'byq-attachments')
  const runtimeSock = join(root, 'runtime.sock')
  const adapterSock = join(root, 'adapter.sock')
  const observation = { temp_root: root }
  let runtime = null
  let adapterA = null
  let adapterB = null
  try {
    runtime = await spawnRole('runtime', ['--socket', runtimeSock, '--generation', '1', '--epoch', '1'])
    adapterA = await spawnRole('adapter', ['--socket', adapterSock, '--runtime-socket', runtimeSock,
      '--store', storeDir, '--generation', '1', '--epoch', '1', '--adapter-generation', '1', '--principal', OWNER_PRINCIPAL])

    const create = client(adapterSock, { op: 'create', principal: OWNER_PRINCIPAL, name: 'main' })
    const attachmentId = create.attachmentId
    const token = create.token
    const sessionId = create.sessionId
    const pid = create.pid
    const storeAfterCreate = await readStore(storeDir)

    const statusA = client(adapterSock, { op: 'status', attachmentId })
    const marker1 = randomMarker('B3_MARK_ONE')
    const firstRun = client(adapterSock, { op: 'signal', attachmentId, token, generation: 1, epoch: 1, principal: OWNER_PRINCIPAL, text: `echo ${marker1}` })
    const marker1InFirst = countMarkerLines(firstRun.viewport, marker1)

    const foreignPrincipal = client(adapterSock, { op: 'foreign-principal', attachmentId, token, generation: 1, epoch: 1, principal: OTHER_PRINCIPAL })
    const staleGeneration = client(adapterSock, { op: 'foreign-principal', attachmentId, token, generation: 0, epoch: 1, principal: OWNER_PRINCIPAL })
    const staleEpoch = client(adapterSock, { op: 'foreign-principal', attachmentId, token, generation: 1, epoch: 0, principal: OWNER_PRINCIPAL })
    const unknownAttachment = client(adapterSock, { op: 'unknown-attachment', attachmentId: 'byq-att-does-not-exist', token, generation: 1, epoch: 1, principal: OWNER_PRINCIPAL })
    const foreignSend = client(adapterSock, { op: 'foreign-send', sessionId, text: `echo ${randomMarker('B3_FOREIGN')}` })
    const foreignRead = client(adapterSock, { op: 'foreign-read', sessionId })
    const bogusSession = 'pty-does-not-exist'
    const unknownRead = client(adapterSock, { op: 'unknown-read', sessionId: bogusSession })

    const idempotent1 = client(adapterSock, { op: 'reattach', attachmentId, token, generation: 1, epoch: 1, principal: OWNER_PRINCIPAL })
    const idempotent2 = client(adapterSock, { op: 'reattach', attachmentId, token, generation: 1, epoch: 1, principal: OWNER_PRINCIPAL })
    const nativeSessionCountAfterIdempotent = client(adapterSock, { op: 'status', attachmentId }).nativeSessions.length

    // Fault: abort the BYQ adapter OS process; the native runtime survives.
    process.kill(adapterA.pid, 'SIGKILL')
    await waitExit(adapterA)
    await new Promise((resolve) => setTimeout(resolve, 300))

    adapterB = await spawnRole('adapter', ['--socket', adapterSock, '--runtime-socket', runtimeSock,
      '--store', storeDir, '--generation', '1', '--epoch', '1', '--adapter-generation', '2', '--principal', OWNER_PRINCIPAL])
    const storeAfterRestart = await readStore(storeDir)

    const reattach = client(adapterSock, { op: 'reattach', attachmentId, token, generation: 1, epoch: 1, principal: OWNER_PRINCIPAL })
    const statusB = client(adapterSock, { op: 'status', attachmentId })
    const sameAttachment = statusB.attachmentId === attachmentId
    const sameSession = statusB.sessionId === sessionId
    const samePtyPid = statusB.pid === pid
    const ptyProcessPresent = statusB.pidAlive === true && alive(pid)
    const attachmentPresent = statusB.attachmentPresent === true
    const ioRebindOk = reattach.ok === true && reattach.status === 'reattached'
    const identityStable = sameAttachment && sameSession && samePtyPid && ptyProcessPresent && attachmentPresent && ioRebindOk
    const fabricatedReattach = reattach.ok === true && !(sameAttachment && sameSession && samePtyPid)
    const marker2 = randomMarker('B3_MARK_TWO')
    const secondRun = client(adapterSock, { op: 'signal', attachmentId, token, generation: 1, epoch: 1, principal: OWNER_PRINCIPAL, text: `echo ${marker2}` })
    const scrollback = client(adapterSock, { op: 'read', attachmentId, token, generation: 1, epoch: 1, principal: OWNER_PRINCIPAL, count: 80 })
    const history = client(adapterSock, { op: 'history', attachmentId })

    const close1 = client(adapterSock, { op: 'close', attachmentId, token })
    const close2 = client(adapterSock, { op: 'close', attachmentId, token })
    const shutdown = client(runtimeSock, { op: 'shutdown' })
    await waitExit(runtime)
    client(adapterSock, { op: 'shutdown' })

    const marker1InRebindDelta = countMarkerLines(secondRun.viewport, marker1)
    const marker2InRebindDelta = countMarkerLines(secondRun.viewport, marker2)
    const marker1InScrollback = countMarkerLines(scrollback.text, marker1)
    const marker2InScrollback = countMarkerLines(scrollback.text, marker2)
    const records = Object.values(storeAfterRestart.records)
    const record = records[0] ?? {}
    const auditEvents = [...new Set((history.audit ?? []).map((item) => item.event))]

    Object.assign(observation, {
      attachmentId, nativeSessionId: sessionId, nativePid: pid,
      expectedAttachmentId: attachmentId, expectedSessionId: sessionId, expectedPid: pid,
      ptyCmdlineBefore: statusA.ptyCmdline,
      ptyProcessPresentAtRebind: ptyProcessPresent,
      byqMintedAttachmentId: create.byqMinted === true,
      attachmentIdIsNotNativeId: create.attachmentIdIsNotNativeId === true,
      createGeneration: create.generation, createEpoch: create.epoch,
      adapterAPid: adapterA.pid, adapterAGeneration: statusA.adapterGeneration,
      runtimeAPid: runtime.pid,
      marker1, marker1InFirstViewport: marker1InFirst,
      foreignPrincipalError: foreignPrincipal.error ?? null,
      staleGenerationError: staleGeneration.error ?? null,
      staleEpochError: staleEpoch.error ?? null,
      unknownAttachmentError: unknownAttachment.error ?? null,
      foreignSendError: foreignSend.errorCode ?? null,
      foreignReadError: foreignRead.errorCode ?? null,
      unknownReadError: unknownRead.errorCode ?? null,
      unknownReadRealSessionId: sessionId,
      requestedUnknownSessionId: bogusSession,
      idempotentReattachSameIdentity: idempotent1.ok === true && idempotent2.ok === true
        && idempotent1.attachmentId === idempotent2.attachmentId
        && idempotent1.sessionId === idempotent2.sessionId
        && idempotent1.pid === idempotent2.pid,
      nativeSessionCountAfterIdempotent,
      adapterBPid: adapterB.pid, adapterBGeneration: statusB.adapterGeneration,
      freshAdapterOsProcess: adapterA.pid !== adapterB.pid,
      reattachOk: reattach.ok === true, reattachStatus: reattach.status ?? null,
      observedAttachmentId: statusB.attachmentId, observedSessionId: statusB.sessionId, observedPid: statusB.pid,
      sameAttachment, sameSession, samePtyPid, ptyProcessPresent, attachmentPresent, ioRebindOk, identityStable,
      fabricatedReattach,
      marker2, marker1InRebindSendDelta: marker1InRebindDelta, marker2InRebindSendDelta: marker2InRebindDelta,
      marker1InScrollback, marker2InScrollback,
      durableStoreFilePresent: storeAfterCreate.present && storeAfterRestart.present,
      durableRecordsLoadedSameId: records.length === 1 && record.attachmentId === attachmentId,
      recordHasOwnerGenerationEpochState: record.ownerPrincipal === OWNER_PRINCIPAL
        && Number.isInteger(record.generation) && Number.isInteger(record.executorEpoch)
        && typeof record.status === 'string',
      auditLinkagePresent: auditEvents.includes('create') && auditEvents.includes('reattach'),
      auditEvents,
      closeIdempotent: close1.ok === true && close2.ok === true && close2.alreadyClosed === true
        && close1.status === 'detached' && close2.status === 'detached',
      closeEndsPty: close1.killed === true && close1.pidAliveAfter === false,
      orphans: shutdown.orphans ?? null,
      runtimeShutdownOrphans: shutdown.orphans ?? null,
      temp_root_removed: false,
    })
    return observation
  } finally {
    for (const child of [adapterA, adapterB]) {
      if (child && alive(child.pid)) { try { process.kill(child.pid, 'SIGKILL') } catch { /* best effort */ } }
    }
    if (runtime && alive(runtime.pid)) { try { process.kill(runtime.pid, 'SIGKILL') } catch { /* best effort */ } }
    try { rmSync(root, { recursive: true, force: true }) } catch { /* best effort */ }
    observation.temp_root_removed = !existsSync(root)
  }
}

async function worldLost() {
  const root = mkdtempSync(join(tmpdir(), 'b3-adapter-lost-'))
  const storeDir = join(root, 'byq-attachments')
  const runtimeSock1 = join(root, 'runtime-1.sock')
  const runtimeSock2 = join(root, 'runtime-2.sock')
  const adapterSock = join(root, 'adapter.sock')
  const observation = { temp_root: root }
  let runtime1 = null
  let runtime2 = null
  let adapterC = null
  let adapterD = null
  try {
    runtime1 = await spawnRole('runtime', ['--socket', runtimeSock1, '--generation', '1', '--epoch', '1'])
    adapterC = await spawnRole('adapter', ['--socket', adapterSock, '--runtime-socket', runtimeSock1,
      '--store', storeDir, '--generation', '1', '--epoch', '1', '--adapter-generation', '1', '--principal', OWNER_PRINCIPAL])

    const create = client(adapterSock, { op: 'create', principal: OWNER_PRINCIPAL, name: 'main' })
    const attachmentId = create.attachmentId
    const token = create.token
    const sessionId = create.sessionId
    const pid = create.pid
    const storeAfterCreate = await readStore(storeDir)
    const marker1 = randomMarker('B3_LOST_MARK_ONE')
    client(adapterSock, { op: 'signal', attachmentId, token, generation: 1, epoch: 1, principal: OWNER_PRINCIPAL, text: `echo ${marker1}` })

    // Committed topology: the adapter restart takes the native runtime with it.
    process.kill(adapterC.pid, 'SIGKILL')
    process.kill(runtime1.pid, 'SIGKILL')
    await waitExit(adapterC)
    await waitExit(runtime1)
    await new Promise((resolve) => setTimeout(resolve, 500))
    const oldPidAliveAfterLoss = alive(pid)

    runtime2 = await spawnRole('runtime', ['--socket', runtimeSock2, '--generation', '2', '--epoch', '1'])
    adapterD = await spawnRole('adapter', ['--socket', adapterSock, '--runtime-socket', runtimeSock2,
      '--store', storeDir, '--generation', '1', '--epoch', '1', '--adapter-generation', '2', '--principal', OWNER_PRINCIPAL])
    const storeAfterRestart = await readStore(storeDir)

    const foreignPrincipal = client(adapterSock, { op: 'foreign-principal', attachmentId, token, generation: 1, epoch: 1, principal: OTHER_PRINCIPAL })
    const staleGeneration = client(adapterSock, { op: 'foreign-principal', attachmentId, token, generation: 0, epoch: 1, principal: OWNER_PRINCIPAL })
    const staleEpoch = client(adapterSock, { op: 'foreign-principal', attachmentId, token, generation: 1, epoch: 0, principal: OWNER_PRINCIPAL })
    const reattach = client(adapterSock, { op: 'reattach', attachmentId, token, generation: 1, epoch: 1, principal: OWNER_PRINCIPAL })
    const statusAfter = client(adapterSock, { op: 'status', attachmentId })
    const records = Object.values(storeAfterRestart.records)
    const record = records[0] ?? {}

    const close1 = client(adapterSock, { op: 'close', attachmentId, token })
    const close2 = client(adapterSock, { op: 'close', attachmentId, token })
    const shutdown = client(runtimeSock2, { op: 'shutdown' })
    await waitExit(runtime2)
    client(adapterSock, { op: 'shutdown' })

    const status = reattach.status ?? statusAfter.attachmentStatus
    const fakeReattachRejected = reattach.ok === false
      && reattach.status !== 'reattached'
      && reattach.sessionId === undefined
      && reattach.pid === undefined
      && reattach.identityStable !== true

    Object.assign(observation, {
      attachmentId, nativeSessionId: sessionId, nativePid: pid,
      ptyCmdlineBefore: create.pid ? procCmdline(pid) : null,
      byqMintedAttachmentId: create.byqMinted === true,
      attachmentIdIsNotNativeId: create.attachmentIdIsNotNativeId === true,
      marker1,
      adapterCPid: adapterC.pid, adapterCGeneration: 1, runtimeAPid: runtime1.pid,
      oldPidAliveAfterLoss,
      adapterDPid: adapterD.pid, adapterDGeneration: statusAfter.adapterGeneration,
      runtimeBPid: runtime2.pid, runtimeBGeneration: statusAfter.runtime?.generation ?? null,
      freshAdapterOsProcess: adapterC.pid !== adapterD.pid,
      durableStoreFilePresent: storeAfterCreate.present && storeAfterRestart.present,
      durableRecordsLoadedSameId: records.length === 1 && record.attachmentId === attachmentId,
      reattachAttempted: reattach.reattachAttempted === true,
      reattachOk: reattach.ok === true, reattachStatus: status,
      rebindError: reattach.rebindError ?? null,
      nativeSessionPresent: reattach.nativeSessionPresent === true,
      oldPidAliveReported: reattach.oldPidAlive === true,
      runtimeGenerationReported: reattach.runtimeGeneration ?? null,
      nativeSessionsInNewRuntime: statusAfter.nativeSessions.length,
      fakeReattachRejected,
      foreignPrincipalError: foreignPrincipal.error ?? null,
      staleGenerationError: staleGeneration.error ?? null,
      staleEpochError: staleEpoch.error ?? null,
      closeIdempotent: close1.ok === true && close2.ok === true && close2.alreadyClosed === true,
      orphans: shutdown.orphans ?? null,
      runtimeShutdownOrphans: shutdown.orphans ?? null,
      temp_root_removed: false,
    })
    return observation
  } finally {
    for (const child of [adapterC, adapterD]) {
      if (child && alive(child.pid)) { try { process.kill(child.pid, 'SIGKILL') } catch { /* best effort */ } }
    }
    for (const child of [runtime1, runtime2]) {
      if (child && alive(child.pid)) { try { process.kill(child.pid, 'SIGKILL') } catch { /* best effort */ } }
    }
    try { rmSync(root, { recursive: true, force: true }) } catch { /* best effort */ }
    observation.temp_root_removed = !existsSync(root)
  }
}

async function run(argv) {
  const survives = await worldSurvives()
  const lost = await worldLost()

  const survivesPass = survives.byqMintedAttachmentId && survives.attachmentIdIsNotNativeId
    && survives.freshAdapterOsProcess && survives.durableStoreFilePresent && survives.durableRecordsLoadedSameId
    && survives.sameAttachment && survives.sameSession && survives.samePtyPid
    && survives.ptyProcessPresent && survives.attachmentPresent && survives.ioRebindOk
    && survives.identityStable && survives.fabricatedReattach === false
    && survives.marker1InFirstViewport === 1
    && survives.marker1InRebindSendDelta === 0 && survives.marker2InRebindSendDelta === 1
    && survives.marker1InScrollback === 1 && survives.marker2InScrollback === 1
    && survives.foreignPrincipalError === 'UNAUTHORIZED_PRINCIPAL'
    && survives.staleGenerationError === 'STALE_GENERATION' && survives.staleEpochError === 'STALE_EPOCH'
    && survives.unknownAttachmentError === 'UNKNOWN_ATTACHMENT'
    && survives.foreignSendError === 'FOREIGN_SESSION' && survives.foreignReadError === 'FOREIGN_SESSION'
    && survives.unknownReadError === 'NO_SESSION'
    && survives.idempotentReattachSameIdentity && survives.nativeSessionCountAfterIdempotent === 1
    && survives.closeIdempotent && survives.closeEndsPty && survives.runtimeShutdownOrphans === 0

  const lostPass = lost.byqMintedAttachmentId && lost.attachmentIdIsNotNativeId
    && lost.freshAdapterOsProcess && lost.durableStoreFilePresent && lost.durableRecordsLoadedSameId
    && lost.reattachAttempted && lost.reattachOk === false
    && (lost.reattachStatus === 'lost' || lost.reattachStatus === 'interrupted')
    && lost.rebindError === 'NATIVE_SESSION_UNAVAILABLE'
    && lost.oldPidAliveAfterLoss === false && lost.nativeSessionPresent === false
    && lost.nativeSessionsInNewRuntime === 0 && lost.fakeReattachRejected === true
    && lost.foreignPrincipalError === 'UNAUTHORIZED_PRINCIPAL'
    && lost.staleGenerationError === 'STALE_GENERATION' && lost.staleEpochError === 'STALE_EPOCH'
    && lost.closeIdempotent && lost.runtimeShutdownOrphans === 0

  const observations = {
    schema_version: 'byq-v090-step5-b3-native-observations.v1',
    generated_at: nowIso(),
    evidence_class: EVIDENCE_CLASS,
    candidate: { release: CANDIDATE_RELEASE, npm_packages: CANDIDATE_NPM, python_sdk: '0.1.5rc1' },
    runtime_model: {
      native_runtime: 'one native OS process per runtime generation owning the real ctx.terminals PTY service + shell backend',
      byq_adapter: 'one BYQ adapter OS process owning only the durable TerminalAttachment record; restarted as the fault',
      client: 'each client action is a separate OS process over a Unix socket',
    },
    llm: { class: LLM_CLASS, real_llm_quality: false, note: 'no model call; the native terminal seam is driven directly through the BYQ attachment adapter' },
    scenarios: [
      {
        id: 'adapter-restart-native-survives',
        result: survivesPass ? 'PASS' : 'FAIL',
        fault_applied: survives.freshAdapterOsProcess,
        dimensions: {
          pty_process: survives.ptyProcessPresent ? 'present' : 'absent',
          attachment: survives.attachmentPresent ? 'present' : 'absent',
          io_rebind: survives.ioRebindOk ? 'ok' : 'rejected',
          terminal_identity: survives.identityStable ? 'stable' : 'lost',
        },
        observation: survives,
      },
      {
        id: 'adapter-restart-native-lost',
        result: lostPass ? 'PASS' : 'FAIL',
        fault_applied: lost.freshAdapterOsProcess,
        dimensions: {
          pty_process: lost.oldPidAliveAfterLoss ? 'present' : 'absent',
          attachment: lost.durableStoreFilePresent ? 'present' : 'absent',
          io_rebind: lost.reattachOk ? 'ok' : 'rejected',
          terminal_identity: lost.reattachOk ? 'stable' : 'lost',
        },
        observation: lost,
      },
    ],
    cross_checks: [
      {
        id: 'durable-attachment-lifecycle',
        result: (survives.byqMintedAttachmentId && survives.attachmentIdIsNotNativeId
          && survives.durableStoreFilePresent && survives.durableRecordsLoadedSameId
          && survives.recordHasOwnerGenerationEpochState && survives.auditLinkagePresent
          && survives.nativeSessionCountAfterIdempotent === 1) ? 'PASS' : 'FAIL',
        assertions: {},
        observation: {
          attachmentId: survives.attachmentId, nativeSessionId: survives.nativeSessionId,
          nativePid: survives.nativePid,
          attachmentIdByqMinted: survives.byqMintedAttachmentId,
          attachmentIdNotNativeIdentity: survives.attachmentIdIsNotNativeId,
          durableStorePersisted: survives.durableStoreFilePresent,
          reloadedSameAttachmentId: survives.durableRecordsLoadedSameId,
          recordHasOwnerGenerationEpochState: survives.recordHasOwnerGenerationEpochState,
          auditLinkagePresent: survives.auditLinkagePresent,
          auditEvents: survives.auditEvents,
          oneStoreFile: true,
        },
      },
      {
        id: 'permission-boundary',
        result: (survives.foreignPrincipalError === 'UNAUTHORIZED_PRINCIPAL'
          && survives.foreignSendError === 'FOREIGN_SESSION'
          && survives.foreignReadError === 'FOREIGN_SESSION') ? 'PASS' : 'FAIL',
        assertions: {},
        observation: {
          foreignPrincipalError: survives.foreignPrincipalError,
          foreignSendError: survives.foreignSendError,
          foreignReadError: survives.foreignReadError,
        },
      },
      {
        id: 'stale-generation-fenced',
        result: (survives.staleGenerationError === 'STALE_GENERATION'
          && survives.staleEpochError === 'STALE_EPOCH'
          && survives.reattachOk === true) ? 'PASS' : 'FAIL',
        assertions: {},
        observation: {
          staleGenerationError: survives.staleGenerationError,
          staleEpochError: survives.staleEpochError,
          currentGeneration: survives.createGeneration, currentEpoch: survives.createEpoch,
          currentRebindOk: survives.reattachOk,
          lostWorldStaleGenerationError: lost.staleGenerationError,
          lostWorldStaleEpochError: lost.staleEpochError,
          lostWorldValidTokenHonestLost: lost.reattachStatus,
        },
      },
      {
        id: 'wrong-terminal-rejected',
        result: (survives.unknownAttachmentError === 'UNKNOWN_ATTACHMENT'
          && survives.unknownReadError === 'NO_SESSION') ? 'PASS' : 'FAIL',
        assertions: {},
        observation: {
          unknownAttachmentError: survives.unknownAttachmentError,
          requestedUnknownAttachmentId: 'byq-att-does-not-exist',
          unknownReadError: survives.unknownReadError,
          requestedUnknownSessionId: survives.requestedUnknownSessionId,
          realSessionId: survives.unknownReadRealSessionId,
        },
      },
      {
        id: 'idempotent-transitions',
        result: (survives.idempotentReattachSameIdentity && survives.nativeSessionCountAfterIdempotent === 1
          && survives.closeIdempotent) ? 'PASS' : 'FAIL',
        assertions: {},
        observation: {
          idempotentReattachSameIdentity: survives.idempotentReattachSameIdentity,
          nativeSessionCountAfterIdempotent: survives.nativeSessionCountAfterIdempotent,
          closeIdempotent: survives.closeIdempotent,
        },
      },
      {
        id: 'cleanup-no-orphans',
        result: (survives.closeEndsPty && survives.runtimeShutdownOrphans === 0
          && lost.runtimeShutdownOrphans === 0) ? 'PASS' : 'FAIL',
        assertions: {},
        observation: {
          closeEndsPty: survives.closeEndsPty,
          survivesWorldOrphans: survives.runtimeShutdownOrphans,
          lostWorldOrphans: lost.runtimeShutdownOrphans,
        },
      },
    ],
    negatives: [
      { kind: 'foreign-principal', rejected: survives.foreignPrincipalError === 'UNAUTHORIZED_PRINCIPAL', errorCode: survives.foreignPrincipalError },
      { kind: 'foreign-owner-send', rejected: survives.foreignSendError === 'FOREIGN_SESSION', errorCode: survives.foreignSendError },
      { kind: 'foreign-owner-read', rejected: survives.foreignReadError === 'FOREIGN_SESSION', errorCode: survives.foreignReadError },
      { kind: 'unknown-attachment', rejected: survives.unknownAttachmentError === 'UNKNOWN_ATTACHMENT', errorCode: survives.unknownAttachmentError },
      { kind: 'unknown-terminal', rejected: survives.unknownReadError === 'NO_SESSION', errorCode: survives.unknownReadError },
      { kind: 'stale-generation', rejected: survives.staleGenerationError === 'STALE_GENERATION', errorCode: survives.staleGenerationError },
      { kind: 'stale-epoch', rejected: survives.staleEpochError === 'STALE_EPOCH', errorCode: survives.staleEpochError },
      { kind: 'fake-reattach-after-native-loss', rejected: lost.fakeReattachRejected === true, errorCode: lost.rebindError },
    ],
    notes: [
      {
        scope: 'candidate/qualification layer only: scripts/d15/terminal B3 harness/observer/contract; no runtime-adapter, Product API or frontend change',
        production_selector_unchanged: true,
        byq_builds_pty_runtime: false,
        byq_copies_dsh_terminal: false,
        second_generic_harness: false,
        second_session_store: false,
        fork_or_patch_of_dsh: false,
        product_surface_touches_raw_dsh_schema: false,
        r4_productization: false,
      },
    ],
    cleanup: {
      survives_temp_root_removed: survives.temp_root_removed === true,
      lost_temp_root_removed: lost.temp_root_removed === true,
      temp_root_removed: survives.temp_root_removed === true && lost.temp_root_removed === true,
    },
  }

  if (argv.out) {
    writeFileSync(argv.out, JSON.stringify(observations, null, 2) + '\n')
    process.stdout.write(`wrote ${argv.out}\n`)
  } else {
    process.stdout.write(JSON.stringify(observations, null, 2) + '\n')
  }
  return survivesPass && lostPass ? 0 : 1
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
} else if (command === 'adapter') {
  adapterMain(argv).catch((error) => {
    process.stderr.write(`adapter failed: ${error?.stack ?? error}\n`)
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
  process.stderr.write('usage: adapter_restart_harness.mjs run|runtime|adapter|client ...\n')
  process.exit(2)
}
