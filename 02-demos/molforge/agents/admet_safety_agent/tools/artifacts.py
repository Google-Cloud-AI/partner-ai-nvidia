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
Artifact storage for ADMET Safety Agent results.
Writes directly to Cloud Storage — no external artifact service required.
"""
import os
import json
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

GCS_BUCKET = os.getenv("MOLFORGE_GCS_BUCKET", "molforge-artifacts")
VIEWER_BASE_URL = os.getenv("MOLFORGE_VIEWER_URL", "https://molforge-viewer.run.app")


def store_admet_results(
    run_id: str,
    screening_results: list,
    safety_narrative: str,
    therapeutic_area: str,
) -> dict:
    """Store complete ADMET screening results to Cloud Storage.

    Args:
        run_id: The run identifier linking to the optimization run
        screening_results: List of per-molecule ADMET results with verdicts
        safety_narrative: The generated natural language safety report
        therapeutic_area: Therapeutic area used for threshold interpretation

    Returns:
        dict with keys:
            - gcs_path: Cloud Storage path to stored results
            - report_url: URL to interactive ADMET report viewer
            - run_id: The run identifier
    """
    try:
        from google.cloud import storage

        payload = {
            "run_id": run_id,
            "artifact_type": "admet_results",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "therapeutic_area": therapeutic_area,
            "screening_results": screening_results,
            "safety_narrative": safety_narrative,
        }

        client = storage.Client()
        bucket = client.bucket(GCS_BUCKET)
        blob_path = f"{run_id}/admet_results.json"
        blob = bucket.blob(blob_path)
        blob.upload_from_string(
            json.dumps(payload, indent=2, default=str),
            content_type="application/json",
        )

        gcs_path = f"gs://{GCS_BUCKET}/{blob_path}"
        logger.info(f"ADMET results stored at {gcs_path}")

        return {
            "gcs_path": gcs_path,
            "report_url": f"{VIEWER_BASE_URL}/admet?id={run_id}",
            "run_id": run_id,
            "status": "stored",
        }
    except Exception as e:
        logger.error(f"Failed to store ADMET results: {e}")
        return {
            "error": f"Failed to store ADMET results: {str(e)}",
            "run_id": run_id,
        }
