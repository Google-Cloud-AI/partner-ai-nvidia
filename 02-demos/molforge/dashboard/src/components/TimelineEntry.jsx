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
 * Single timeline entry in the Internal Agent Orchestra.
 * Color-coded by provider: NVIDIA green, Google blue.
 */
export default function TimelineEntry({ entry }) {
  const isNvidia = entry.provider === 'NVIDIA'
  const isGoogle = entry.provider === 'Google'

  const accent = isNvidia
    ? 'border-l-nvidia bg-nvidia-light/40'
    : isGoogle
    ? 'border-l-google bg-google-light/40'
    : 'border-l-gray-300 bg-gray-50'

  const badgeStyle = isNvidia
    ? 'bg-nvidia text-white'
    : isGoogle
    ? 'bg-google text-white'
    : 'bg-gray-400 text-white'

  const kindLabel = {
    tool_call: 'tool call',
    tool_response: 'response',
    sub_agent_model: 'model',
    model_text: 'thought',
    error: 'error',
  }[entry.kind] || entry.kind

  return (
    <div className={`border-l-4 ${accent} pl-3 pr-2 py-2 mb-2 rounded-r`}>
      <div className="flex items-center gap-2 mb-1">
        <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded uppercase tracking-wide ${badgeStyle}`}>
          {entry.provider}
        </span>
        <span className="text-[10px] text-gray-500 uppercase tracking-wide font-medium">
          {kindLabel}
        </span>
      </div>
      {entry.name && (
        <div className="text-xs font-semibold text-gray-800 mb-0.5 truncate">
          {entry.name}
        </div>
      )}
      {entry.model && (
        <div className="text-[10px] font-mono text-gray-500 truncate">
          {entry.model}
        </div>
      )}
      {entry.sub_agent && entry.kind === 'tool_response' && (
        <div className="text-[10px] text-gray-500 truncate">
          → {entry.sub_agent}
        </div>
      )}
      {entry.summary && (
        <div className="text-[11px] text-gray-700 mt-1 leading-snug line-clamp-3">
          {entry.summary}
        </div>
      )}
    </div>
  )
}
