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

"""
NVIDIA API key resolver for the hosted GenMol/DiffDock NIMs.

Security: the key is NEVER stored in .env or the deployed artifact. It is fetched
from Secret Manager at runtime via the Agent Runtime service account (which is
granted roles/secretmanager.secretAccessor on `molforge-nvidia-api-key`). An env
override is supported only for local dev.
"""
import os
import logging

logger = logging.getLogger(__name__)
_cached = None

# Built from GOOGLE_CLOUD_PROJECT rather than hardcoded: the old literal meant a
# fresh deployment asked *our* project for the key and got a 403 it could not act
# on. NVIDIA_API_KEY_SECRET still overrides the whole resource path outright.
_PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT")
_SECRET = os.getenv("NVIDIA_API_KEY_SECRET") or (
    f"projects/{_PROJECT_ID}/secrets/molforge-nvidia-api-key/versions/latest"
    if _PROJECT_ID
    else ""
)


def get_nvidia_key() -> str:
    """Return the NVIDIA API key (env override for dev, else Secret Manager). Cached."""
    global _cached
    if _cached:
        return _cached
    env = os.getenv("NVIDIA_API_KEY", "")
    if env:
        _cached = env
        return env
    # Unlike the sibling tool modules this one does not raise at import:
    # NVIDIA_API_KEY alone is a valid local-dev config, and it was just checked.
    # Past that point an unset project means there is no secret to read.
    if not _SECRET:
        logger.error(
            "No NVIDIA API key source: NVIDIA_API_KEY is unset and the Secret "
            "Manager path cannot be built because GOOGLE_CLOUD_PROJECT is unset. "
            "Set GOOGLE_CLOUD_PROJECT, or NVIDIA_API_KEY_SECRET to a full "
            "projects/*/secrets/*/versions/* path."
        )
        return ""
    try:
        from google.cloud import secretmanager
        client = secretmanager.SecretManagerServiceClient()
        _cached = client.access_secret_version(name=_SECRET).payload.data.decode("utf-8").strip()
        return _cached
    except Exception as e:
        logger.error(f"Failed to fetch NVIDIA API key from Secret Manager: {e}")
        return ""
