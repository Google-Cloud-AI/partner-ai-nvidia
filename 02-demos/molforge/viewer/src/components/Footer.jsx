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

export default function Footer() {
  return (
    <footer className="border-t border-gray-200 bg-gray-50 mt-12">
      <div className="max-w-6xl mx-auto px-6 py-4 text-[11px] text-gray-500 flex items-center justify-between">
        <div>
          MolForge Viewer · Agentic Drug Discovery · NVIDIA × Google Cloud Co-Innovation
        </div>
        <div className="text-gray-400">
          Schneider Larbi · Senior Manager, Partner Technical Architecture · Google Cloud
        </div>
      </div>
    </footer>
  )
}
