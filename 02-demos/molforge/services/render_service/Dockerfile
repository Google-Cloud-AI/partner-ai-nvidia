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

# MolForge Render Service — CPU, Cloud Run. Matplotlib-fallback image; the
# deployed service is built from Dockerfile.pymol (ray-traced).
#
# Pinned by digest: python:3.12-slim is a moving tag. The image behind it
# silently dropped its expat package, which is half of why an untouched
# ADMET Dockerfile rebuilt into a broken container on 2026-09-03.
# To update: docker buildx imagetools inspect python:3.12-slim, swap the
# digest, rebuild, and confirm the smoke test below still passes.
FROM python:3.12-slim@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea

# RDKit Cairo drawing (rdMolDraw2D) needs these system libs on slim images.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libxrender1 libxext6 libexpat1 libcairo2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py mol3d.py smoketest.py ./

# Fail the BUILD, not production. RDKit's Cairo drawing and the matplotlib 3D
# path both depend on system libs installed above; a missing one otherwise
# surfaces as a broken image long after /health has gone green. This image has
# no PyMOL by design, so the expected renderer is the matplotlib fallback.
RUN python smoketest.py matplotlib \
    && python -c "\
from rdkit import Chem; \
from rdkit.Chem.Draw import rdMolDraw2D; \
m = Chem.MolFromSmiles('CC(=O)Oc1ccccc1C(=O)O'); \
d = rdMolDraw2D.MolDraw2DCairo(200, 200); \
rdMolDraw2D.PrepareAndDrawMolecule(d, m); \
d.FinishDrawing(); \
assert d.GetDrawingText(), 'smoke test: Cairo produced no 2D image'; \
print('smoke test OK: RDKit Cairo 2D drawing works')"

ENV PORT=8080
# Default image: 2D (RDKit) + 3D matplotlib fallback. For ray-traced 3D, build
# with Dockerfile.pymol instead (same code; PyMOL is auto-preferred when present).
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
