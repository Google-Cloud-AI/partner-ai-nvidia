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
ADMET-AI Tool — calls the ADMET-AI service on GKE for ADMET property prediction.
ADMET-AI v2 uses Chemprop-RDKit trained on 41 TDC datasets. CPU-only, no GPU needed.
"""
import os
import requests

ADMET_AI_URL = os.getenv("MOLFORGE_ADMET_AI_URL", "http://admet-ai-service:8080")


def predict_admet_properties(
    smiles_list: list,
    drugbank_atc_filter: str = "all",
) -> dict:
    """Predict 41 ADMET properties for a list of molecules using ADMET-AI.

    ADMET-AI uses Chemprop-RDKit graph neural networks trained on the
    Therapeutics Data Commons. It is the highest-ranked model on the
    TDC ADMET Benchmark leaderboard.

    Each prediction includes a DrugBank percentile — the molecule's score
    compared against 2,579 approved drugs. This provides critical context:
    a raw score of 0.6 means nothing without knowing where approved drugs fall.

    Args:
        smiles_list: List of SMILES strings to predict. Up to 1000 molecules per call.
        drugbank_atc_filter: ATC code to filter the DrugBank reference set.
            Use this to compare against drugs in the same therapeutic class.
            Examples:
                "all" - compare against all approved drugs (default)
                "L" - antineoplastic (oncology)
                "N" - nervous system (CNS)
                "C" - cardiovascular
                "J" - anti-infectives (antiviral, antibacterial)
                "M" - musculoskeletal (autoimmune)

    Returns:
        dict with keys:
            - predicted_count: Number of molecules successfully predicted
            - failed_count: Number of invalid SMILES
            - atc_filter: The DrugBank reference set used
            - results: List of dicts, each with:
                - smiles: Input SMILES
                - absorption:
                    - caco2_permeability: Caco-2 cell permeability (regression)
                    - hia: Human Intestinal Absorption probability
                    - pgp_inhibitor: P-glycoprotein inhibitor probability
                    - bioavailability_f20: Probability of > 20% oral bioavailability
                - distribution:
                    - bbb_penetration: Blood-brain barrier penetration probability
                    - ppb: Plasma protein binding (fraction bound)
                    - vdss: Volume of distribution at steady state
                - metabolism:
                    - cyp1a2_inhibitor: CYP1A2 inhibition probability
                    - cyp2c9_inhibitor: CYP2C9 inhibition probability
                    - cyp2c19_inhibitor: CYP2C19 inhibition probability
                    - cyp2d6_inhibitor: CYP2D6 inhibition probability
                    - cyp3a4_inhibitor: CYP3A4 inhibition probability
                    - cyp2c9_substrate: CYP2C9 substrate probability
                    - cyp2d6_substrate: CYP2D6 substrate probability
                    - cyp3a4_substrate: CYP3A4 substrate probability
                - excretion:
                    - half_life: Predicted half-life (hours)
                    - clearance_hepatocyte: Hepatocyte clearance
                    - clearance_microsome: Microsome clearance
                - toxicity:
                    - herg_inhibitor: hERG channel inhibition probability (CRITICAL)
                    - ames_mutagenicity: Ames test mutagenicity probability
                    - dili: Drug-Induced Liver Injury probability
                    - ld50: Lethal dose 50 (mg/kg)
                    - skin_sensitization: Skin sensitization probability
                    - carcinogenicity: Carcinogenicity probability
                    - clinical_toxicity: Clinical toxicity probability
                - drugbank_percentiles: Dict mapping each property to its percentile
                    vs the filtered DrugBank reference set (0-100)
    """
    try:
        response = requests.post(
            f"{ADMET_AI_URL}/predict",
            json={
                "smiles_list": smiles_list,
                "drugbank_atc_filter": drugbank_atc_filter,
            },
            timeout=120,
        )
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        return {"error": f"ADMET-AI prediction failed: {str(e)}"}
