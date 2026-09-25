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

import React, { useState } from 'react'

/**
 * Bottom-pinned input bar. Multi-turn — sends the current text to the parent.
 * Enter sends, Shift+Enter inserts newline.
 */
export default function InputBar({ onSend, isLoading, examplePrompts }) {
  const [text, setText] = useState('')

  const handleSend = () => {
    const trimmed = text.trim()
    if (!trimmed || isLoading) return
    onSend(trimmed)
    setText('')
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  return (
    <div className="border-t border-gray-200 bg-white px-6 py-4">
      <div className="max-w-3xl mx-auto">
        {examplePrompts && examplePrompts.length > 0 && (
          <div className="flex flex-wrap gap-2 mb-3">
            {examplePrompts.map((p, i) => (
              <button
                key={i}
                onClick={() => setText(p.prompt)}
                disabled={isLoading}
                className="text-[11px] px-2.5 py-1 bg-gray-100 hover:bg-gray-200 border border-gray-200 rounded-full text-gray-700 disabled:opacity-50"
              >
                {p.label}
              </button>
            ))}
          </div>
        )}

        <div className="flex items-end gap-2">
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Message MolForge..."
            rows={2}
            disabled={isLoading}
            className="flex-1 resize-none border border-gray-300 rounded-xl px-4 py-3 text-sm text-gray-900 placeholder-gray-400 focus:outline-none focus:border-gray-900 focus:ring-1 focus:ring-gray-900 disabled:bg-gray-50"
          />
          <button
            onClick={handleSend}
            disabled={!text.trim() || isLoading}
            className="px-4 py-3 bg-gray-900 text-white rounded-xl text-sm font-semibold hover:bg-gray-800 disabled:bg-gray-300 disabled:cursor-not-allowed transition"
          >
            Send
          </button>
        </div>
        <div className="text-[10px] text-gray-400 mt-2 text-center">
          MolForge orchestrates Gemini and NVIDIA Nemotron on Google Cloud. Press Enter to send, Shift+Enter for newline.
        </div>
      </div>
    </div>
  )
}
