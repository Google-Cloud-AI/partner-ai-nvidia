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

import React, { useEffect, useRef } from 'react'
import MessageBubble from './MessageBubble.jsx'

/**
 * Scrolling chat column — newest messages at the bottom.
 * Auto-scrolls into view when new messages arrive.
 */
export default function ChatColumn({ messages, isLoading }) {
  const bottomRef = useRef(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [messages, isLoading])

  return (
    <div className="flex-1 overflow-y-auto chat-scroll bg-white">
      <div className="max-w-3xl mx-auto px-6 py-8">
        {messages.length === 0 && !isLoading && (
          <div className="text-center mt-16">
            <div className="inline-block w-16 h-16 rounded-full bg-gradient-to-br from-nvidia to-google flex items-center justify-center text-2xl font-bold text-white mb-4">
              M
            </div>
            <h1 className="text-2xl font-bold text-gray-900 mb-2">MolForge</h1>
            <p className="text-sm text-gray-500 max-w-md mx-auto">
              Agentic AI drug discovery platform. Powered by NVIDIA Nemotron and Google Cloud.
              Ask MolForge to optimize a lead compound or screen molecules for ADMET safety.
            </p>
          </div>
        )}

        {messages.map((msg, i) => (
          <MessageBubble key={i} role={msg.role} text={msg.text} />
        ))}

        {isLoading && <MessageBubble role="assistant" text="" isLoading={true} />}

        <div ref={bottomRef} />
      </div>
    </div>
  )
}
