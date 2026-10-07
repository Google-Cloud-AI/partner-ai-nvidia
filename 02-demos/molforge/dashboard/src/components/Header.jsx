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

export default function Header() {
  return (
    <header className="border-b border-gray-200 bg-white px-6 py-3 flex items-center justify-between">
      <div className="flex items-center gap-3">
        <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-nvidia to-google flex items-center justify-center text-sm font-bold text-white">
          M
        </div>
        <div>
          <h1 className="text-base font-bold text-gray-900 leading-tight">MolForge</h1>
          <p className="text-[10px] text-gray-500 leading-tight">Agentic Drug Discovery</p>
        </div>
      </div>

      <div className="flex items-center gap-2">
        <div className="flex items-center gap-1.5 px-2.5 py-1 bg-nvidia-light border border-nvidia/30 rounded-full">
          <span className="w-1.5 h-1.5 rounded-full bg-nvidia"></span>
          <span className="text-[11px] font-semibold text-nvidia-dark">NVIDIA Nemotron</span>
        </div>
        <div className="flex items-center gap-1.5 px-2.5 py-1 bg-google-light border border-google/30 rounded-full">
          <span className="w-1.5 h-1.5 rounded-full bg-google"></span>
          <span className="text-[11px] font-semibold text-google-dark">Google Cloud</span>
        </div>
      </div>
    </header>
  )
}
