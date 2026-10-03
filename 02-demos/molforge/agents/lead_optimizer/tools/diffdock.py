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
DiffDock Tool — calls NVIDIA DiffDock NIM 2.2.0 for molecular docking.

Architecture (v2):
- DiffDock NIM 2.2.0 is consumed as an NVIDIA-HOSTED NIM (build.nvidia.com),
  NOT self-hosted: DiffDock 2.2.0 has no Blackwell (sm_120) build, so v2 runs it
  on NVIDIA's cloud. Override MOLFORGE_DIFFDOCK_URL to self-host the same NIM
  (e.g. in your own VPC) for IP-sensitive workloads.
- Uses NVIDIA's PLINDER+SAIR-trained checkpoints with cuEquivariance
  optimizations (~4 second batch inference for 10 ligands on a 263-residue
  kinase).

Key API points:
- Endpoint: POST /molecular-docking/diffdock/generate
- Request: { ligand, ligand_file_type ("txt"|"sdf"), protein, num_poses,
             time_divisions, steps, save_trajectory, is_staged }
- The protein field is the PDB ATOM lines joined by REAL newlines (not
  the bash backslash-n escape idiom — that breaks JSON encoding).
- Multi-chain crystals must be filtered to a single chain (we use chain A).
  Sending a multi-chain blob causes "Fail to generate complex graph - need
  at least one array to concatenate".
- The NIM has built-in RDKit, so SMILES can be sent directly with
  ligand_file_type="txt"; no client-side SDF generation needed.
- Batch mode: multiple SMILES separated by newlines docks them all in one
  NIM call. The response then has nested arrays indexed by ligand.

Author: Schneider Larbi
        Senior Manager, Global Partner Technical Architecture — AI & SaaS ISVs
        Google Cloud
"""
import os
import re
import json
import time
import logging
from datetime import datetime, timezone

import requests

from ._nvidia import get_nvidia_key

logger = logging.getLogger(__name__)

# v2: NVIDIA-HOSTED DiffDock NIM (build.nvidia.com). DiffDock NIM 2.2.0 has no
# Blackwell (sm_120) build, so v2 runs it on NVIDIA's cloud instead of a local
# A100 node. Override MOLFORGE_DIFFDOCK_URL to point at a self-hosted NIM.
DIFFDOCK_URL = os.getenv("MOLFORGE_DIFFDOCK_URL", "https://health.api.nvidia.com/v1/biology/mit/diffdock")
DIFFDOCK_GENERATE_PATH = os.getenv("MOLFORGE_DIFFDOCK_PATH", "")  # hosted URL is the full endpoint
GCS_BUCKET = os.getenv("MOLFORGE_ARTIFACTS_BUCKET", "molforge-artifacts")
VIEWER_BASE_URL = os.getenv("MOLFORGE_VIEWER_URL", "https://molforge-viewer.run.app")
RCSB_BASE = "https://files.rcsb.org/download"

NIM_TIMEOUT_SECONDS = 600


def _resolve_pdb_content(protein_pdb_path: str):
    """Resolve a protein input to (pdb_content_string, source_label).

    Accepts:
    - 4-character PDB ID (e.g., "2HYY") -> fetch from RCSB
    - http(s):// URL -> fetch directly
    - gs:// path -> fetch via google-cloud-storage (lazy import)
    - local file path -> read directly
    - inline PDB content (starts with HEADER/ATOM/HETATM) -> use as-is
    """
    s = (protein_pdb_path or "").strip()
    if not s:
        raise ValueError("protein_pdb_path is empty")

    if s.startswith(("HEADER", "ATOM", "HETATM")):
        return s, "inline_pdb"

    if re.fullmatch(r"[A-Za-z0-9]{4}", s):
        url = f"{RCSB_BASE}/{s.upper()}.pdb"
        logger.info(f"Fetching PDB {s.upper()} from RCSB: {url}")
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        return resp.text, f"rcsb:{s.upper()}"

    if s.startswith("gs://"):
        from google.cloud import storage
        client = storage.Client()
        path = s[5:]
        bucket_name, _, blob_path = path.partition("/")
        if not blob_path:
            raise ValueError(f"Invalid GCS path: {s}")
        blob = client.bucket(bucket_name).blob(blob_path)
        content = blob.download_as_text()
        return content, s

    if s.startswith(("http://", "https://")):
        resp = requests.get(s, timeout=60)
        resp.raise_for_status()
        return resp.text, s

    if os.path.isfile(s):
        with open(s) as f:
            return f.read(), s

    raise ValueError(
        f"Cannot resolve protein input: {s[:80]!r} is not a PDB ID, "
        "URL, GCS path, local file, or inline PDB content"
    )


def _filter_chain_a(pdb_content: str):
    """Extract ATOM lines for chain A only.

    Returns (chain_a_text, atom_count, residue_count). Falls back to all
    ATOM records if no chain A is found (proteins without chain IDs).
    """
    chain_a_lines = [
        line.rstrip()
        for line in pdb_content.split("\n")
        if line.startswith("ATOM") and len(line) > 21 and line[21] == "A"
    ]

    if not chain_a_lines:
        chain_a_lines = [
            line.rstrip()
            for line in pdb_content.split("\n")
            if line.startswith("ATOM")
        ]

    residues = set()
    for line in chain_a_lines:
        if len(line) >= 26:
            residues.add(line[22:26].strip())

    return "\n".join(chain_a_lines), len(chain_a_lines), len(residues)


def _save_protein_to_gcs(dock_id: str, pdb_content: str) -> str:
    """Save the chain-A-filtered protein PDB to GCS for the docking viewer."""
    if not pdb_content:
        return ""
    try:
        from google.cloud import storage
        client = storage.Client()
        bucket = client.bucket(GCS_BUCKET)
        blob_path = f"docking/{dock_id}/protein.pdb"
        blob = bucket.blob(blob_path)
        blob.upload_from_string(pdb_content, content_type="chemical/x-pdb")
        return f"gs://{GCS_BUCKET}/{blob_path}"
    except Exception as e:
        logger.warning(f"Failed to save protein PDB to GCS ({dock_id}): {e}")
        return ""


def _save_manifest_to_gcs(dock_id: str, manifest: dict) -> str:
    """Save the docking run manifest (ligand index ↔ SMILES + metadata) to GCS."""
    try:
        from google.cloud import storage
        client = storage.Client()
        bucket = client.bucket(GCS_BUCKET)
        blob_path = f"docking/{dock_id}/manifest.json"
        blob = bucket.blob(blob_path)
        blob.upload_from_string(
            json.dumps(manifest, indent=2, default=str),
            content_type="application/json",
        )
        return f"gs://{GCS_BUCKET}/{blob_path}"
    except Exception as e:
        logger.warning(f"Failed to save manifest to GCS ({dock_id}): {e}")
        return ""


def _save_pose_to_gcs(dock_id: str, ligand_idx: int, rank: int,
                      confidence: float, sdf_content: str) -> str:
    """Save a docking pose SDF to GCS and return the gs:// path."""
    if not sdf_content:
        return ""
    try:
        from google.cloud import storage
        client = storage.Client()
        bucket = client.bucket(GCS_BUCKET)
        conf_str = f"{confidence:.4f}" if confidence is not None else "none"
        blob_path = (
            f"docking/{dock_id}/lig{ligand_idx:03d}_rank{rank}_conf{conf_str}.sdf"
        )
        blob = bucket.blob(blob_path)
        blob.upload_from_string(sdf_content, content_type="chemical/x-mdl-sdfile")
        return f"gs://{GCS_BUCKET}/{blob_path}"
    except Exception as e:
        logger.warning(f"Failed to save pose to GCS ({dock_id}, lig{ligand_idx}, rank{rank}): {e}")
        return ""


def dock_molecules(
    protein_pdb_path: str,
    ligand_smiles_list: list,
    num_poses: int = 10,
) -> dict:
    """Dock ligands against a protein using NVIDIA DiffDock NIM 2.2.0.

    Use this tool for both atomic standalone docking and as the docking
    step inside the full lead optimization pipeline. Batch mode is used
    automatically when multiple SMILES are provided.

    Args:
        protein_pdb_path: PDB ID (e.g., "2HYY"), gs:// path, http(s):// URL,
            local file path, or inline PDB content (starting with HEADER/ATOM).
        ligand_smiles_list: List of SMILES strings to dock.
        num_poses: Poses generated per ligand (default 10).

    Returns:
        dict with:
            - status: "success" | "partial" | "failed"
            - dock_id: unique ID for this docking run
            - pdb_source: where the protein came from (rcsb:2HYY, gs://..., etc.)
            - protein_residue_count: residues in the parsed chain
            - num_ligands: count of ligands docked
            - docked_count: how many got valid poses
            - failed_count: how many failed
            - num_poses_per_ligand: echo of num_poses
            - elapsed_seconds: NIM call latency
            - results: list of per-ligand dicts:
                * smiles: input SMILES
                * status: per-ligand status
                * confidence: rank-1 confidence (DiffDock scale, higher = more confident)
                * binding_score: same value (for optimize_complete consumer)
                * binding_confidence: same value
                * pose_path: gs:// path to rank-1 pose SDF
                * num_poses: poses returned for this ligand
                * all_poses: list of {rank, confidence, pose_gcs_path}
            - errors: non-fatal errors
            - model, provider, infrastructure: provider attribution
    """
    dock_id = (
        f"dock_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_"
        f"{os.urandom(4).hex()}"
    )
    errors = []

    if not ligand_smiles_list:
        return {
            "status": "failed",
            "dock_id": dock_id,
            "error": "ligand_smiles_list is empty",
            "errors": ["empty ligand list"],
            "results": [],
            "model": "nvidia/diffdock:2.2.0",
            "provider": "NVIDIA",
        }

    # 1. Resolve protein
    try:
        pdb_content, pdb_source = _resolve_pdb_content(protein_pdb_path)
        logger.info(f"[{dock_id}] PDB resolved from {pdb_source} ({len(pdb_content)} chars)")
    except Exception as e:
        logger.error(f"[{dock_id}] PDB resolution failed: {e}")
        return {
            "status": "failed",
            "dock_id": dock_id,
            "error": f"Failed to resolve protein: {e}",
            "errors": [str(e)],
            "results": [],
            "model": "nvidia/diffdock:2.2.0",
            "provider": "NVIDIA",
        }

    # 2. Filter to chain A
    protein_bytes, atom_count, residue_count = _filter_chain_a(pdb_content)
    if not protein_bytes:
        return {
            "status": "failed",
            "dock_id": dock_id,
            "error": "No ATOM records found in protein PDB",
            "errors": ["empty atom list after chain A filter"],
            "results": [],
            "pdb_source": pdb_source,
            "model": "nvidia/diffdock:2.2.0",
            "provider": "NVIDIA",
        }
    logger.info(
        f"[{dock_id}] Chain A filter: {atom_count} atoms, {residue_count} residues"
    )

    # Persist chain-A protein PDB to GCS for the docking viewer
    protein_gcs_path = _save_protein_to_gcs(dock_id, protein_bytes)
    if protein_gcs_path:
        logger.info(f"[{dock_id}] Protein PDB saved: {protein_gcs_path}")

    # Persist manifest (ligand index ↔ SMILES + run metadata) for the docking viewer
    manifest = {
        "dock_id": dock_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "pdb_source": pdb_source,
        "protein_residue_count": residue_count,
        "protein_atom_count": atom_count,
        "num_ligands": len(ligand_smiles_list),
        "num_poses_per_ligand": int(num_poses),
        "ligands": [
            {"lig_idx": i, "smiles": s} for i, s in enumerate(ligand_smiles_list)
        ],
        "model": "nvidia/diffdock:2.2.0",
        "provider": "NVIDIA",
    }
    manifest_gcs_path = _save_manifest_to_gcs(dock_id, manifest)
    if manifest_gcs_path:
        logger.info(f"[{dock_id}] Manifest saved: {manifest_gcs_path}")

    # 3. Build batch ligand text
    #
    # Blank entries are dropped from the request, so DiffDock's response arrays
    # are indexed by position in the FILTERED list, not by position in
    # ligand_smiles_list. Keep that mapping explicit: walking the unfiltered
    # list against the response pairs every ligand after a blank with the next
    # ligand's pose and confidence, silently and with no error.
    docked = [(i, s.strip()) for i, s in enumerate(ligand_smiles_list) if s and s.strip()]
    skipped = [i for i, s in enumerate(ligand_smiles_list) if not (s and s.strip())]
    ligand_bytes = "\n".join(s for _, s in docked)
    if not ligand_bytes:
        return {
            "status": "failed",
            "dock_id": dock_id,
            "error": "All SMILES were empty",
            "errors": ["empty ligand text"],
            "results": [],
            "pdb_source": pdb_source,
            "model": "nvidia/diffdock:2.2.0",
            "provider": "NVIDIA",
        }

    payload = {
        "ligand": ligand_bytes,
        "ligand_file_type": "txt",
        "protein": protein_bytes,
        "num_poses": int(num_poses),
        "time_divisions": 20,
        "steps": 18,
        "save_trajectory": False,
        "is_staged": False,
    }

    logger.info(
        f"[{dock_id}] POST {DIFFDOCK_URL}{DIFFDOCK_GENERATE_PATH} "
        f"({len(ligand_smiles_list)} ligands x {num_poses} poses)"
    )

    # 4. Call NIM
    t0 = time.time()
    try:
        _headers = {"Content-Type": "application/json"}
        _nv_key = get_nvidia_key()
        if _nv_key:
            _headers["Authorization"] = f"Bearer {_nv_key}"
        resp = requests.post(
            f"{DIFFDOCK_URL}{DIFFDOCK_GENERATE_PATH}",
            json=payload,
            headers=_headers,
            timeout=NIM_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        data = resp.json()
        elapsed = time.time() - t0
        logger.info(f"[{dock_id}] NIM responded in {elapsed:.2f}s")
    except requests.exceptions.HTTPError as e:
        elapsed = time.time() - t0
        try:
            err_body = e.response.text[:500] if e.response is not None else ""
        except Exception:
            err_body = ""
        logger.error(f"[{dock_id}] DiffDock NIM HTTP {e.response.status_code}: {err_body}")
        return {
            "status": "failed",
            "dock_id": dock_id,
            "error": f"DiffDock NIM HTTP error: {err_body}",
            "errors": [str(e)],
            "results": [],
            "pdb_source": pdb_source,
            "elapsed_seconds": round(elapsed, 2),
            "model": "nvidia/diffdock:2.2.0",
            "provider": "NVIDIA",
        }
    except Exception as e:
        elapsed = time.time() - t0
        logger.error(f"[{dock_id}] DiffDock NIM call failed: {e}")
        return {
            "status": "failed",
            "dock_id": dock_id,
            "error": f"DiffDock NIM call failed: {e}",
            "errors": [str(e)],
            "results": [],
            "pdb_source": pdb_source,
            "elapsed_seconds": round(elapsed, 2),
            "model": "nvidia/diffdock:2.2.0",
            "provider": "NVIDIA",
        }

    # 5. Parse response (handles both single and batch mode)
    overall_status = data.get("status")
    poses = data.get("ligand_positions", [])
    confidences = data.get("position_confidence", [])

    is_batch = (
        isinstance(poses, list) and len(poses) > 0 and isinstance(poses[0], list)
    )

    if not is_batch:
        # Single-ligand response — wrap as batch of 1
        poses = [poses] if poses else [[]]
        confidences = [confidences] if confidences else [[]]
        statuses = [overall_status] if isinstance(overall_status, str) else ["success"]
    else:
        if isinstance(overall_status, list):
            statuses = overall_status
        else:
            statuses = [overall_status or "success"] * len(poses)

    # 6. Build per-ligand results — one entry per INPUT ligand, in input order.
    #    `pos` indexes the response arrays; `idx` is the caller's position and is
    #    what names the pose files, so the two must not be conflated.
    results_by_idx = {}
    for i in skipped:
        results_by_idx[i] = {
            "smiles": ligand_smiles_list[i],
            "status": "failed",
            "error": "Empty SMILES — not submitted for docking",
            "confidence": None,
            "binding_score": None,
            "binding_confidence": None,
            "pose_path": "",
            "num_poses": 0,
            "all_poses": [],
        }
        errors.append(f"ligand {i}: empty SMILES, not submitted")

    for pos, (idx, smiles) in enumerate(docked):
        if pos >= len(poses):
            results_by_idx[idx] = {
                "smiles": smiles,
                "status": "failed",
                "error": "DiffDock returned no result for this ligand",
                "confidence": None,
                "binding_score": None,
                "binding_confidence": None,
                "pose_path": "",
                "num_poses": 0,
                "all_poses": [],
            }
            errors.append(f"ligand {idx}: no result returned")
            continue

        ligand_poses = poses[pos] or []
        ligand_confs = confidences[pos] if pos < len(confidences) else []
        ligand_status = statuses[pos] if pos < len(statuses) else "unknown"

        valid_confs = [c for c in (ligand_confs or []) if c is not None]
        if not valid_confs:
            results_by_idx[idx] = {
                "smiles": smiles,
                "status": ligand_status or "failed",
                "error": "No valid confidence scores returned",
                "confidence": None,
                "binding_score": None,
                "binding_confidence": None,
                "pose_path": "",
                "num_poses": 0,
                "all_poses": [],
            }
            errors.append(f"ligand {idx}: no valid confidences")
            continue

        ranked_indices = sorted(
            range(len(ligand_confs)),
            key=lambda i: (ligand_confs[i] is None, -(ligand_confs[i] or float("-inf"))),
        )

        all_pose_records = []
        rank1_path = ""
        for rank, pose_idx in enumerate(ranked_indices, 1):
            conf = ligand_confs[pose_idx]
            if conf is None:
                continue
            sdf = ligand_poses[pose_idx] if pose_idx < len(ligand_poses) else ""
            gcs_path = _save_pose_to_gcs(dock_id, idx, rank, conf, sdf)
            all_pose_records.append({
                "rank": rank,
                "confidence": conf,
                "pose_gcs_path": gcs_path,
            })
            if rank == 1:
                rank1_path = gcs_path

        rank1_conf = ligand_confs[ranked_indices[0]] if ranked_indices else None

        results_by_idx[idx] = {
            "smiles": smiles,
            "status": ligand_status or "success",
            "confidence": rank1_conf,
            "binding_confidence": rank1_conf,
            "binding_score": rank1_conf,  # consumed by optimize_complete
            "pose_path": rank1_path,
            "num_poses": len(all_pose_records),
            "all_poses": all_pose_records,
        }

    # Re-emit in the caller's order so results[i] always describes input i.
    results = [results_by_idx[i] for i in range(len(ligand_smiles_list))]

    docked_count = sum(1 for r in results if r.get("confidence") is not None)
    failed_count = len(results) - docked_count
    final_status = (
        "success" if not errors and docked_count == len(results)
        else ("partial" if docked_count > 0 else "failed")
    )

    logger.info(
        f"[{dock_id}] Done: {docked_count}/{len(ligand_smiles_list)} docked, "
        f"{len(errors)} non-fatal errors, status={final_status}"
    )

    return {
        "status": final_status,
        "dock_id": dock_id,
        "viewer_url": f"{VIEWER_BASE_URL}/docking?id={dock_id}",
        "pdb_source": pdb_source,
        "protein_residue_count": residue_count,
        "num_ligands": len(ligand_smiles_list),
        "docked_count": docked_count,
        "failed_count": failed_count,
        "num_poses_per_ligand": int(num_poses),
        "elapsed_seconds": round(elapsed, 2),
        "results": results,
        "errors": errors,
        "model": "nvidia/diffdock:2.2.0",
        "provider": "NVIDIA",
        "infrastructure": "NVIDIA-hosted DiffDock NIM 2.2.0 (build.nvidia.com)",
    }
