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
Complete ADMET Screening Tool — internally chains all ADMET pipeline steps
into a single tool call to eliminate Gemini MALFORMED_FUNCTION_CALL failures
on multi-step tool chaining.

Architecture:
    LLM makes ONE tool call → this function internally runs:
        1. predict_admet_properties (ADMET-AI on GKE)
        2. compute_properties (RDKit on GKE)
        3. generate_safety_report (NVIDIA Nemotron Nano VL 12B v2 on Model Garden)
        4. store_admet_results (Cloud Storage)
    Returns a single consolidated dict.

This pattern matches NVIDIA reference blueprints: Gemini orchestrates with
one decision per turn, Nemotron does all the reasoning inside the tool.

Author: Schneider Larbi
        Senior Manager, Global Partner Technical Architecture — AI & SaaS ISVs
        Google Cloud
"""
import logging
import uuid
from datetime import datetime, timezone

from .admet_predict import predict_admet_properties
from .rdkit_props import compute_properties
from .report_gen import generate_safety_report
from .artifacts import store_admet_results

logger = logging.getLogger(__name__)


def screen_molecules_complete(
    smiles_list: list,
    therapeutic_area: str = "",
    optimization_context: str = "",
    drugbank_atc_filter: str = "",
) -> dict:
    """Run the complete ADMET safety screening pipeline in a single tool call.

    This tool internally chains all four pipeline steps so the LLM only ever
    makes one function call. This eliminates the Gemini MALFORMED_FUNCTION_CALL
    failure mode that occurs when chaining multiple tools with large outputs.

    Args:
        smiles_list: List of SMILES strings for the candidate molecules
        therapeutic_area: Optional therapeutic indication (e.g., "cardiovascular",
                          "oncology", "CNS", "autoimmune") used for context-aware
                          interpretation. Infer it rather than asking for it; the
                          screen runs fine without one.
        optimization_context: Optional notes about scientist priorities or constraints
        drugbank_atc_filter: Optional ATC code prefix to filter DrugBank percentiles
                             (e.g., "C" for cardiovascular, "L" for oncology)

    Returns:
        dict with keys:
            - run_id: Unique identifier for this screening run
            - therapeutic_area: Echo of input
            - molecule_count: Number of molecules screened
            - admet_predictions: Raw ADMET-AI predictions
            - physicochemical: RDKit-computed properties
            - safety_narrative: Full pharmacological report from Nemotron Nano VL 12B v2
            - executive_summary: Short summary from Nemotron
            - generation_model: NVIDIA model used for the narrative
            - storage: GCS storage result with viewer URL
            - status: 'success' or 'partial' if any step failed
            - errors: List of any non-fatal errors encountered
    """
    therapeutic_area = therapeutic_area or "general small-molecule therapeutics"
    run_id = (
        f"run_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
        f"_{uuid.uuid4().hex[:8]}"
    )
    errors = []

    logger.info(
        f"[{run_id}] Starting complete ADMET screen: "
        f"{len(smiles_list)} molecules, area={therapeutic_area}"
    )

    # Step 1: ADMET-AI predictions
    try:
        admet_result = predict_admet_properties(
            smiles_list=smiles_list,
            drugbank_atc_filter=drugbank_atc_filter or "",
        )
        if admet_result.get("error"):
            errors.append(f"predict_admet_properties: {admet_result['error']}")
            logger.error(f"[{run_id}] ADMET prediction failed: {admet_result['error']}")
            return {
                "run_id": run_id,
                "status": "failed",
                "step_failed": "predict_admet_properties",
                "errors": errors,
            }
        logger.info(f"[{run_id}] ADMET predictions complete: {admet_result.get('predicted_count', 0)}")
    except Exception as e:
        logger.error(f"[{run_id}] ADMET prediction exception: {e}", exc_info=True)
        return {
            "run_id": run_id,
            "status": "failed",
            "step_failed": "predict_admet_properties",
            "errors": [str(e)],
        }

    # Step 2: RDKit physicochemical properties
    try:
        physchem_result = compute_properties(smiles_list=smiles_list)
        if physchem_result.get("error"):
            errors.append(f"compute_properties: {physchem_result['error']}")
        logger.info(f"[{run_id}] RDKit properties complete: {physchem_result.get('computed_count', 0)}")
    except Exception as e:
        logger.warning(f"[{run_id}] RDKit failed (non-fatal): {e}")
        errors.append(f"compute_properties: {e}")
        physchem_result = {"results": [], "error": str(e)}

    # Step 3: Combine ADMET + RDKit into per-molecule records for the narrative
    combined = []
    admet_results = admet_result.get("results", [])
    physchem_results = physchem_result.get("results", [])
    physchem_by_smiles = {r.get("smiles"): r for r in physchem_results}

    for admet_row in admet_results:
        smiles = admet_row.get("smiles")
        merged = dict(admet_row)
        if smiles in physchem_by_smiles:
            merged["physicochemical"] = physchem_by_smiles[smiles]
        combined.append(merged)

    # Step 4: Nemotron Nano VL safety narrative
    try:
        narrative_result = generate_safety_report(
            admet_results=combined,
            therapeutic_area=therapeutic_area,
            optimization_context=optimization_context,
        )
        if narrative_result.get("error"):
            errors.append(f"generate_safety_report: {narrative_result['error']}")
            logger.error(f"[{run_id}] Nemotron report failed: {narrative_result['error']}")
        else:
            logger.info(
                f"[{run_id}] Nemotron narrative complete: "
                f"{len(narrative_result.get('narrative', ''))} chars"
            )
    except Exception as e:
        logger.error(f"[{run_id}] Nemotron exception: {e}", exc_info=True)
        narrative_result = {"error": str(e), "narrative": "", "executive_summary": ""}
        errors.append(f"generate_safety_report: {e}")

    # Step 5: Store to GCS
    try:
        storage_result = store_admet_results(
            run_id=run_id,
            screening_results=combined,
            safety_narrative=narrative_result.get("narrative", ""),
            therapeutic_area=therapeutic_area,
        )
        if storage_result.get("error"):
            errors.append(f"store_admet_results: {storage_result['error']}")
            logger.warning(f"[{run_id}] Storage failed (non-fatal): {storage_result['error']}")
        else:
            logger.info(f"[{run_id}] Storage complete: {storage_result.get('gcs_path')}")
    except Exception as e:
        logger.warning(f"[{run_id}] Storage exception (non-fatal): {e}")
        errors.append(f"store_admet_results: {e}")
        storage_result = {"error": str(e)}

    status = "success" if not errors else "partial"

    return {
        "run_id": run_id,
        "status": status,
        "therapeutic_area": therapeutic_area,
        "molecule_count": len(combined),
        "admet_predictions": admet_results,
        "physicochemical": physchem_results,
        "safety_narrative": narrative_result.get("narrative", ""),
        "executive_summary": narrative_result.get("executive_summary", ""),
        "generation_model": narrative_result.get("generation_model", ""),
        "model_provider": narrative_result.get("model_provider", ""),
        "storage": storage_result,
        "errors": errors,
    }
