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

/**
 * MoleculeViewer3D — wraps 3Dmol.js (loaded via CDN in index.html).
 *
 * Props:
 *   pdbText    — protein PDB as a string (required)
 *   sdfTexts   — array of SDF strings for ligands to overlay (optional)
 *   colorMode  — 'spectrum' (pLDDT from b-factor, ESMFold case) or 'chain' (default)
 *   height     — CSS height for the viewer div (default '70vh')
 *
 * Waits for window.$3Dmol to be defined (CDN async load).
 */
export default function MoleculeViewer3D({
  pdbText,
  sdfTexts = [],
  colorMode = 'chain',
  height = '70vh',
}) {
  const containerRef = useRef(null)
  const viewerRef = useRef(null)

  useEffect(() => {
    if (!containerRef.current || !pdbText) return

    let cancelled = false
    let pollCount = 0

    const init = () => {
      if (cancelled) return
      if (!window.$3Dmol) {
        if (pollCount++ < 50) {
          setTimeout(init, 100)
          return
        }
        console.error('3Dmol.js failed to load from CDN after 5s')
        return
      }

      if (viewerRef.current) {
        try { viewerRef.current.clear() } catch {}
      }
      containerRef.current.innerHTML = ''

      const viewer = window.$3Dmol.createViewer(containerRef.current, {
        backgroundColor: '#0f1115',
        antialias: true,
      })
      viewerRef.current = viewer

      // Protein model (index 0)
      viewer.addModel(pdbText, 'pdb')

      if (colorMode === 'spectrum') {
        // pLDDT from b-factor: 50 (red) → 70 (yellow) → 90 (green) → 100 (blue)
        viewer.setStyle(
          {},
          {
            cartoon: {
              colorscheme: { prop: 'b', gradient: 'roygb', min: 50, max: 100 },
            },
          }
        )
      } else {
        viewer.setStyle({}, { cartoon: { color: 'spectrum' } })
      }

      // Ligand models (indices 1..N)
      sdfTexts.forEach((sdf) => {
        if (sdf) viewer.addModel(sdf, 'sdf')
      })
      for (let i = 1; i <= sdfTexts.length; i++) {
        viewer.setStyle(
          { model: i },
          { stick: { radius: 0.2 }, sphere: { scale: 0.25 } }
        )
      }

      viewer.zoomTo()
      viewer.spin('y', 0.5)
      viewer.render()
    }

    init()

    return () => {
      cancelled = true
      if (viewerRef.current) {
        try { viewerRef.current.clear() } catch {}
      }
    }
  }, [pdbText, sdfTexts, colorMode])

  return (
    <div
      ref={containerRef}
      className="relative w-full rounded-xl border border-gray-800 overflow-hidden"
      style={{ height }}
    />
  )
}
