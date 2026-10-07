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

# Pinned by digest: python:3.12-slim is a moving tag. The image behind it
# silently dropped its expat package, which is half of why an untouched
# ADMET Dockerfile rebuilt into a broken container on 2026-09-03.
# To update: docker buildx imagetools inspect python:3.12-slim, swap the
# digest, rebuild, and confirm the smoke test below still passes.
FROM python:3.12-slim@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Fail the BUILD, not production. Import every third-party module the service
# needs at request time; a missing native dependency otherwise surfaces as a
# 500 on the first real query, long after /health has gone green.
RUN python -c "\
import fastapi, uvicorn, requests; \
from pydantic import BaseModel; \
from google.cloud import storage; \
print('smoke test OK: storage and web stack import cleanly')"

COPY app.py .

EXPOSE 8080

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
