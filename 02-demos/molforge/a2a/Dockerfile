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
COPY server.py .
COPY a2ui.py .

# Fail the BUILD, not production. This bridge is the only thing Gemini
# Enterprise talks to, and its `vertexai` import chain is the fragile part: a
# major-version move under google-cloud-aiplatform breaks stream_query()
# delegation without touching a line of this repo. Import the real modules
# and construct the AgentCard the way /.well-known/agent.json does.
# The two env vars are the required-config contract server.py enforces at import
# (no hardcoded project/self-URL fallbacks). Their presence here is deliberate:
# if someone reintroduces a literal default, this line stops testing anything,
# and if someone adds a new required var, the build breaks until it is declared.
RUN MOLFORGE_A2UI=1 \
    GOOGLE_CLOUD_PROJECT=smoke-test-project \
    A2A_SERVER_URL=https://smoke-test.invalid \
    python -c "\
import vertexai; \
from vertexai import agent_engines; \
import server; \
exts = server.AGENT_CARD.get('capabilities', {}).get('extensions', []); \
assert any('a2ui' in e.get('uri', '') for e in exts), \
    'smoke test: AgentCard lost its A2UI extension -- GE would render text only'; \
print('smoke test OK: vertexai agent_engines imports, AgentCard declares A2UI')"

ENV PORT=8080
EXPOSE 8080
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8080"]
