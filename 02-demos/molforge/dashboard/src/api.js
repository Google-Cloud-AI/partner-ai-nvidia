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
 * MolForge A2A client.
 *
 * Talks to the MolForge A2A server (Cloud Run) via JSON-RPC for chat,
 * and via REST GET endpoints for service health probes.
 */

// Baked in at build time by Vite (see dashboard/Dockerfile's VITE_A2A_URL build
// arg). This was previously a hardcoded literal, which meant a dashboard built
// from a fresh clone sent every message to the original project's bridge.
const A2A_URL = import.meta.env.VITE_A2A_URL

if (!A2A_URL) {
  throw new Error(
    'VITE_A2A_URL was not set at build time. Build with ' +
      '`--build-arg VITE_A2A_URL=https://<your-bridge>.run.app` (setup.sh does this).',
  )
}

/**
 * Send a message to MolForge.
 *
 * @param {string} text The user's message
 * @param {string|null} contextId Reuse this to thread multi-turn conversations
 * @returns {Promise<{
 *   text: string,
 *   contextId: string,
 *   taskId: string,
 *   timeline: Array,
 *   completedAt: string,
 *   raw: object,
 * }>}
 */
export async function sendMessage(text, contextId = null) {
  const requestId = `dashboard-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`

  const params = {
    message: {
      role: 'user',
      parts: [{ kind: 'text', text }],
    },
  }
  if (contextId) {
    params.contextId = contextId
  }

  const body = {
    jsonrpc: '2.0',
    method: 'message/send',
    id: requestId,
    params,
  }

  let response
  try {
    response = await fetch(`${A2A_URL}/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
  } catch (networkErr) {
    throw new Error(`Network error reaching MolForge A2A: ${networkErr.message}`)
  }

  if (!response.ok) {
    const errText = await response.text().catch(() => '(no body)')
    throw new Error(`A2A server returned ${response.status}: ${errText.slice(0, 300)}`)
  }

  const data = await response.json()

  if (data.error) {
    throw new Error(`A2A error ${data.error.code}: ${data.error.message}`)
  }

  const result = data.result || {}
  const meta = data.meta || {}
  const statusMessage = result.status?.message?.parts?.[0]?.text || ''

  return {
    text: statusMessage,
    contextId: result.contextId || null,
    taskId: result.id || null,
    timeline: Array.isArray(meta.timeline) ? meta.timeline : [],
    completedAt: meta.completed_at || null,
    raw: data,
  }
}

/**
 * Probe all 6 GKE services in parallel via the A2A server.
 *
 * @returns {Promise<{
 *   services: Array<{name, label, status, latency_ms, model_loaded}>,
 *   summary: {total, healthy, cold, unhealthy},
 *   checked_at: string,
 * }>}
 */
export async function probeAllServices() {
  try {
    const r = await fetch(`${A2A_URL}/warmup-all`, {
      method: 'GET',
      cache: 'no-cache',
    })
    if (!r.ok) {
      throw new Error(`Probe failed: HTTP ${r.status}`)
    }
    return await r.json()
  } catch (err) {
    throw new Error(`Service probe error: ${err.message}`)
  }
}

/**
 * Probe a single GKE service via the A2A server.
 *
 * @param {string} name Service name (e.g., 'genmol', 'diffdock')
 * @returns {Promise<{name, label, status, latency_ms, model_loaded}>}
 */
export async function probeService(name) {
  try {
    const r = await fetch(`${A2A_URL}/warmup/${encodeURIComponent(name)}`, {
      method: 'GET',
      cache: 'no-cache',
    })
    if (!r.ok) {
      throw new Error(`Probe failed: HTTP ${r.status}`)
    }
    return await r.json()
  } catch (err) {
    throw new Error(`Service probe error: ${err.message}`)
  }
}
