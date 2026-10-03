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
Structure-Activity Relationship (SAR) Analysis Tool — uses NVIDIA Nemotron
Super 49B v1.5 on a Model Garden dedicated endpoint to perform medicinal
chemistry reasoning over a set of candidate molecules.

In the MolForge architecture, Gemini handles ONLY orchestration and tool
dispatch. All reasoning, generation, analysis, ranking, and narrative work
is done by NVIDIA Nemotron models. This tool is the SAR brain of the Lead
Optimizer.

Author: Schneider Larbi
        Senior Manager, Global Partner Technical Architecture — AI & SaaS ISVs
        Google Cloud
"""
import os
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
        "agents/lead_optimizer/.env (setup.sh writes it); export it for local runs."
    )
LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")

# Nemotron Super 49B v1.5 — Model Garden one-click deploy
NEMOTRON_SUPER_ENDPOINT = "mg-endpoint-4a30e3e5-8c89-4f15-9086-0dc51692e554"
NEMOTRON_SUPER_MODEL = "nvidia/llama-3.3-nemotron-super-49b-v1.5"

# Model Garden dedicated-endpoint prediction-domain project number
# (NOT the IAM project number — this is the Google-managed prediction project)
PREDICTION_PROJECT_NUMBER = "901265056707"

# Character budget for the candidate set embedded in the prompt.
#
# WHOLE-CANDIDATE budget, never a byte cut. A mid-record slice fits roughly 19
# candidates and then silently hands Nemotron a half-written dict while the
# prompt header still announces the full count — so the model ranks candidates
# it never saw. Anything that does not fit is dropped whole, named in the
# prompt, and returned in `omitted_candidates`.
MAX_CANDIDATE_CHARS = int(os.getenv("MOLFORGE_MAX_CANDIDATE_CHARS", "60000"))


def _format_candidate(index: int, cand: dict) -> str:
    """Render one candidate record as a compact block for the prompt."""
    lines = [f"Candidate {index}: {cand.get('smiles', '?')}"]
    if cand.get("binding_score") is not None:
        lines.append(f"  binding_score: {cand['binding_score']}")
    if cand.get("binding_confidence") is not None:
        lines.append(f"  binding_confidence: {cand['binding_confidence']}")
    props = cand.get("properties") or {}
    if isinstance(props, dict):
        rendered = ", ".join(
            f"{k}={v}" for k, v in props.items() if k != "smiles" and v is not None
        )
        if rendered:
            lines.append(f"  properties: {rendered}")
    if cand.get("binding_score") is None and not props:
        lines.append("  (no docking or property data — do not rank on absent evidence)")
    return "\n".join(lines)


def _format_candidates(candidates: list, budget: int = MAX_CANDIDATE_CHARS) -> tuple:
    """Serialize as many whole candidates as fit the budget.

    Returns (text, omitted_smiles). Never returns a partial candidate.
    """
    blocks = []
    omitted = []
    used = 0
    for i, cand in enumerate(candidates, start=1):
        cand = cand if isinstance(cand, dict) else {"smiles": str(cand)}
        block = _format_candidate(i, cand)
        if blocks and used + len(block) + 1 > budget:
            omitted.append(cand.get("smiles", f"#{i}"))
            continue
        blocks.append(block)
        used += len(block) + 1
    return "\n".join(blocks), omitted


def _call_nemotron_super(
    messages: list,
    max_tokens: int = 6144,
    temperature: float = 0.3,
) -> dict:
    """Call NVIDIA Nemotron Super 49B v1.5 on its Model Garden dedicated endpoint.

    Args:
        messages: OpenAI-compatible chat messages list
        max_tokens: Maximum tokens to generate (default 6144 for full SAR reports)
        temperature: Sampling temperature (default 0.3 for factual reasoning)

    Returns:
        dict with 'content' (str) and 'usage' (dict) keys
    """
    from google.auth import default
    from google.auth.transport.requests import Request as AuthRequest

    credentials, _ = default()
    credentials.refresh(AuthRequest())

    url = (
        f"https://{NEMOTRON_SUPER_ENDPOINT}.{LOCATION}-{PREDICTION_PROJECT_NUMBER}"
        f".prediction.vertexai.goog/v1/projects/{PROJECT_ID}"
        f"/locations/{LOCATION}/endpoints/{NEMOTRON_SUPER_ENDPOINT}:rawPredict"
    )

    payload = {
        "model": NEMOTRON_SUPER_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": False,
    }

    headers = {
        "Authorization": f"Bearer {credentials.token}",
        "Content-Type": "application/json",
    }

    logger.info(
        f"Calling Nemotron Super 49B endpoint {NEMOTRON_SUPER_ENDPOINT} "
        f"(max_tokens={max_tokens})"
    )
    response = requests.post(url, json=payload, headers=headers, timeout=300)
    response.raise_for_status()
    result = response.json()

    content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
    usage = result.get("usage", {})

    logger.info(
        f"Nemotron Super 49B response: {len(content)} chars | "
        f"completion_tokens={usage.get('completion_tokens', 'N/A')}"
    )

    return {"content": content, "usage": usage}


def nemotron_sar_analysis(
    candidates: list,
    lead_smiles: str,
    target_name: str,
    objectives: str = "",
    therapeutic_area: str = "",
) -> dict:
    """Run medicinal chemistry SAR analysis over a set of optimization candidates
    using NVIDIA Nemotron Super 49B v1.5.

    The model performs all reasoning: scaffold analysis, structure-activity
    interpretation, ranking, prioritization, synthetic accessibility judgment,
    and risk assessment. No hardcoded ranking logic or thresholds.

    Args:
        candidates: List of candidate dicts. Each may contain:
            - smiles (str)
            - binding_score (float, from DiffDock)
            - binding_confidence (float, optional)
            - properties (dict, from RDKit: mw, logp, hba, hbd, tpsa, qed, etc.)
            - generation_round (int, optional)
        lead_smiles: The original lead compound SMILES the optimization started from
        target_name: Name or identifier of the target protein
        objectives: Free-text optimization objectives from the scientist
        therapeutic_area: Therapeutic area context (oncology, CNS, cardiovascular, etc.)

    Returns:
        dict with keys:
            - sar_narrative: Full SAR analysis as markdown text
            - executive_summary: Short summary
            - generation_model: NVIDIA model used
            - model_provider: 'NVIDIA'
            - usage: Token usage from Nemotron
    """
    try:
        system_prompt = (
            "/no_think\n"
            "You are a senior medicinal chemist with deep expertise in "
            "structure-activity relationships, fragment-based drug design, "
            "scaffold analysis, and multi-objective lead optimization. You "
            "review sets of generated drug candidates from GenMol and DiffDock "
            "and produce rigorous, decision-oriented SAR analyses. You rank "
            "candidates holistically — binding affinity, drug-likeness, "
            "structural novelty, synthetic accessibility, and risk profile. "
            "Your reports are scientifically rigorous and direct. You explain "
            "WHY each pick matters and what risks remain. You never apply rigid "
            "numeric thresholds — you reason from chemistry."
        )

        candidate_data, omitted = _format_candidates(candidates)
        if omitted:
            logger.warning(
                f"Candidate set exceeded {MAX_CANDIDATE_CHARS} chars — "
                f"{len(omitted)} of {len(candidates)} candidate(s) omitted from the prompt"
            )
        omission_note = (
            ""
            if not omitted
            else (
                f"\n\nNOTE: {len(omitted)} candidate(s) did not fit this request and are "
                f"NOT included above: {', '.join(omitted)}. Do NOT rank or discuss them. "
                "State explicitly in the report that they were not analysed in this round."
            )
        )

        user_prompt = f"""Lead compound: {lead_smiles}
Target protein: {target_name}
Therapeutic area: {therapeutic_area or "not specified"}
Optimization objectives: {objectives or "Improve binding affinity and drug-likeness while preserving the core scaffold."}

Candidates from the GenMol → DiffDock → RDKit pipeline ({len(candidates) - len(omitted)} total):
{candidate_data}{omission_note}

Write a CONCISE, decision-oriented SAR report. Be direct and cut filler — a busy medicinal chemist will read this. Use exactly these sections:

1. **Executive Summary** (2-3 sentences: overall quality of the set, whether optimization is converging, your confidence level.)

2. **Top 3 Picks (ranked)** — the 3 strongest candidates. For each, ONE tight block:
   - SMILES + binding score (with a one-clause interpretation)
   - Key properties: MW, LogP, HBD/HBA, PSA, QED
   - Structural rationale vs the lead (what changed, what's preserved, what novelty) AND the main risk — 1-2 sentences total.

3. **SAR Insights** (3-4 bullets: which scaffold changes consistently helped or hurt binding; which chemical-space regions look promising vs dead ends.)

4. **Recommended Next Step** (1-2 sentences: another optimization round, synthesize/test the top picks, or a scaffold hop — be specific.)

Be direct. If the set is weak, say so. Flag near-duplicate candidates and any great-binding-but-unworkable-chemistry picks explicitly. Do not pad — stop when the analysis is complete."""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        logger.info(
            f"Running Nemotron Super 49B SAR analysis: "
            f"{len(candidates)} candidates, target={target_name}"
        )

        result = _call_nemotron_super(
            messages=messages,
            max_tokens=3000,  # trimmed from 6144: concise report → faster generation, less truncation
            temperature=0.3,
        )

        sar_text = result["content"]

        # Strip any leaked <think>...</think> blocks (Super sometimes ignores /no_think)
        if "<think>" in sar_text and "</think>" in sar_text:
            think_end = sar_text.find("</think>") + len("</think>")
            sar_text = sar_text[think_end:].strip()

        executive_summary = (
            sar_text.split("\n\n")[0]
            if "\n\n" in sar_text
            else sar_text[:500]
        )

        return {
            "sar_narrative": sar_text,
            "executive_summary": executive_summary,
            "generation_model": NEMOTRON_SUPER_MODEL,
            "model_provider": "NVIDIA",
            "usage": result["usage"],
            # Empty in the normal case. Non-empty means the analysis covers fewer
            # candidates than were generated — do not present it as complete.
            "omitted_candidates": omitted,
        }

    except requests.exceptions.HTTPError as e:
        logger.error(
            f"Nemotron Super 49B HTTP error: "
            f"{e.response.status_code} {e.response.text[:500]}"
        )
        return {
            "error": f"Nemotron Super 49B call failed: {e.response.status_code}",
            "details": e.response.text[:500],
            "sar_narrative": "",
        }
    except Exception as e:
        logger.error(f"SAR analysis failed: {e}", exc_info=True)
        return {"error": f"SAR analysis failed: {str(e)}", "sar_narrative": ""}
