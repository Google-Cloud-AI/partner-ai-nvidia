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
ESMFold Service — FastAPI wrapper around HuggingFace ESMFold for
protein structure prediction from sequence.

Deployed on GKE with RTX PRO 6000 Blackwell (NGC PyTorch 26.02).

Architecture:
    - On startup (FastAPI lifespan), load EsmForProteinFolding from HuggingFace.
    - The model loads ONCE and is cached in module-level globals for the
      lifetime of the pod.
    - /health reports the real loaded state (model_loaded: true) immediately
      after startup completes — no longer requires a /predict call to "warm" it.
    - /predict uses the cached model with no per-request loading overhead.
"""
import os
import re
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("esmfold-service")

# Module-level globals — populated by lifespan startup
_model = None
_tokenizer = None

GCS_BUCKET = os.getenv("MOLFORGE_ARTIFACTS_BUCKET", "molforge-artifacts")
VIEWER_BASE_URL = os.getenv("MOLFORGE_VIEWER_URL", "https://molforge-viewer.run.app")


def _slugify(name: str) -> str:
    """Filename-safe slug for a protein name. A name with spaces/illegal chars otherwise
    produces a gs:// object + viewer URL that the viewer's filename guard ([A-Za-z0-9_.-])
    and the bridge's inline-render regex both reject. Mirrors esmfold.py::_slugify in the
    lead_optimizer tool (the authoritative writer today; this path is dormant while the GPU
    node has read-only storage scope, but kept correct in case that ever changes)."""
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", (name or "").strip())
    slug = re.sub(r"_{2,}", "_", slug).strip("._-")
    return slug or "structure"


def _load_model():
    """Load EsmForProteinFolding from HuggingFace and cache it globally."""
    global _model, _tokenizer
    import torch
    from transformers import AutoTokenizer, EsmForProteinFolding

    logger.info("Loading ESMFold model from HuggingFace (facebook/esmfold_v1)...")
    _tokenizer = AutoTokenizer.from_pretrained("facebook/esmfold_v1")
    _model = EsmForProteinFolding.from_pretrained(
        "facebook/esmfold_v1",
        low_cpu_mem_usage=True,
    )
    if torch.cuda.is_available():
        _model = _model.cuda()
        _model.esm = _model.esm.half()
    _model.eval()
    logger.info("ESMFold loaded successfully")


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        _load_model()
    except Exception as e:
        logger.error(f"FATAL: ESMFold model load failed at startup: {e}", exc_info=True)
        # Don't crash — let /health report cold state so warmup bar shows the issue.
    yield
    # Shutdown: nothing to clean up; pod tear-down handles GPU memory release


app = FastAPI(title="MolForge ESMFold Service", version="1.1.0", lifespan=lifespan)


class PredictRequest(BaseModel):
    sequence: str
    protein_name: str = "target"


@app.get("/health")
async def health():
    import torch
    return {
        "status": "healthy",
        "model_loaded": _model is not None,
        "model_kind": "esmfold_v1",
        "gpu_available": torch.cuda.is_available(),
        "gpu_name": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
    }


@app.post("/predict")
async def predict(req: PredictRequest):
    """Predict protein 3D structure from amino acid sequence."""
    if _model is None or _tokenizer is None:
        raise HTTPException(status_code=503, detail="ESMFold model not loaded — check pod startup logs")

    try:
        import torch
        import numpy as np
        from transformers.models.esm.openfold_utils.protein import to_pdb, Protein as OFProtein

        logger.info(f"Predicting structure for {req.protein_name} ({len(req.sequence)} residues)")

        inputs = _tokenizer([req.sequence], return_tensors="pt", add_special_tokens=False)
        if torch.cuda.is_available():
            inputs = {k: v.cuda() for k, v in inputs.items()}

        with torch.no_grad():
            output = _model(**inputs)

        # ESMFold returns pLDDT on a 0-1 scale per atom; normalize to 0-100 per residue
        plddt_raw = output["plddt"].cpu().numpy()[0, :len(req.sequence), 1]
        plddt_normalized = (plddt_raw * 100).tolist()
        mean_plddt = round(float(np.mean(plddt_normalized)), 2)

        pdb_content = to_pdb(
            OFProtein(
                aatype=output["aatype"].cpu().numpy()[0, :len(req.sequence)],
                atom_positions=output["positions"].cpu().numpy()[0, -1, :len(req.sequence)],
                atom_mask=output["atom37_atom_exists"].cpu().numpy()[0, :len(req.sequence)],
                residue_index=np.arange(len(req.sequence)) + 1,
                b_factors=np.repeat(np.array(plddt_normalized)[:, None], 37, axis=1),
            )
        )

        # High-confidence regions (>70 pLDDT)
        high_conf_regions = []
        start = None
        for i, score in enumerate(plddt_normalized):
            if score > 70 and start is None:
                start = i + 1
            elif score <= 70 and start is not None:
                high_conf_regions.append(f"{start}-{i}")
                start = None
        if start is not None:
            high_conf_regions.append(f"{start}-{len(plddt_normalized)}")

        # Optional GCS upload
        gcs_path = ""
        viewer_url = ""
        try:
            from google.cloud import storage
            client = storage.Client()
            bucket = client.bucket(GCS_BUCKET)
            slug = _slugify(req.protein_name)
            blob_path = f"structures/{slug}.pdb"
            blob = bucket.blob(blob_path)
            blob.upload_from_string(pdb_content)
            gcs_path = f"gs://{GCS_BUCKET}/{blob_path}"
            viewer_url = f"{VIEWER_BASE_URL}/protein?file={slug}.pdb"
        except Exception as e:
            logger.warning(f"GCS upload failed (non-fatal): {e}")

        return {
            "protein_name": req.protein_name,
            "sequence_length": len(req.sequence),
            "pdb_content": pdb_content,
            "pdb_gcs_path": gcs_path,
            "plddt_mean": mean_plddt,
            "plddt_per_residue": plddt_normalized,
            "high_confidence_regions": high_conf_regions,
            "viewer_url": viewer_url,
        }

    except Exception as e:
        logger.error(f"Structure prediction failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
