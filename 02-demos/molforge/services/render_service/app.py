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
MolForge Render Service — server-side molecular rendering for inline display
in Gemini Enterprise via A2UI.

Phase 1 scope: 2D structure rendering (RDKit → PNG). A2UI's `Image` component
needs raster bytes; all prior MolForge rendering was client-side (RDKit-JS /
3Dmol.js in the viewer), so this service produces the PNGs the A2A bridge
embeds inline.

Phase 2 will add `/render/3d` (headless PyMOL ray-trace + turntable).

Runs on Cloud Run (CPU) — deliberately off the Blackwell GPU so renders never
steal inference cycles.

Author: Schneider Larbi
        Senior Manager, Global Partner Technical Architecture — AI & SaaS ISVs
        Google Cloud
"""
import os
import base64
import logging
from typing import Optional

from fastapi import FastAPI
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("molforge-render")

# The interactive API docs are off by default: this service is public and
# unauthenticated, so there is no reason to publish its schema. Set
# MOLFORGE_API_DOCS=1 to expose /docs, /redoc and /openapi.json while debugging.
_API_DOCS = os.getenv("MOLFORGE_API_DOCS", "0") != "0"

app = FastAPI(
    title="MolForge Render Service",
    version="1.0.0",
    docs_url="/docs" if _API_DOCS else None,
    redoc_url="/redoc" if _API_DOCS else None,
    openapi_url="/openapi.json" if _API_DOCS else None,
)

DEFAULT_SIZE = int(os.getenv("RENDER_DEFAULT_SIZE", "320"))
MAX_MOLECULES = int(os.getenv("RENDER_MAX_MOLECULES", "50"))


class Render2DRequest(BaseModel):
    smiles: Optional[str] = None
    smiles_list: Optional[list] = None
    legends: Optional[list] = None
    size: int = DEFAULT_SIZE


class Render3DRequest(BaseModel):
    protein_pdb: Optional[str] = None   # gs:// uri, http(s):// url, or inline PDB content
    ligand_sdf: Optional[str] = None    # gs:// uri, http(s):// url, or inline SDF content
    color_by: str = "chain"             # "plddt" (folding) | "chain" (docking)
    size: int = 640
    mode: str = "snapshot"              # "snapshot" (PNG) | "turntable" (GIF)


def _render_one(smiles: str, size: int, legend: str = "") -> dict:
    """Render a single SMILES to a PNG (base64). Returns an outcome dict."""
    from rdkit import Chem
    from rdkit.Chem.Draw import rdMolDraw2D

    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return {"smiles": smiles, "ok": False, "error": "invalid SMILES"}
    try:
        drawer = rdMolDraw2D.MolDraw2DCairo(size, size)
        opts = drawer.drawOptions()
        opts.clearBackground = True
        if legend:
            opts.legendFontSize = max(12, size // 24)
        rdMolDraw2D.PrepareAndDrawMolecule(drawer, mol, legend=legend or "")
        drawer.FinishDrawing()
        png = drawer.GetDrawingText()  # bytes
        return {
            "smiles": smiles,
            "ok": True,
            "png_b64": base64.b64encode(png).decode("ascii"),
            "mime_type": "image/png",
        }
    except Exception as e:  # pragma: no cover - defensive
        logger.warning(f"render failed for {smiles[:40]}: {e}")
        return {"smiles": smiles, "ok": False, "error": str(e)[:200]}


def _resolution_error(exc: Exception) -> str:
    """Log a resolution failure and return what is safe to tell the caller.

    StructureResolutionError messages are written to be caller-safe. Anything
    else (auth failures, transport errors) can carry internal detail, so it is
    logged and reported generically.
    """
    import mol3d

    logger.warning(f"3D input resolution failed: {exc}")
    if isinstance(exc, mol3d.StructureResolutionError):
        return f"input resolution failed: {exc}"
    return "input resolution failed"


@app.get("/health")
async def health():
    try:
        import rdkit  # noqa: F401
        rdkit_ok = True
    except Exception:
        rdkit_ok = False
    return {"status": "healthy", "service": "molforge-render", "rdkit": rdkit_ok}


@app.post("/render/2d")
async def render_2d(req: Render2DRequest):
    """Render one or more SMILES to PNG (base64).

    Body: {"smiles": "CCO"} or {"smiles_list": ["CCO", ...], "legends": [...], "size": 320}
    Returns: {"count": N, "images": [{"smiles", "ok", "png_b64", "mime_type"} | {"smiles","ok":false,"error"}]}
    """
    smiles_list = req.smiles_list or ([req.smiles] if req.smiles else [])
    smiles_list = [s for s in smiles_list if isinstance(s, str) and s.strip()]
    if not smiles_list:
        return JSONResponse(status_code=400, content={"error": "no SMILES provided"})

    truncated = len(smiles_list) > MAX_MOLECULES
    smiles_list = smiles_list[:MAX_MOLECULES]
    legends = req.legends or []
    size = max(64, min(req.size or DEFAULT_SIZE, 1024))

    images = [
        _render_one(s, size, legends[i] if i < len(legends) else "")
        for i, s in enumerate(smiles_list)
    ]
    return {
        "count": len(images),
        "rendered": sum(1 for im in images if im.get("ok")),
        "truncated": truncated,
        "images": images,
    }


@app.post("/render/3d")
async def render_3d(req: Render3DRequest):
    """Render a 3D structure (protein cartoon + ligand sticks) to PNG/GIF.

    Body: {"protein_pdb": "gs://.../protein.pdb", "ligand_sdf": "gs://.../pose.sdf",
           "color_by": "chain"|"plddt", "mode": "snapshot"|"turntable", "size": 640}
    Either protein_pdb or ligand_sdf (or both) is required.
    Returns: {"ok", "png_b64", "mime_type", "renderer"} or {"ok": false, "error"}.
    """
    import mol3d

    if not req.protein_pdb and not req.ligand_sdf:
        return JSONResponse(status_code=400, content={"error": "protein_pdb or ligand_sdf required"})
    try:
        protein = mol3d.resolve_uri(req.protein_pdb) if req.protein_pdb else None
        ligand = mol3d.resolve_uri(req.ligand_sdf) if req.ligand_sdf else None
    except Exception as e:
        return JSONResponse(status_code=400, content={"error": _resolution_error(e)})

    out = mol3d.render_structure(
        protein_pdb=protein, ligand_sdf=ligand,
        color_by=req.color_by, size=req.size, mode=req.mode,
    )
    return out


@app.get("/render/2d.png")
async def render_2d_png(smiles: str, size: int = DEFAULT_SIZE):
    """Convenience: render a single SMILES and return raw PNG bytes (for <img> / quick tests)."""
    size = max(64, min(size, 1024))
    out = _render_one(smiles, size)
    if not out.get("ok"):
        return JSONResponse(status_code=400, content={"error": out.get("error", "render failed")})
    return Response(content=base64.b64decode(out["png_b64"]), media_type="image/png")


RENDER_CACHE_BUCKET = os.getenv("MOLFORGE_ARTIFACTS_BUCKET", "molforge-artifacts")
# Bump to invalidate all cached renders after changing renderer/turntable settings.
RENDER_VERSION = os.getenv("MOLFORGE_RENDER_VERSION", "v2-smooth16")


def _cache_key(protein, ligand, color_by, size, mode) -> str:
    import hashlib
    raw = f"{RENDER_VERSION}|{protein}|{ligand}|{color_by}|{size}|{mode}".encode()
    return hashlib.sha256(raw).hexdigest()[:40]


@app.get("/render/3d.png")
async def render_3d_png(protein: str = None, ligand: str = None,
                        color_by: str = "chain", size: int = 640, mode: str = "snapshot"):
    """Render a 3D structure to raw image bytes (PNG snapshot or GIF turntable) — so an
    A2UI Image component (or <img>) can source it by URL. `protein`/`ligand` are gs://
    (or http/inline) URIs resolved via GCS.

    PER-STRUCTURE CACHE: the result is keyed by a hash of (protein, ligand, color_by,
    size, mode) and stored at gs://<bucket>/renders/<key>.<ext>. Each distinct structure
    has its own key, so a cache hit only ever serves the EXACT same inputs — different
    proteins/poses always render fresh. This makes the expensive PyMOL turntable render
    once per structure, then serve instantly.
    """
    import mol3d

    if not protein and not ligand:
        return JSONResponse(status_code=400, content={"error": "protein or ligand required"})
    size = max(128, min(size, 1600))
    ext = "gif" if mode == "turntable" else "png"
    mime = "image/gif" if ext == "gif" else "image/png"
    key = _cache_key(protein, ligand, color_by, size, mode)
    blob_path = f"renders/{key}.{ext}"

    bucket = None
    try:
        from google.cloud import storage
        bucket = storage.Client().bucket(RENDER_CACHE_BUCKET)
        blob = bucket.blob(blob_path)
        if blob.exists():
            logger.info(f"3D cache HIT {blob_path}")
            return Response(content=blob.download_as_bytes(), media_type=mime,
                            headers={"X-Cache": "hit"})
    except Exception as e:
        logger.warning(f"3D cache lookup failed: {e}")

    try:
        p = mol3d.resolve_uri(protein) if protein else None
        lig = mol3d.resolve_uri(ligand) if ligand else None
    except Exception as e:
        return JSONResponse(status_code=400, content={"error": _resolution_error(e)})
    out = mol3d.render_structure(protein_pdb=p, ligand_sdf=lig,
                                 color_by=color_by, size=size, mode=mode)
    if not out.get("ok"):
        return JSONResponse(status_code=400, content={"error": out.get("error", "render failed")})
    data = base64.b64decode(out["png_b64"])
    mime = out.get("mime_type", mime)
    if bucket is not None:
        try:
            bucket.blob(blob_path).upload_from_string(data, content_type=mime)
            logger.info(f"3D cache STORE {blob_path} ({len(data)} bytes, {out.get('renderer')})")
        except Exception as e:
            logger.warning(f"3D cache store failed: {e}")
    return Response(content=data, media_type=mime, headers={"X-Cache": "miss"})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8080")))
