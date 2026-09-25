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
Data Retrieval Service — unified API for querying public biological databases.
Wraps RCSB PDB, UniProt, ChEMBL, and ZINC20 behind a consistent interface.
CPU-only, no GPU required.
"""
import os
import logging
import requests as http_requests
from typing import Optional
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("data-retrieval-service")

app = FastAPI(title="MolForge Data Retrieval Service", version="1.0.0")

GCS_BUCKET = os.getenv("MOLFORGE_ARTIFACTS_BUCKET", "molforge-artifacts")


# ── Request Models ──

class ProteinStructureRequest(BaseModel):
    query: str
    query_type: str = "name"


class ProteinSequenceRequest(BaseModel):
    query: str
    query_type: str = "name"


class KnownActivesRequest(BaseModel):
    target_query: str
    max_results: int = 50
    activity_threshold_um: float = 1.0


class PurchasableSimilarRequest(BaseModel):
    query_smiles: str
    similarity_threshold: float = 0.7
    max_results: int = 20


# ── Health ──

@app.get("/health")
async def health():
    return {"status": "healthy", "databases": ["RCSB PDB", "UniProt", "ChEMBL", "ZINC20"]}


# ── RCSB PDB ──

@app.post("/protein/structure")
async def fetch_protein_structure(req: ProteinStructureRequest):
    """Fetch protein 3D structure from RCSB Protein Data Bank."""
    try:
        if req.query_type == "pdb_id":
            pdb_id = req.query.upper().strip()
        else:
            # Hardened RCSB resolution. Multi-strategy so it finds the RIGHT protein, not
            # just any high-res text match:
            #   • mutation queries ("BRAF V600E") → full_text first to catch the exact mutant
            #     structure (→ 6V34); if none, fall back to the gene-name match.
            #   • plain names/symbols ("EGFR", "KIT") → exact GENE-NAME match (precise:
            #     KIT→c-KIT, PTGS2→COX-2), then full_text as a last resort.
            # Gene-name search is far more precise than full_text, which alone returns
            # irrelevant high-res hits for ambiguous terms.
            import re as _re
            search_url = "https://search.rcsb.org/rcsbsearch/v2/query"
            q = req.query.strip()
            stripped = _re.sub(r"\s+", " ", _re.sub(r"\b[A-Z]\d{1,4}[A-Z]\b", "", q)).strip()
            has_mut = bool(_re.search(r"\b[A-Z]\d{1,4}[A-Z]\b", q))

            def _gene(value):
                return {"query": {"type": "terminal", "service": "text", "parameters": {
                            "attribute": "rcsb_entity_source_organism.rcsb_gene_name.value",
                            "operator": "exact_match", "value": value.upper()}},
                        "return_type": "entry",
                        "request_options": {"results_content_type": ["experimental"],
                            "sort": [{"sort_by": "rcsb_entry_info.resolution_combined", "direction": "asc"}],
                            "paginate": {"start": 0, "rows": 1}}}

            def _ftext(value):
                return {"query": {"type": "terminal", "service": "full_text",
                                  "parameters": {"value": value}},
                        "return_type": "entry",
                        "request_options": {"results_content_type": ["experimental"],
                                            "paginate": {"start": 0, "rows": 1}}}

            if has_mut:
                attempts = [_ftext(q), _gene(stripped or q), _ftext(stripped or q)]
            else:
                attempts = [_gene(q), _ftext(q)]

            pdb_id = None
            for payload in attempts:
                try:
                    resp = http_requests.post(search_url, json=payload, timeout=15)
                    if resp.status_code == 200 and resp.json().get("result_set"):
                        pdb_id = resp.json()["result_set"][0]["identifier"]
                        break
                except Exception:
                    continue
            if not pdb_id:
                return {"error": f"No PDB structure found for query: {req.query}"}

        # Fetch structure metadata
        meta_url = f"https://data.rcsb.org/rest/v1/core/entry/{pdb_id}"
        meta_resp = http_requests.get(meta_url, timeout=15)
        meta_resp.raise_for_status()
        meta = meta_resp.json()

        # Check for bound ligands
        ligand_smiles = ""
        has_ligand = False
        try:
            ligand_url = f"https://data.rcsb.org/rest/v1/core/nonpolymer_entity/{pdb_id}/1"
            lig_resp = http_requests.get(ligand_url, timeout=10)
            if lig_resp.status_code == 200:
                has_ligand = True
                lig_data = lig_resp.json()
                ligand_smiles = lig_data.get("rcsb_nonpolymer_entity_container_identifiers", {}).get("chem_comp_id", "")
        except Exception:
            pass

        resolution = None
        if "rcsb_entry_info" in meta:
            resolution = meta["rcsb_entry_info"].get("resolution_combined", [None])[0]

        # Download the PDB from RCSB and cache it to GCS so the pipeline has a REAL,
        # existing gs:// path — and never has to invent one. (The prior empty gcs_path
        # invited the orchestrator LLM to hallucinate a bogus path → docking 404.)
        gcs_path = ""
        try:
            from google.cloud import storage as _gcs
            pdb_text = http_requests.get(f"https://files.rcsb.org/download/{pdb_id}.pdb", timeout=25).text
            if pdb_text and pdb_text.lstrip().startswith(("HEADER", "ATOM", "CRYST", "TITLE")):
                bucket_name = os.getenv("MOLFORGE_ARTIFACTS_BUCKET", "molforge-artifacts")
                blob_path = f"structures/{pdb_id}.pdb"
                _gcs.Client().bucket(bucket_name).blob(blob_path).upload_from_string(
                    pdb_text, content_type="chemical/x-pdb")
                gcs_path = f"gs://{bucket_name}/{blob_path}"
        except Exception as e:
            logger.warning(f"PDB GCS cache failed for {pdb_id}: {e}")

        return {
            "pdb_id": pdb_id,
            "title": meta.get("struct", {}).get("title", ""),
            "resolution": resolution,
            "method": meta.get("rcsb_entry_info", {}).get("experimental_method", ""),
            "organism": meta.get("rcsb_entry_info", {}).get("organism_scientific_name", ""),
            "pdb_url": f"https://files.rcsb.org/download/{pdb_id}.pdb",
            "gcs_path": gcs_path,
            "has_ligand": has_ligand,
            "ligand_smiles": ligand_smiles,
        }

    except Exception as e:
        logger.error(f"PDB fetch failed: {e}")
        return {"error": f"Failed to fetch protein structure: {str(e)}"}


# ── UniProt ──

@app.post("/protein/sequence")
async def fetch_protein_sequence(req: ProteinSequenceRequest):
    """Fetch protein sequence and annotations from UniProt."""
    try:
        if req.query_type == "uniprot_id":
            uniprot_id = req.query.strip()
        else:
            # Search UniProt by protein name or gene
            search_url = f"https://rest.uniprot.org/uniprotkb/search?query={req.query}&format=json&size=1"
            resp = http_requests.get(search_url, timeout=15)
            resp.raise_for_status()
            results = resp.json()
            if not results.get("results"):
                return {"error": f"No UniProt entry found for: {req.query}"}
            uniprot_id = results["results"][0]["primaryAccession"]

        # Fetch full entry
        entry_url = f"https://rest.uniprot.org/uniprotkb/{uniprot_id}.json"
        entry_resp = http_requests.get(entry_url, timeout=15)
        entry_resp.raise_for_status()
        entry = entry_resp.json()

        # Extract sequence
        sequence = entry.get("sequence", {}).get("value", "")

        # Extract protein name
        protein_name = ""
        if "proteinDescription" in entry:
            rec_name = entry["proteinDescription"].get("recommendedName", {})
            protein_name = rec_name.get("fullName", {}).get("value", "")

        # Extract function
        function_text = ""
        for comment in entry.get("comments", []):
            if comment.get("commentType") == "FUNCTION":
                texts = comment.get("texts", [])
                if texts:
                    function_text = texts[0].get("value", "")
                break

        # Extract domains
        domains = []
        for feature in entry.get("features", []):
            if feature.get("type") == "Domain":
                domains.append({
                    "name": feature.get("description", ""),
                    "start": feature.get("location", {}).get("start", {}).get("value"),
                    "end": feature.get("location", {}).get("end", {}).get("value"),
                })

        # Extract disease associations
        diseases = []
        for comment in entry.get("comments", []):
            if comment.get("commentType") == "DISEASE":
                disease = comment.get("disease", {})
                if disease:
                    diseases.append(disease.get("diseaseId", ""))

        return {
            "uniprot_id": uniprot_id,
            "protein_name": protein_name,
            "sequence": sequence,
            "sequence_length": len(sequence),
            "organism": entry.get("organism", {}).get("scientificName", ""),
            "function": function_text,
            "domains": domains,
            "active_sites": [],
            "disease_associations": diseases,
            "known_mutations": [],
        }

    except Exception as e:
        logger.error(f"UniProt fetch failed: {e}")
        return {"error": f"Failed to fetch protein sequence: {str(e)}"}


# ── ChEMBL ──

@app.post("/compound/known-actives")
async def fetch_known_actives(req: KnownActivesRequest):
    """Fetch known active compounds for a target from ChEMBL."""
    try:
        # Search for target
        target_url = f"https://www.ebi.ac.uk/chembl/api/data/target/search.json?q={req.target_query}&limit=1"
        target_resp = http_requests.get(target_url, timeout=15)
        target_resp.raise_for_status()
        target_data = target_resp.json()

        if not target_data.get("targets"):
            return {"error": f"No ChEMBL target found for: {req.target_query}"}

        target = target_data["targets"][0]
        target_chembl_id = target["target_chembl_id"]
        target_name = target.get("pref_name", req.target_query)

        # Fetch activities
        activity_url = (
            f"https://www.ebi.ac.uk/chembl/api/data/activity.json"
            f"?target_chembl_id={target_chembl_id}"
            f"&standard_type__in=IC50,Ki,Kd"
            f"&standard_value__lte={req.activity_threshold_um * 1000}"
            f"&limit={req.max_results}"
        )
        act_resp = http_requests.get(activity_url, timeout=30)
        act_resp.raise_for_status()
        act_data = act_resp.json()

        compounds = []
        seen_ids = set()
        for activity in act_data.get("activities", []):
            mol_id = activity.get("molecule_chembl_id", "")
            if mol_id in seen_ids:
                continue
            seen_ids.add(mol_id)

            smiles = activity.get("canonical_smiles", "")
            if not smiles:
                continue

            std_value = activity.get("standard_value")
            activity_um = float(std_value) / 1000.0 if std_value else None

            compounds.append({
                "smiles": smiles,
                "chembl_id": mol_id,
                "activity_type": activity.get("standard_type", ""),
                "activity_value_um": round(activity_um, 4) if activity_um else None,
                "assay_description": activity.get("assay_description", "")[:200],
            })

        return {
            "target_name": target_name,
            "target_chembl_id": target_chembl_id,
            "compound_count": len(compounds),
            "compounds": compounds,
        }

    except Exception as e:
        logger.error(f"ChEMBL fetch failed: {e}")
        return {"error": f"Failed to fetch known actives: {str(e)}"}


# ── ZINC20 ──

@app.post("/compound/purchasable-similar")
async def fetch_purchasable_similar(req: PurchasableSimilarRequest):
    """Search ZINC20 for purchasable compounds similar to a query molecule."""
    try:
        zinc_url = f"https://zinc20.docking.org/substances/similarity/{req.query_smiles}"
        params = {
            "threshold": req.similarity_threshold,
            "count": req.max_results,
            "output": "json",
        }
        resp = http_requests.get(zinc_url, params=params, timeout=30)

        if resp.status_code != 200:
            return {
                "query_smiles": req.query_smiles,
                "similar_count": 0,
                "compounds": [],
                "note": "ZINC20 search returned no results or service unavailable",
            }

        zinc_data = resp.json()
        compounds = []
        for item in zinc_data:
            compounds.append({
                "smiles": item.get("smiles", ""),
                "zinc_id": item.get("zinc_id", ""),
                "similarity": item.get("similarity", 0),
                "vendor": item.get("vendor", ""),
                "catalog_id": item.get("catalog_id", ""),
            })

        return {
            "query_smiles": req.query_smiles,
            "similar_count": len(compounds),
            "compounds": compounds,
        }

    except Exception as e:
        logger.error(f"ZINC20 search failed: {e}")
        return {"error": f"Failed to search ZINC20: {str(e)}"}
