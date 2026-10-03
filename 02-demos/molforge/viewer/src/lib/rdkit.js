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

/**
 * RDKit-JS loader hook.
 *
 * RDKit-JS is loaded as a global script tag from CDN in index.html.
 * window.initRDKitModule() returns a promise resolving to an RDKit instance.
 * We cache the instance globally so multiple components share the same load.
 */
import { useEffect, useState } from 'react'

let rdkitPromise = null

export function loadRDKit() {
  if (rdkitPromise) return rdkitPromise
  rdkitPromise = new Promise((resolve, reject) => {
    if (typeof window === 'undefined') {
      reject(new Error('window is undefined'))
      return
    }
    const tryLoad = (attemptsLeft) => {
      if (window.initRDKitModule) {
        window
          .initRDKitModule()
          .then((rdkit) => resolve(rdkit))
          .catch((err) => reject(err))
        return
      }
      if (attemptsLeft <= 0) {
        reject(new Error('RDKit-JS failed to load from CDN within timeout'))
        return
      }
      setTimeout(() => tryLoad(attemptsLeft - 1), 200)
    }
    tryLoad(100) // 20 seconds max
  })
  return rdkitPromise
}

export function useRDKit() {
  const [rdkit, setRdkit] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    let cancelled = false
    loadRDKit()
      .then((instance) => {
        if (!cancelled) setRdkit(instance)
      })
      .catch((err) => {
        if (!cancelled) setError(err)
      })
    return () => {
      cancelled = true
    }
  }, [])

  return { rdkit, error, loading: !rdkit && !error }
}
