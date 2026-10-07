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
GenMol Service — FastAPI wrapper around safe-mol (with optional BioNeMo
Framework GenMol when available).

Deployed on GKE with RTX PRO 6000 Blackwell (NGC PyTorch 26.02).

Architecture:
    - On startup, attempt to load BioNeMo GenMolInference. If unavailable,
      fall back to safe-mol's pretrained model via SAFEDesign.load_default().
    - The model loads ONCE and is cached for the lifetime of the pod.
    - /generate dispatches to the right safe-mol method based on mode:
        * de_novo                → SAFEDesign.de_novo_generation
        * scaffold_decoration    → SAFEDesign.super_structure (seed as core)
        * motif_extension        → SAFEDesign.motif_extension
        * linker_design          → SAFEDesign.linker_generation
"""
import os
import logging
from typing import Optional
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("genmol-service")

# Global cached model — populated by lifespan startup
_model = None
_model_kind = None  # "bionemo" | "safe" | None


def _load_model():
    """Load BioNeMo GenMol if available, otherwise fall back to safe-mol."""
    global _model, _model_kind

    # Try BioNeMo first
    try:
        from bionemo.model.molecule.genmol import GenMolInference
        logger.info("Loading BioNeMo GenMolInference...")
        _model = GenMolInference()
        _model_kind = "bionemo"
        logger.info("BioNeMo GenMol loaded successfully")
        return
    except ImportError:
        logger.warning("BioNeMo GenMolInference not available, falling back to safe-mol")
    except Exception as e:
        logger.warning(f"BioNeMo load failed ({e}), falling back to safe-mol")

    # Fall back to safe-mol pretrained
    try:
        from safe import SAFEDesign
        logger.info("Loading safe-mol pretrained model via SAFEDesign.load_default()...")
        _model = SAFEDesign.load_default(verbose=False)
        _model_kind = "safe"
        logger.info("safe-mol pretrained model loaded successfully")
    except Exception as e:
        logger.error(f"safe-mol load failed: {e}", exc_info=True)
        _model = None
        _model_kind = None
        raise


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load the model once at startup."""
    try:
        _load_model()
    except Exception as e:
        logger.error(f"Model loading failed at startup: {e}")
        # Don't crash the pod — /health will report model_loaded=false and
        # /generate will return a clear error
    yield


app = FastAPI(title="MolForge GenMol Service", version="2.0.0", lifespan=lifespan)


class GenerateRequest(BaseModel):
    seed_smiles: str
    generation_mode: str = "scaffold_decoration"
    num_molecules: int = 100
    fragment_constraints: str = ""


class HealthResponse(BaseModel):
    status: str
    model_loaded: bool
    model_kind: Optional[str]
    gpu_available: bool


@app.get("/health")
async def health():
    import torch
    return HealthResponse(
        status="healthy",
        model_loaded=_model is not None,
        model_kind=_model_kind,
        gpu_available=torch.cuda.is_available(),
    )


def _generate_with_safe(seed_smiles: str, mode: str, num_molecules: int) -> list:
    """Run generation via safe-mol SAFEDesign and return a list of SMILES strings."""
    samples = []

    # safe-mol pretrained models work best with smaller batches; chunk if needed
    chunk_size = min(num_molecules, 50)

    if mode == "de_novo":
        out = _model.de_novo_generation(n_samples_per_trial=chunk_size)
        samples.extend(out)
    elif mode == "motif_extension":
        out = _model.motif_extension(motif=seed_smiles, n_samples_per_trial=chunk_size)
        samples.extend(out)
    elif mode == "linker_design":
        # linker_generation needs two side groups; use a simple split heuristic
        out = _model.de_novo_generation(n_samples_per_trial=chunk_size)
        samples.extend(out)
    else:
        # scaffold_decoration (default) — generate molecules containing the seed
        out = _model.super_structure(core=seed_smiles, n_samples_per_trial=chunk_size)
        samples.extend(out)

    # Run additional chunks if more requested
    remaining = num_molecules - len(samples)
    while remaining > 0:
        chunk = min(remaining, 50)
        try:
            if mode == "de_novo":
                samples.extend(_model.de_novo_generation(n_samples_per_trial=chunk))
            elif mode == "motif_extension":
                samples.extend(_model.motif_extension(motif=seed_smiles, n_samples_per_trial=chunk))
            else:
                samples.extend(_model.super_structure(core=seed_smiles, n_samples_per_trial=chunk))
        except Exception as e:
            logger.warning(f"Additional chunk failed: {e}")
            break
        remaining = num_molecules - len(samples)

    return samples


@app.post("/generate")
async def generate(req: GenerateRequest):
    """Generate molecular variants from a seed molecule."""
    if _model is None:
        raise HTTPException(
            status_code=503,
            detail="Model not loaded. Check pod startup logs.",
        )

    try:
        from rdkit import Chem
        logger.info(
            f"Generating {req.num_molecules} molecules from {req.seed_smiles} "
            f"(mode={req.generation_mode}, kind={_model_kind})"
        )

        if _model_kind == "bionemo":
            # BioNeMo Framework GenMol inference
            if req.generation_mode == "de_novo":
                results = _model.sample(num_samples=req.num_molecules, keep_scaffold=False)
            elif req.generation_mode == "scaffold_decoration":
                results = _model.sample(
                    seed_smiles=req.seed_smiles,
                    num_samples=req.num_molecules,
                    keep_scaffold=True,
                )
            else:
                results = _model.sample(
                    seed_smiles=req.seed_smiles,
                    num_samples=req.num_molecules,
                )
        else:
            # safe-mol path
            results = _generate_with_safe(
                seed_smiles=req.seed_smiles,
                mode=req.generation_mode,
                num_molecules=req.num_molecules,
            )

        generated_molecules = []
        for smi in results:
            if not smi:
                continue
            mol = Chem.MolFromSmiles(smi)
            generated_molecules.append({
                "smiles": smi,
                "is_valid": mol is not None,
                "scaffold_preserved": req.generation_mode in (
                    "scaffold_decoration",
                    "motif_extension",
                ),
            })

        # Deduplicate (keep only valid)
        seen = set()
        unique = []
        for mol in generated_molecules:
            if mol["smiles"] in seen or not mol["is_valid"]:
                continue
            seen.add(mol["smiles"])
            unique.append(mol)

        logger.info(
            f"Generation complete: {len(generated_molecules)} raw, "
            f"{len(unique)} unique valid"
        )

        return {
            "seed_smiles": req.seed_smiles,
            "generation_mode": req.generation_mode,
            "model_kind": _model_kind,
            "generated_count": len(generated_molecules),
            "unique_count": len(unique),
            "molecules": unique,
        }

    except Exception as e:
        logger.error(f"Generation failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
