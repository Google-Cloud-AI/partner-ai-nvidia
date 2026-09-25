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
GenMol Tool — calls NVIDIA's HOSTED GenMol NIM (build.nvidia.com) for molecule
generation. v2: hosted on NVIDIA's cloud (no local GPU) instead of self-hosted
GenMol on GKE — removes a Blackwell-build dependency and frees the local GPU.

Endpoint:  POST https://health.api.nvidia.com/v1/biology/nvidia/genmol/generate
Auth:      Authorization: Bearer <NVIDIA_API_KEY>
Response:  {"status":"success","molecules":[{"smiles": "...", "score": 0.79}, ...]}
"""
import os
import requests

from ._nvidia import get_nvidia_key

# Hosted GenMol NIM. Override MOLFORGE_GENMOL_URL to point at a self-hosted NIM.
GENMOL_URL = os.getenv(
    "MOLFORGE_GENMOL_URL",
    "https://health.api.nvidia.com/v1/biology/nvidia/genmol/generate",
)


def generate_molecules(
    seed_smiles: str,
    generation_mode: str = "scaffold_decoration",
    num_molecules: int = 100,
    fragment_constraints: str = "",
) -> dict:
    """Generate molecular variants using NVIDIA GenMol (hosted NIM).

    GenMol uses masked diffusion over SAFE molecular representations to generate
    structurally diverse, drug-like variants of a seed molecule.

    Args:
        seed_smiles: SMILES string of the seed molecule to optimize from.
        generation_mode: Retained for orchestration compatibility. GenMol's hosted
            API drives diversity via temperature/noise rather than discrete modes;
            'de_novo' raises temperature for broader exploration.
        num_molecules: Number of variants to generate.
        fragment_constraints: Optional SAFE/SMILES fragment to keep (passed through
            when provided; GenMol preserves supplied scaffold context).

    Returns:
        dict with keys:
            - status: "success" on success
            - molecules: list of {smiles, score} (consumed by optimize_lead_complete)
            - generation_model / model_provider: attribution
            - error: present only on failure
    """
    nvidia_key = get_nvidia_key()
    if not nvidia_key:
        return {"error": "GenMol: NVIDIA API key unavailable (Secret Manager)", "molecules": []}

    # GenMol accepts a SMILES/SAFE seed directly. de_novo => broader sampling.
    temperature = 1.2 if generation_mode == "de_novo" else 1.0
    payload = {
        "smiles": fragment_constraints.strip() or seed_smiles,
        "num_molecules": int(num_molecules),
        "temperature": temperature,
        "noise": 1.0,
        "step_size": 1,
        "scoring": "QED",
        "unique": True,
    }
    try:
        response = requests.post(
            GENMOL_URL,
            headers={
                "Authorization": f"Bearer {nvidia_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=120,
        )
        response.raise_for_status()
        data = response.json()
        # Normalize: surface molecules list + attribution for the timeline.
        data.setdefault("molecules", data.get("generated_molecules", []))
        data["generation_model"] = "nvidia/genmol"
        data["model_provider"] = "NVIDIA"
        return data
    except requests.exceptions.RequestException as e:
        body = ""
        try:
            body = e.response.text[:300] if e.response is not None else ""
        except Exception:
            pass
        return {"error": f"GenMol hosted NIM failed: {e} {body}", "molecules": []}
