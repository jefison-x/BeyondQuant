// Keyless URL/header probe for the pinned official DSH Anthropic SDK.
// Usage: node probe-opencode-messages-path.mjs /tmp/byq-dsh-acp-rc2-source
import { createServer } from 'node:http'
import { readFileSync } from 'node:fs'
import { pathToFileURL } from 'node:url'
import { resolve } from 'node:path'

const source = resolve(process.argv[2] ?? '')
if (!process.argv[2]) throw new Error('official source path is required')
const commit = readFileSync(`${source}/.git/HEAD`, 'utf8').trim()
if (commit !== '639ed015397290b3745d163aafe02ffee4aa3f84') {
  throw new Error(`unexpected official source commit: ${commit}`)
}
const sdkPath = `${source}/node_modules/.pnpm/@anthropic-ai+sdk@0.124.0_zod@4.4.3/node_modules/@anthropic-ai/sdk/index.mjs`
const { default: Anthropic } = await import(pathToFileURL(sdkPath).href)

const observations = []
const server = createServer((request, response) => {
  observations.push({
    method: request.method,
    path: request.url,
    authorization: request.headers.authorization ?? null,
    hasXApiKey: typeof request.headers['x-api-key'] === 'string',
    anthropicVersion: request.headers['anthropic-version'] ?? null,
  })
  response.writeHead(200, { 'content-type': 'application/json' })
  response.end('{}')
})

await new Promise((resolve, reject) => {
  server.once('error', reject)
  server.listen(0, '127.0.0.1', resolve)
})

try {
  const address = server.address()
  if (address === null || typeof address === 'string') throw new Error('missing loopback address')
  const cases = [
    { basePath: '/zen/go/v1', expected: '/zen/go/v1/v1/messages?beta=true' },
    { basePath: '/zen/go', expected: '/zen/go/v1/messages?beta=true' },
    { basePath: '/zen', expected: '/zen/v1/messages?beta=true' },
  ]
  for (const item of cases) {
    const client = new Anthropic({
      apiKey: 'synthetic-key-no-provider-call',
      baseURL: `http://127.0.0.1:${address.port}${item.basePath}`,
      maxRetries: 0,
    })
    await client.beta.messages.create({
      model: 'qwen3.8-max', max_tokens: 16,
      messages: [{ role: 'user', content: 'local route probe' }],
    }).asResponse()
  }
  if (observations.length !== cases.length) throw new Error('unexpected local request count')
  for (const [index, row] of observations.entries()) {
    if (row.method !== 'POST' || row.path !== cases[index].expected ||
        row.authorization !== null || !row.hasXApiKey ||
        row.anthropicVersion !== '2023-06-01') {
      throw new Error(`unexpected local path or headers at case ${index}: ${JSON.stringify(row)}`)
    }
  }
  console.log('prior duplicated-v1 case: PASS (local fake server)')
  console.log('corrected Go and Zen cases: PASS (local fake server)')
} finally {
  await new Promise((resolve, reject) => server.close(error => error ? reject(error) : resolve()))
}
