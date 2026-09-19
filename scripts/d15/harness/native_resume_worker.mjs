/**
 * D15-3 native resume worker: one OS process == one runtime generation.
 *
 * The qualification harness spawns this worker to create/hold/resume a real
 * persisted DSH session. Because a generation is a process, a new worker
 * process opening the SAME session id through `SessionPersistence.open` is a
 * genuine cross-process native resume, and a SIGKILL of a holder exercises the
 * kernel `flock(2)` write-lease release on process death.
 *
 * Usage: node native_resume_worker.mjs '<json-command>'
 *   { "cmd": "create-hold", "root": "...", "id": "...", "events": "completed|open|none", "flush": true }
 *   { "cmd": "create-exit", "root": "...", "id": "...", "events": "...", "flush": true }
 *   { "cmd": "resume-write", "root": "...", "id": "..." }
 *   { "cmd": "hold-write", "root": "...", "id": "..." }
 *   { "cmd": "cold-read", "root": "...", "id": "..." }
 */

import { readColdSessionLog } from '@deepseek-ai/dsh-session-query'
import {
  closeBackend, completedTurn, contiguous, eventTypes, hasOpenTurn, jsonLine,
  mountBackend, nextTurn, openTurn, sessionHeader, validateEvents,
} from './native_resume_common.mjs'

const command = JSON.parse(process.argv[2] ?? '{}')
const { root, id } = command

async function holdForever() {
  await new Promise(() => {
    setInterval(() => {}, 1 << 30)
  })
}

async function main() {
  const ctx = await mountBackend(root)
  const persistence = ctx.sessionPersistence
  switch (command.cmd) {
    case 'create-hold':
    case 'create-exit': {
      const handle = await persistence.create(sessionHeader(id, root))
      let appended = 0
      if (command.events === 'completed') {
        await handle.append(validateEvents(completedTurn(0, 1)))
        appended = 6
      } else if (command.events === 'open') {
        await handle.append(validateEvents(openTurn(0, 1)))
        appended = 3
      }
      let flushed = false
      if (command.flush !== false) {
        await handle.flush()
        flushed = true
      }
      jsonLine({ cmd: command.cmd, created: true, session_id: String(handle.id), appended, flushed })
      if (command.cmd === 'create-exit') {
        await handle.close()
        await closeBackend(ctx)
        return
      }
      await holdForever()
      return
    }
    case 'hold-write': {
      const handle = await persistence.open(id, 'write')
      const slice = await handle.read(0)
      jsonLine({ cmd: 'hold-write', opened: true, session_id: String(handle.id), events: slice.events.length })
      await holdForever()
      return
    }
    case 'resume-write': {
      const handle = await persistence.open(id, 'write')
      const slice = await handle.read(0)
      const before = slice.events.length
      const events = validateEvents(completedTurn(before, nextTurn(slice.events)))
      await handle.append(events)
      await handle.flush()
      const after = (await handle.read(0)).events
      jsonLine({
        cmd: 'resume-write', opened: true, session_id: String(handle.id),
        events_before: before, events_after: after.length,
        first_seq: after[0]?.seq ?? null, last_seq: after[after.length - 1]?.seq ?? null,
        sequence_contiguous: contiguous(after),
        event_types: eventTypes(after),
      })
      await handle.close()
      await closeBackend(ctx)
      return
    }
    case 'cold-read': {
      const cold = await readColdSessionLog(persistence, id)
      jsonLine({
        cmd: 'cold-read', session_id: String(cold.header.id), events: cold.events.length,
        event_types: eventTypes(cold.events), open_turn: hasOpenTurn(cold.events),
        inherited_event_count: Number(cold.inheritedEventCount),
      })
      await closeBackend(ctx)
      return
    }
    default:
      throw new Error(`unknown worker command: ${String(command.cmd)}`)
  }
}

main().catch((error) => {
  jsonLine({ cmd: command.cmd, error: error?.name ?? 'Error', message: String(error?.message ?? error).slice(0, 400) })
  process.exit(1)
})
