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

import React, { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { fetchStructure } from '../api.js'
import LoadingState from '../components/LoadingState.jsx'
import ErrorState from '../components/ErrorState.jsx'
import MoleculeViewer3D from '../components/MoleculeViewer3D.jsx'

export default function ProteinPage() {
  const [searchParams] = useSearchParams()
  const filename = searchParams.get('file')

  const [pdbText, setPdbText] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    if (!filename) {
      setError('No file provided in URL. Expected ?file=name.pdb')
      setLoading(false)
      return
    }
    if (!/^[A-Za-z0-9_.-]+\.pdb$/.test(filename)) {
      setError('Invalid filename format: ' + filename)
      setLoading(false)
      return
    }
    setLoading(true)
    setError(null)
    fetchStructure(filename)
      .then((text) => setPdbText(text))
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false))
  }, [filename])

  if (loading)
    return <LoadingState message="Loading protein structure from Cloud Storage..." />
  if (error)
    return (
      <ErrorState
        title="Could not load protein structure"
        message={error}
        runId={filename}
      />
    )
  if (!pdbText) return null

  return (
    <div className="max-w-7xl mx-auto px-6 py-8">
      <div className="bg-gradient-to-br from-gray-50 to-white border border-gray-200 rounded-xl p-5 mb-6">
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div>
            <div className="text-[10px] font-semibold text-gray-500 uppercase tracking-wide">
              Protein Structure Viewer
            </div>
            <div className="mt-1 text-xl font-bold text-gray-900 font-mono break-all">
              {filename}
            </div>
            <div className="mt-2 text-[11px] text-gray-500">
              Predicted by NVIDIA ESMFold on RTX PRO 6000 Blackwell · colored by
              pLDDT confidence (50–100)
            </div>
          </div>
          <div className="text-right text-[10px] text-gray-400 font-mono">
            gs://molforge-artifacts/structures/{filename}
          </div>
        </div>
      </div>

      <div className="relative">
        <MoleculeViewer3D pdbText={pdbText} colorMode="spectrum" height="72vh" />
        <div className="absolute top-4 right-4 bg-white/95 backdrop-blur border border-gray-200 rounded-lg p-3 text-[10px] shadow-sm">
          <div className="font-semibold text-gray-700 mb-2 uppercase tracking-wide">
            pLDDT
          </div>
          <div className="flex items-center gap-2">
            <div
              className="w-4 h-24 rounded"
              style={{
                background:
                  'linear-gradient(to top, #ff0000, #ffff00, #00ff00, #0000ff)',
              }}
            />
            <div className="flex flex-col justify-between h-24 text-gray-600">
              <span>100</span>
              <span>75</span>
              <span>50</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
