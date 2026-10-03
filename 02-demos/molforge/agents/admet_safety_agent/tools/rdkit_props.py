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
RDKit Properties Tool — shared with Lead Optimizer, calls same GKE service.
"""
import os
import requests

RDKIT_URL = os.getenv("MOLFORGE_RDKIT_URL", "http://rdkit-service:8080")


def compute_properties(smiles_list: list) -> dict:
    """Compute physicochemical properties for candidate molecules.

    Supplements ADMET-AI predictions with RDKit-calculated descriptors
    including Lipinski Rule of Five, QED drug-likeness, and synthetic
    accessibility scores.

    Args:
        smiles_list: List of SMILES strings to evaluate.

    Returns:
        dict with results per molecule: molecular_weight, logp, hbd, hba,
        tpsa, rotatable_bonds, lipinski_violations, lipinski_pass, qed, sa_score.
    """
    try:
        response = requests.post(
            f"{RDKIT_URL}/properties",
            json={"smiles_list": smiles_list},
            timeout=60,
        )
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        return {"error": f"RDKit property computation failed: {str(e)}"}
