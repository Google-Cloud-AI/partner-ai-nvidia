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
Artifact Management Tools for MolForge Orchestrator.

Handles run ID generation and artifact storage to Cloud Storage
for downstream viewer access and audit trail.
"""
import os
import uuid
from datetime import datetime


GCS_BUCKET = os.getenv("MOLFORGE_ARTIFACTS_BUCKET", "molforge-artifacts")
VIEWER_BASE_URL = os.getenv("MOLFORGE_VIEWER_URL", "https://molforge-viewer.run.app")


def generate_run_id() -> dict:
    """Generate a unique run identifier for a new MolForge pipeline execution.

    Call this at the start of every new scientist request to create a unique
    run_id that links all artifacts, results, and audit entries together.

    Returns:
        dict with keys:
            - run_id: Unique identifier (format: run_YYYYMMDD_HHMMSS_uuid8)
            - timestamp: ISO timestamp of creation
            - artifacts_base_path: Cloud Storage base path for this run
            - viewer_base_url: Base URL for viewer links for this run
    """
    timestamp = datetime.utcnow()
    short_uuid = uuid.uuid4().hex[:8]
    run_id = f"run_{timestamp.strftime('%Y%m%d_%H%M%S')}_{short_uuid}"

    return {
        "run_id": run_id,
        "timestamp": timestamp.isoformat() + "Z",
        "artifacts_base_path": f"gs://{GCS_BUCKET}/{run_id}/",
        "viewer_base_url": f"{VIEWER_BASE_URL}?id={run_id}",
    }


def store_run_artifact(
    run_id: str,
    artifact_type: str,
    content: str,
    filename: str,
) -> dict:
    """Store an artifact in Cloud Storage for a given run.

    Use this to persist intermediate or final results that need to be
    accessible by the viewer service or downloadable by the scientist.

    Args:
        run_id: The run identifier from generate_run_id
        artifact_type: Category of artifact. One of:
            "structures" - PDB protein structure files
            "molecules" - Generated candidate data (JSON, SDF, SVG)
            "docking" - DiffDock docking pose files (SDF)
            "admet" - ADMET screening results (JSON)
            "reports" - Summary reports (PDF, HTML)
        content: The artifact content as a string (JSON, PDB text, etc.)
        filename: Name of the file to store

    Returns:
        dict with keys:
            - gcs_path: Full Cloud Storage path to the stored artifact
            - viewer_url: Direct viewer URL for this artifact (if applicable)
            - size_bytes: Size of stored content
    """
    from google.cloud import storage

    gcs_path = f"{run_id}/{artifact_type}/{filename}"

    try:
        client = storage.Client()
        bucket = client.bucket(GCS_BUCKET)
        blob = bucket.blob(gcs_path)
        blob.upload_from_string(content)

        viewer_url = ""
        if artifact_type == "structures" and filename.endswith(".pdb"):
            viewer_url = f"{VIEWER_BASE_URL}/protein?id={run_id}&file={filename}"
        elif artifact_type == "docking":
            viewer_url = f"{VIEWER_BASE_URL}/docking?id={run_id}"
        elif artifact_type == "admet":
            viewer_url = f"{VIEWER_BASE_URL}/admet?id={run_id}"
        elif artifact_type == "molecules":
            viewer_url = f"{VIEWER_BASE_URL}/gallery?id={run_id}"

        return {
            "gcs_path": f"gs://{GCS_BUCKET}/{gcs_path}",
            "viewer_url": viewer_url,
            "size_bytes": len(content.encode("utf-8")),
        }
    except Exception as e:
        return {"error": f"Failed to store artifact: {str(e)}"}
