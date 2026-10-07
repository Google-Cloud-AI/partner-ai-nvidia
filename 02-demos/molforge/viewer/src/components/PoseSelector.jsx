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

export default function PoseSelector({ ligands, selectedIndices, onToggle }) {
  if (!ligands || ligands.length === 0) {
    return (
      <div className="bg-white border border-gray-200 rounded-xl p-4 text-xs text-gray-500 italic">
        No ligands in manifest.
      </div>
    )
  }

  return (
    <div className="bg-white border border-gray-200 rounded-xl p-4">
      <div className="text-[10px] font-semibold text-gray-500 uppercase tracking-wide mb-3">
        Ligands ({ligands.length})
      </div>
      <div className="space-y-2 max-h-[65vh] overflow-y-auto pr-1">
        {ligands.map((lig) => {
          const checked = selectedIndices.has(lig.lig_idx)
          return (
            <label
              key={lig.lig_idx}
              className={
                'flex items-start gap-2 p-2 rounded-lg border cursor-pointer text-xs ' +
                (checked
                  ? 'border-green-500 bg-green-50'
                  : 'border-gray-200 hover:border-gray-300')
              }
            >
              <input
                type="checkbox"
                checked={checked}
                onChange={() => onToggle(lig.lig_idx)}
                className="mt-0.5"
              />
              <div className="flex-1 min-w-0">
                <div className="font-mono text-[10px] text-gray-500">
                  lig{String(lig.lig_idx).padStart(3, '0')}
                </div>
                <div className="font-mono text-[11px] text-gray-800 break-all">
                  {lig.smiles}
                </div>
              </div>
            </label>
          )
        })}
      </div>
    </div>
  )
}
