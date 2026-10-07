# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# Stage 1: build the React frontend
#
# Pinned by digest: node:20-alpine is a moving tag. Dependencies here are
# already lockfile-pinned by `npm ci`, so the base image is the one input that
# could still change under a rebuild -- and a floating base is exactly what
# broke the ADMET service on 2026-09-03.
# To update: docker buildx imagetools inspect node:20-alpine, swap the digest,
# rebuild, and confirm the smoke test below still passes.
FROM node:20-alpine@sha256:fb4cd12c85ee03686f6af5362a0b0d56d50c58a04632e6c0fb8363f609372293 AS build
WORKDIR /app

# Install all deps (dev deps needed for vite build)
COPY package.json package-lock.json* ./
RUN npm ci --no-audit --no-fund

# Copy source and build
COPY . .
RUN npm run build

# Stage 2: runtime — node running Express that serves both API + built React
FROM node:20-alpine@sha256:fb4cd12c85ee03686f6af5362a0b0d56d50c58a04632e6c0fb8363f609372293 AS runtime
WORKDIR /app
ENV NODE_ENV=production

# Install ONLY production deps (smaller image)
COPY package.json package-lock.json* ./
RUN npm ci --omit=dev --no-audit --no-fund

# Copy Express server and built frontend
COPY server.js smoketest.mjs ./
COPY --from=build /app/dist ./dist

# Fail the BUILD, not production. Boots the real server on production-only
# deps and calls /api/health, and checks the vite build actually emitted a
# bundle -- a missing prod dependency or an empty dist otherwise ships an
# image that starts cleanly and serves a blank page. See smoketest.mjs.
RUN node smoketest.mjs

# Cloud Run conventions
EXPOSE 8080
ENV PORT=8080

CMD ["node", "server.js"]
