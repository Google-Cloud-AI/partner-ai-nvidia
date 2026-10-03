// Copyright 2026 Google LLC
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     https://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

// Build-time smoke test for the viewer image.
//
// The runtime stage installs with `npm ci --omit=dev` and copies `dist` from a
// separate build stage, so two things can go wrong without anything failing:
// a production dependency that only the dev install happened to provide, and a
// vite build that emitted nothing. Either ships an image that starts, answers
// its health check, and serves a blank page.
//
// So this boots the real server and calls the real endpoint, rather than
// checking that files exist.
import { spawn } from 'child_process'
import { existsSync, readFileSync, readdirSync } from 'fs'

const PORT = 8081 // not 8080: avoid colliding with anything the daemon sets up
const TIMEOUT_MS = 30_000

function fail(msg) {
  console.error(`smoke test FAILED: ${msg}`)
  process.exit(1)
}

// 1. The vite build actually produced a bundle.
if (!existsSync('dist/index.html')) fail('dist/index.html is missing -- the vite build produced nothing')
const html = readFileSync('dist/index.html', 'utf8')
if (!html.includes('/assets/')) {
  fail('dist/index.html references no /assets/ bundle -- the build emitted an empty shell')
}
const assets = existsSync('dist/assets') ? readdirSync('dist/assets') : []
if (!assets.some((f) => f.endsWith('.js'))) fail('dist/assets contains no JS bundle')

// 2. The server boots with production-only dependencies and answers.
const server = spawn('node', ['server.js'], {
  // GOOGLE_CLOUD_PROJECT is the required-config contract server.js enforces at
  // startup (no hardcoded project fallback). Declaring it here is deliberate: if
  // someone reintroduces a literal default this stops testing anything, and if a
  // new required var appears the build breaks until it is declared.
  env: { ...process.env, PORT: String(PORT), GOOGLE_CLOUD_PROJECT: 'smoke-test-project' },
  stdio: ['ignore', 'inherit', 'inherit'],
})
server.on('error', (e) => fail(`could not spawn server.js: ${e.message}`))

const deadline = Date.now() + TIMEOUT_MS
let body = null
while (Date.now() < deadline) {
  try {
    const res = await fetch(`http://127.0.0.1:${PORT}/api/health`)
    if (res.ok) {
      body = await res.json()
      break
    }
  } catch {
    // not listening yet
  }
  await new Promise((r) => setTimeout(r, 250))
}
server.kill('SIGKILL')

if (!body) fail(`server never answered /api/health within ${TIMEOUT_MS / 1000}s`)
if (body.status !== 'ok') fail(`/api/health returned status=${JSON.stringify(body.status)}`)

console.log(`smoke test OK: ${assets.length} built assets, /api/health -> ${body.status} (bucket ${body.bucket})`)
