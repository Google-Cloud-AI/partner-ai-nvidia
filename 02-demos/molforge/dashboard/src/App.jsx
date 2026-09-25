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

import React, { useState, useEffect, useCallback } from 'react'
import Header from './components/Header.jsx'
import InternalOrchestra from './components/InternalOrchestra.jsx'
import ExternalA2A from './components/ExternalA2A.jsx'
import ChatColumn from './components/ChatColumn.jsx'
import WarmupBar from './components/WarmupBar.jsx'
import InputBar from './components/InputBar.jsx'
import { sendMessage, probeAllServices, probeService } from './api.js'

/**
 * MolForge Dashboard — Phase 4 (real warmup wired).
 */

const INITIAL_SERVICES = [
  { name: 'genmol', label: 'GenMol', status: 'unknown' },
  { name: 'diffdock', label: 'DiffDock', status: 'unknown' },
  { name: 'esmfold', label: 'ESMFold', status: 'unknown' },
  { name: 'rdkit', label: 'RDKit', status: 'unknown' },
  { name: 'admet', label: 'ADMET-AI', status: 'unknown' },
  { name: 'data', label: 'Data Retrieval', status: 'unknown' },
]

const EXAMPLE_PROMPTS = [
  {
    label: 'Screen aspirin (ADMET)',
    prompt:
      'Screen aspirin SMILES CC(=O)Oc1ccccc1C(=O)O for ADMET safety in cardiovascular indication. One molecule, quick test.',
  },
  {
    label: 'Optimize Imatinib',
    prompt:
      'Optimize the lead compound Imatinib (SMILES: CC1=C(C=C(C=C1)NC(=O)C2=CC=C(C=C2)CN3CCN(CC3)C)NC4=NC=CC(=N4)C5=CN=CC=C5) for the BCR-ABL kinase target. Therapeutic area: oncology. Generate 10 variants. No structure available — proceed without docking.',
  },
]

export default function App() {
  const [messages, setMessages] = useState([])
  const [timeline, setTimeline] = useState([])
  const [interactions, setInteractions] = useState([])
  const [services, setServices] = useState(INITIAL_SERVICES)
  const [contextId, setContextId] = useState(null)
  const [isLoading, setIsLoading] = useState(false)

  // Initial warmup probe on mount + every 60s
  const refreshAllServices = useCallback(async () => {
    try {
      const data = await probeAllServices()
      const merged = INITIAL_SERVICES.map((s) => {
        const found = data.services.find((d) => d.name === s.name)
        return found ? { ...s, ...found } : s
      })
      setServices(merged)
    } catch (err) {
      console.error('Warmup probe failed:', err)
    }
  }, [])

  useEffect(() => {
    refreshAllServices()
    const interval = setInterval(refreshAllServices, 60000)
    return () => clearInterval(interval)
  }, [refreshAllServices])

  const handleSend = async (text) => {
    setMessages((prev) => [...prev, { role: 'user', text }])
    setIsLoading(true)

    try {
      const result = await sendMessage(text, contextId)

      if (result.contextId && !contextId) {
        setContextId(result.contextId)
      }

      setMessages((prev) => [
        ...prev,
        { role: 'assistant', text: result.text || '(empty response)' },
      ])

      setTimeline(result.timeline)
    } catch (err) {
      console.error(err)
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          text: `**Error reaching MolForge A2A**\n\n\`${err.message}\`\n\nCheck that the A2A server is running and your network can reach it.`,
        },
      ])
    } finally {
      setIsLoading(false)
    }
  }

  const handleWarmup = async (svcName) => {
    // Mark this service as 'warming' immediately for UI feedback
    setServices((prev) =>
      prev.map((s) => (s.name === svcName ? { ...s, status: 'warming' } : s))
    )
    try {
      const result = await probeService(svcName)
      setServices((prev) =>
        prev.map((s) => (s.name === svcName ? { ...s, ...result } : s))
      )
    } catch (err) {
      console.error('Per-service probe failed:', err)
      setServices((prev) =>
        prev.map((s) => (s.name === svcName ? { ...s, status: 'unhealthy' } : s))
      )
    }
  }

  return (
    <div className="h-screen w-screen flex flex-col bg-white overflow-hidden">
      <Header />

      <div className="flex-1 flex overflow-hidden">
        <InternalOrchestra timeline={timeline} />
        <ChatColumn messages={messages} isLoading={isLoading} />
        <ExternalA2A interactions={interactions} />
      </div>

      <WarmupBar services={services} onWarmup={handleWarmup} />
      <InputBar
        onSend={handleSend}
        isLoading={isLoading}
        examplePrompts={EXAMPLE_PROMPTS}
      />
    </div>
  )
}
