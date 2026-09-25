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
Delegation Tools for MolForge Orchestrator.

Delegates tasks to sub-agents on Agent Runtime using stream_query(),
and to PharmaPilot peer system via A2A.

Each delegation tool returns a structured contract containing the sub-agent's
verbatim narrative AND metadata about which models were used internally
(Gemini for orchestration, Nemotron for reasoning), so the React Dashboard
can render the Internal Agent Orchestra panel with correct provider attribution.
"""
import os
import json
import logging
import requests

logger = logging.getLogger(__name__)

# Required, no default. A hardcoded project-id fallback silently points a fresh
# deployment at somebody else's project instead of failing. The agent's .env
# (written by setup.sh) sets this, and ADK loads it before the tools import.
PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT")
if not PROJECT_ID:
    raise RuntimeError(
        "GOOGLE_CLOUD_PROJECT is not set. It belongs in "
        "agents/orchestrator/.env (setup.sh writes it); export it for local runs."
    )
LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")

# Also required, for the same reason: every `adk deploy` of a sub-agent mints a
# new engine ID, so a baked-in value is stale by construction. Fail here rather
# than let the orchestrator delegate into a 404 mid-conversation.
LEAD_OPTIMIZER_ENGINE_ID = os.getenv("LEAD_OPTIMIZER_ENGINE_ID")
ADMET_SAFETY_ENGINE_ID = os.getenv("ADMET_SAFETY_ENGINE_ID")
_missing = [
    name
    for name, value in (
        ("LEAD_OPTIMIZER_ENGINE_ID", LEAD_OPTIMIZER_ENGINE_ID),
        ("ADMET_SAFETY_ENGINE_ID", ADMET_SAFETY_ENGINE_ID),
    )
    if not value
]
if _missing:
    raise RuntimeError(
        f"{' and '.join(_missing)} not set. These are the numeric IDs minted by "
        "each sub-agent's `adk deploy`; they belong in agents/orchestrator/.env. "
        "Deploy the sub-agents before the orchestrator so the IDs exist."
    )
PHARMAPILOT_A2A_URL = os.getenv("PHARMAPILOT_A2A_URL", "http://pharmapilot-a2a-server:8080")


def _infer_provider(model_name: str) -> str:
    """Map a model identifier to its provider for dashboard color-coding."""
    if not model_name:
        return "Unknown"
    m = model_name.lower()
    if m.startswith("nvidia/") or "nemotron" in m:
        return "NVIDIA"
    if m.startswith("gemini") or "gemini" in m:
        return "Google"
    return "Unknown"


def _extract_text_from_event(event) -> str:
    """Extract text content from an ADK event, handling all known structures."""
    if isinstance(event, dict):
        content = event.get("content", {})
        if isinstance(content, dict):
            parts = content.get("parts", [])
            if isinstance(parts, list):
                texts = []
                for part in parts:
                    if isinstance(part, dict) and part.get("text"):
                        texts.append(part["text"])
                if texts:
                    return "\n".join(texts)
        if event.get("text"):
            return event["text"]
    elif hasattr(event, "text") and event.text:
        return event.text
    return ""


def _query_agent_engine(engine_id: str, agent_display_name: str, message: str) -> dict:
    """Call a sub-agent on Agent Runtime via stream_query and return
    the verbatim narrative plus model attribution metadata.
    """
    try:
        import vertexai
        client = vertexai.Client(project=PROJECT_ID, location=LOCATION)
        resource_name = f"projects/{PROJECT_ID}/locations/{LOCATION}/reasoningEngines/{engine_id}"
        agent = client.agent_engines.get(name=resource_name)

        text_chunks = []
        models_used = []
        seen_models = set()
        run_id = None
        status = None
        event_count = 0

        def add_model(model: str, role: str):
            if not model:
                return
            key = (model, role)
            if key in seen_models:
                return
            seen_models.add(key)
            models_used.append({
                "model": model,
                "provider": _infer_provider(model),
                "role": role,
            })

        for event in agent.stream_query(
            user_id="molforge-orchestrator",
            message=message,
        ):
            event_count += 1

            if isinstance(event, dict):
                model_version = event.get("model_version")
                if model_version:
                    add_model(model_version, "sub_agent_orchestration")

            text = _extract_text_from_event(event)
            if text:
                text_chunks.append(text)

            if isinstance(event, dict):
                parts = (event.get("content") or {}).get("parts") or []
                if isinstance(parts, list):
                    for part in parts:
                        if not isinstance(part, dict):
                            continue
                        fr = part.get("function_response")
                        if not fr:
                            continue
                        resp = fr.get("response", {}) or {}
                        if not isinstance(resp, dict):
                            continue
                        if resp.get("generation_model"):
                            tool_name = fr.get("name", "")
                            if "safety" in tool_name.lower() or "screen_molecules" in tool_name:
                                role = "safety_narrative"
                            elif "sar" in tool_name.lower() or "optimize_lead" in tool_name:
                                role = "sar_analysis"
                            else:
                                role = "reasoning"
                            add_model(resp["generation_model"], role)
                        if resp.get("run_id"):
                            run_id = resp["run_id"]
                        if resp.get("status"):
                            status = resp["status"]

        response_text = "\n".join(text_chunks).strip()
        logger.info(
            f"Sub-agent {agent_display_name} ({engine_id}): "
            f"{event_count} events, text len {len(response_text)}, "
            f"models {[m['model'] for m in models_used]}, run_id {run_id}"
        )

        return {
            "text": response_text if response_text else "(sub-agent returned no text)",
            "models_used": models_used,
            "run_id": run_id,
            "status": status,
            "event_count": event_count,
            "error": None,
        }
    except Exception as e:
        logger.error(f"Agent Runtime query failed for {engine_id}: {e}", exc_info=True)
        return {
            "text": "",
            "models_used": [],
            "run_id": None,
            "status": "failed",
            "event_count": 0,
            "error": f"Agent Runtime call failed: {str(e)}",
        }


def delegate_lead_optimization(
    lead_smiles: str,
    target_pdb_id: str,
    optimization_objectives: str,
    therapeutic_area: str = "",
    target_name: str = "",
    num_variants: int = 10,
    known_actives_summary: str = "",
    pdb_gcs_path: str = "",
) -> dict:
    """Delegate molecule optimization to the Lead Optimization Agent.

    target_name: the human-readable target name (e.g. "ABL kinase", "KIT D816V") — pass it so
    the result is labeled correctly; falls back to the PDB ID if omitted.
    num_variants: the number of variants the scientist asked for — e.g. "generate 8 variants"
    -> num_variants=8. Default 10 when unspecified.
    therapeutic_area: optional. Infer it from the target and the request rather than asking.
    """
    area = therapeutic_area or "general small-molecule therapeutics"
    display_target = target_name or target_pdb_id or "the target"
    structure_line = f"Target Protein Name: {display_target}\n"
    if target_pdb_id:
        structure_line += f"Target Protein PDB ID: {target_pdb_id}\n"
    if pdb_gcs_path:
        structure_line += f"PDB File Path: {pdb_gcs_path}\n"
    if not target_pdb_id and not pdb_gcs_path:
        structure_line += "No target structure available — proceed without docking.\n"

    message = f"""Optimize the following lead compound for {area}:

Lead SMILES: {lead_smiles}
{structure_line}Optimization Objectives: {optimization_objectives}
Number of Variants to Generate: {num_variants}
{f'Known Actives Context: {known_actives_summary}' if known_actives_summary else ''}

Call optimize_lead_complete with num_variants={num_variants}. Generate exactly that many variants, then dock, score, and rank them, and return your top candidates with binding scores and property profiles."""

    result = _query_agent_engine(
        engine_id=LEAD_OPTIMIZER_ENGINE_ID,
        agent_display_name="Lead Optimizer",
        message=message,
    )

    return {
        "narrative": result["text"],
        "response": result["text"],
        "run_id": result["run_id"],
        "status": result["status"],
        "sub_agent": {
            "name": "molforge_lead_optimizer",
            "engine_id": LEAD_OPTIMIZER_ENGINE_ID,
        },
        "sub_agent_models": result["models_used"],
        "event_count": result["event_count"],
        "source": "lead_optimizer_agent_engine",
        "error": result["error"],
    }


def delegate_admet_screening(
    candidate_smiles: list,
    therapeutic_area: str = "",
    optimization_context: str = "",
    run_id: str = "",
) -> dict:
    """Delegate ADMET safety screening to the ADMET Safety Oracle.

    therapeutic_area: optional. Infer it from the request when the scientist has not
    named one — never stop to ask for it. A required parameter here reads to the model
    as something it must obtain from the user, which turned "screen these molecules"
    into a clarifying question instead of a screen.
    """
    area = therapeutic_area or "general small-molecule therapeutics"
    smiles_list = "\n".join([f"- {s}" for s in candidate_smiles])
    message = f"""Screen the following {len(candidate_smiles)} candidate molecules for ADMET safety.

Therapeutic area: {area}
Scientist's priorities: {optimization_context}
{f'Run ID: {run_id}' if run_id else ''}

Candidate molecules:
{smiles_list}

Run all candidates through the full 41-endpoint ADMET screening, apply context-aware traffic-light scoring for {area}, and provide your safety verdicts."""

    result = _query_agent_engine(
        engine_id=ADMET_SAFETY_ENGINE_ID,
        agent_display_name="ADMET Safety Agent",
        message=message,
    )

    return {
        "narrative": result["text"],
        "response": result["text"],
        "run_id": result["run_id"],
        "status": result["status"],
        "sub_agent": {
            "name": "molforge_admet_safety_agent",
            "engine_id": ADMET_SAFETY_ENGINE_ID,
        },
        "sub_agent_models": result["models_used"],
        "event_count": result["event_count"],
        "source": "admet_safety_agent_engine",
        "error": result["error"],
    }


def delegate_molecular_docking(
    target_pdb_or_id: str,
    ligand_smiles_list: list,
    num_poses: int = 10,
) -> dict:
    """Delegate atomic molecular docking to the Lead Optimization Agent.

    Use this when the scientist asks to dock specific ligand(s) against a
    specific protein and does NOT ask to generate new molecules or run a
    full optimization pipeline. The Lead Optimizer's ATOMIC DOCKING mode
    calls the NVIDIA-hosted DiffDock NIM 2.2.0 (build.nvidia.com) in a single
    batch and returns ranked binding poses with confidence scores.

    Args:
        target_pdb_or_id: PDB ID (e.g., "2HYY"), gs:// path, http(s):// URL,
            local file path, or inline PDB content. The Lead Optimizer's
            DiffDock client will resolve and chain-A-filter automatically.
        ligand_smiles_list: List of SMILES strings to dock.
        num_poses: Poses generated per ligand (default 10).

    Returns:
        dict with the verbatim Lead Optimizer narrative plus structured
        dock_id, per-ligand confidence scores, and pose GCS paths.
    """
    smiles_block = "\n".join(f"- {s}" for s in ligand_smiles_list)
    message = f"""ATOMIC DOCKING: Dock the following ligand(s) against the target protein and return the ranked binding poses.

Target protein: {target_pdb_or_id}
Number of poses per ligand: {num_poses}

Ligand SMILES:
{smiles_block}

Use the dock_molecules tool ONCE with all ligands batched into a single call. Do not generate new molecules. Do not run SAR analysis. Do not call optimize_lead_complete. Return the dock_id, per-ligand confidence scores, and pose_path GCS links so I can surface them to the scientist."""

    result = _query_agent_engine(
        engine_id=LEAD_OPTIMIZER_ENGINE_ID,
        agent_display_name="Lead Optimizer (Atomic Docking)",
        message=message,
    )

    return {
        "narrative": result["text"],
        "response": result["text"],
        "run_id": result["run_id"],
        "status": result["status"],
        "sub_agent": {
            "name": "molforge_lead_optimizer",
            "engine_id": LEAD_OPTIMIZER_ENGINE_ID,
            "mode": "atomic_docking",
        },
        "sub_agent_models": result["models_used"],
        "event_count": result["event_count"],
        "source": "lead_optimizer_atomic_docking",
        "error": result["error"],
    }


def delegate_protein_folding(
    amino_acid_sequence: str,
    protein_name: str = "target",
) -> dict:
    """Delegate atomic protein structure prediction to the Lead Optimization Agent.

    Use this when the scientist asks to fold a specific amino acid sequence
    and does NOT ask to dock anything or run a full optimization pipeline.
    The Lead Optimizer's ATOMIC FOLDING mode calls ESMFold on RTX PRO 6000
    Blackwell and returns the predicted structure with pLDDT confidence.

    Args:
        amino_acid_sequence: Full amino acid sequence in one-letter code.
            Example: "MVLSPADKTNVKAAWGKVGA..."
        protein_name: Human-readable name for file naming. Example: "braf_v600e"

    Returns:
        dict with the verbatim Lead Optimizer narrative plus structured
        pdb_gcs_path, plddt_mean, and viewer_url.
    """
    message = f"""ATOMIC FOLDING: Fold the following amino acid sequence and return the predicted structure.

Protein name: {protein_name}
Sequence length: {len(amino_acid_sequence)} amino acids

Sequence:
{amino_acid_sequence}

Use the predict_structure tool ONCE with this sequence. Do not dock anything. Do not call optimize_lead_complete. Return the pdb_gcs_path, plddt_mean, viewer_url, and a one-sentence summary of fold quality so I can surface them to the scientist."""

    result = _query_agent_engine(
        engine_id=LEAD_OPTIMIZER_ENGINE_ID,
        agent_display_name="Lead Optimizer (Atomic Folding)",
        message=message,
    )

    return {
        "narrative": result["text"],
        "response": result["text"],
        "run_id": result["run_id"],
        "status": result["status"],
        "sub_agent": {
            "name": "molforge_lead_optimizer",
            "engine_id": LEAD_OPTIMIZER_ENGINE_ID,
            "mode": "atomic_folding",
        },
        "sub_agent_models": result["models_used"],
        "event_count": result["event_count"],
        "source": "lead_optimizer_atomic_folding",
        "error": result["error"],
    }


def delegate_literature_search(
    query: str,
    search_scope: str = "all",
) -> dict:
    """Delegate a literature search to the PharmaPilot peer system via A2A.

    PharmaPilot is an external sovereign system. Provider attribution for
    PharmaPilot calls is handled separately in the dashboard's External A2A
    Interactions panel, not the Internal Agent Orchestra.
    """
    try:
        response = requests.post(
            f"{PHARMAPILOT_A2A_URL}/",
            json={
                "jsonrpc": "2.0",
                "method": "tasks/send",
                "id": "lit-search-001",
                "params": {
                    "message": {
                        "role": "user",
                        "parts": [{"kind": "text", "text": query}],
                    },
                    "metadata": {"skill_id": "literature_search", "scope": search_scope},
                },
            },
            timeout=60,
        )
        response.raise_for_status()
        result = response.json()
        if "result" in result and "artifacts" in result["result"]:
            artifacts = result["result"]["artifacts"]
            text_parts = []
            for artifact in artifacts:
                for part in artifact.get("parts", []):
                    if part.get("kind") == "text":
                        text_parts.append(part["text"])
                    elif part.get("kind") == "data":
                        return json.loads(part.get("data", "{}"))
            return {
                "summary": "\n".join(text_parts),
                "source": "PharmaPilot A2A",
                "external_peer": "PharmaPilot",
            }
        return {
            "summary": "No results returned from PharmaPilot",
            "source": "PharmaPilot A2A",
            "external_peer": "PharmaPilot",
        }
    except requests.exceptions.RequestException as e:
        return {
            "error": f"PharmaPilot literature search failed: {str(e)}. PharmaPilot may not be running yet.",
            "source": "PharmaPilot A2A",
            "external_peer": "PharmaPilot",
        }
