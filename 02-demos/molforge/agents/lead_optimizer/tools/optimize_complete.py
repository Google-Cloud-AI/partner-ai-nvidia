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
Complete Lead Optimization Tool — internally chains all lead optimization
pipeline steps into a single tool call to eliminate Gemini
MALFORMED_FUNCTION_CALL failures on multi-step tool chaining.

Architecture:
    LLM makes ONE tool call → this function internally runs:
        1. predict_structure (ESMFold on RTX PRO 6000) — only if no PDB and sequence given
        2. generate_molecules (GenMol — NVIDIA-hosted NIM)
        3. dock_molecules (DiffDock — NVIDIA-hosted NIM) — only if a target structure exists
        4. compute_properties (RDKit) for all candidates
        5. nemotron_sar_analysis (NVIDIA Nemotron Super 49B v1.5 on Model Garden)
        6. store_optimization_results (Cloud Storage)
    Returns a single consolidated dict.

This pattern matches NVIDIA reference blueprints: Gemini orchestrates with
ONE decision per turn, Nemotron Super 49B does ALL the SAR reasoning and
ranking inside the tool. ZERO hardcoded ranking or filter logic in Python.

Author: Schneider Larbi
        Senior Manager, Global Partner Technical Architecture — AI & SaaS ISVs
        Google Cloud
"""
import logging
import uuid
from datetime import datetime, timezone

from .genmol import generate_molecules
from .diffdock import dock_molecules
from .esmfold import predict_structure
from .rdkit_props import compute_properties
from .artifacts import store_optimization_results
from .sar_analysis import nemotron_sar_analysis

logger = logging.getLogger(__name__)


def optimize_lead_complete(
    lead_smiles: str,
    target_name: str,
    objectives: str = "",
    therapeutic_area: str = "",
    target_pdb_path: str = "",
    target_sequence: str = "",
    generation_mode: str = "scaffold_decoration",
    num_variants: int = 10,
    fragment_constraints: str = "",
) -> dict:
    """Run the complete lead optimization pipeline in a single tool call.

    This tool internally chains all pipeline steps so the LLM only ever
    makes one function call. Eliminates Gemini MALFORMED_FUNCTION_CALL failures
    on chained tools with large structured outputs.

    Args:
        lead_smiles: SMILES string of the lead compound to optimize
        target_name: Name or identifier of the target protein
        objectives: Free-text optimization goals from the scientist
        therapeutic_area: Therapeutic area context for SAR judgment
        target_pdb_path: Optional path to an experimental PDB structure of the target
        target_sequence: Optional amino acid sequence (used by ESMFold if no PDB given)
        generation_mode: GenMol mode — 'scaffold_decoration', 'motif_extension',
                         'linker_design', or 'de_novo'
        num_variants: Number of variants to generate (default 10; set from the request)
        fragment_constraints: Optional SAFE-format fragment constraints for GenMol

    Returns:
        dict with keys:
            - run_id: Unique identifier for this optimization run
            - status: 'success', 'partial', or 'failed'
            - lead_smiles, target_name: Echo of inputs
            - candidate_count: Number of candidates after the full pipeline
            - candidates: List of candidate dicts with smiles, binding_score, properties
            - sar_narrative: Full SAR analysis from Nemotron Super 49B v1.5 (verbatim)
            - executive_summary: Short summary from Nemotron
            - generation_model: NVIDIA model used for SAR reasoning
            - model_provider: 'NVIDIA'
            - target_structure: Source of target structure ('user_pdb', 'esmfold', or 'none')
            - storage: GCS storage result
            - errors: Non-fatal errors encountered
    """
    run_id = (
        f"opt_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
        f"_{uuid.uuid4().hex[:8]}"
    )
    errors = []

    logger.info(
        f"[{run_id}] Starting complete lead optimization: "
        f"lead={lead_smiles[:60]}, target={target_name}, mode={generation_mode}, "
        f"num_variants={num_variants}"
    )

    # Step 1: Resolve target structure (if any)
    pdb_path = ""
    target_structure_source = "none"

    if target_pdb_path:
        pdb_path = target_pdb_path
        target_structure_source = "user_pdb"
        logger.info(f"[{run_id}] Using user-provided PDB: {pdb_path}")
    elif target_sequence:
        try:
            logger.info(f"[{run_id}] Folding target sequence with ESMFold ({len(target_sequence)} aa)")
            esmfold_result = predict_structure(
                amino_acid_sequence=target_sequence,
                protein_name=target_name,
            )
            if esmfold_result.get("error"):
                errors.append(f"predict_structure: {esmfold_result['error']}")
                logger.warning(f"[{run_id}] ESMFold failed: {esmfold_result['error']}")
            else:
                # ESMFold service returns pdb_gcs_path (gs:// URL); diffdock._resolve_pdb_content handles gs:// natively
                pdb_path = esmfold_result.get("pdb_gcs_path") or ""
                if pdb_path:
                    target_structure_source = "esmfold"
                    logger.info(f"[{run_id}] ESMFold structure: {pdb_path}")
                else:
                    errors.append("predict_structure: returned no structure path")
        except Exception as e:
            logger.warning(f"[{run_id}] ESMFold exception (non-fatal): {e}")
            errors.append(f"predict_structure: {e}")

    # Step 2: GenMol — generate variants
    try:
        # Over-generate: GenMol repeats at noise=1.0 (~40-60% unique yield), so request a generous
        # 5x buffer (capped at 96), then dedup + cap to num_variants below. GenMol latency is ~flat in
        # count, so this is cheap; the 96 cap stops a very large request from exploding generation time.
        # NOTE: for very large N you may still get fewer — GenMol's unique-variant count for a given
        # scaffold has a chemistry ceiling no amount of over-generation can exceed.
        gen_target = min(max(num_variants * 5, num_variants + 12), 96)
        genmol_result = generate_molecules(
            seed_smiles=lead_smiles,
            generation_mode=generation_mode,
            num_molecules=gen_target,
            fragment_constraints=fragment_constraints or "",
        )
        if genmol_result.get("error"):
            errors.append(f"generate_molecules: {genmol_result['error']}")
            logger.error(f"[{run_id}] GenMol failed: {genmol_result['error']}")
            return {
                "run_id": run_id,
                "status": "failed",
                "step_failed": "generate_molecules",
                "errors": errors,
                "sar_narrative": "",
            }

        generated_smiles = (
            genmol_result.get("smiles_list")
            or genmol_result.get("molecules")
            or genmol_result.get("results")
            or []
        )
        if isinstance(generated_smiles, list) and generated_smiles and isinstance(generated_smiles[0], dict):
            generated_smiles = [m.get("smiles", "") for m in generated_smiles if m.get("smiles")]

        # Dedup (order-preserving) and cap to the requested count, so the scientist gets up to
        # num_variants UNIQUE candidates regardless of GenMol's duplicate rate. Done before docking.
        _raw = len(generated_smiles)
        _seen = set()
        generated_smiles = [s for s in generated_smiles
                            if s and not (s in _seen or _seen.add(s))][:num_variants]
        logger.info(f"[{run_id}] GenMol produced {_raw} raw; kept {len(generated_smiles)} unique "
                    f"(capped to num_variants={num_variants})")
    except Exception as e:
        logger.error(f"[{run_id}] GenMol exception: {e}", exc_info=True)
        return {
            "run_id": run_id,
            "status": "failed",
            "step_failed": "generate_molecules",
            "errors": [str(e)],
            "sar_narrative": "",
        }

    if not generated_smiles:
        return {
            "run_id": run_id,
            "status": "failed",
            "step_failed": "generate_molecules",
            "errors": errors + ["generate_molecules returned no candidates"],
            "sar_narrative": "",
        }

    # Step 3: DiffDock — only if a target structure is available
    docking_results = []
    dock_id_for_run = ""
    if pdb_path:
        try:
            logger.info(f"[{run_id}] Docking {len(generated_smiles)} candidates with DiffDock")
            dock_result = dock_molecules(
                protein_pdb_path=pdb_path,
                ligand_smiles_list=generated_smiles,
                num_poses=5,
            )
            if dock_result.get("error"):
                errors.append(f"dock_molecules: {dock_result['error']}")
                logger.warning(f"[{run_id}] DiffDock failed (non-fatal): {dock_result['error']}")
            else:
                docking_results = (
                    dock_result.get("results")
                    or dock_result.get("docking_results")
                    or []
                )
                dock_id_for_run = dock_result.get("dock_id") or ""
                logger.info(f"[{run_id}] DiffDock returned {len(docking_results)} results, dock_id={dock_id_for_run}")
        except Exception as e:
            logger.warning(f"[{run_id}] DiffDock exception (non-fatal): {e}")
            errors.append(f"dock_molecules: {e}")
    else:
        logger.info(f"[{run_id}] No target structure — skipping docking")

    # Step 4: RDKit physicochemical properties for all candidates
    properties_by_smiles = {}
    try:
        rdkit_result = compute_properties(smiles_list=generated_smiles)
        if rdkit_result.get("error"):
            errors.append(f"compute_properties: {rdkit_result['error']}")
            logger.warning(f"[{run_id}] RDKit failed (non-fatal): {rdkit_result['error']}")
        else:
            for r in rdkit_result.get("results", []):
                if r.get("smiles"):
                    properties_by_smiles[r["smiles"]] = r
            logger.info(f"[{run_id}] RDKit computed properties for {len(properties_by_smiles)} candidates")
    except Exception as e:
        logger.warning(f"[{run_id}] RDKit exception (non-fatal): {e}")
        errors.append(f"compute_properties: {e}")

    # Step 5: Build unified candidate records (data merge only — no ranking, no filtering)
    docking_by_smiles = {}
    for d in docking_results:
        if isinstance(d, dict):
            s = d.get("smiles") or d.get("ligand_smiles")
            if s:
                docking_by_smiles[s] = d

    candidates = []
    for smiles in generated_smiles:
        record = {"smiles": smiles}
        if smiles in docking_by_smiles:
            d = docking_by_smiles[smiles]
            record["binding_score"] = d.get("binding_score") or d.get("score")
            record["binding_confidence"] = d.get("confidence") or d.get("binding_confidence")
            if d.get("pose_path"):
                record["pose_path"] = d["pose_path"]
        if smiles in properties_by_smiles:
            record["properties"] = properties_by_smiles[smiles]
        candidates.append(record)

    # Step 6: Nemotron Super 49B — SAR reasoning, ranking, narrative
    try:
        sar_result = nemotron_sar_analysis(
            candidates=candidates,
            lead_smiles=lead_smiles,
            target_name=target_name,
            objectives=objectives,
            therapeutic_area=therapeutic_area,
        )
        if sar_result.get("error"):
            errors.append(f"nemotron_sar_analysis: {sar_result['error']}")
            logger.error(f"[{run_id}] Nemotron Super 49B failed: {sar_result['error']}")
        else:
            logger.info(
                f"[{run_id}] Nemotron Super 49B SAR complete: "
                f"{len(sar_result.get('sar_narrative', ''))} chars"
            )
    except Exception as e:
        logger.error(f"[{run_id}] Nemotron Super 49B exception: {e}", exc_info=True)
        sar_result = {
            "error": str(e),
            "sar_narrative": "",
            "executive_summary": "",
            "generation_model": "",
            "model_provider": "",
            "usage": {},
        }
        errors.append(f"nemotron_sar_analysis: {e}")

    # Step 7: Store to GCS
    try:
        storage_result = store_optimization_results(
            run_id=run_id,
            target_name=target_name,
            candidates=candidates,
            rounds_completed=1,
            total_generated=len(generated_smiles),
            total_filtered=len(candidates),
            sar_narrative=sar_result.get("sar_narrative", "") if isinstance(sar_result, dict) else "",
            generation_model=sar_result.get("generation_model", "") if isinstance(sar_result, dict) else "",
            model_provider=sar_result.get("model_provider", "") if isinstance(sar_result, dict) else "",
            dock_id=dock_id_for_run,
        )
        if storage_result.get("error"):
            errors.append(f"store_optimization_results: {storage_result['error']}")
            logger.warning(
                f"[{run_id}] Storage failed (non-fatal): {storage_result['error']}"
            )
    except Exception as e:
        logger.warning(f"[{run_id}] Storage exception (non-fatal): {e}")
        errors.append(f"store_optimization_results: {e}")
        storage_result = {"error": str(e)}

    status = "success" if not errors else "partial"

    return {
        "run_id": run_id,
        "status": status,
        "lead_smiles": lead_smiles,
        "target_name": target_name,
        "target_structure": target_structure_source,
        "candidate_count": len(candidates),
        "candidates": candidates,
        "sar_narrative": sar_result.get("sar_narrative", ""),
        "executive_summary": sar_result.get("executive_summary", ""),
        "generation_model": sar_result.get("generation_model", ""),
        "model_provider": sar_result.get("model_provider", ""),
        "storage": storage_result,
        "errors": errors,
    }
