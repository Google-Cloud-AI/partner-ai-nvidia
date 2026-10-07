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
ESMFold Tool — calls the ESMFold service (RTX PRO 6000 Blackwell on GKE) for
protein structure prediction.

v2 note: the GPU node runs with a read-only storage scope, so the ESMFold pod
cannot write to GCS. This tool therefore persists the returned PDB to GCS here,
using the Agent Runtime service account (which has write access), so docking and
the viewer can consume gs:// paths.
"""
import os
import re
import logging
import requests

logger = logging.getLogger(__name__)

ESMFOLD_URL = os.getenv("MOLFORGE_ESMFOLD_URL", "http://esmfold-service:8000")
GCS_BUCKET = os.getenv("MOLFORGE_ARTIFACTS_BUCKET", "molforge-artifacts")
VIEWER_BASE_URL = os.getenv("MOLFORGE_VIEWER_URL", "https://molforge-viewer.run.app")


def _slugify(name: str) -> str:
    """Filename-safe slug for a protein name → 'Hemoglobin subunit gamma-2' becomes
    'Hemoglobin_subunit_gamma-2'. The raw name flows straight into the GCS object name,
    the viewer URL, and (via the narrative) the bridge's inline-render regex — so a name
    with spaces/illegal chars silently produces a gs:// object and viewer URL that the
    viewer's filename guard ([A-Za-z0-9_.-]) and the bridge regex (\\S+) both reject.
    Collapse anything outside that set to '_' so every downstream consumer accepts it."""
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", (name or "").strip())
    slug = re.sub(r"_{2,}", "_", slug).strip("._-")
    return slug or "structure"


def _persist_pdb(protein_name: str, pdb_content: str) -> str:
    """Upload PDB to GCS from the agent (its SA has write access). Returns gs:// path or ''."""
    if not pdb_content:
        return ""
    try:
        from google.cloud import storage
        client = storage.Client()
        blob = client.bucket(GCS_BUCKET).blob(f"structures/{protein_name}.pdb")
        blob.upload_from_string(pdb_content, content_type="chemical/x-pdb")
        return f"gs://{GCS_BUCKET}/structures/{protein_name}.pdb"
    except Exception as e:
        logger.warning(f"ESMFold PDB persist to GCS failed (non-fatal): {e}")
        return ""


def predict_structure(
    amino_acid_sequence: str,
    protein_name: str = "target",
) -> dict:
    """Predict protein 3D structure from amino acid sequence using ESMFold.

    Use this ONLY when no experimental structure exists in the PDB. ESMFold
    predicts structures from single sequences without requiring MSAs.

    pLDDT (0-100): 90+ very high, 70-90 confident, 50-70 low, <50 unusable.

    Args:
        amino_acid_sequence: Full amino acid sequence in one-letter code.
        protein_name: Human-readable name for file naming (e.g., "braf_v600e").

    Returns:
        dict with: protein_name, sequence_length, pdb_content, pdb_gcs_path,
        plddt_mean, plddt_per_residue, high_confidence_regions, viewer_url.
    """
    # Slugify for ALL file/URL references; keep the raw name only for human-readable
    # display. Sent to the service too, so any path it builds is clean as well.
    slug = _slugify(protein_name)
    try:
        response = requests.post(
            f"{ESMFOLD_URL}/predict",
            json={"sequence": amino_acid_sequence, "protein_name": slug},
            timeout=180,
        )
        response.raise_for_status()
        result = response.json()
    except requests.exceptions.RequestException as e:
        return {"error": f"ESMFold prediction failed: {str(e)}"}

    # The ESMFold pod can't write GCS (read-only node scope) — persist here instead.
    if not result.get("pdb_gcs_path") and result.get("pdb_content"):
        gcs_path = _persist_pdb(slug, result["pdb_content"])
        if gcs_path:
            result["pdb_gcs_path"] = gcs_path
    if result.get("pdb_gcs_path"):
        result["viewer_url"] = f"{VIEWER_BASE_URL}/protein?file={slug}.pdb"
    result["protein_name"] = protein_name  # human-readable name for display/narrative
    return result
