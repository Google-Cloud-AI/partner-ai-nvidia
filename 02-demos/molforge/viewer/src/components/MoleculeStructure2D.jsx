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

import React, { useEffect, useState } from 'react'
import { useRDKit } from '../lib/rdkit.js'

/**
 * Render a SMILES string as a 2D molecular structure SVG using RDKit-JS.
 * Falls back to a placeholder if RDKit is loading or the SMILES is invalid.
 */
export default function MoleculeStructure2D({ smiles, width = 400, height = 300 }) {
  const { rdkit, loading, error } = useRDKit()
  const [svg, setSvg] = useState(null)
  const [parseError, setParseError] = useState(null)

  useEffect(() => {
    if (!rdkit || !smiles) return
    try {
      const mol = rdkit.get_mol(smiles)
      if (!mol || !mol.is_valid()) {
        setParseError(`Invalid SMILES: ${smiles}`)
        if (mol) mol.delete()
        return
      }
      const svgString = mol.get_svg(width, height)
      setSvg(svgString)
      mol.delete()
      setParseError(null)
    } catch (err) {
      setParseError(`RDKit error: ${err.message}`)
    }
  }, [rdkit, smiles, width, height])

  if (loading) {
    return (
      <div
        style={{ width, height }}
        className="flex items-center justify-center bg-gray-50 border border-gray-200 rounded text-xs text-gray-400"
      >
        Loading RDKit…
      </div>
    )
  }

  if (error) {
    return (
      <div
        style={{ width, height }}
        className="flex items-center justify-center bg-red-50 border border-red-200 rounded text-xs text-red-600 p-2 text-center"
      >
        RDKit failed to load: {error.message}
      </div>
    )
  }

  if (parseError) {
    return (
      <div
        style={{ width, height }}
        className="flex items-center justify-center bg-yellow-50 border border-yellow-200 rounded text-xs text-yellow-700 p-2 text-center"
      >
        {parseError}
      </div>
    )
  }

  if (!svg) {
    return <div style={{ width, height }} className="bg-gray-50 border border-gray-200 rounded" />
  }

  return (
    <div
      className="bg-white border border-gray-200 rounded overflow-hidden flex items-center justify-center"
      style={{ width, height }}
      dangerouslySetInnerHTML={{ __html: svg }}
    />
  )
}
