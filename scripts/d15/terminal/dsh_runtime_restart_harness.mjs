#!/usr/bin/env node
/**
 * 0.9 strict-order step-5 B4 `terminal-dsh-runtime-restart` real native probe.
 *
 * Owner node: `d15-5-candidate-attachment-layer` (pre-gate; never post-GO R4).
 *
 * The one question: after generation A establishes a real native persistent
 * terminal plus a durable BYQ `TerminalAttachment`, and the DSH runtime OS
 * process is TRULY terminated and restarted, does generation B reconcile the
 * durable attachment and truthfully record native-state loss (`lost` /
 * `interrupted`) without ever fabricating a reattach? When a surviving PTY has
 * no attachment, is it reconciled as `lost` and never silently reused? Does the
 * terminal lifetime stay independent from conversation / durable-job lifetime?
 *
 * Reuse (no second harness): the DSH runtime role is the committed B3 harness
 * (`adapter_restart_harness.mjs runtime`), which owns the REAL native
 * `@deepseek-ai/dsh-terminal` + `@deepseek-ai/dsh-terminal-bash` PTY/shell/IO.
 * This file adds only the B4 orchestration and the B4 adapter role, and reuses
 * B3's minimal BYQ `TerminalAttachment` record schema and authorization gate
 * (`byq-terminal-attachment-store.v1`). It is NOT a generic agent harness, it
 * calls no model (`not-applicable`), and it never copies, persists or fakes the
 * native PTY.
 *
 * Modes:
 *   run [--out <path>]        orchestrate both worlds
 *   adapter --socket <p> --runtime-socket <p> --store <dir> --generation N
 *           --epoch N --adapter-generation N --principal <p>
 *   client  --socket <p> --request '<json>'
 */

import { mkdtempSync, readFileSync, writeFileSync, renameSync, rmSync, existsSync, mkdirSync } from 'node:fs'
import { randomBytes } from 'node:crypto'
import { tmpdir } from 'node:os'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { spawn, spawnSync } from 'node:child_process'
import { createServer, connect } from 'node:net'

export const EVIDENCE_CLASS = 'native-runtime-isolated-b4'
export const LLM_CLASS = 'not-applicable'
export const CANDIDATE_RELEASE = 'dsh-0.1.5rc1'
export const CANDIDATE_NPM = '0.1.5-rc.1'
export const STORE_FILE = 'terminal-attachments.v1.json'
// Reused verbatim from the B3 minimal TerminalAttachment lifecycle.
export const ATTACHMENT_STORE_SCHEMA = 'byq-terminal-attachment-store.v1'

const HERE = dirname(fileURLToPath(import.meta.url))
const NODE = process.execPath
const B3_HARNESS = join(HERE, 'adapter_restart_harness.mjs')

const OWNER_ID = 'd15-5-owner'
const OTHER_OWNER_ID = 'd15-5-other-owner'
const OWNER_PRINCIPAL = 'principal-owner'
const OTHER_PRINCIPAL = 'principal-other'

// ---------------------------------------------------------------------------
// helpers (same protocol as the reused B3 runtime role)
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

function serve(socketPath, handle) {
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
        .then((response) => socket.end(JSON.stringify(response) + '\n'))
        .catch((error) => socket.end(JSON.stringify(reject('SERVER_ERROR', String(error?.stack ?? error))) + '\n'))
    })
  })
  rmSync(socketPath, { force: true })
  return new Promise((resolve, rejectPromise) => {
    server.once('error', rejectPromise)
    server.listen(socketPath, () => resolve(server))
  })
}

// ---------------------------------------------------------------------------
// BYQ adapter OS process: owns ONLY the durable TerminalAttachment lifecycle
// (same record schema + gate as the B3 minimal lifecycle) plus B4 reconcile
// ---------------------------------------------------------------------------

function loadStore(storeDir) {
  const path = join(storeDir, STORE_FILE)
  const empty = { path, records: {}, conversations: {}, jobs: {} }
  if (!existsSync(path)) return empty
  try {
    const parsed = JSON.parse(readFileSync(path, 'utf8'))
    if (parsed && typeof parsed === 'object' && parsed.records && typeof parsed.records === 'object') {
      return {
        path,
        records: parsed.records,
        conversations: parsed.conversations && typeof parsed.conversations === 'object' ? parsed.conversations : {},
        jobs: parsed.jobs && typeof parsed.jobs === 'object' ? parsed.jobs : {},
      }
    }
  } catch { /* fall through to empty */ }
  return empty
}

function saveStore(store) {
  mkdirSync(dirname(store.path), { recursive: true })
  const tmp = `${store.path}.${process.pid}.tmp`
  writeFileSync(tmp, JSON.stringify({
    schema_version: ATTACHMENT_STORE_SCHEMA,
    records: store.records,
    conversations: store.conversations,
    jobs: store.jobs,
  }, null, 2) + '\n')
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

  function conversationSnapshot(record) {
    const conversation = record ? store.conversations[record.conversationId] : undefined
    const job = record ? store.jobs[record.durableJobId] : undefined
    return {
      conversationId: conversation?.conversationId ?? null,
      conversationStatus: conversation?.status ?? null,
      conversationCreatedByAttachment: conversation?.attachmentId ?? null,
      durableJobId: job?.durableJobId ?? null,
      durableJobStatus: job?.status ?? null,
      durableJobCreatedByAttachment: job?.attachmentId ?? null,
    }
  }

  async function handle(request) {
    switch (request.op) {
      case 'create': {
        if (request.principal !== ownerPrincipal) return reject('UNAUTHORIZED_PRINCIPAL')
        const spawned = await runtimeCall({ op: 'spawn', name: request.name })
        if (spawned.ok !== true) return reject('NATIVE_SPAWN_FAILED', spawned)
        const attachmentId = `byq-att-${randomBytes(9).toString('hex')}`
        const conversationId = `byq-conv-${randomBytes(9).toString('hex')}`
        const durableJobId = `byq-job-${randomBytes(9).toString('hex')}`
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
          conversationId,
          durableJobId,
          createdAt: nowIso(),
          audit: [],
        }
        // BYQ domain identities with independent lifetime (terminal loss must
        // never define conversation/durable-job lifetime).
        store.conversations[conversationId] = {
          schema_version: 'byq-durable-conversation.v1',
          conversationId, attachmentId, status: 'active', createdAt: record.createdAt,
        }
        store.jobs[durableJobId] = {
          schema_version: 'byq-durable-job.v1',
          durableJobId, attachmentId, conversationId, status: 'active', createdAt: record.createdAt,
        }
        audit(record, 'create', { nativeSessionId: record.nativeSessionId, conversationId, durableJobId })
        store.records[attachmentId] = record
        saveStore(store)
        return {
          ok: true, attachmentId, token: record.token, sessionId: record.nativeSessionId,
          pid: record.nativePid, generation: record.generation, epoch: record.executorEpoch,
          nativeRuntimeGeneration: record.nativeRuntimeGeneration, byqMinted: true,
          attachmentIdIsNotNativeId: attachmentId !== record.nativeSessionId && attachmentId !== `pid-${record.nativePid}`,
          conversationId, durableJobId, adapterGeneration: record.adapterGeneration, storePath: store.path,
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
          // Honest loss: NEVER return the old native session/pid or claim identity.
          return {
            ok: false, status: record.status, attachmentId: record.attachmentId,
            reattachAttempted: true, rebindError: 'NATIVE_SESSION_UNAVAILABLE',
            nativeSessionPresent: false, expectedSessionId: record.nativeSessionId,
            expectedPid: record.nativePid, oldPidAlive: alive(record.nativePid),
            runtimeGeneration: native.generation ?? null, adapterGeneration: record.adapterGeneration,
            nativeSessionCount: native.ok === true ? (native.sessions ?? []).length : null,
            returnedSessionId: null, returnedPid: null, identityStable: false,
            conversation: conversationSnapshot(record),
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
      case 'conversation-status': {
        const record = store.records[request.attachmentId]
        if (record === undefined) return reject('UNKNOWN_ATTACHMENT')
        return { ok: true, attachmentId: record.attachmentId, attachmentStatus: record.status, ...conversationSnapshot(record) }
      }
      // B4 fault injection: BYQ loses the attachment record while the native PTY
      // survives. The native session is then an orphan (surviving PTY with no
      // attachment) and MUST reconcile as lost, never be silently reused.
      case 'drop-record': {
        const record = store.records[request.attachmentId]
        if (record === undefined) return reject('UNKNOWN_ATTACHMENT')
        delete store.records[request.attachmentId]
        saveStore(store)
        return {
          ok: true, dropped: true, attachmentId: record.attachmentId,
          nativeSessionId: record.nativeSessionId, nativePid: record.nativePid,
          conversationId: record.conversationId, durableJobId: record.durableJobId,
          nativePidAliveAfterDrop: alive(record.nativePid),
        }
      }
      // Reconcile native sessions against durable attachments: a surviving PTY
      // with no attachment is an orphan classified lost; it is never adopted.
      case 'reconcile': {
        const native = await runtimeCall({ op: 'status' })
        const sessions = native.ok === true ? (native.sessions ?? []) : []
        const referenced = new Set(Object.values(store.records).map((item) => item.nativeSessionId))
        const orphans = sessions.filter((item) => !referenced.has(item.sessionId))
        const orphanRows = orphans.map((item) => ({
          sessionId: item.sessionId, pid: item.pid ?? null,
          nativeStatus: item.status ?? null, classified: 'lost', reused: false, adopted: false,
        }))
        return {
          ok: true, reconcileRan: true, nativeSessions: sessions.length,
          attachmentRecords: Object.keys(store.records).length,
          orphanNativeSessions: orphanRows.length, orphanClassified: orphanRows.length > 0 ? 'lost' : 'none',
          orphans: orphanRows, runtime: { generation: native.generation ?? null, ok: native.ok === true },
        }
      }
      // Negative probe: attempting to reuse/adopt an orphan native session must
      // fail closed and MUST NOT create an attachment record.
      case 'orphan-reuse-attempt': {
        const native = await runtimeCall({ op: 'status' })
        const sessions = native.ok === true ? (native.sessions ?? []) : []
        const isNativeSession = sessions.some((item) => item.sessionId === request.sessionId)
        const alreadyReferenced = Object.values(store.records).some((item) => item.nativeSessionId === request.sessionId)
        if (!isNativeSession) return reject('NO_SESSION', { sessionId: request.sessionId })
        if (alreadyReferenced) return reject('ALREADY_ATTACHED', { sessionId: request.sessionId })
        return {
          ok: false, error: 'ORPHAN_NOT_REUSABLE', adopted: false, attachmentCreated: false,
          sessionId: request.sessionId, detail: 'a surviving PTY with no attachment is lost, never silently reused',
        }
      }
      case 'cleanup-orphans': {
        const native = await runtimeCall({ op: 'status' })
        const sessions = native.ok === true ? (native.sessions ?? []) : []
        const referenced = new Set(Object.values(store.records).map((item) => item.nativeSessionId))
        const orphans = sessions.filter((item) => !referenced.has(item.sessionId))
        const killed = []
        for (const item of orphans) {
          const result = await runtimeCall({ op: 'kill', sessionId: item.sessionId, reason: 'b4 orphan cleanup' })
          killed.push({ sessionId: item.sessionId, pid: item.pid ?? null, killed: result.ok === true, pidAliveAfter: item.pid ? alive(item.pid) : false })
        }
        await new Promise((resolve) => setTimeout(resolve, 250))
        const stillAlive = orphans.filter((item) => alive(item.pid)).length
        return { ok: true, orphansFound: orphans.length, killed, orphansRemaining: stillAlive, cleanupComplete: stillAlive === 0 }
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
          conversation: record ? conversationSnapshot(record) : null,
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
          const result = await runtimeCall({ op: 'kill', sessionId: record.nativeSessionId, reason: 'b4 close' })
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

function spawnRole(file, mode, args, readyKey) {
  const child = spawn(NODE, [file, mode, ...args], { stdio: ['ignore', 'pipe', 'pipe'] })
  let stdout = ''
  let stderr = ''
  child.stderr.on('data', (chunk) => { stderr += chunk.toString('utf8') })
  return new Promise((resolve, rejectPromise) => {
    const timer = setTimeout(() => rejectPromise(new Error(`${mode} did not become ready: ${stderr}`)), 90000)
    child.stdout.on('data', (chunk) => {
      stdout += chunk.toString('utf8')
      const index = stdout.indexOf('\n')
      if (index >= 0 && !child.b4Ready) {
        child.b4Ready = JSON.parse(stdout.slice(0, index))
        child[readyKey] = child.b4Ready
        clearTimeout(timer)
        resolve(child)
      }
    })
    child.on('exit', (code) => {
      if (!child.b4Ready) {
        clearTimeout(timer)
        rejectPromise(new Error(`${mode} exited ${code}: ${stderr}`))
      }
    })
  })
}

const spawnRuntime = (socket, generation, epoch) => spawnRole(
  B3_HARNESS, 'runtime', ['--socket', socket, '--generation', String(generation), '--epoch', String(epoch)], 'runtimeInfo')

const spawnAdapter = (socket, runtimeSocket, store, generation, epoch, adapterGeneration) => spawnRole(
  fileURLToPath(import.meta.url), 'adapter',
  ['--socket', socket, '--runtime-socket', runtimeSocket, '--store', store,
    '--generation', String(generation), '--epoch', String(epoch),
    '--adapter-generation', String(adapterGeneration), '--principal', OWNER_PRINCIPAL], 'adapterInfo')

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
  process.stderr.write(`[b4] ${message}\n`)
}

function readStore(storeDir) {
  const path = join(storeDir, STORE_FILE)
  if (!existsSync(path)) return { present: false, records: {}, conversations: {}, jobs: {} }
  try {
    const parsed = JSON.parse(readFileSync(path, 'utf8'))
    return {
      present: true, records: parsed.records ?? {},
      conversations: parsed.conversations ?? {}, jobs: parsed.jobs ?? {},
    }
  } catch {
    return { present: false, records: {}, conversations: {}, jobs: {} }
  }
}

async function killAndWait(child) {
  if (!child || !alive(child.pid)) return
  try { process.kill(child.pid, 'SIGKILL') } catch { /* best effort */ }
  await waitExit(child)
  await new Promise((resolve) => setTimeout(resolve, 300))
}

// ---------------------------------------------------------------------------
// World 1: truly terminate + restart the DSH runtime OS process
// ---------------------------------------------------------------------------

async function worldRuntimeRestart() {
  const root = mkdtempSync(join(tmpdir(), 'b4-runtime-restart-'))
  const storeDir = join(root, 'byq-attachments')
  const runtimeSock1 = join(root, 'runtime-1.sock')
  const runtimeSock2 = join(root, 'runtime-2.sock')
  const adapterSock = join(root, 'adapter.sock')
  const observation = { temp_root: root }
  let runtime1 = null
  let runtime2 = null
  let adapterA = null
  let adapterB = null
  try {
    runtime1 = await spawnRuntime(runtimeSock1, 1, 1)
    adapterA = await spawnAdapter(adapterSock, runtimeSock1, storeDir, 1, 1, 1)

    const create = client(adapterSock, { op: 'create', principal: OWNER_PRINCIPAL, name: 'main' })
    const attachmentId = create.attachmentId
    const token = create.token
    const sessionId = create.sessionId
    const pid = create.pid
    const conversationId = create.conversationId
    const durableJobId = create.durableJobId
    const storeAfterCreate = await readStore(storeDir)

    const statusA = client(adapterSock, { op: 'status', attachmentId })
    const marker1 = randomMarker('B4_RESTART_MARK_ONE')
    const firstRun = client(adapterSock, { op: 'signal', attachmentId, token, generation: 1, epoch: 1, principal: OWNER_PRINCIPAL, text: `echo ${marker1}` })
    const marker1InFirst = countMarkerLines(firstRun.viewport, marker1)
    const conversationBefore = client(adapterSock, { op: 'conversation-status', attachmentId })

    const foreignPrincipal = client(adapterSock, { op: 'foreign-principal', attachmentId, token, generation: 1, epoch: 1, principal: OTHER_PRINCIPAL })
    const staleGeneration = client(adapterSock, { op: 'foreign-principal', attachmentId, token, generation: 0, epoch: 1, principal: OWNER_PRINCIPAL })
    const staleEpoch = client(adapterSock, { op: 'foreign-principal', attachmentId, token, generation: 1, epoch: 0, principal: OWNER_PRINCIPAL })
    const unknownAttachment = client(adapterSock, { op: 'unknown-attachment', attachmentId: 'byq-att-does-not-exist', token, generation: 1, epoch: 1, principal: OWNER_PRINCIPAL })
    const foreignSend = client(adapterSock, { op: 'foreign-send', sessionId, text: `echo ${randomMarker('B4_FOREIGN')}` })
    const foreignRead = client(adapterSock, { op: 'foreign-read', sessionId })
    const bogusSession = 'pty-does-not-exist'
    const unknownRead = client(adapterSock, { op: 'unknown-read', sessionId: bogusSession })

    const pidAliveBeforeFault = alive(pid)

    // FAULT: truly terminate the DSH runtime OS process (generation A). The
    // native PTY dies with the runtime (bwrap --die-with-parent). A genuinely
    // fresh OS process is then started as runtime generation B.
    process.kill(runtime1.pid, 'SIGKILL')
    await waitExit(runtime1)
    await new Promise((resolve) => setTimeout(resolve, 600))
    const oldPidAliveAfterRuntimeRestart = alive(pid)

    runtime2 = await spawnRuntime(runtimeSock2, 2, 1)
    adapterB = await spawnAdapter(adapterSock, runtimeSock2, storeDir, 1, 1, 2)
    const storeAfterRestart = await readStore(storeDir)

    const reattach = client(adapterSock, { op: 'reattach', attachmentId, token, generation: 1, epoch: 1, principal: OWNER_PRINCIPAL })
    const reattachRetry = client(adapterSock, { op: 'reattach', attachmentId, token, generation: 1, epoch: 1, principal: OWNER_PRINCIPAL })
    const conversationAfter = client(adapterSock, { op: 'conversation-status', attachmentId })
    const statusB = client(adapterSock, { op: 'status', attachmentId })
    const history = client(adapterSock, { op: 'history', attachmentId })
    const records = Object.values(storeAfterRestart.records)
    const record = records[0] ?? {}
    const auditEvents = [...new Set((history.audit ?? []).map((item) => item.event))]

    const close1 = client(adapterSock, { op: 'close', attachmentId, token })
    const close2 = client(adapterSock, { op: 'close', attachmentId, token })
    const shutdown = client(runtimeSock2, { op: 'shutdown' })
    await waitExit(runtime2)
    client(adapterSock, { op: 'shutdown' })

    const runtimeARestarted = runtime1.pid !== runtime2.pid
    const status = reattach.status ?? statusB.attachmentStatus
    const fakeReattachRejected = reattach.ok === false
      && reattach.returnedSessionId === null && reattach.returnedPid === null
      && reattach.identityStable !== true && reattach.sessionId === undefined && reattach.pid === undefined
    const conversationSurvived = conversationAfter.conversationId === conversationId
      && conversationAfter.conversationStatus === 'active'
    const durableJobSurvived = conversationAfter.durableJobId === durableJobId
      && conversationAfter.durableJobStatus === 'active'

    Object.assign(observation, {
      attachmentId, nativeSessionId: sessionId, nativePid: pid,
      expectedAttachmentId: attachmentId, expectedSessionId: sessionId, expectedPid: pid,
      conversationId, durableJobId,
      ptyCmdlineBefore: statusA.ptyCmdline,
      byqMintedAttachmentId: create.byqMinted === true,
      attachmentIdIsNotNativeId: create.attachmentIdIsNotNativeId === true,
      createGeneration: create.generation, createEpoch: create.epoch,
      marker1, marker1InFirstViewport: marker1InFirst,
      pidAliveBeforeFault,
      runtimeAPid: runtime1.pid, runtimeARuntimePid: runtime1.runtimeInfo?.runtimePid ?? null,
      runtimeAGeneration: runtime1.runtimeInfo?.generation ?? null,
      runtimeBPid: runtime2.pid, runtimeBRuntimePid: runtime2.runtimeInfo?.runtimePid ?? null,
      runtimeBGeneration: runtime2.runtimeInfo?.generation ?? null,
      runtimeOsProcessRestart: runtimeARestarted,
      dshRuntimeRestarted: runtimeARestarted && runtime2.runtimeInfo?.generation === 2,
      oldPidAliveAfterRuntimeRestart,
      oldPidAliveReported: reattach.oldPidAlive === true,
      adapterAPid: adapterA.pid, adapterAGeneration: statusA.adapterGeneration,
      adapterBPid: adapterB.pid, adapterBGeneration: statusB.adapterGeneration,
      freshAdapterOsProcess: adapterA.pid !== adapterB.pid,
      durableStoreFilePresent: storeAfterCreate.present && storeAfterRestart.present,
      durableRecordsLoadedSameId: records.length === 1 && record.attachmentId === attachmentId,
      recordHasOwnerGenerationEpochState: record.ownerPrincipal === OWNER_PRINCIPAL
        && Number.isInteger(record.generation) && Number.isInteger(record.executorEpoch)
        && typeof record.status === 'string',
      auditLinkagePresent: auditEvents.includes('create') && auditEvents.includes('lost'),
      auditEvents,
      reattachAttempted: reattach.reattachAttempted === true,
      reattachOk: reattach.ok === true, reattachStatus: status,
      rebindError: reattach.rebindError ?? null,
      nativeSessionPresent: reattach.nativeSessionPresent === true,
      nativeSessionsInNewRuntime: statusB.nativeSessions.length,
      returnedSessionId: reattach.returnedSessionId ?? null,
      returnedPid: reattach.returnedPid ?? null,
      identityStable: reattach.identityStable === true,
      fakeReattachRejected,
      reattachRetrySameLoss: reattachRetry.ok === false
        && (reattachRetry.status === 'lost' || reattachRetry.status === 'interrupted')
        && reattachRetry.rebindError === reattach.rebindError,
      conversationBeforeStatus: conversationBefore.conversationStatus ?? null,
      conversationStatusAfterLoss: conversationAfter.conversationStatus ?? null,
      durableJobStatusAfterLoss: conversationAfter.durableJobStatus ?? null,
      conversationSurvived, durableJobSurvived,
      conversationUnchanged: conversationBefore.conversationStatus === conversationAfter.conversationStatus,
      terminalLifetimeDefinesConversation: !conversationSurvived || !durableJobSurvived,
      foreignPrincipalError: foreignPrincipal.error ?? null,
      staleGenerationError: staleGeneration.error ?? null,
      staleEpochError: staleEpoch.error ?? null,
      unknownAttachmentError: unknownAttachment.error ?? null,
      foreignSendError: foreignSend.errorCode ?? null,
      foreignReadError: foreignRead.errorCode ?? null,
      unknownReadError: unknownRead.errorCode ?? null,
      requestedUnknownSessionId: bogusSession,
      unknownReadRealSessionId: sessionId,
      closeIdempotent: close1.ok === true && close2.ok === true && close2.alreadyClosed === true
        && close1.status === 'detached' && close2.status === 'detached',
      orphans: shutdown.orphans ?? null,
      runtimeShutdownOrphans: shutdown.orphans ?? null,
      temp_root_removed: false,
    })
    return observation
  } finally {
    await killAndWait(adapterA)
    await killAndWait(adapterB)
    await killAndWait(runtime1)
    await killAndWait(runtime2)
    try { rmSync(root, { recursive: true, force: true }) } catch { /* best effort */ }
    observation.temp_root_removed = !existsSync(root)
  }
}

// ---------------------------------------------------------------------------
// World 2: a surviving PTY with no attachment must reconcile as lost
// ---------------------------------------------------------------------------

async function worldSurvivingPtyWithoutAttachment() {
  const root = mkdtempSync(join(tmpdir(), 'b4-orphan-'))
  const storeDir = join(root, 'byq-attachments')
  const runtimeSock = join(root, 'runtime.sock')
  const adapterSock = join(root, 'adapter.sock')
  const observation = { temp_root: root }
  let runtime = null
  let adapterA = null
  let adapterB = null
  try {
    runtime = await spawnRuntime(runtimeSock, 1, 1)
    adapterA = await spawnAdapter(adapterSock, runtimeSock, storeDir, 1, 1, 1)

    const create = client(adapterSock, { op: 'create', principal: OWNER_PRINCIPAL, name: 'main' })
    const attachmentId = create.attachmentId
    const token = create.token
    const sessionId = create.sessionId
    const pid = create.pid
    const conversationId = create.conversationId
    const durableJobId = create.durableJobId
    const storeAfterCreate = await readStore(storeDir)
    const marker1 = randomMarker('B4_ORPHAN_MARK_ONE')
    client(adapterSock, { op: 'signal', attachmentId, token, generation: 1, epoch: 1, principal: OWNER_PRINCIPAL, text: `echo ${marker1}` })

    // Permission/fencing checks while the durable record still exists.
    const foreignPrincipal = client(adapterSock, { op: 'foreign-principal', attachmentId, token, generation: 1, epoch: 1, principal: OTHER_PRINCIPAL })
    const staleGeneration = client(adapterSock, { op: 'foreign-principal', attachmentId, token, generation: 0, epoch: 1, principal: OWNER_PRINCIPAL })
    const staleEpoch = client(adapterSock, { op: 'foreign-principal', attachmentId, token, generation: 1, epoch: 0, principal: OWNER_PRINCIPAL })
    const foreignSend = client(adapterSock, { op: 'foreign-send', sessionId, text: `echo ${randomMarker('B4_ORPHAN_FOREIGN')}` })
    const foreignRead = client(adapterSock, { op: 'foreign-read', sessionId })
    const unknownAttachment = client(adapterSock, { op: 'unknown-attachment', attachmentId: 'byq-att-does-not-exist', token, generation: 1, epoch: 1, principal: OWNER_PRINCIPAL })

    // Fault: BYQ loses the durable attachment record while the native DSH state
    // (the PTY) genuinely survives. This is the surviving-PTY-without-attachment
    // case, not a DSH runtime restart.
    const nativePtyAliveBeforeDrop = alive(pid)
    const dropped = client(adapterSock, { op: 'drop-record', attachmentId })
    const storeAfterDrop = await readStore(storeDir)
    const nativePtyAliveAfterDrop = alive(pid)

    // Reconcile with a FRESH adapter generation B over the same native runtime.
    process.kill(adapterA.pid, 'SIGKILL')
    await waitExit(adapterA)
    await new Promise((resolve) => setTimeout(resolve, 300))
    adapterB = await spawnAdapter(adapterSock, runtimeSock, storeDir, 1, 1, 2)

    const reconcile = client(adapterSock, { op: 'reconcile' })
    const reconcileRetry = client(adapterSock, { op: 'reconcile' })
    const reuse = client(adapterSock, { op: 'orphan-reuse-attempt', sessionId })
    const staleReattach = client(adapterSock, { op: 'reattach', attachmentId, token, generation: 1, epoch: 1, principal: OWNER_PRINCIPAL })
    const statusAfterReconcile = client(adapterSock, { op: 'status' })
    const storeAfterReconcile = await readStore(storeDir)

    const cleanup = client(adapterSock, { op: 'cleanup-orphans' })
    await new Promise((resolve) => setTimeout(resolve, 300))
    const orphanPidAliveAfterCleanup = alive(pid)
    const shutdown = client(runtimeSock, { op: 'shutdown' })
    await waitExit(runtime)
    client(adapterSock, { op: 'shutdown' })

    const conversation = storeAfterReconcile.conversations[conversationId]
    const job = storeAfterReconcile.jobs[durableJobId]
    const conversationSurvived = conversation?.status === 'active'
    const durableJobSurvived = job?.status === 'active'
    const orphanRow = (reconcile.orphans ?? [])[0] ?? {}
    const orphanReconcileIdempotent = reconcile.orphanNativeSessions === reconcileRetry.orphanNativeSessions
      && reconcileRetry.orphanNativeSessions === 1

    Object.assign(observation, {
      attachmentId, nativeSessionId: sessionId, nativePid: pid,
      conversationId, durableJobId,
      byqMintedAttachmentId: create.byqMinted === true,
      attachmentIdIsNotNativeId: create.attachmentIdIsNotNativeId === true,
      durableStoreFilePresent: storeAfterCreate.present && storeAfterDrop.present,
      durableRecordsLoadedSameId: Object.keys(storeAfterCreate.records).length === 1
        && Object.keys(storeAfterCreate.records)[0] === attachmentId,
      nativePtyAliveBeforeDrop,
      dropped: dropped.dropped === true,
      droppedNativeSessionId: dropped.nativeSessionId ?? null,
      droppedNativePid: dropped.nativePid ?? null,
      nativePtyAliveAfterDrop,
      remainingAttachmentRecords: Object.keys(storeAfterDrop.records).length,
      adapterAPid: adapterA.pid, adapterBPid: adapterB.pid,
      freshAdapterOsProcess: adapterA.pid !== adapterB.pid,
      orphanReconcileRan: reconcile.reconcileRan === true,
      orphanNativeSessionsDetected: reconcile.orphanNativeSessions ?? null,
      orphanClassified: orphanRow.classified ?? null,
      orphanReused: orphanRow.reused === true || reuse.adopted === true,
      orphanAdoptedAsAttachment: reuse.attachmentCreated === true
        || Object.keys(storeAfterReconcile.records).length > 0,
      orphanReuseAttemptError: reuse.error ?? null,
      orphanReconcileIdempotent,
      oldAttachmentIdReattachError: staleReattach.error ?? null,
      conversationStatusAfter: conversation?.status ?? null,
      durableJobStatusAfter: job?.status ?? null,
      conversationSurvived, durableJobSurvived,
      terminalLifetimeDefinesConversation: !conversationSurvived || !durableJobSurvived,
      foreignPrincipalError: foreignPrincipal.error ?? null,
      staleGenerationError: staleGeneration.error ?? null,
      staleEpochError: staleEpoch.error ?? null,
      foreignSendError: foreignSend.errorCode ?? null,
      foreignReadError: foreignRead.errorCode ?? null,
      unknownAttachmentError: unknownAttachment.error ?? null,
      cleanupKilledOrphan: (cleanup.killed ?? []).some((item) => item.killed === true),
      cleanupOrphansFound: cleanup.orphansFound ?? null,
      orphanPidAliveAfterCleanup,
      orphans: shutdown.orphans ?? null,
      runtimeShutdownOrphans: shutdown.orphans ?? null,
      nativeSessionsAfterCleanup: (client(runtimeSock, { op: 'status' }).sessions ?? []).length,
      temp_root_removed: false,
    })
    return observation
  } finally {
    await killAndWait(adapterA)
    await killAndWait(adapterB)
    await killAndWait(runtime)
    try { rmSync(root, { recursive: true, force: true }) } catch { /* best effort */ }
    observation.temp_root_removed = !existsSync(root)
  }
}

async function run(argv) {
  const restart = await worldRuntimeRestart()
  const orphan = await worldSurvivingPtyWithoutAttachment()

  const restartPass = restart.byqMintedAttachmentId && restart.attachmentIdIsNotNativeId
    && restart.durableStoreFilePresent && restart.durableRecordsLoadedSameId
    && restart.recordHasOwnerGenerationEpochState && restart.auditLinkagePresent
    && restart.pidAliveBeforeFault && restart.marker1InFirstViewport === 1
    && restart.dshRuntimeRestarted && restart.oldPidAliveAfterRuntimeRestart === false
    && restart.freshAdapterOsProcess
    && restart.reattachAttempted && restart.reattachOk === false
    && (restart.reattachStatus === 'lost' || restart.reattachStatus === 'interrupted')
    && restart.rebindError === 'NATIVE_SESSION_UNAVAILABLE'
    && restart.nativeSessionPresent === false && restart.nativeSessionsInNewRuntime === 0
    && restart.fakeReattachRejected && restart.reattachRetrySameLoss
    && restart.conversationSurvived && restart.durableJobSurvived
    && restart.terminalLifetimeDefinesConversation === false
    && restart.foreignPrincipalError === 'UNAUTHORIZED_PRINCIPAL'
    && restart.staleGenerationError === 'STALE_GENERATION' && restart.staleEpochError === 'STALE_EPOCH'
    && restart.unknownAttachmentError === 'UNKNOWN_ATTACHMENT'
    && restart.foreignSendError === 'FOREIGN_SESSION' && restart.foreignReadError === 'FOREIGN_SESSION'
    && restart.unknownReadError === 'NO_SESSION'
    && restart.closeIdempotent && restart.runtimeShutdownOrphans === 0

  const orphanPass = orphan.byqMintedAttachmentId && orphan.attachmentIdIsNotNativeId
    && orphan.durableStoreFilePresent && orphan.durableRecordsLoadedSameId
    && orphan.nativePtyAliveBeforeDrop && orphan.dropped
    && orphan.nativePtyAliveAfterDrop && orphan.remainingAttachmentRecords === 0
    && orphan.freshAdapterOsProcess
    && orphan.orphanReconcileRan && orphan.orphanNativeSessionsDetected === 1
    && orphan.orphanClassified === 'lost' && orphan.orphanReused === false
    && orphan.orphanAdoptedAsAttachment === false
    && orphan.orphanReuseAttemptError === 'ORPHAN_NOT_REUSABLE'
    && orphan.orphanReconcileIdempotent
    && orphan.oldAttachmentIdReattachError === 'UNKNOWN_ATTACHMENT'
    && orphan.conversationSurvived && orphan.durableJobSurvived
    && orphan.terminalLifetimeDefinesConversation === false
    && orphan.foreignPrincipalError === 'UNAUTHORIZED_PRINCIPAL'
    && orphan.staleGenerationError === 'STALE_GENERATION' && orphan.staleEpochError === 'STALE_EPOCH'
    && orphan.foreignSendError === 'FOREIGN_SESSION' && orphan.foreignReadError === 'FOREIGN_SESSION'
    && orphan.unknownAttachmentError === 'UNKNOWN_ATTACHMENT'
    && orphan.cleanupKilledOrphan && orphan.orphanPidAliveAfterCleanup === false
    && orphan.orphans === 0 && orphan.nativeSessionsAfterCleanup === 0

  const observations = {
    schema_version: 'byq-v090-step5-b4-native-observations.v1',
    generated_at: nowIso(),
    evidence_class: EVIDENCE_CLASS,
    candidate: { release: CANDIDATE_RELEASE, npm_packages: CANDIDATE_NPM, python_sdk: '0.1.5rc1' },
    runtime_model: {
      native_runtime: 'one native DSH runtime OS process per runtime generation owning the real ctx.terminals PTY service + shell backend (reused committed B3 runtime role)',
      byq_adapter: 'one BYQ adapter OS process owning only the durable TerminalAttachment + reconcile surface; the DSH runtime restart and the adapter restart are the faults',
      client: 'each client action is a separate OS process over a Unix socket',
    },
    llm: { class: LLM_CLASS, real_llm_quality: false, note: 'no model call; the real native terminal seam is driven through the BYQ attachment adapter' },
    scenarios: [
      {
        id: 'dsh-runtime-restart-terminal-lost',
        result: restartPass ? 'PASS' : 'FAIL',
        fault_applied: restart.dshRuntimeRestarted === true,
        dimensions: {
          pty_process: restart.oldPidAliveAfterRuntimeRestart ? 'present' : 'absent',
          attachment: restart.durableStoreFilePresent ? 'present' : 'absent',
          io_rebind: restart.reattachOk ? 'ok' : 'rejected',
          terminal_identity: restart.reattachOk ? 'stable' : 'lost',
        },
        observation: restart,
      },
      {
        id: 'surviving-pty-without-attachment-lost',
        result: orphanPass ? 'PASS' : 'FAIL',
        fault_applied: orphan.dropped === true && orphan.freshAdapterOsProcess === true,
        dimensions: {
          pty_process: orphan.nativePtyAliveAfterDrop ? 'present' : 'absent',
          attachment: orphan.remainingAttachmentRecords === 0 ? 'absent' : 'present',
          io_rebind: 'rejected',
          terminal_identity: 'lost',
        },
        observation: orphan,
      },
    ],
    cross_checks: [
      {
        id: 'durable-attachment-lifecycle',
        result: (restart.byqMintedAttachmentId && restart.attachmentIdIsNotNativeId
          && restart.durableStoreFilePresent && restart.durableRecordsLoadedSameId
          && restart.recordHasOwnerGenerationEpochState && restart.auditLinkagePresent) ? 'PASS' : 'FAIL',
        assertions: {},
        observation: {
          attachmentId: restart.attachmentId, nativeSessionId: restart.nativeSessionId,
          nativePid: restart.nativePid,
          attachmentIdByqMinted: restart.byqMintedAttachmentId,
          attachmentIdNotNativeIdentity: restart.attachmentIdIsNotNativeId,
          durableStorePersisted: restart.durableStoreFilePresent,
          reloadedSameAttachmentId: restart.durableRecordsLoadedSameId,
          recordHasOwnerGenerationEpochState: restart.recordHasOwnerGenerationEpochState,
          auditLinkagePresent: restart.auditLinkagePresent,
          auditEvents: restart.auditEvents,
          oneStoreFile: true,
        },
      },
      {
        id: 'real-dsh-runtime-restart',
        result: (restart.pidAliveBeforeFault
          && restart.runtimeOsProcessRestart && restart.dshRuntimeRestarted
          && restart.oldPidAliveAfterRuntimeRestart === false) ? 'PASS' : 'FAIL',
        assertions: {},
        observation: {
          runtimeAPid: restart.runtimeAPid, runtimeBPid: restart.runtimeBPid,
          runtimeAGeneration: restart.runtimeAGeneration, runtimeBGeneration: restart.runtimeBGeneration,
          runtimeOsProcessRestart: restart.runtimeOsProcessRestart,
          dshRuntimeRestarted: restart.dshRuntimeRestarted,
          pidAliveBeforeFault: restart.pidAliveBeforeFault,
          oldPtyPid: restart.nativePid,
          oldPidAliveAfterRuntimeRestart: restart.oldPidAliveAfterRuntimeRestart,
          nativeSessionsInNewRuntime: restart.nativeSessionsInNewRuntime,
        },
      },
      {
        id: 'permission-boundary',
        result: (restart.foreignPrincipalError === 'UNAUTHORIZED_PRINCIPAL'
          && restart.foreignSendError === 'FOREIGN_SESSION'
          && restart.foreignReadError === 'FOREIGN_SESSION') ? 'PASS' : 'FAIL',
        assertions: {},
        observation: {
          foreignPrincipalError: restart.foreignPrincipalError,
          foreignSendError: restart.foreignSendError,
          foreignReadError: restart.foreignReadError,
        },
      },
      {
        id: 'stale-generation-fenced',
        result: (restart.staleGenerationError === 'STALE_GENERATION'
          && restart.staleEpochError === 'STALE_EPOCH') ? 'PASS' : 'FAIL',
        assertions: {},
        observation: {
          staleGenerationError: restart.staleGenerationError,
          staleEpochError: restart.staleEpochError,
          currentGeneration: restart.createGeneration, currentEpoch: restart.createEpoch,
          orphanWorldStaleGenerationError: orphan.staleGenerationError,
          orphanWorldStaleEpochError: orphan.staleEpochError,
        },
      },
      {
        id: 'wrong-terminal-rejected',
        result: (restart.unknownAttachmentError === 'UNKNOWN_ATTACHMENT'
          && restart.unknownReadError === 'NO_SESSION') ? 'PASS' : 'FAIL',
        assertions: {},
        observation: {
          unknownAttachmentError: restart.unknownAttachmentError,
          requestedUnknownAttachmentId: 'byq-att-does-not-exist',
          unknownReadError: restart.unknownReadError,
          requestedUnknownSessionId: restart.requestedUnknownSessionId,
          realSessionId: restart.unknownReadRealSessionId,
        },
      },
      {
        id: 'idempotent-transitions',
        result: (restart.reattachRetrySameLoss && orphan.orphanReconcileIdempotent
          && restart.closeIdempotent) ? 'PASS' : 'FAIL',
        assertions: {},
        observation: {
          reattachRetrySameLoss: restart.reattachRetrySameLoss,
          orphanReconcileIdempotent: orphan.orphanReconcileIdempotent,
          closeIdempotent: restart.closeIdempotent,
        },
      },
      {
        id: 'cleanup-no-orphans',
        result: (restart.runtimeShutdownOrphans === 0 && orphan.cleanupKilledOrphan
          && orphan.orphanPidAliveAfterCleanup === false && orphan.orphans === 0
          && orphan.nativeSessionsAfterCleanup === 0) ? 'PASS' : 'FAIL',
        assertions: {},
        observation: {
          restartWorldOrphans: restart.runtimeShutdownOrphans,
          orphanWorldOrphans: orphan.orphans,
          orphanCleanupKilled: orphan.cleanupKilledOrphan,
          orphanPidAliveAfterCleanup: orphan.orphanPidAliveAfterCleanup,
          nativeSessionsAfterCleanup: orphan.nativeSessionsAfterCleanup,
        },
      },
      {
        id: 'terminal-lifetime-independent',
        result: (restart.conversationSurvived && restart.durableJobSurvived
          && restart.terminalLifetimeDefinesConversation === false
          && orphan.conversationSurvived && orphan.durableJobSurvived
          && orphan.terminalLifetimeDefinesConversation === false) ? 'PASS' : 'FAIL',
        assertions: {},
        observation: {
          conversationId: restart.conversationId, durableJobId: restart.durableJobId,
          conversationStatusAfterLoss: restart.conversationStatusAfterLoss,
          durableJobStatusAfterLoss: restart.durableJobStatusAfterLoss,
          restartConversationSurvived: restart.conversationSurvived,
          restartDurableJobSurvived: restart.durableJobSurvived,
          orphanConversationStatus: orphan.conversationStatusAfter,
          orphanDurableJobStatus: orphan.durableJobStatusAfter,
          orphanConversationSurvived: orphan.conversationSurvived,
          orphanDurableJobSurvived: orphan.durableJobSurvived,
        },
      },
    ],
    negatives: [
      { kind: 'foreign-principal', rejected: restart.foreignPrincipalError === 'UNAUTHORIZED_PRINCIPAL', errorCode: restart.foreignPrincipalError },
      { kind: 'foreign-owner-send', rejected: restart.foreignSendError === 'FOREIGN_SESSION', errorCode: restart.foreignSendError },
      { kind: 'foreign-owner-read', rejected: restart.foreignReadError === 'FOREIGN_SESSION', errorCode: restart.foreignReadError },
      { kind: 'unknown-attachment', rejected: restart.unknownAttachmentError === 'UNKNOWN_ATTACHMENT', errorCode: restart.unknownAttachmentError },
      { kind: 'unknown-terminal', rejected: restart.unknownReadError === 'NO_SESSION', errorCode: restart.unknownReadError },
      { kind: 'stale-generation', rejected: restart.staleGenerationError === 'STALE_GENERATION', errorCode: restart.staleGenerationError },
      { kind: 'stale-epoch', rejected: restart.staleEpochError === 'STALE_EPOCH', errorCode: restart.staleEpochError },
      { kind: 'fake-reattach-after-dsh-runtime-restart', rejected: restart.fakeReattachRejected === true, errorCode: restart.rebindError },
      { kind: 'orphan-reuse', rejected: orphan.orphanReuseAttemptError === 'ORPHAN_NOT_REUSABLE', errorCode: orphan.orphanReuseAttemptError },
      { kind: 'dropped-attachment-reattach', rejected: orphan.oldAttachmentIdReattachError === 'UNKNOWN_ATTACHMENT', errorCode: orphan.oldAttachmentIdReattachError },
    ],
    notes: [
      {
        scope: 'candidate/qualification layer only: scripts/d15/terminal B4 harness/observer/contract; reuses the committed B3 native runtime role and the minimal TerminalAttachment record schema; no runtime-adapter, Product API or frontend change',
        reuses_b3_native_runtime_role: true,
        reuses_b3_attachment_store_schema: true,
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
      restart_world_temp_root_removed: restart.temp_root_removed === true,
      orphan_world_temp_root_removed: orphan.temp_root_removed === true,
      temp_root_removed: restart.temp_root_removed === true && orphan.temp_root_removed === true,
    },
  }

  if (argv.out) {
    writeFileSync(argv.out, JSON.stringify(observations, null, 2) + '\n')
    process.stdout.write(`wrote ${argv.out}\n`)
  } else {
    process.stdout.write(JSON.stringify(observations, null, 2) + '\n')
  }
  return restartPass && orphanPass ? 0 : 1
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

if (command === 'adapter') {
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
  process.stderr.write('usage: dsh_runtime_restart_harness.mjs run|adapter|client ...\n')
  process.exit(2)
}
