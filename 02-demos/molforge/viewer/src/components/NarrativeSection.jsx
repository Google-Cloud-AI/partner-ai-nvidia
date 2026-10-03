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
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

/**
 * Render a verbatim Nemotron narrative as markdown.
 *
 * Props:
 *   - narrative: the markdown string
 *   - title: header label (e.g. "Safety Assessment by NVIDIA Nemotron Nano VL")
 *   - provider: "NVIDIA" | "Google" (default "NVIDIA")
 *   - emptyHint: what to show if narrative is missing
 */
export default function NarrativeSection({
  narrative,
  title = 'Safety Assessment by NVIDIA Nemotron Nano VL',
  provider = 'NVIDIA',
  emptyHint,
}) {
  if (!narrative) {
    if (!emptyHint) return null
    return (
      <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4 text-sm text-yellow-800 mb-6">
        {emptyHint}
      </div>
    )
  }

  const isNvidia = provider === 'NVIDIA'
  const stripBg = isNvidia ? 'bg-nvidia-light' : 'bg-google-light'
  const stripBorder = isNvidia ? 'border-nvidia/20' : 'border-google/20'
  const textColor = isNvidia ? 'text-nvidia-dark' : 'text-google-dark'
  const dotColor = isNvidia ? 'bg-nvidia' : 'bg-google'

  return (
    <div className="bg-white border border-gray-200 rounded-xl overflow-hidden mb-6">
      <div className={`${stripBg} border-b ${stripBorder} px-5 py-3 flex items-center gap-2`}>
        <span className={`w-2 h-2 rounded-full ${dotColor}`}></span>
        <h2 className={`text-sm font-bold ${textColor} uppercase tracking-wide`}>{title}</h2>
      </div>
      <div className="px-6 py-5 markdown-body text-sm text-gray-800">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{narrative}</ReactMarkdown>
      </div>
    </div>
  )
}
