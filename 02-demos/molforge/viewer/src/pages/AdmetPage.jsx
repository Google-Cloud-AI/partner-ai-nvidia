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
import { fetchRun } from '../api.js'
import LoadingState from '../components/LoadingState.jsx'
import ErrorState from '../components/ErrorState.jsx'
import RunHeader from '../components/RunHeader.jsx'
import NarrativeSection from '../components/NarrativeSection.jsx'
import MoleculeStructure2D from '../components/MoleculeStructure2D.jsx'
import EndpointTable from '../components/EndpointTable.jsx'

export default function AdmetPage() {
  const [searchParams] = useSearchParams()
  const runId = searchParams.get('id')

  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    if (!runId) {
      setError('No run_id provided in URL. Expected ?id=run_xxx')
      setLoading(false)
      return
    }
    setLoading(true)
    setError(null)
    fetchRun(runId)
      .then((res) => {
        if (res.kind !== 'admet') {
          setError(
            `This run is not an ADMET run (it's a ${res.kind} run). ` +
              `Try the /gallery viewer instead.`
          )
        } else {
          setData(res)
        }
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false))
  }, [runId])

  if (loading) return <LoadingState message="Loading ADMET run from Cloud Storage..." />
  if (error) return <ErrorState title="Could not load ADMET run" message={error} runId={runId} />
  if (!data) return null

  const run = data.data
  const molecules = Array.isArray(run.screening_results) ? run.screening_results : []

  return (
    <div className="max-w-6xl mx-auto px-6 py-8">
      <RunHeader
        runId={run.run_id}
        therapeuticArea={run.therapeutic_area}
        timestamp={run.timestamp}
        candidateCount={molecules.length}
        gcsPath={data.gcsPath}
      />

      <NarrativeSection narrative={run.safety_narrative} title="Safety Assessment by NVIDIA Nemotron Nano VL" />

      {molecules.length === 0 ? (
        <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4 text-sm text-yellow-800">
          No screening_results found in this run.
        </div>
      ) : (
        molecules.map((molecule, i) => (
          <div key={i} className="mb-10">
            <div className="flex items-center gap-3 mb-4">
              <h2 className="text-lg font-bold text-gray-900">
                Candidate {i + 1}{molecules.length > 1 ? ` of ${molecules.length}` : ''}
              </h2>
              <code className="text-[11px] font-mono text-gray-500 bg-gray-100 px-2 py-0.5 rounded">
                {molecule.smiles}
              </code>
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-6">
              <div className="lg:col-span-1">
                <div className="bg-white border border-gray-200 rounded-xl p-4">
                  <div className="text-[10px] font-semibold text-gray-500 uppercase tracking-wide mb-3">
                    2D Structure
                  </div>
                  <div className="flex justify-center">
                    <MoleculeStructure2D smiles={molecule.smiles} width={300} height={240} />
                  </div>
                </div>
              </div>

              <div className="lg:col-span-2">
                <div className="bg-white border border-gray-200 rounded-xl p-4">
                  <div className="text-[10px] font-semibold text-gray-500 uppercase tracking-wide mb-3">
                    Physicochemical Properties
                  </div>
                  {molecule.physicochemical ? (
                    <div className="grid grid-cols-2 sm:grid-cols-3 gap-x-4 gap-y-2 text-sm">
                      {Object.entries(molecule.physicochemical).filter(([k]) => k !== "smiles").map(([k, v]) => (
                        <div key={k} className="flex items-baseline justify-between border-b border-gray-50 pb-1">
                          <span className="text-xs text-gray-500">{k}</span>
                          <span className="font-mono text-gray-800 tabular-nums">
                            {typeof v === 'number' ? (Math.abs(v) >= 10 ? v.toFixed(1) : v.toFixed(3)) : String(v)}
                          </span>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="text-xs text-gray-400 italic">No physicochemical data</div>
                  )}
                </div>
              </div>
            </div>

            <EndpointTable molecule={molecule} />
          </div>
        ))
      )}
    </div>
  )
}
