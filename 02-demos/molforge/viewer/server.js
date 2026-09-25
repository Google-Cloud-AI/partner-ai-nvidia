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
 * MolForge Viewer — Express backend.
 *
 * Serves:
 *   - GET  /api/health                 — liveness check
 *   - GET  /api/run/:runId             — fetch run JSON from gs://molforge-artifacts/{runId}/
 *   - GET  /*                          — static React build (SPA fallback to index.html)
 *
 * Auth: Application Default Credentials (Cloud Run compute SA in prod, gcloud ADC in dev).
 */
import express from 'express'
import path from 'path'
import { fileURLToPath } from 'url'
import { Storage } from '@google-cloud/storage'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)

const PORT = parseInt(process.env.PORT || '8080', 10)
const BUCKET_NAME = process.env.MOLFORGE_GCS_BUCKET || 'molforge-artifacts'
// Required, no default. A hardcoded project-id fallback silently points a fresh
// deployment at somebody else's project instead of failing; the miss then
// surfaces as a confusing 403 on the first GCS read. Fail at startup instead.
const PROJECT_ID = process.env.GOOGLE_CLOUD_PROJECT
if (!PROJECT_ID) {
  console.error(
    'GOOGLE_CLOUD_PROJECT is not set. Deploy with ' +
      '`--set-env-vars GOOGLE_CLOUD_PROJECT=<your-project>` (setup.sh does this), ' +
      'or export it for local runs.',
  )
  process.exit(1)
}

const storage = new Storage({ projectId: PROJECT_ID })
const bucket = storage.bucket(BUCKET_NAME)

const app = express()
app.use(express.json({ limit: '4mb' }))

// ────────────────────────────────────────────────────────────
// API: health
// ────────────────────────────────────────────────────────────
app.get('/api/health', (req, res) => {
  res.json({
    status: 'ok',
    service: 'molforge-viewer',
    bucket: BUCKET_NAME,
    project: PROJECT_ID,
    timestamp: new Date().toISOString(),
  })
})

// ────────────────────────────────────────────────────────────
// API: fetch a run from GCS
// Tries admet_results.json first, then optimization_results.json.
// Returns { kind: 'admet'|'optimization', data: {...}, runId }
// ────────────────────────────────────────────────────────────
app.get('/api/run/:runId', async (req, res) => {
  const { runId } = req.params

  if (!/^[a-zA-Z0-9_-]+$/.test(runId)) {
    return res.status(400).json({ error: 'Invalid run_id format' })
  }

  const candidates = [
    { kind: 'admet', path: `${runId}/admet_results.json` },
    { kind: 'optimization', path: `${runId}/optimization_results.json` },
  ]

  for (const candidate of candidates) {
    try {
      const file = bucket.file(candidate.path)
      const [exists] = await file.exists()
      if (!exists) continue
      const [contents] = await file.download()
      const json = JSON.parse(contents.toString('utf-8'))
      return res.json({
        kind: candidate.kind,
        runId,
        gcsPath: `gs://${BUCKET_NAME}/${candidate.path}`,
        data: json,
      })
    } catch (err) {
      console.error(`[viewer] error reading ${candidate.path}:`, err.message)
      return res.status(500).json({
        error: `Failed to read ${candidate.path}: ${err.message}`,
      })
    }
  }

  return res.status(404).json({
    error: `Run not found in gs://${BUCKET_NAME}/${runId}/`,
    tried: candidates.map((c) => c.path),
  })
})

// ────────────────────────────────────────────────────────────
// API: fetch a raw PDB structure file from GCS
// Used by /protein?file=name.pdb (mirrors ESMFold service layout)
// ────────────────────────────────────────────────────────────
app.get('/api/structure/:filename', async (req, res) => {
  const { filename } = req.params

  if (!/^[A-Za-z0-9_.-]+\.pdb$/.test(filename)) {
    return res.status(400).json({ error: 'Invalid filename format' })
  }

  try {
    const file = bucket.file(`structures/${filename}`)
    const [exists] = await file.exists()
    if (!exists) {
      return res.status(404).json({
        error: `Structure not found: gs://${BUCKET_NAME}/structures/${filename}`,
      })
    }
    const [contents] = await file.download()
    res.set('Content-Type', 'text/plain; charset=utf-8')
    res.set('Cache-Control', 'public, max-age=300')
    return res.send(contents.toString('utf-8'))
  } catch (err) {
    console.error(`[viewer] /api/structure error:`, err.message)
    return res.status(500).json({ error: `Failed to read structure: ${err.message}` })
  }
})

// ────────────────────────────────────────────────────────────
// API: fetch a docking run manifest from GCS
// Used by /docking?id=dock_xxx to discover ligands + pose files
// ────────────────────────────────────────────────────────────
app.get('/api/dock/:dockId/manifest', async (req, res) => {
  const { dockId } = req.params

  if (!/^[a-zA-Z0-9_-]+$/.test(dockId)) {
    return res.status(400).json({ error: 'Invalid dock_id format' })
  }

  try {
    const file = bucket.file(`docking/${dockId}/manifest.json`)
    const [exists] = await file.exists()
    if (!exists) {
      return res.status(404).json({
        error: `Manifest not found: gs://${BUCKET_NAME}/docking/${dockId}/manifest.json`,
      })
    }
    const [contents] = await file.download()
    const json = JSON.parse(contents.toString('utf-8'))
    return res.json(json)
  } catch (err) {
    console.error(`[viewer] /api/dock/:dockId/manifest error:`, err.message)
    return res.status(500).json({ error: `Failed to read manifest: ${err.message}` })
  }
})

// ────────────────────────────────────────────────────────────
// API: fetch the chain-A protein PDB for a docking run
// Used by /docking?id=dock_xxx to render the protein surface
// ────────────────────────────────────────────────────────────
app.get('/api/dock/:dockId/protein', async (req, res) => {
  const { dockId } = req.params

  if (!/^[a-zA-Z0-9_-]+$/.test(dockId)) {
    return res.status(400).json({ error: 'Invalid dock_id format' })
  }

  try {
    const file = bucket.file(`docking/${dockId}/protein.pdb`)
    const [exists] = await file.exists()
    if (!exists) {
      return res.status(404).json({
        error: `Protein not found: gs://${BUCKET_NAME}/docking/${dockId}/protein.pdb`,
      })
    }
    const [contents] = await file.download()
    res.set('Content-Type', 'text/plain; charset=utf-8')
    res.set('Cache-Control', 'public, max-age=300')
    return res.send(contents.toString('utf-8'))
  } catch (err) {
    console.error(`[viewer] /api/dock/:dockId/protein error:`, err.message)
    return res.status(500).json({ error: `Failed to read protein: ${err.message}` })
  }
})

// ────────────────────────────────────────────────────────────
// API: list all pose files in a docking run
// Used by /docking?id=dock_xxx to discover lig*_rank*_conf*.sdf filenames
// (needed because the confidence value is embedded in the filename)
// ────────────────────────────────────────────────────────────
app.get('/api/dock/:dockId/files', async (req, res) => {
  const { dockId } = req.params

  if (!/^[a-zA-Z0-9_-]+$/.test(dockId)) {
    return res.status(400).json({ error: 'Invalid dock_id format' })
  }

  try {
    const [files] = await bucket.getFiles({ prefix: `docking/${dockId}/` })
    const names = files
      .map((f) => f.name.replace(`docking/${dockId}/`, ''))
      .filter((n) => n && n.endsWith('.sdf'))
      .sort()
    return res.json({ dockId, files: names })
  } catch (err) {
    console.error(`[viewer] /api/dock/:dockId/files error:`, err.message)
    return res.status(500).json({ error: `Failed to list files: ${err.message}` })
  }
})

// ────────────────────────────────────────────────────────────
// API: fetch a single pose SDF file from a docking run
// ────────────────────────────────────────────────────────────
app.get('/api/dock/:dockId/pose/:filename', async (req, res) => {
  const { dockId, filename } = req.params

  if (!/^[a-zA-Z0-9_-]+$/.test(dockId)) {
    return res.status(400).json({ error: 'Invalid dock_id format' })
  }
  if (!/^lig\d+_rank\d+_conf[\d.]+\.sdf$/.test(filename)) {
    return res.status(400).json({ error: 'Invalid pose filename format' })
  }

  try {
    const file = bucket.file(`docking/${dockId}/${filename}`)
    const [exists] = await file.exists()
    if (!exists) {
      return res.status(404).json({
        error: `Pose not found: gs://${BUCKET_NAME}/docking/${dockId}/${filename}`,
      })
    }
    const [contents] = await file.download()
    res.set('Content-Type', 'chemical/x-mdl-sdfile')
    res.set('Cache-Control', 'public, max-age=300')
    return res.send(contents.toString('utf-8'))
  } catch (err) {
    console.error(`[viewer] /api/dock/:dockId/pose error:`, err.message)
    return res.status(500).json({ error: `Failed to read pose: ${err.message}` })
  }
})

// ────────────────────────────────────────────────────────────
// Static React build + SPA fallback
// In dev, Vite serves the frontend on port 5174 with /api proxied to us.
// In prod, we serve both from this single Express process.
// ────────────────────────────────────────────────────────────
const distPath = path.join(__dirname, 'dist')
app.use(express.static(distPath, { index: false }))

app.get('*', (req, res) => {
  if (req.path.startsWith('/api/')) {
    return res.status(404).json({ error: 'Unknown API route' })
  }
  res.sendFile(path.join(distPath, 'index.html'), (err) => {
    if (err) {
      res.status(404).send('MolForge Viewer — frontend not built. Run `npm run build` first.')
    }
  })
})

app.listen(PORT, '0.0.0.0', () => {
  console.log(`[molforge-viewer] listening on http://0.0.0.0:${PORT}`)
  console.log(`[molforge-viewer] bucket=${BUCKET_NAME} project=${PROJECT_ID}`)
})
