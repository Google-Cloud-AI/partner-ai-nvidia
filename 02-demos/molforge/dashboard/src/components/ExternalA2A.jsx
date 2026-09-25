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
 * Right sidebar — External A2A Interactions.
 * Will show inbound/outbound exchanges with peer systems like PharmaPilot.
 * Empty state for now — populated once PharmaPilot is online.
 */
export default function ExternalA2A({ interactions }) {
  return (
    <aside className="w-72 border-l border-gray-200 flex flex-col bg-white">
      <div className="px-4 py-3 border-b border-gray-200">
        <h2 className="text-sm font-semibold text-gray-900">External A2A Interactions</h2>
        <p className="text-xs text-gray-500 mt-0.5">Peer system exchanges</p>
      </div>

      <div className="flex-1 overflow-y-auto px-3 py-3">
        {interactions.length === 0 ? (
          <div className="text-xs text-gray-400 italic text-center py-8 px-2 leading-relaxed">
            No external A2A exchanges yet.
            <br /><br />
            PharmaPilot and other peer systems will appear here when connected.
          </div>
        ) : (
          interactions.map((ix, i) => (
            <div key={i} className="border border-gray-200 rounded p-2 mb-2">
              <div className="text-[10px] font-semibold text-gray-500 uppercase">
                {ix.direction === 'outbound' ? '→ outbound' : '← inbound'}
              </div>
              <div className="text-xs font-medium text-gray-800 mt-1">{ix.peer}</div>
              <div className="text-[11px] text-gray-600 mt-1 line-clamp-3">{ix.summary}</div>
            </div>
          ))
        )}
      </div>
    </aside>
  )
}
