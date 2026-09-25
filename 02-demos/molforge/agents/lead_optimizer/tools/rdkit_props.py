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
RDKit Tools — calls the RDKit service on GKE for molecular property
calculation and 2D structure rendering.
"""
import os
import requests

RDKIT_URL = os.getenv("MOLFORGE_RDKIT_URL", "http://rdkit-service:8080")


def compute_properties(
    smiles_list: list,
) -> dict:
    """Compute physicochemical properties and drug-likeness for a list of molecules.

    Calculates Lipinski Rule of Five properties and additional descriptors
    relevant to drug-likeness assessment. Use this to filter generated
    candidates before reporting results.

    Args:
        smiles_list: List of SMILES strings to evaluate.

    Returns:
        dict with keys:
            - computed_count: Number of molecules successfully computed
            - failed_count: Number of invalid SMILES that could not be parsed
            - results: List of dicts, each with:
                - smiles: Input SMILES
                - molecular_weight: Molecular weight in Daltons
                - logp: Calculated octanol-water partition coefficient
                - hbd: Number of hydrogen bond donors
                - hba: Number of hydrogen bond acceptors
                - tpsa: Topological polar surface area (Angstrom^2)
                - rotatable_bonds: Number of rotatable bonds
                - num_rings: Number of ring systems
                - lipinski_violations: Number of Lipinski Rule of Five violations (0-4)
                - lipinski_pass: Boolean — true if violations <= 1
                - qed: Quantitative Estimate of Drug-likeness (0-1, higher is better)
                - sa_score: Synthetic Accessibility score (1-10, lower is easier to synthesize)
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


def render_molecule_svg(
    smiles: str,
    highlight_scaffold: str = "",
    width: int = 400,
    height: int = 300,
) -> dict:
    """Generate a 2D structure diagram (SVG) for a molecule.

    Use this to create visual representations of candidate molecules
    for the dashboard and reports.

    Args:
        smiles: SMILES string of the molecule to render.
        highlight_scaffold: Optional SMILES of a substructure to highlight
            in contrasting color (e.g., the core scaffold of the lead compound).
        width: SVG width in pixels (default 400).
        height: SVG height in pixels (default 300).

    Returns:
        dict with keys:
            - smiles: Input SMILES
            - svg_content: The SVG markup as a string
            - gcs_path: Cloud Storage path where the SVG was saved (if applicable)
    """
    try:
        response = requests.post(
            f"{RDKIT_URL}/render",
            json={
                "smiles": smiles,
                "highlight_scaffold": highlight_scaffold,
                "width": width,
                "height": height,
            },
            timeout=30,
        )
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        return {"error": f"RDKit rendering failed: {str(e)}"}
