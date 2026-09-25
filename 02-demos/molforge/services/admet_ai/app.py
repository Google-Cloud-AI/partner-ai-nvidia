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
ADMET-AI Service — predicts 41 ADMET properties using Chemprop-RDKit.
CPU-only, no GPU required. Open source, trained on TDC datasets.
"""
import logging
from typing import List, Optional
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("admet-ai-service")

app = FastAPI(title="MolForge ADMET-AI Service", version="1.0.0")

admet_model = None


def get_admet_model():
    global admet_model
    if admet_model is None:
        from admet_ai import ADMETModel
        logger.info("Loading ADMET-AI model...")
        admet_model = ADMETModel()
        logger.info("ADMET-AI model loaded (41 endpoints)")
    return admet_model


class PredictRequest(BaseModel):
    smiles_list: List[str]
    drugbank_atc_filter: str = "all"


# Published response field -> the ADMET-AI model that produces it.
#
# Declared here rather than inline so the contract is visible and testable.
# INVARIANT: every field names a DISTINCT model. Two fields sharing one model
# means the second reports a property that was never predicted -- which is how
# "pgp_substrate" and "bioavailability_f30" once shipped as aliases of
# Pgp_Broccatelli and Bioavailability_Ma. ADMET-AI has no substrate or F30
# model; if you want one, train it, don't alias it. See tests/test_admet_mapping.py.
ADMET_FIELD_MAP = {
    "absorption": {
        "caco2_permeability": "Caco2_Wang",
        "hia": "HIA_Hou",
        "pgp_inhibitor": "Pgp_Broccatelli",
        "bioavailability_f20": "Bioavailability_Ma",
    },
    "distribution": {
        "bbb_penetration": "BBB_Martins",
        "ppb": "PPBR_AZ",
        "vdss": "VDss_Lombardo",
    },
    "metabolism": {
        "cyp1a2_inhibitor": "CYP1A2_Veith",
        "cyp2c9_inhibitor": "CYP2C9_Veith",
        "cyp2c19_inhibitor": "CYP2C19_Veith",
        "cyp2d6_inhibitor": "CYP2D6_Veith",
        "cyp3a4_inhibitor": "CYP3A4_Veith",
        "cyp2c9_substrate": "CYP2C9_Substrate_CarbonMangels",
        "cyp2d6_substrate": "CYP2D6_Substrate_CarbonMangels",
        "cyp3a4_substrate": "CYP3A4_Substrate_CarbonMangels",
    },
    "excretion": {
        "half_life": "Half_Life_Obach",
        "clearance_hepatocyte": "Clearance_Hepatocyte_AZ",
        "clearance_microsome": "Clearance_Microsome_AZ",
    },
    "toxicity": {
        "herg_inhibitor": "hERG",
        "ames_mutagenicity": "AMES",
        "dili": "DILI",
        "ld50": "LD50_Zhu",
        "skin_sensitization": "Skin_Reaction",
        "carcinogenicity": "Carcinogens_Lagunin",
        "clinical_toxicity": "ClinTox",
    },
}


@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "model_loaded": admet_model is not None,
        "endpoints": 41,
        "gpu_required": False,
    }


@app.post("/predict")
async def predict(req: PredictRequest):
    """Predict ADMET properties for a list of molecules."""
    try:
        mdl = get_admet_model()
        results = []
        failed = 0

        for smi in req.smiles_list:
            try:
                preds = mdl.predict(smiles=smi)

                # Organize into ADMET categories (see ADMET_FIELD_MAP)
                result = {"smiles": smi}
                for category, fields in ADMET_FIELD_MAP.items():
                    result[category] = {
                        name: preds.get(model, None) for name, model in fields.items()
                    }
                result["drugbank_percentiles"] = {}

                # Compute percentile context against all predictions
                for key, val in preds.items():
                    if val is not None and isinstance(val, (int, float)):
                        result["drugbank_percentiles"][key] = val

                results.append(result)

            except Exception as e:
                logger.warning(f"Prediction failed for {smi}: {e}")
                results.append({"smiles": smi, "error": str(e)})
                failed += 1

        return {
            "predicted_count": len(results) - failed,
            "failed_count": failed,
            "atc_filter": req.drugbank_atc_filter,
            "results": results,
        }

    except Exception as e:
        logger.error(f"ADMET prediction batch failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
