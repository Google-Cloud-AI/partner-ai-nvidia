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

import React, { useState } from 'react'
import MoleculeStructure2D from './MoleculeStructure2D.jsx'

/**
 * Compact card for a single Lead Optimizer candidate.
 *
 * Shows:
 *   - Rank badge
 *   - 2D structure (RDKit-JS)
 *   - SMILES (code label, truncated if long)
 *   - 6 key drug-likeness properties
 *   - Lipinski pass/fail pill
 *   - Expandable "Show all properties" toggle revealing all 12 fields
 */

const KEY_PROPERTIES = [
  { key: 'molecular_weight', label: 'MW', format: (v) => v?.toFixed?.(1) ?? '—', unit: 'g/mol' },
  { key: 'logp', label: 'LogP', format: (v) => v?.toFixed?.(2) ?? '—', unit: '' },
  { key: 'hbd', label: 'HBD', format: (v) => v ?? '—', unit: '' },
  { key: 'hba', label: 'HBA', format: (v) => v ?? '—', unit: '' },
  { key: 'qed', label: 'QED', format: (v) => v?.toFixed?.(3) ?? '—', unit: '' },
  { key: 'tpsa', label: 'TPSA', format: (v) => v?.toFixed?.(1) ?? '—', unit: 'Å²' },
]

// Keys that are shown in the "always visible" KEY_PROPERTIES grid above
const KEY_PROPERTY_KEYS = new Set(KEY_PROPERTIES.map((p) => p.key))

// Keys to hide from the expanded view — SMILES is already shown as the card label
const HIDDEN_EXPANDED_KEYS = new Set(['smiles'])

function formatAnyValue(v) {
  if (v === null || v === undefined) return '—'
  if (typeof v === 'boolean') return v ? 'Yes' : 'No'
  if (typeof v === 'number') {
    if (Number.isInteger(v)) return String(v)
    if (Math.abs(v) >= 100) return v.toFixed(1)
    if (Math.abs(v) >= 1) return v.toFixed(3)
    return v.toFixed(4)
  }
  return String(v)
}

export default function CandidateCard({ candidate, rank }) {
  const [expanded, setExpanded] = useState(false)

  const smiles = candidate.smiles
  const props = candidate.properties || {}

  // Lipinski pass/fail — derive from violations or pass field
  const lipinskiPass =
    props.lipinski_pass === true ||
    props.lipinski_violations === 0 ||
    (typeof props.lipinski_violations === 'number' && props.lipinski_violations === 0)
  const lipinskiKnown =
    props.lipinski_pass !== undefined || props.lipinski_violations !== undefined

  // Extra properties = everything in `properties` not in KEY_PROPERTY_KEYS and not hidden
  const extraProperties = Object.entries(props).filter(
    ([k]) => !KEY_PROPERTY_KEYS.has(k) && !HIDDEN_EXPANDED_KEYS.has(k)
  )

  return (
    <div className="bg-white border border-gray-200 rounded-xl overflow-hidden hover:shadow-md transition-shadow">
      {/* Header strip with rank */}
      <div className="flex items-center gap-3 px-5 py-3 bg-gradient-to-r from-gray-50 to-white border-b border-gray-100">
        <div className="w-8 h-8 rounded-full bg-gray-900 text-white text-sm font-bold flex items-center justify-center flex-shrink-0">
          {rank}
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-[10px] font-semibold text-gray-500 uppercase tracking-wide">
            Candidate {rank}
          </div>
          <div className="text-[11px] font-mono text-gray-600 truncate" title={smiles}>
            {smiles}
          </div>
        </div>
        {lipinskiKnown && (
          <div
            className={`flex-shrink-0 text-[10px] font-bold px-2 py-1 rounded-full ${
              lipinskiPass
                ? 'bg-nvidia-light text-nvidia-dark'
                : 'bg-red-50 text-red-700'
            }`}
          >
            {lipinskiPass ? 'LIPINSKI ✓' : 'LIPINSKI ✗'}
          </div>
        )}
      </div>

      {/* Body: structure + properties side by side */}
      <div className="p-5">
        <div className="flex flex-col sm:flex-row gap-5">
          {/* 2D structure */}
          <div className="flex-shrink-0">
            <MoleculeStructure2D smiles={smiles} width={220} height={180} />
          </div>

          {/* Key properties grid */}
          <div className="flex-1 min-w-0">
            <div className="text-[10px] font-semibold text-gray-500 uppercase tracking-wide mb-2">
              Key Properties
            </div>
            <div className="grid grid-cols-3 gap-x-4 gap-y-2">
              {KEY_PROPERTIES.map((p) => (
                <div key={p.key}>
                  <div className="text-[10px] text-gray-500">{p.label}</div>
                  <div className="text-sm font-mono text-gray-900 tabular-nums">
                    {p.format(props[p.key])}
                    {p.unit && <span className="text-[10px] text-gray-400 ml-0.5">{p.unit}</span>}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Expand / collapse toggle */}
        {extraProperties.length > 0 && (
          <div className="mt-4 pt-4 border-t border-gray-100">
            <button
              onClick={() => setExpanded(!expanded)}
              className="text-[11px] font-semibold text-gray-600 hover:text-gray-900 uppercase tracking-wide flex items-center gap-1"
            >
              {expanded ? '▾ Hide' : '▸ Show'} all {Object.keys(props).length - HIDDEN_EXPANDED_KEYS.size} properties
            </button>

            {expanded && (
              <div className="mt-3 grid grid-cols-2 sm:grid-cols-3 gap-x-4 gap-y-2">
                {extraProperties.map(([k, v]) => (
                  <div key={k} className="flex items-baseline justify-between border-b border-gray-50 pb-1">
                    <span className="text-[10px] text-gray-500">{k}</span>
                    <span className="font-mono text-xs text-gray-800 tabular-nums">
                      {formatAnyValue(v)}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
