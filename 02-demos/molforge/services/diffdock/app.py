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
DiffDock Service — FastAPI wrapper around DiffDock V2 inference.

Deployed on GKE with RTX PRO 6000 Blackwell (NGC PyTorch 26.02).

Architecture:
    - On startup (FastAPI lifespan), attempt to load BioNeMo DiffDockInference.
      If unavailable (which is the current state — BioNeMo Framework is not
      yet installed in this image), fall back to a mock model that returns
      plausible docking results for architecture demos and pipeline testing.
    - The model loads ONCE and is cached in module-level globals.
    - /health reports the real loaded state (model_loaded: true) plus
      model_kind so callers know whether they're getting real or mock results.
    - /dock dispatches to the appropriate path based on model kind.

Note: this service is intentionally tolerant of mock mode because the
Lead Optimizer gracefully degrades when no protein structure is available
(see optimize_complete.py — runs GenMol + RDKit + Nemotron SAR analysis
without docking when no PDB is provided).
"""
import os
import logging
import tempfile
from contextlib import asynccontextmanager
from typing import List
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("diffdock-service")

# Module-level globals — populated by lifespan startup
_model = None
_model_kind = None  # "bionemo" | "mock" | None


def _load_model():
    """Try to load BioNeMo DiffDockInference; fall back to mock mode."""
    global _model, _model_kind
    try:
        from bionemo.model.molecule.diffdock import DiffDockInference  # type: ignore
        logger.info("Loading BioNeMo DiffDockInference...")
        _model = DiffDockInference()
        _model_kind = "bionemo"
        logger.info("DiffDock V2 (BioNeMo) loaded successfully")
    except ImportError:
        logger.warning(
            "BioNeMo DiffDockInference not available — running in mock mode. "
            "Lead Optimizer will degrade gracefully when PDB structures are provided."
        )
        _model = "mock"
        _model_kind = "mock"
    except Exception as e:
        logger.error(f"Failed to load DiffDock: {e}", exc_info=True)
        _model = "mock"
        _model_kind = "mock"


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        _load_model()
    except Exception as e:
        logger.error(f"FATAL: DiffDock startup failed: {e}", exc_info=True)
    yield


app = FastAPI(title="MolForge DiffDock Service", version="1.1.0", lifespan=lifespan)


class DockRequest(BaseModel):
    protein_pdb_path: str
    ligand_smiles_list: List[str]
    num_poses: int = 5


@app.get("/health")
async def health():
    import torch
    return {
        "status": "healthy",
        "model_loaded": _model is not None,
        "model_kind": _model_kind,
        "gpu_available": torch.cuda.is_available(),
    }


@app.post("/dock")
async def dock(req: DockRequest):
    """Dock ligands against a protein target."""
    if _model is None:
        raise HTTPException(status_code=503, detail="DiffDock not loaded — check pod startup logs")

    try:
        import time
        start = time.time()
        results = []

        if _model_kind == "mock" or _model == "mock":
            import random
            for smi in req.ligand_smiles_list:
                results.append({
                    "smiles": smi,
                    "confidence_score": round(random.uniform(0.3, 0.95), 4),
                    "top_pose_sdf": f"MOCK_SDF_FOR_{smi}",
                    "num_poses_generated": req.num_poses,
                    "binding_pocket_residues": ["ALA123", "GLY456", "LEU789"],
                    "_mock": True,
                })
        else:
            from google.cloud import storage

            if req.protein_pdb_path.startswith("gs://"):
                client = storage.Client()
                bucket_name = req.protein_pdb_path.split("/")[2]
                blob_path = "/".join(req.protein_pdb_path.split("/")[3:])
                bucket = client.bucket(bucket_name)
                blob = bucket.blob(blob_path)

                with tempfile.NamedTemporaryFile(suffix=".pdb", delete=False) as tmp:
                    blob.download_to_filename(tmp.name)
                    pdb_path = tmp.name
            else:
                pdb_path = req.protein_pdb_path

            for smi in req.ligand_smiles_list:
                try:
                    dock_result = _model.dock(
                        protein_path=pdb_path,
                        ligand_smiles=smi,
                        num_poses=req.num_poses,
                    )
                    results.append({
                        "smiles": smi,
                        "confidence_score": float(dock_result.confidence),
                        "top_pose_sdf": dock_result.top_pose_sdf,
                        "num_poses_generated": len(dock_result.poses),
                        "binding_pocket_residues": dock_result.contact_residues,
                    })
                except Exception as e:
                    logger.warning(f"Docking failed for {smi}: {e}")
                    results.append({
                        "smiles": smi,
                        "confidence_score": 0.0,
                        "error": str(e),
                    })

        elapsed = time.time() - start
        docked = [r for r in results if "error" not in r]
        failed = [r for r in results if "error" in r]

        return {
            "protein_pdb": req.protein_pdb_path,
            "model_kind": _model_kind,
            "docked_count": len(docked),
            "failed_count": len(failed),
            "results": results,
            "batch_processing_time_seconds": round(elapsed, 2),
        }

    except Exception as e:
        logger.error(f"Docking failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
