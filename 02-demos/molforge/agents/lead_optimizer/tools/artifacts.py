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
Artifact storage for Lead Optimization results.
Writes directly to Cloud Storage — no external artifact service required.
"""
import os
import json
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

GCS_BUCKET = os.getenv("MOLFORGE_GCS_BUCKET", "molforge-artifacts")
VIEWER_BASE_URL = os.getenv("MOLFORGE_VIEWER_URL", "https://molforge-viewer.run.app")


def store_optimization_results(
    run_id: str,
    candidates: list,
    rounds_completed: int,
    total_generated: int,
    total_filtered: int,
    sar_narrative: str = "",
    generation_model: str = "",
    model_provider: str = "",
    dock_id: str = "",
    target_name: str = "",
) -> dict:
    """Store the complete optimization results to Cloud Storage.

    Call this at the end of the optimization loop to persist all results
    for the viewer, audit trail, and downstream ADMET screening.

    Args:
        run_id: The run identifier from the Orchestrator
        candidates: List of candidate dicts with smiles, scores, and properties
        rounds_completed: Number of optimization rounds executed
        total_generated: Total molecules generated across all rounds
        total_filtered: Number of molecules that survived all filters
        sar_narrative: Full verbatim SAR analysis from NVIDIA Nemotron Super 49B v1.5.
                       Stored as-is so the Mol* Gallery viewer can render it inline.
        generation_model: Model identifier that produced the SAR narrative
                          (e.g., "nvidia/llama-3.3-nemotron-super-49b-v1.5")
        model_provider: Provider name for dashboard color-coding (e.g., "NVIDIA")

    Returns:
        dict with keys:
            - gcs_path: Cloud Storage path to the results JSON
            - viewer_url: URL to the molecule gallery viewer
            - docking_viewer_url: URL to the docking pose viewer
            - candidate_count: Number of candidates stored
            - run_id: The run identifier
            - status: 'stored'
    """
    try:
        from google.cloud import storage

        payload = {
            "run_id": run_id,
            "artifact_type": "optimization_results",
            "target_name": target_name or "",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "rounds_completed": rounds_completed,
            "total_generated": total_generated,
            "total_filtered": total_filtered,
            "candidate_count": len(candidates),
            "candidates": candidates,
            "sar_narrative": sar_narrative or "",
            "generation_model": generation_model or "",
            "model_provider": model_provider or "",
            "dock_id": dock_id or "",
        }

        client = storage.Client()
        bucket = client.bucket(GCS_BUCKET)
        blob_path = f"{run_id}/optimization_results.json"
        blob = bucket.blob(blob_path)
        blob.upload_from_string(
            json.dumps(payload, indent=2, default=str),
            content_type="application/json",
        )

        gcs_path = f"gs://{GCS_BUCKET}/{blob_path}"
        logger.info(
            f"Optimization results stored at {gcs_path} "
            f"(candidates={len(candidates)}, sar_narrative={len(sar_narrative or '')} chars)"
        )

        return {
            "gcs_path": gcs_path,
            "viewer_url": f"{VIEWER_BASE_URL}/gallery?id={run_id}",
            "docking_viewer_url": f"{VIEWER_BASE_URL}/docking?id={run_id}",
            "candidate_count": len(candidates),
            "run_id": run_id,
            "status": "stored",
        }
    except Exception as e:
        logger.error(f"Failed to store optimization results: {e}")
        return {
            "error": f"Failed to store optimization results: {str(e)}",
            "run_id": run_id,
        }
