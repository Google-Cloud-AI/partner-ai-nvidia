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

/**
 * DrugBank approved-drugs percentile bar.
 *
 * Shows where this molecule's value falls relative to all approved drugs.
 * The marker color reflects directionality:
 *   - lower_better: marker green at low percentiles, red at high
 *   - higher_better: marker red at low, green at high
 *   - context: neutral gray (no judgment)
 */
export default function PercentileBar({ percentile, direction = 'context' }) {
  if (percentile === null || percentile === undefined) {
    return <span className="text-xs text-gray-400">—</span>
  }

  const pct = Math.max(0, Math.min(100, percentile))

  let markerColor = '#6b7280' // gray for context
  if (direction === 'lower_better') {
    if (pct < 33) markerColor = '#16a34a'      // green
    else if (pct < 66) markerColor = '#eab308' // yellow
    else markerColor = '#dc2626'               // red
  } else if (direction === 'higher_better') {
    if (pct < 33) markerColor = '#dc2626'
    else if (pct < 66) markerColor = '#eab308'
    else markerColor = '#16a34a'
  }

  return (
    <div className="flex items-center gap-2 min-w-[140px]">
      <div className="flex-1 h-1.5 bg-gray-100 rounded-full relative">
        <div
          className="absolute top-1/2 -translate-y-1/2 w-3 h-3 rounded-full border-2 border-white shadow-sm"
          style={{
            left: `${pct}%`,
            transform: `translate(-50%, -50%)`,
            backgroundColor: markerColor,
          }}
        />
      </div>
      <span className="text-[11px] font-mono text-gray-600 tabular-nums w-10 text-right">
        {pct.toFixed(0)}%
      </span>
    </div>
  )
}
