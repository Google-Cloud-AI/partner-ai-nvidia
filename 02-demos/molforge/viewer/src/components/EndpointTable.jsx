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
import PercentileBar from './PercentileBar.jsx'
import { ENDPOINT_GROUPS, lookupPercentile, formatValue } from '../lib/admetMappings.js'

/**
 * Render the full ADMET endpoint table for one molecule.
 * Groups endpoints into Absorption / Distribution / Metabolism / Excretion / Toxicity.
 */
export default function EndpointTable({ molecule }) {
  if (!molecule) return null

  return (
    <div className="space-y-6">
      {ENDPOINT_GROUPS.map((group) => {
        const groupData = molecule[group.id] || {}
        return (
          <div key={group.id} className="border border-gray-200 rounded-lg overflow-hidden">
            <div className="bg-gray-50 border-b border-gray-200 px-4 py-2 flex items-center gap-2">
              <span className="w-6 h-6 rounded-full bg-gray-900 text-white text-xs font-bold flex items-center justify-center">
                {group.icon}
              </span>
              <h3 className="text-sm font-semibold text-gray-900">{group.label}</h3>
              <span className="text-[11px] text-gray-500 ml-auto">
                {group.endpoints.length} endpoints
              </span>
            </div>
            <table className="w-full text-sm">
              <thead className="bg-white border-b border-gray-100">
                <tr>
                  <th className="text-left px-4 py-2 text-[11px] font-semibold text-gray-500 uppercase tracking-wide w-2/5">
                    Endpoint
                  </th>
                  <th className="text-right px-4 py-2 text-[11px] font-semibold text-gray-500 uppercase tracking-wide w-24">
                    Value
                  </th>
                  <th className="text-left px-4 py-2 text-[11px] font-semibold text-gray-500 uppercase tracking-wide">
                    DrugBank Percentile
                  </th>
                </tr>
              </thead>
              <tbody>
                {group.endpoints.map((ep) => {
                  const rawValue = groupData[ep.key]
                  const percentile = lookupPercentile(ep.percentileKey, molecule.drugbank_percentiles)
                  return (
                    <tr key={ep.key} className="border-b border-gray-50 last:border-0 hover:bg-gray-50/50">
                      <td className="px-4 py-2.5">
                        <div className="text-sm text-gray-900">{ep.displayName}</div>
                        <div className="text-[10px] text-gray-500 mt-0.5">{ep.description}</div>
                      </td>
                      <td className="px-4 py-2.5 text-right font-mono text-sm text-gray-700 tabular-nums">
                        {formatValue(rawValue)}
                      </td>
                      <td className="px-4 py-2.5">
                        <PercentileBar percentile={percentile} direction={ep.direction} />
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )
      })}
    </div>
  )
}
