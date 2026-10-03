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

export default function HomePage() {
  return (
    <div className="max-w-3xl mx-auto px-6 py-16">
      <div className="text-center">
        <div className="inline-block w-16 h-16 rounded-full bg-gradient-to-br from-nvidia to-google flex items-center justify-center text-2xl font-bold text-white mb-4">
          M
        </div>
        <h1 className="text-3xl font-bold text-gray-900 mb-3">MolForge Viewer</h1>
        <p className="text-base text-gray-600 max-w-xl mx-auto leading-relaxed">
          Interactive 3D molecular structures, ADMET safety reports, and lead optimization galleries
          from MolForge — the agentic AI drug discovery platform powered by NVIDIA Nemotron and Google Cloud.
        </p>
      </div>

      <div className="mt-12 bg-gray-50 border border-gray-200 rounded-xl p-6">
        <h2 className="text-sm font-bold text-gray-900 uppercase tracking-wide mb-3">
          How to use this viewer
        </h2>
        <p className="text-sm text-gray-600 leading-relaxed mb-4">
          When MolForge agents return safety reports or optimization results, they include a viewer link
          that opens in this browser tab. The link contains a <code className="text-xs bg-white px-1.5 py-0.5 rounded border border-gray-200">run_id</code> identifying
          the run in Cloud Storage.
        </p>
        <ul className="text-sm text-gray-600 space-y-2">
          <li>
            <code className="text-xs bg-white px-1.5 py-0.5 rounded border border-gray-200">/admet?id=run_xxx</code> —
            ADMET safety report with all 41 endpoints, DrugBank percentile context, and the Nemotron Nano VL safety narrative
          </li>
          <li>
            <code className="text-xs bg-white px-1.5 py-0.5 rounded border border-gray-200">/protein?file=xxx.pdb</code> —
            Interactive 3D protein structure viewer with pLDDT confidence coloring from NVIDIA ESMFold
          </li>
          <li>
            <code className="text-xs bg-white px-1.5 py-0.5 rounded border border-gray-200">/gallery?id=opt_xxx</code> —
            Lead Optimizer candidate gallery with 2D structures, binding scores, and the Nemotron Super 49B SAR analysis
          </li>
          <li>
            <code className="text-xs bg-white px-1.5 py-0.5 rounded border border-gray-200">/docking?id=opt_xxx</code> —
            Interactive 3D protein-ligand docking pose viewer
          </li>
        </ul>
      </div>

      <div className="mt-8 bg-white border border-gray-200 rounded-xl p-6">
        <h2 className="text-sm font-bold text-gray-900 uppercase tracking-wide mb-3">
          For Gemini Enterprise users
        </h2>
        <p className="text-sm text-gray-600 leading-relaxed">
          Gemini Enterprise's security policy blocks rich content like 3D structures and large data tables
          from rendering inline in agent responses. This viewer is the bridge — MolForge agent responses
          contain clickable links that open here in a new tab, where the full interactive experience renders without restriction.
        </p>
      </div>
    </div>
  )
}
