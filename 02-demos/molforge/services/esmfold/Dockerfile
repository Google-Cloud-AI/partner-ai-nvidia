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

# ESMFold — the one local-GPU workload (RTX PRO 6000 Blackwell, sm_120).
#
# Pinned by digest: nvcr.io/nvidia/pytorch:26.02-py3 is a moving tag, and this
# base is load-bearing in a way the CPU services' are not -- it supplies the
# CUDA/PyTorch build that has to match Blackwell sm_120. A silently-rebased
# 26.02 could ship a torch that no longer compiles kernels for this GPU, and
# the pod would fail at first inference, not at startup.
# To update: docker buildx imagetools inspect nvcr.io/nvidia/pytorch:26.02-py3.
FROM nvcr.io/nvidia/pytorch:26.02-py3@sha256:bbc2b67e2533edd63ff1496bb1ed00a00338cdc1478af6c1a0bf9f4b369977e7
WORKDIR /app

# Pinned to the versions read out of the running esmfold pod, so a rebuild
# reproduces the environment that is actually serving rather than whatever
# resolves today. transformers especially: the old `<4.47.0` ceiling still
# floated across minor releases, and the ESMFold weights load through it.
#
# NOT pinned here: torch and the CUDA stack. Those come from the base image
# (2.11.0a0+eb65b36914.nv26.02, an NVIDIA build) and must not be overridden by
# pip -- installing an upstream torch on top would replace the Blackwell-
# capable build with a generic wheel.
RUN pip install --no-cache-dir --break-system-packages \
    fastapi==0.137.0 \
    uvicorn==0.49.0 \
    transformers==4.46.3 \
    accelerate==1.14.0 \
    biopython==1.87 \
    google-cloud-storage==3.12.0
COPY app.py .

# Fail the BUILD, not production, as far as is possible without a GPU: the
# builder has no Blackwell card, so this cannot verify inference. It checks
# what is checkable on CPU -- that the app imports, that transformers still
# exposes the ESMFold entry point this code loads, and that torch is still the
# NVIDIA build from the base image rather than a pip-installed replacement.
# The GPU path is verified by rollout, not here; see deployment.yaml.
RUN python -c "\
import torch, transformers; \
from transformers import EsmForProteinFolding; \
import app; \
assert 'nv' in torch.__version__, \
    f'smoke test: torch is {torch.__version__}, not the NVIDIA base build -- pip replaced it'; \
print(f'smoke test OK: torch {torch.__version__}, transformers {transformers.__version__}, app imports')"
EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
