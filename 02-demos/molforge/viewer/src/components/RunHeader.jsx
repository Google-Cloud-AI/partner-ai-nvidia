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

import React from 'react'

export default function RunHeader({ runId, therapeuticArea, timestamp, candidateCount, gcsPath }) {
  const dateStr = timestamp
    ? new Date(timestamp).toLocaleString(undefined, {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
      })
    : '—'

  return (
    <div className="bg-gradient-to-br from-gray-50 to-white border border-gray-200 rounded-xl p-5 mb-6">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <div className="text-[10px] font-semibold text-gray-500 uppercase tracking-wide">
            ADMET Safety Report
          </div>
          <div className="mt-1 text-xl font-bold text-gray-900">
            {therapeuticArea ? therapeuticArea.charAt(0).toUpperCase() + therapeuticArea.slice(1) : 'General'}
          </div>
          <div className="mt-2 text-xs text-gray-500 font-mono">{runId}</div>
        </div>
        <div className="text-right">
          <div className="text-[10px] font-semibold text-gray-500 uppercase tracking-wide">Generated</div>
          <div className="mt-1 text-sm text-gray-900">{dateStr}</div>
          <div className="mt-2 text-xs text-gray-500">
            {candidateCount} candidate{candidateCount === 1 ? '' : 's'}
          </div>
        </div>
      </div>
      {gcsPath && (
        <div className="mt-4 pt-4 border-t border-gray-200 text-[10px] text-gray-400 font-mono break-all">
          {gcsPath}
        </div>
      )}
    </div>
  )
}
