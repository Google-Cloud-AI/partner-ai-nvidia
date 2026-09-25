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
RDKit Service — molecular property calculation and 2D structure rendering.
CPU-only, no GPU required.
"""
import logging
from typing import List, Optional
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from rdkit import Chem
from rdkit.Chem import Descriptors, Draw, rdMolDescriptors, QED
from rdkit.Chem.Draw import rdMolDraw2D

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("rdkit-service")

app = FastAPI(title="MolForge RDKit Service", version="1.0.0")


class PropertiesRequest(BaseModel):
    smiles_list: List[str]


class RenderRequest(BaseModel):
    smiles: str
    highlight_scaffold: str = ""
    width: int = 400
    height: int = 300


@app.get("/health")
async def health():
    return {"status": "healthy", "rdkit_version": Chem.rdBase.rdkitVersion}


@app.post("/properties")
async def compute_properties(req: PropertiesRequest):
    """Compute physicochemical properties for a list of molecules."""
    results = []
    failed = 0

    for smi in req.smiles_list:
        mol = Chem.MolFromSmiles(smi)
        if mol is None:
            results.append({"smiles": smi, "error": "Invalid SMILES"})
            failed += 1
            continue

        mw = Descriptors.MolWt(mol)
        logp = Descriptors.MolLogP(mol)
        hbd = rdMolDescriptors.CalcNumHBD(mol)
        hba = rdMolDescriptors.CalcNumHBA(mol)
        tpsa = Descriptors.TPSA(mol)
        rotatable = rdMolDescriptors.CalcNumRotatableBonds(mol)
        num_rings = rdMolDescriptors.CalcNumRings(mol)

        # Lipinski violations
        violations = sum([
            mw > 500,
            logp > 5,
            hbd > 5,
            hba > 10,
        ])

        try:
            qed_score = round(QED.qed(mol), 4)
        except Exception:
            qed_score = None

        # Synthetic accessibility (SA score approximation using fragment-based method)
        try:
            from rdkit.Chem import RDConfig
            import os
            from rdkit.Contrib.SA_Score import sascorer
            sa_score = round(sascorer.calculateScore(mol), 2)
        except Exception:
            sa_score = None

        results.append({
            "smiles": smi,
            "molecular_weight": round(mw, 2),
            "logp": round(logp, 2),
            "hbd": hbd,
            "hba": hba,
            "tpsa": round(tpsa, 2),
            "rotatable_bonds": rotatable,
            "num_rings": num_rings,
            "lipinski_violations": violations,
            "lipinski_pass": violations <= 1,
            "qed": qed_score,
            "sa_score": sa_score,
        })

    return {
        "computed_count": len(results) - failed,
        "failed_count": failed,
        "results": results,
    }


@app.post("/render")
async def render_molecule(req: RenderRequest):
    """Generate a 2D structure diagram as SVG."""
    mol = Chem.MolFromSmiles(req.smiles)
    if mol is None:
        raise HTTPException(status_code=400, detail=f"Invalid SMILES: {req.smiles}")

    drawer = rdMolDraw2D.MolDraw2DSVG(req.width, req.height)

    if req.highlight_scaffold:
        scaffold = Chem.MolFromSmiles(req.highlight_scaffold)
        if scaffold:
            match = mol.GetSubstructMatch(scaffold)
            if match:
                drawer.DrawMolecule(mol, highlightAtoms=list(match))
            else:
                drawer.DrawMolecule(mol)
        else:
            drawer.DrawMolecule(mol)
    else:
        drawer.DrawMolecule(mol)

    drawer.FinishDrawing()
    svg = drawer.GetDrawingText()

    return {
        "smiles": req.smiles,
        "svg_content": svg,
    }
