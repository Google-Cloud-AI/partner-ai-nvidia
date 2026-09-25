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
Data Retrieval Tools for MolForge Orchestrator.

These tools query public biological databases (RCSB PDB, UniProt, ChEMBL, ZINC20)
via the Data Retrieval Service running on GKE. The service URL is configured via
environment variable.
"""
import os
import json
import urllib.parse
import requests
from google.adk.tools import FunctionTool

DATA_RETRIEVAL_URL = os.getenv(
    "MOLFORGE_DATA_RETRIEVAL_URL",
    "http://data-retrieval-service:8080"
)


def resolve_compound_smiles(compound_name: str) -> dict:
    """Resolve a compound NAME to its canonical SMILES via the PubChem PUG-REST API.

    Use this whenever the scientist names a compound (e.g., "Imatinib", "aspirin",
    "gefitinib") but does NOT provide a SMILES string. This is a deterministic database
    lookup of the real structure — NEVER guess, invent, or approximate a SMILES yourself.
    If this returns an error, tell the scientist the name could not be resolved; do not
    proceed with a made-up structure.

    Args:
        compound_name: Common, brand, or IUPAC name of the compound (e.g., "Imatinib").

    Returns:
        dict with keys:
            - compound_name: echo of input
            - smiles: canonical/isomeric SMILES from PubChem ("" if unresolved)
            - cid: PubChem Compound ID (when found)
            - source: "PubChem"
            - error: present ONLY on failure (do not proceed/guess on error)
    """
    import time
    name = (compound_name or "").strip()
    if not name:
        return {"compound_name": compound_name, "smiles": "", "error": "empty compound name"}
    enc = urllib.parse.quote(name, safe="")
    ua = {"User-Agent": "MolForge/1.0 (NVIDIA x Google Cloud drug-discovery)"}
    errors = []

    # 1) NCI CACTUS (plain-text SMILES) — handles cloud egress IPs more reliably than PubChem.
    try:
        r = requests.get(f"https://cactus.nci.nih.gov/chemical/structure/{enc}/smiles",
                         headers=ua, timeout=20)
        if r.status_code == 200 and r.text.strip() and "Page not found" not in r.text:
            smi = r.text.strip().splitlines()[0].strip()
            if smi:
                return {"compound_name": name, "smiles": smi, "source": "NCI CACTUS"}
        elif r.status_code == 404:
            errors.append("CACTUS: not found")
        else:
            errors.append(f"CACTUS HTTP {r.status_code}")
    except requests.exceptions.RequestException as e:
        errors.append(f"CACTUS: {str(e)[:60]}")

    # 2) PubChem fallback (PUG-REST is rate-limited from cloud IPs → retry on 503 ServerBusy).
    url = (f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{enc}"
           f"/property/SMILES,ConnectivitySMILES/JSON")
    for attempt in range(3):
        try:
            r = requests.get(url, headers=ua, timeout=25)
            if r.status_code == 404:
                errors.append("PubChem: not found")
                break
            if r.status_code in (429, 500, 503):
                time.sleep(1.0 * (attempt + 1))
                continue
            r.raise_for_status()
            props = r.json()["PropertyTable"]["Properties"][0]
            smi = props.get("SMILES") or props.get("ConnectivitySMILES") or ""
            if smi:
                return {"compound_name": name, "smiles": smi,
                        "cid": props.get("CID"), "source": "PubChem"}
            errors.append("PubChem: no SMILES")
            break
        except requests.exceptions.RequestException as e:
            errors.append(f"PubChem: {str(e)[:60]}")

    return {"compound_name": name, "smiles": "",
            "error": f"Could not resolve '{name}' (CACTUS + PubChem unavailable): {'; '.join(errors[:3])}"}


def fetch_protein_structure(
    query: str,
    query_type: str = "name",
) -> dict:
    """Fetch a protein 3D structure from RCSB Protein Data Bank.

    Use this tool when the scientist specifies a target protein and you need
    its 3D structure for docking or visualization. Supports lookup by protein
    name, PDB ID, UniProt ID, or gene name.

    Args:
        query: The protein identifier. Examples: "BRAF V600E", "3OG7", "P15056", "EGFR"
        query_type: Type of identifier. One of: "name", "pdb_id", "uniprot_id", "gene"

    Returns:
        dict with keys:
            - pdb_id: The resolved PDB identifier
            - title: Structure title from PDB
            - resolution: Experimental resolution in Angstroms (lower is better)
            - method: Experimental method (X-ray, cryo-EM, NMR)
            - organism: Source organism
            - pdb_url: Direct download URL for the PDB file
            - gcs_path: Cloud Storage path where the structure was cached
            - has_ligand: Whether the structure contains a bound ligand
            - ligand_smiles: SMILES of bound ligand if present
    """
    try:
        response = requests.post(
            f"{DATA_RETRIEVAL_URL}/protein/structure",
            json={"query": query, "query_type": query_type},
            timeout=30,
        )
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        return {"error": f"Failed to fetch protein structure: {str(e)}"}


def fetch_protein_sequence(
    query: str,
    query_type: str = "name",
) -> dict:
    """Fetch protein sequence and functional annotations from UniProt.

    Use this tool when you need the amino acid sequence for structure prediction
    with ESMFold, or when you need functional annotations (domains, active sites,
    disease associations) to inform optimization strategy.

    Args:
        query: The protein identifier. Examples: "BRAF", "P15056", "EGFR"
        query_type: Type of identifier. One of: "name", "uniprot_id", "gene"

    Returns:
        dict with keys:
            - uniprot_id: The resolved UniProt identifier
            - protein_name: Full protein name
            - sequence: Amino acid sequence (one-letter code)
            - sequence_length: Number of residues
            - organism: Source organism
            - function: Functional description
            - domains: List of annotated domains with residue ranges
            - active_sites: List of known active site residues
            - disease_associations: Diseases linked to this protein
            - known_mutations: Clinically relevant mutations
    """
    try:
        response = requests.post(
            f"{DATA_RETRIEVAL_URL}/protein/sequence",
            json={"query": query, "query_type": query_type},
            timeout=30,
        )
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        return {"error": f"Failed to fetch protein sequence: {str(e)}"}


def fetch_known_actives(
    target_query: str,
    max_results: int = 50,
    activity_threshold_um: float = 1.0,
) -> dict:
    """Fetch known active compounds for a target protein from ChEMBL.

    Use this tool to gather reference compounds — molecules that have already
    been tested against this target with measured binding activity. This provides
    context for the Lead Optimization Agent: known scaffolds, activity ranges,
    and what has already been explored.

    Args:
        target_query: Target protein name or ChEMBL target ID. Examples: "BRAF", "CHEMBL5145"
        max_results: Maximum number of compounds to return (default 50)
        activity_threshold_um: Only return compounds with IC50/Ki below this value in micromolar (default 1.0)

    Returns:
        dict with keys:
            - target_name: Resolved target name
            - target_chembl_id: ChEMBL target identifier
            - compound_count: Number of active compounds found
            - compounds: List of dicts, each with:
                - smiles: Compound SMILES string
                - chembl_id: ChEMBL compound identifier
                - activity_type: IC50, Ki, Kd, etc.
                - activity_value_um: Activity value in micromolar
                - assay_description: Brief description of the assay
    """
    try:
        response = requests.post(
            f"{DATA_RETRIEVAL_URL}/compound/known-actives",
            json={
                "target_query": target_query,
                "max_results": max_results,
                "activity_threshold_um": activity_threshold_um,
            },
            timeout=30,
        )
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        return {"error": f"Failed to fetch known actives: {str(e)}"}


def fetch_purchasable_similar(
    query_smiles: str,
    similarity_threshold: float = 0.7,
    max_results: int = 20,
) -> dict:
    """Search ZINC20 for commercially purchasable compounds similar to a query molecule.

    Use this tool after Lead Optimization generates candidates, to check if similar
    molecules are already commercially available for immediate wet-lab testing
    without custom synthesis.

    Args:
        query_smiles: SMILES string of the query molecule
        similarity_threshold: Tanimoto similarity threshold (0.0-1.0, default 0.7)
        max_results: Maximum number of similar compounds to return (default 20)

    Returns:
        dict with keys:
            - query_smiles: The input molecule
            - similar_count: Number of similar purchasable compounds found
            - compounds: List of dicts, each with:
                - smiles: Purchasable compound SMILES
                - zinc_id: ZINC database identifier
                - similarity: Tanimoto similarity score
                - vendor: Commercial vendor name
                - catalog_id: Vendor catalog identifier
    """
    try:
        response = requests.post(
            f"{DATA_RETRIEVAL_URL}/compound/purchasable-similar",
            json={
                "query_smiles": query_smiles,
                "similarity_threshold": similarity_threshold,
                "max_results": max_results,
            },
            timeout=30,
        )
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        return {"error": f"Failed to search purchasable compounds: {str(e)}"}
