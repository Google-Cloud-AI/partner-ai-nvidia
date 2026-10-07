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
 * Single chat message — user or assistant.
 * Assistant messages render markdown for Nemotron narratives.
 */
export default function MessageBubble({ role, text, isLoading }) {
  if (role === 'user') {
    return (
      <div className="flex justify-end mb-6">
        <div className="max-w-[85%] bg-gray-900 text-white rounded-2xl rounded-br-md px-4 py-3 text-sm leading-relaxed">
          {text}
        </div>
      </div>
    )
  }

  return (
    <div className="flex justify-start mb-6">
      <div className="max-w-[90%] w-full">
        <div className="flex items-center gap-2 mb-2">
          <div className="w-6 h-6 rounded-full bg-gradient-to-br from-nvidia to-google flex items-center justify-center text-[10px] font-bold text-white">
            M
          </div>
          <span className="text-xs font-semibold text-gray-700">MolForge</span>
        </div>
        <div className="bg-gray-50 border border-gray-200 rounded-2xl rounded-tl-md px-5 py-4">
          {isLoading ? (
            <div className="flex items-center gap-2 text-sm text-gray-500">
              <div className="flex gap-1">
                <span className="w-1.5 h-1.5 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '0ms' }}></span>
                <span className="w-1.5 h-1.5 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '150ms' }}></span>
                <span className="w-1.5 h-1.5 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '300ms' }}></span>
              </div>
              <span>Thinking...</span>
            </div>
          ) : (
            <div className="markdown-body text-sm text-gray-800">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {text}
              </ReactMarkdown>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
