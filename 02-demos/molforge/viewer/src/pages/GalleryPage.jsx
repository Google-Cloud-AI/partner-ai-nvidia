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
import NarrativeSection from '../components/NarrativeSection.jsx'
import CandidateCard from '../components/CandidateCard.jsx'

export default function GalleryPage() {
  const [searchParams] = useSearchParams()
  const runId = searchParams.get('id')

  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    if (!runId) {
      setError('No run_id provided in URL. Expected ?id=opt_xxx')
      setLoading(false)
      return
    }
    setLoading(true)
    setError(null)
    fetchRun(runId)
      .then((res) => {
        if (res.kind !== 'optimization') {
          setError(
            `This run is not a Lead Optimization run (it's a ${res.kind} run). ` +
              `Try the /admet viewer instead.`
          )
        } else {
          setData(res)
        }
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false))
  }, [runId])

  if (loading) return <LoadingState message="Loading optimization run from Cloud Storage..." />
  if (error) return <ErrorState title="Could not load optimization run" message={error} runId={runId} />
  if (!data) return null

  const run = data.data
  const candidates = Array.isArray(run.candidates) ? run.candidates : []
  const dateStr = run.timestamp
    ? new Date(run.timestamp).toLocaleString(undefined, {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
      })
    : '—'

  return (
    <div className="max-w-6xl mx-auto px-6 py-8">
      {/* Header card */}
      <div className="bg-gradient-to-br from-gray-50 to-white border border-gray-200 rounded-xl p-5 mb-6">
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div>
            <div className="text-[10px] font-semibold text-gray-500 uppercase tracking-wide">
              Lead Optimization Gallery
            </div>
            <div className="mt-1 text-xl font-bold text-gray-900">
              {run.candidate_count} Candidate{run.candidate_count === 1 ? '' : 's'}
              <span className="text-base font-normal text-gray-500 ml-3">
                · {run.rounds_completed} round{run.rounds_completed === 1 ? '' : 's'}
              </span>
            </div>
            <div className="mt-2 text-xs text-gray-500 font-mono">{run.run_id}</div>
          </div>
          <div className="text-right">
            <div className="text-[10px] font-semibold text-gray-500 uppercase tracking-wide">Generated</div>
            <div className="mt-1 text-sm text-gray-900">{dateStr}</div>
            <div className="mt-2 text-[11px] text-gray-500">
              {run.total_generated} generated · {run.total_filtered} survived filters
            </div>
          </div>
        </div>
        {data.gcsPath && (
          <div className="mt-4 pt-4 border-t border-gray-200 text-[10px] text-gray-400 font-mono break-all">
            {data.gcsPath}
          </div>
        )}
      </div>

      {/* SAR narrative (conditional — only if stored in GCS) */}
      <NarrativeSection
        narrative={run.sar_narrative}
        title="SAR Analysis by NVIDIA Nemotron Super 49B"
        provider="NVIDIA"
        emptyHint={
          'SAR narrative not persisted for this run. Earlier runs stored candidates only — future runs will include the full Nemotron Super 49B SAR analysis inline here.'
        }
      />

      {/* Candidate grid */}
      {candidates.length === 0 ? (
        <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4 text-sm text-yellow-800">
          No candidates found in this run.
        </div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
          {candidates.map((candidate, i) => (
            <CandidateCard key={i} candidate={candidate} rank={i + 1} />
          ))}
        </div>
      )}
    </div>
  )
}
