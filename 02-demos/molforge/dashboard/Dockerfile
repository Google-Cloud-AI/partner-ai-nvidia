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

# Stage 1: build
#
# Pinned by digest: node:20-alpine is a moving tag. Dependencies here are
# already lockfile-pinned by `npm ci`, so the base image is the one input that
# could still change under a rebuild -- and a floating base is exactly what
# broke the ADMET service on 2026-09-03.
# To update: docker buildx imagetools inspect node:20-alpine, swap the digest,
# rebuild, and confirm the smoke test below still passes.
FROM node:20-alpine@sha256:fb4cd12c85ee03686f6af5362a0b0d56d50c58a04632e6c0fb8363f609372293 AS build
WORKDIR /app

# Install deps first (cached layer)
COPY package.json package-lock.json* ./
RUN npm ci --no-audit --no-fund

# Copy source and build
COPY . .

# The bridge URL is baked into the bundle at BUILD time -- Vite substitutes
# import.meta.env.* during `npm run build`, so this cannot be a Cloud Run
# runtime env var on a static nginx container. setup.sh used to pass
# VITE_A2A_URL with `gcloud run deploy --set-env-vars`, which reached nothing:
# the deployed dashboard kept whatever URL the bundle was built with.
ARG VITE_A2A_URL
ENV VITE_A2A_URL=${VITE_A2A_URL}
RUN test -n "${VITE_A2A_URL}" \
    || (echo "build arg VITE_A2A_URL is required: --build-arg VITE_A2A_URL=https://<your-bridge>.run.app" >&2; exit 1)
RUN npm run build

# Stage 2: serve
# Pinned by digest for the same reason as the build stage above.
# To update: docker buildx imagetools inspect nginx:alpine.
FROM nginx:alpine@sha256:a9ae6f6d078d477e21323310498e5196cb2b7c0aedd9e07b7306612077227d7c

# Custom nginx config for Cloud Run (port 8080) + SPA fallback
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Copy built assets
COPY --from=build /app/dist /usr/share/nginx/html

# Fail the BUILD, not production. `nginx -t` catches a config that a newer
# nginx no longer accepts (the container would crash-loop on start instead),
# and the asset checks catch a vite build that emitted an empty shell -- which
# would serve a blank page while passing every health check.
#
# The VITE_A2A_URL grep is the one that would have caught the real bug: the
# bundle silently keeping a stale bridge URL because the value was supplied as a
# runtime env var Vite never saw. Asserting the string is actually IN the built
# JS is the only way to prove the substitution happened.
ARG VITE_A2A_URL
RUN nginx -t \
    && test -s /usr/share/nginx/html/index.html \
    && grep -q '/assets/' /usr/share/nginx/html/index.html \
    && ls /usr/share/nginx/html/assets/*.js >/dev/null \
    && grep -rqF "${VITE_A2A_URL}" /usr/share/nginx/html/assets/ \
    && echo "smoke test OK: nginx config valid, dist has index.html + JS bundle baked against ${VITE_A2A_URL}"

EXPOSE 8080
CMD ["nginx", "-g", "daemon off;"]
