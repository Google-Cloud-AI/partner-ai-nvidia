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

import React, { useEffect, useState, useCallback, useRef } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  fetchRun,
  fetchDockManifest,
  fetchDockProtein,
  fetchDockFiles,
  fetchDockPose,
} from '../api.js'
import LoadingState from '../components/LoadingState.jsx'
import ErrorState from '../components/ErrorState.jsx'
import MoleculeViewer3D from '../components/MoleculeViewer3D.jsx'
import PoseSelector from '../components/PoseSelector.jsx'

export default function DockingPage() {
  const [searchParams] = useSearchParams()
  const id = searchParams.get('id')

  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [dockId, setDockId] = useState(null)
  const [manifest, setManifest] = useState(null)
  const [protein, setProtein] = useState(null)
  const [filesList, setFilesList] = useState([])
  const [poses, setPoses] = useState({})
  const [selected, setSelected] = useState(new Set())

  const posesRef = useRef({})
  useEffect(() => {
    posesRef.current = poses
  }, [poses])

  useEffect(() => {
    if (!id) {
      setError('No id provided. Expected ?id=dock_xxx or ?id=opt_xxx')
      setLoading(false)
      return
    }

    let cancelled = false
    setLoading(true)
    setError(null)

    async function load() {
      try {
        let resolvedDockId = id

        if (id.startsWith('opt_')) {
          const runData = await fetchRun(id)
          const storedDockId = runData?.data?.dock_id
          if (!storedDockId) {
            throw new Error(
              'This optimization run (' +
                id +
                ') has no associated docking results. It may be an older run from before dock_id persistence, or it was run without a target structure. Try /gallery?id=' +
                id +
                ' for the candidate gallery view.'
            )
          }
          resolvedDockId = storedDockId
        }

        const [mf, pdb, fl] = await Promise.all([
          fetchDockManifest(resolvedDockId),
          fetchDockProtein(resolvedDockId),
          fetchDockFiles(resolvedDockId),
        ])

        if (cancelled) return

        setDockId(resolvedDockId)
        setManifest(mf)
        setProtein(pdb)
        setFilesList(fl.files || [])

        if (mf && mf.ligands && mf.ligands.length > 0) {
          setSelected(new Set([mf.ligands[0].lig_idx]))
        }
      } catch (err) {
        if (!cancelled) setError(err.message)
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    load()
    return () => {
      cancelled = true
    }
  }, [id])

  const findRank1File = useCallback(
    (ligIdx) => {
      const prefix = 'lig' + String(ligIdx).padStart(3, '0') + '_rank1_'
      return filesList.find((f) => f.startsWith(prefix))
    },
    [filesList]
  )

  useEffect(() => {
    if (!dockId || selected.size === 0) return

    selected.forEach(async (ligIdx) => {
      if (posesRef.current[ligIdx]) return
      const filename = findRank1File(ligIdx)
      if (!filename) return
      try {
        const sdf = await fetchDockPose(dockId, filename)
        setPoses((prev) => ({ ...prev, [ligIdx]: sdf }))
      } catch (err) {
        console.error('Failed to load pose for lig' + ligIdx + ':', err)
      }
    })
  }, [selected, dockId, findRank1File])

  const onToggle = useCallback((ligIdx) => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(ligIdx)) next.delete(ligIdx)
      else next.add(ligIdx)
      return next
    })
  }, [])

  if (loading)
    return <LoadingState message="Loading docking run from Cloud Storage..." />
  if (error)
    return (
      <ErrorState title="Could not load docking run" message={error} runId={id} />
    )
  if (!manifest || !protein) return null

  const selectedSdfs = Array.from(selected)
    .map((idx) => poses[idx])
    .filter(Boolean)

  return (
    <div className="max-w-7xl mx-auto px-6 py-8">
      <div className="bg-gradient-to-br from-gray-50 to-white border border-gray-200 rounded-xl p-5 mb-6">
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div>
            <div className="text-[10px] font-semibold text-gray-500 uppercase tracking-wide">
              Docking Pose Viewer
            </div>
            <div className="mt-1 text-xl font-bold text-gray-900">
              {manifest.num_ligands} ligand
              {manifest.num_ligands === 1 ? '' : 's'} ·{' '}
              {manifest.protein_residue_count} residues
              <span className="text-base font-normal text-gray-500 ml-3">
                · {manifest.num_poses_per_ligand} pose
                {manifest.num_poses_per_ligand === 1 ? '' : 's'}/ligand
              </span>
            </div>
            <div className="mt-2 text-xs text-gray-500 font-mono">{dockId}</div>
            <div className="mt-1 text-[11px] text-gray-500">
              Docked by NVIDIA DiffDock NIM 2.2.0 on A100 · protein from{' '}
              <span className="font-mono">{manifest.pdb_source}</span>
            </div>
          </div>
          <div className="text-right text-[10px] text-gray-400 font-mono">
            gs://molforge-artifacts/docking/{dockId}/
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-5">
        <div className="lg:col-span-3">
          <MoleculeViewer3D
            pdbText={protein}
            sdfTexts={selectedSdfs}
            colorMode="chain"
            height="72vh"
          />
        </div>
        <div className="lg:col-span-1">
          <PoseSelector
            ligands={manifest.ligands || []}
            selectedIndices={selected}
            onToggle={onToggle}
          />
        </div>
      </div>
    </div>
  )
}
