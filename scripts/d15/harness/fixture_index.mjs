/**
 * Record the immutable D15-2 fixture index (sha256 + provenance).
 *
 * Usage:
 *   node fixture_index.mjs <fixtures-root> <index.json>
 */

import { createHash } from 'node:crypto'
import { readFile, readdir, stat, writeFile } from 'node:fs/promises'
import { join } from 'node:path'

const fixturesRoot = process.argv[2]
const indexPath = process.argv[3]
if (!fixturesRoot || !indexPath) {
  console.error('usage: node fixture_index.mjs <fixtures-root> <index.json>')
  process.exit(2)
}

const RELEASED_V2 = 'Constructed deterministically with the released DSH 0.1.5-rc.1 v2 physical codec; byte-accurate released-v2 format, not captured from a live 0.1.2 process.'
const provenance = {
  'f-normal': 'REAL: produced by running the official DSH 0.1.2-rc.1 bundled runtime in isolation (keyless synthetic loopback provider + MCP) through the BYQ runtime adapter, then decompressing the released-v0 multi-frame zstd session log losslessly to raw JSONL.',
  'f-completed': RELEASED_V2,
  'f-interrupted': RELEASED_V2,
  'f-compacted': RELEASED_V2,
  'f-large': RELEASED_V2,
  'f-subagent': RELEASED_V2,
  'f-continuable': 'Constructed by running the real DSH 0.1.5-rc.1 session-format catalog migration over a v2 subagent base and re-encoding with the released v3 current codec; the continuable activation descriptor itself is deferred to D15-4.',
  'f-forked': RELEASED_V2,
  'f-old-lifecycle': `${RELEASED_V2} Includes a synthetic BYQ lifecycle-evidence sibling file that the migration harness must not read or mutate.`,
}
const categories = {
  'f-normal': 'normal',
  'f-completed': 'completed',
  'f-interrupted': 'interrupted',
  'f-compacted': 'compacted',
  'f-large': 'large',
  'f-subagent': 'subagent',
  'f-continuable': 'continuable-subagent',
  'f-forked': 'forked',
  'f-old-lifecycle': 'with-old-lifecycle-evidence',
}
const order = ['f-normal', 'f-completed', 'f-interrupted', 'f-compacted', 'f-large', 'f-subagent', 'f-continuable', 'f-forked', 'f-old-lifecycle']

const sha256 = (value) => createHash('sha256').update(value).digest('hex')

async function main() {
  const fixtures = []
  for (const id of order) {
    const dir = join(fixturesRoot, id)
    const log = await readFile(join(dir, 'session.jsonl'))
    const rows = log.toString('utf8').split('\n').filter(Boolean)
    const siblings = (await readdir(dir)).filter((name) => name !== 'session.jsonl').sort()
    const siblingRecords = []
    for (const name of siblings) {
      const bytes = await readFile(join(dir, name))
      siblingRecords.push({ name, bytes: (await stat(join(dir, name))).size, sha256: sha256(bytes) })
    }
    fixtures.push({
      id,
      category: categories[id],
      immutable: true,
      source_format: JSON.parse(rows[0]).version,
      rows: rows.length,
      bytes: log.length,
      sha256: sha256(log),
      sibling_files: siblingRecords,
      provenance: provenance[id],
    })
  }
  const index = {
    schema_version: 'byq-d15-2-fixture-index.v1',
    target: 'dsh-v0.1.5-rc.1 session migration qualification source fixtures',
    fixtures,
  }
  await writeFile(indexPath, `${JSON.stringify(index, null, 2)}\n`, 'utf8')
  console.log(`indexed ${fixtures.length} fixtures -> ${indexPath}`)
}

await main()
