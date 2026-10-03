/*
 * Copyright 2026 Google LLC
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     https://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

/**
 * MolForge Viewer client API.
 *
 * Talks to the local Express server at /api/* (which proxies to GCS).
 * In dev, Vite proxies /api/* to localhost:8080. In prod, Express serves both.
 */

export async function fetchRun(runId) {
  if (!runId) throw new Error('runId is required')
  const r = await fetch(`/api/run/${encodeURIComponent(runId)}`, {
    method: 'GET',
    cache: 'no-cache',
  })
  if (!r.ok) {
    let msg = `HTTP ${r.status}`
    try {
      const body = await r.json()
      if (body?.error) msg = body.error
    } catch {}
    throw new Error(msg)
  }
  return r.json()
}

export async function fetchHealth() {
  const r = await fetch('/api/health', { method: 'GET', cache: 'no-cache' })
  if (!r.ok) throw new Error(`HTTP ${r.status}`)
  return r.json()
}

export async function fetchStructure(filename) {
  if (!filename) throw new Error('filename is required')
  const r = await fetch(`/api/structure/${encodeURIComponent(filename)}`, {
    method: 'GET',
    cache: 'no-cache',
  })
  if (!r.ok) {
    let msg = `HTTP ${r.status}`
    try {
      const body = await r.json()
      if (body?.error) msg = body.error
    } catch {}
    throw new Error(msg)
  }
  return r.text()
}

export async function fetchDockManifest(dockId) {
  if (!dockId) throw new Error('dockId is required')
  const r = await fetch(`/api/dock/${encodeURIComponent(dockId)}/manifest`, {
    method: 'GET',
    cache: 'no-cache',
  })
  if (!r.ok) {
    let msg = `HTTP ${r.status}`
    try {
      const body = await r.json()
      if (body?.error) msg = body.error
    } catch {}
    throw new Error(msg)
  }
  return r.json()
}

export async function fetchDockProtein(dockId) {
  if (!dockId) throw new Error('dockId is required')
  const r = await fetch(`/api/dock/${encodeURIComponent(dockId)}/protein`, {
    method: 'GET',
    cache: 'no-cache',
  })
  if (!r.ok) {
    let msg = `HTTP ${r.status}`
    try {
      const body = await r.json()
      if (body?.error) msg = body.error
    } catch {}
    throw new Error(msg)
  }
  return r.text()
}

export async function fetchDockFiles(dockId) {
  if (!dockId) throw new Error('dockId is required')
  const r = await fetch(`/api/dock/${encodeURIComponent(dockId)}/files`, {
    method: 'GET',
    cache: 'no-cache',
  })
  if (!r.ok) {
    let msg = `HTTP ${r.status}`
    try {
      const body = await r.json()
      if (body?.error) msg = body.error
    } catch {}
    throw new Error(msg)
  }
  return r.json()
}

export async function fetchDockPose(dockId, filename) {
  if (!dockId) throw new Error('dockId is required')
  if (!filename) throw new Error('filename is required')
  const r = await fetch(
    `/api/dock/${encodeURIComponent(dockId)}/pose/${encodeURIComponent(filename)}`,
    { method: 'GET', cache: 'no-cache' }
  )
  if (!r.ok) {
    let msg = `HTTP ${r.status}`
    try {
      const body = await r.json()
      if (body?.error) msg = body.error
    } catch {}
    throw new Error(msg)
  }
  return r.text()
}
