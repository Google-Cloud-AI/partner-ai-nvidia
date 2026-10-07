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

# Pinned by digest. This is the image whose floating base took ADMET down on
# 2026-09-03: an untouched Dockerfile rebuilt into a python:3.12-slim that had
# silently dropped its expat package. Pinning the Python deps below was only
# half the fix -- the base itself is an input.
# This digest is the same python:3.12-slim that built the currently-serving
# revision (admet-ai-00004-fzv), so pinning it changes nothing about what runs
# today; it stops the next rebuild from drifting.
# To update: docker buildx imagetools inspect python:3.12-slim, swap the
# digest, rebuild, and confirm the smoke test below still passes.
FROM python:3.12-slim@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea

WORKDIR /app

# libexpat1: chemprop >=2.3 imports cuik_molmaker, a native extension linking
# libexpat.so.1. python:3.12-slim carries no expat package at all, so without
# this the image builds, starts, and passes /health -- then every /predict
# returns 500 on the lazy model load. That is exactly how a broken revision
# took 100% of traffic on 2026-09-03.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libxrender1 libxext6 libexpat1 \
    && rm -rf /var/lib/apt/lists/*

# PIN EVERYTHING. This image was previously unpinned on both the base tag and
# the Python deps, so an untouched Dockerfile rebuilt months later produced a
# materially different image -- newer chemprop had picked up the cuik_molmaker
# dependency above. Bump these deliberately, and re-run the build-time smoke
# test below when you do.
RUN pip install --no-cache-dir \
    fastapi==0.141.1 \
    uvicorn==0.52.4 \
    admet-ai==2.0.1

# Fail the BUILD, not production. /health does not touch the model (it loads
# lazily on first predict), so a container that cannot serve still goes ready
# and Cloud Run routes to it. Exercising a real prediction here is what makes
# the missing-shared-library class of failure impossible to ship.
RUN python -c "\
from admet_ai import ADMETModel; \
p = ADMETModel().predict(smiles='CC(=O)Oc1ccccc1C(=O)O'); \
assert len(p) > 50, f'smoke test: only {len(p)} predictions'; \
print(f'smoke test OK: {len(p)} predictions')"

COPY app.py .

EXPOSE 8080

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
