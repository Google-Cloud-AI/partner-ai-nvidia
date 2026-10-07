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
Safety Report Generation Tool — uses NVIDIA Nemotron Nano VL 12B v2
on a Model Garden dedicated endpoint to write the pharmacological safety
narrative from ADMET screening data.

In the MolForge architecture, Gemini handles ONLY orchestration and tool
dispatch. All reasoning, generation, analysis, and narrative work is done
by NVIDIA Nemotron models.

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
        "agents/admet_safety_agent/.env (setup.sh writes it); export it for local runs."
    )
LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")

# Nemotron Nano VL 12B v2 — Model Garden one-click deploy
NEMOTRON_NANO_VL_ENDPOINT = "mg-endpoint-bf879bfb-ff1f-47a3-aeb9-197a17dbc3d9"
NEMOTRON_NANO_VL_MODEL = "nvidia/nemotron-nano-12b-v2-vl"

# Model Garden dedicated-endpoint prediction-domain project number
# (NOT the IAM project number — this is the Google-managed prediction project)
PREDICTION_PROJECT_NUMBER = "901265056707"

# Character budget for the screening data embedded in the prompt.
#
# This is a WHOLE-MOLECULE budget, never a byte cut. A mid-record slice used to
# hand Nemotron ~1.4 molecules while the prompt header still announced the full
# count, so it wrote traffic-light verdicts -- including KILL -- for molecules
# whose data it had never seen. Molecules that do not fit are dropped entirely,
# named in the prompt, and returned in `omitted_molecules`.
MAX_SCREENING_CHARS = int(os.getenv("MOLFORGE_MAX_SCREENING_CHARS", "60000"))

_PERCENTILE_SUFFIX = "_drugbank_approved_percentile"


def _format_molecule(index: int, mol: dict) -> str:
    """Render one ADMET result as a compact block for the prompt.

    `str(dict)` was ~5.6 kB per molecule, 83% of it the raw `drugbank_percentiles`
    dump -- which repeats every predicted value twice (once under the model name,
    once under the percentile name). Emitting the published fields once and the
    percentiles once cuts that by more than half and reads better besides.

    Categories are read off the record rather than hardcoded, so this tracks the
    service's ADMET_FIELD_MAP without a second copy of the contract to drift.
    """
    if mol.get("error"):
        return f"Molecule {index}: {mol.get('smiles', '?')}\n  PREDICTION FAILED: {mol['error']}"

    lines = [f"Molecule {index}: {mol.get('smiles', '?')}"]
    for category, fields in mol.items():
        if category in ("smiles", "error", "drugbank_percentiles"):
            continue
        if not isinstance(fields, dict):
            continue
        rendered = ", ".join(
            f"{name}={value}" for name, value in fields.items() if value is not None
        )
        if rendered:
            lines.append(f"  {category}: {rendered}")

    percentiles = mol.get("drugbank_percentiles") or {}
    approved = {
        key[: -len(_PERCENTILE_SUFFIX)]: value
        for key, value in percentiles.items()
        if key.endswith(_PERCENTILE_SUFFIX)
    }
    if approved:
        rendered = ", ".join(f"{name}={value}" for name, value in sorted(approved.items()))
        lines.append(f"  DrugBank approved-drug percentiles: {rendered}")
    return "\n".join(lines)


def _format_screening_data(admet_results: list, budget: int = MAX_SCREENING_CHARS) -> tuple:
    """Serialize as many whole molecules as fit the budget.

    Returns (text, omitted_smiles). Never returns a partial molecule.
    """
    blocks = []
    omitted = []
    used = 0
    for i, mol in enumerate(admet_results, start=1):
        block = _format_molecule(i, mol if isinstance(mol, dict) else {"smiles": str(mol)})
        if blocks and used + len(block) + 1 > budget:
            omitted.append(
                mol.get("smiles", f"#{i}") if isinstance(mol, dict) else f"#{i}"
            )
            continue
        blocks.append(block)
        used += len(block) + 1
    return "\n".join(blocks), omitted


def _call_nemotron(
    endpoint_id: str,
    model_name: str,
    messages: list,
    max_tokens: int = 4096,
    temperature: float = 0.3,
) -> dict:
    """Call a Nemotron model on a Model Garden dedicated endpoint.

    Args:
        endpoint_id: The mg-endpoint-... resource ID
        model_name: The NVIDIA model name (e.g., 'nvidia/nemotron-nano-12b-v2-vl')
        messages: OpenAI-compatible chat messages list
        max_tokens: Maximum tokens to generate (default 4096 for full reports)
        temperature: Sampling temperature (default 0.3 for factual content)

    Returns:
        dict with 'content' (str) and 'usage' (dict) keys
    """
    from google.auth import default
    from google.auth.transport.requests import Request as AuthRequest

    credentials, _ = default()
    credentials.refresh(AuthRequest())

    url = (
        f"https://{endpoint_id}.{LOCATION}-{PREDICTION_PROJECT_NUMBER}"
        f".prediction.vertexai.goog/v1/projects/{PROJECT_ID}"
        f"/locations/{LOCATION}/endpoints/{endpoint_id}:rawPredict"
    )

    payload = {
        "model": model_name,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": False,
    }

    headers = {
        "Authorization": f"Bearer {credentials.token}",
        "Content-Type": "application/json",
    }

    logger.info(f"Calling Nemotron endpoint {endpoint_id} ({model_name})")
    response = requests.post(url, json=payload, headers=headers, timeout=300)
    response.raise_for_status()
    result = response.json()

    content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
    usage = result.get("usage", {})

    logger.info(
        f"Nemotron response: {len(content)} chars | "
        f"completion_tokens={usage.get('completion_tokens', 'N/A')}"
    )

    return {"content": content, "usage": usage}


def generate_safety_report(
    admet_results: list,
    therapeutic_area: str,
    optimization_context: str = "",
) -> dict:
    """Generate a natural language safety report from ADMET screening data
    using NVIDIA Nemotron Nano VL 12B v2.

    Args:
        admet_results: List of per-molecule ADMET result dicts
        therapeutic_area: The therapeutic indication for context-aware interpretation
        optimization_context: Additional context about what matters most

    Returns:
        dict with keys:
            - narrative: Full safety report as markdown text
            - executive_summary: 2-3 sentence summary
            - generation_model: Model used for report generation
            - usage: Token usage from Nemotron
    """
    try:
        system_prompt = (
            "/no_think\n"
            "You are a senior pharmacologist writing safety assessment reports for "
            "drug discovery teams. Your reports are scientifically rigorous, direct, "
            "and decision-oriented. You use DrugBank percentiles to contextualize every "
            "score, explain WHY each flag matters for the specific therapeutic area, "
            "and assign clear traffic-light verdicts (PROCEED / INVESTIGATE / KILL). "
            "If a molecule should be killed, you say so and explain why."
        )

        screening_data, omitted = _format_screening_data(admet_results)
        if omitted:
            logger.warning(
                f"Screening data exceeded {MAX_SCREENING_CHARS} chars — "
                f"{len(omitted)} of {len(admet_results)} molecule(s) omitted from the prompt"
            )
        # State the omission in the prompt as well as the return value: the model
        # must not invent a verdict for data it was not given.
        omission_note = (
            ""
            if not omitted
            else (
                f"\n\nNOTE: {len(omitted)} molecule(s) did not fit this request and are "
                f"NOT included above: {', '.join(omitted)}. Do NOT assess them. State "
                "explicitly in the report that they were not screened in this batch."
            )
        )

        user_prompt = f"""Therapeutic area: {therapeutic_area}
Scientist's priorities: {optimization_context or "Standard safety screening for lead optimization."}

ADMET screening data for {len(admet_results) - len(omitted)} candidate molecule(s):
{screening_data}{omission_note}

Write a complete safety report with the following sections:

1. Executive Summary (2-3 sentences with overall verdict)
2. Per-Molecule Assessment (traffic-light verdict + rationale for each)
3. Detailed ADMET Profile (absorption, distribution, metabolism, excretion, toxicity)
4. Cross-Candidate Comparison (highlight safest options)
5. Key Concerns (across all candidates, contextualized to {therapeutic_area})
6. Recommended Next Steps

Use DrugBank percentiles to contextualize every score. Be direct."""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        logger.info(
            f"Generating safety report via Nemotron Nano VL 12B v2 "
            f"for {len(admet_results)} molecule(s) ({therapeutic_area})"
        )

        result = _call_nemotron(
            endpoint_id=NEMOTRON_NANO_VL_ENDPOINT,
            model_name=NEMOTRON_NANO_VL_MODEL,
            messages=messages,
            max_tokens=4096,
            temperature=0.3,
        )

        report_text = result["content"]

        # Strip any leaked <think> blocks (Nemotron sometimes ignores /no_think)
        if "<think>" in report_text and "</think>" in report_text:
            think_end = report_text.find("</think>") + len("</think>")
            report_text = report_text[think_end:].strip()

        executive_summary = (
            report_text.split("\n\n")[0]
            if "\n\n" in report_text
            else report_text[:500]
        )

        return {
            "narrative": report_text,
            "executive_summary": executive_summary,
            "generation_model": NEMOTRON_NANO_VL_MODEL,
            "model_provider": "NVIDIA",
            "usage": result["usage"],
            # Empty in the normal case. Non-empty means the report covers fewer
            # molecules than were screened — the caller must not present it as complete.
            "omitted_molecules": omitted,
        }

    except requests.exceptions.HTTPError as e:
        logger.error(f"Nemotron HTTP error: {e.response.status_code} {e.response.text[:500]}")
        return {
            "error": f"Nemotron call failed: {e.response.status_code}",
            "details": e.response.text[:500],
        }
    except Exception as e:
        logger.error(f"Report generation failed: {e}", exc_info=True)
        return {"error": f"Report generation failed: {str(e)}"}
