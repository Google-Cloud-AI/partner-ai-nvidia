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
 * Infrastructure Warm-Up Panel — GKE service health pills above the input bar.
 * Click a pill to wake up its service before a demo.
 */
export default function WarmupBar({ services, onWarmup }) {
  return (
    <div className="border-t border-gray-200 bg-gray-50 px-6 py-2">
      <div className="max-w-5xl mx-auto flex items-center gap-3">
        <span className="text-[11px] font-semibold text-gray-500 uppercase tracking-wide">
          Infrastructure
        </span>
        <div className="flex items-center gap-2 flex-wrap">
          {services.map((svc) => {
            const statusColor =
              svc.status === 'healthy' ? 'bg-nvidia' :
              svc.status === 'warming' ? 'bg-yellow-400' :
              svc.status === 'cold' ? 'bg-gray-300' :
              'bg-red-400'
            return (
              <button
                key={svc.name}
                onClick={() => onWarmup?.(svc.name)}
                className="flex items-center gap-1.5 px-2.5 py-1 bg-white border border-gray-200 rounded-full text-[11px] font-medium text-gray-700 hover:border-gray-300 hover:bg-gray-50 transition"
              >
                <span className={`w-1.5 h-1.5 rounded-full ${statusColor}`}></span>
                {svc.label}
              </button>
            )
          })}
        </div>
      </div>
    </div>
  )
}
