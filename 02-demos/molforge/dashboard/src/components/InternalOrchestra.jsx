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
import TimelineEntry from './TimelineEntry.jsx'

/**
 * Left sidebar — Internal Agent Orchestra.
 * Shows the timeline of agent activity color-coded by provider.
 */
export default function InternalOrchestra({ timeline }) {
  const nvidiaCount = timeline.filter(e => e.provider === 'NVIDIA').length
  const googleCount = timeline.filter(e => e.provider === 'Google').length

  return (
    <aside className="w-72 border-r border-gray-200 flex flex-col bg-white">
      <div className="px-4 py-3 border-b border-gray-200">
        <h2 className="text-sm font-semibold text-gray-900">Internal Agent Orchestra</h2>
        <p className="text-xs text-gray-500 mt-0.5">Live agent + model activity</p>
        <div className="flex items-center gap-3 mt-2 text-[11px]">
          <span className="flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-nvidia"></span>
            <span className="text-gray-600">{nvidiaCount} NVIDIA</span>
          </span>
          <span className="flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-google"></span>
            <span className="text-gray-600">{googleCount} Google</span>
          </span>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-3 py-3">
        {timeline.length === 0 ? (
          <div className="text-xs text-gray-400 italic text-center py-8">
            No activity yet. Send a message to begin.
          </div>
        ) : (
          timeline.map((entry, i) => <TimelineEntry key={i} entry={entry} />)
        )}
      </div>
    </aside>
  )
}
