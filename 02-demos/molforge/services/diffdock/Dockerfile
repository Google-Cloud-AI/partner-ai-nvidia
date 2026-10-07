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

# DiffDock — self-hosted fallback wrapper. NOT deployed: the v2 architecture
# calls the hosted NVIDIA DiffDock NIM, and the self-hosted NIM path is
# services/diffdock-nim/deployment.yaml. Kept as reference/lab material.
#
# Pinned by digest: nvcr.io/nvidia/pytorch:26.02-py3 is a moving tag, and it
# supplies the CUDA/PyTorch build. To update:
# docker buildx imagetools inspect nvcr.io/nvidia/pytorch:26.02-py3
FROM nvcr.io/nvidia/pytorch:26.02-py3@sha256:bbc2b67e2533edd63ff1496bb1ed00a00338cdc1478af6c1a0bf9f4b369977e7
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    libxrender1 libxext6 \
    && rm -rf /var/lib/apt/lists/*
# Pinned exactly. fastapi/uvicorn/biopython match the versions running in the
# ESMFold pod on this same NGC base; rdkit matches the render service. scipy
# has no in-repo precedent, so it is pinned at what pip resolves today -- which
# is what the unpinned spec installed anyway, now stated explicitly.
# torch and the CUDA stack come from the base image and must NOT be pip-installed
# over: an upstream wheel would replace the NVIDIA build.
RUN pip install --no-cache-dir --break-system-packages \
    fastapi==0.137.0 \
    uvicorn==0.49.0 \
    biopython==1.87 \
    scipy==1.18.1 \
    rdkit==2026.3.5
COPY app.py .

# Fail the BUILD, not production, as far as a CPU builder can: it has no GPU,
# so inference is unverifiable here. This checks that the app imports, that the
# scientific stack it uses is present, and that torch is still the NVIDIA base
# build rather than a pip replacement.
RUN python -c "\
import torch, scipy, Bio; \
from rdkit import Chem; \
import app; \
assert 'nv' in torch.__version__, \
    f'smoke test: torch is {torch.__version__}, not the NVIDIA base build -- pip replaced it'; \
print(f'smoke test OK: torch {torch.__version__}, scipy/biopython/rdkit and app import')"

EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
