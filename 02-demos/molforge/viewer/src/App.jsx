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
import { Routes, Route } from 'react-router-dom'
import Header from './components/Header.jsx'
import Footer from './components/Footer.jsx'
import HomePage from './pages/HomePage.jsx'
import AdmetPage from './pages/AdmetPage.jsx'
import GalleryPage from './pages/GalleryPage.jsx'
import DockingPage from './pages/DockingPage.jsx'
import ProteinPage from './pages/ProteinPage.jsx'

export default function App() {
  return (
    <div className="min-h-screen flex flex-col bg-white">
      <Header />
      <main className="flex-1">
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/admet" element={<AdmetPage />} />
          <Route path="/gallery" element={<GalleryPage />} />
          <Route path="/docking" element={<DockingPage />} />
          <Route path="/protein" element={<ProteinPage />} />
          <Route
            path="*"
            element={
              <div className="max-w-2xl mx-auto px-6 py-20 text-center">
                <h1 className="text-2xl font-bold text-gray-900 mb-2">Page not found</h1>
                <p className="text-sm text-gray-500">
                  The page you're looking for doesn't exist in the MolForge Viewer.
                </p>
              </div>
            }
          />
        </Routes>
      </main>
      <Footer />
    </div>
  )
}
