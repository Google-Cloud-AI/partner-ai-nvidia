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
import { Link } from 'react-router-dom'

export default function ErrorState({ title = 'Could not load run', message, runId }) {
  return (
    <div className="max-w-lg mx-auto py-20 text-center">
      <div className="w-12 h-12 rounded-full bg-red-50 border-2 border-red-200 flex items-center justify-center mx-auto mb-4">
        <span className="text-2xl text-red-500">!</span>
      </div>
      <h2 className="text-lg font-bold text-gray-900 mb-2">{title}</h2>
      {runId && (
        <p className="text-xs text-gray-500 font-mono mb-2">run_id: {runId}</p>
      )}
      <p className="text-sm text-gray-600 mb-6">{message}</p>
      <Link
        to="/"
        className="inline-block px-4 py-2 bg-gray-900 text-white text-sm font-semibold rounded-lg hover:bg-gray-800 transition"
      >
        Back to MolForge Viewer
      </Link>
    </div>
  )
}
