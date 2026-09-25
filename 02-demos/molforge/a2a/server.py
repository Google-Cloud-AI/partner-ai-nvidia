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
MolForge A2A Server — Cloud Run service exposing the MolForge agentic
drug discovery platform via the A2A protocol.

Author: Schneider Larbi
        Senior Manager, Global Partner Technical Architecture — AI & SaaS ISVs
        Google Cloud
"""
import os
import json
import uuid
import logging
import requests
from datetime import datetime, timezone
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

try:
    import a2ui  # sibling module — A2UI component-tree builder for Gemini Enterprise
except Exception:  # pragma: no cover - bridge still works in text-only mode
    a2ui = None

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("molforge-a2a")

# Required, no default. A hardcoded project-id fallback silently points a fresh
# deployment at somebody else's project instead of failing, so the miss surfaces
# as a confusing 403 from GCS or Agent Platform several frames deep. Fail at import.
PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT")
if not PROJECT_ID:
    raise RuntimeError(
        "GOOGLE_CLOUD_PROJECT is not set. Deploy with "
        "`--set-env-vars GOOGLE_CLOUD_PROJECT=<your-project>` (setup.sh does this), "
        "or export it for local runs."
    )
LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
# Also required, for the same reason: every `adk deploy` mints a new engine ID,
# so any baked-in value is stale by construction and routes to an engine that
# does not exist in this project.
ORCHESTRATOR_ENGINE_ID = os.getenv("ORCHESTRATOR_ENGINE_ID")
if not ORCHESTRATOR_ENGINE_ID:
    raise RuntimeError(
        "ORCHESTRATOR_ENGINE_ID is not set. It is the numeric ID minted by the "
        "orchestrator's `adk deploy` — read it from the deploy output, or from "
        "`gcloud beta ai reasoning-engines list`."
    )
# Self-URL advertised in the AgentCard. setup.sh patches this post-deploy once
# Cloud Run has minted the service URL (see `update-env-vars A2A_SERVER_URL`).
SERVER_URL = os.getenv("A2A_SERVER_URL", "").rstrip("/")
if not SERVER_URL:
    raise RuntimeError(
        "A2A_SERVER_URL is not set. It must be this service's own public URL — "
        "Gemini Enterprise reads it out of /.well-known/agent.json to call back."
    )

# Inline-rendering (A2UI) config
GCS_BUCKET = os.getenv("MOLFORGE_GCS_BUCKET", "molforge-artifacts")
VIEWER_BASE_URL = os.getenv("MOLFORGE_VIEWER_URL", "https://molforge-viewer.run.app").rstrip("/")
RENDER_SERVICE_URL = os.getenv("MOLFORGE_RENDER_URL", "").rstrip("/")
MAX_RENDER = int(os.getenv("MOLFORGE_MAX_RENDER", "8"))
RENDER_3D_ENABLED = os.getenv("MOLFORGE_RENDER_3D", "1") != "0"
RENDER_3D_TIMEOUT = int(os.getenv("MOLFORGE_RENDER_3D_TIMEOUT", "45"))
# Pre-warm budget for a cold turntable GIF (16 ray-traced frames) — longer than the
# snapshot timeout since the GIF render scales with structure size (~15s small protein,
# more for large). Blocks the fold response until the spinning image is cached.
PREWARM_TURNTABLE_TIMEOUT = int(os.getenv("MOLFORGE_PREWARM_TURNTABLE_TIMEOUT", "180"))
# A2UI inline rendering is OFF by default: Gemini Enterprise does not consume the
# application/json+a2ui DataPart (it sends acceptedOutputModes=[] and renders only the
# markdown text part). Enable for A2UI-capable A2A clients. Keeping it off also removes
# the server-side image-render latency from every response.
A2UI_ENABLED = os.getenv("MOLFORGE_A2UI", "0") != "0"
# A2UI is negotiated via this A2A extension (declared on the AgentCard + an
# X-A2A-Extensions response header) — NOT via defaultOutputModes.
A2UI_EXT = "https://a2ui.org/a2a-extension/a2ui/v0.8"

ORCHESTRATOR_RESOURCE = (
    f"projects/{PROJECT_ID}/locations/{LOCATION}/reasoningEngines/{ORCHESTRATOR_ENGINE_ID}"
)

# The interactive API docs are off by default: this service is public and
# unauthenticated, so there is no reason to publish its schema. Set
# MOLFORGE_API_DOCS=1 to expose /docs, /redoc and /openapi.json while debugging.
_API_DOCS = os.getenv("MOLFORGE_API_DOCS", "0") != "0"

app = FastAPI(
    title="MolForge A2A Server",
    version="1.1.0",
    docs_url="/docs" if _API_DOCS else None,
    redoc_url="/redoc" if _API_DOCS else None,
    openapi_url="/openapi.json" if _API_DOCS else None,
)
# CORS is only for browser clients. Gemini Enterprise and the agents reach this
# server side-to-side, where CORS does not apply at all -- so the default is an
# EMPTY allowlist and no middleware, and a deployment with no browser front-end
# grants no cross-origin access to anyone.
#
#   MOLFORGE_CORS_ORIGINS  comma-separated exact origins ("https://host[:port]").
#                          setup.sh sets it to the dashboard's URL once Cloud Run
#                          has minted one. "*" is accepted as a deliberate
#                          opt-out but logged loudly.
#
# This replaced allow_origins=["*"] + allow_credentials=True. That pair looks
# like "public read-only API" but is not: Starlette cannot send a literal "*"
# alongside credentials, so it echoes the caller's Origin back instead. The
# server was returning `Access-Control-Allow-Origin: <whatever you sent>` with
# `Access-Control-Allow-Credentials: true`, i.e. a credentialed grant to every
# origin on the internet. Credentials are now off unconditionally -- nothing
# here authenticates by cookie (Agent Runtime sessions are keyed by a user_id in
# the request body), so no client needs them, and leaving them on is what
# silently upgrades a wildcard into origin-echo.
_CORS_ORIGINS = [
    o.strip().rstrip("/")
    for o in os.getenv("MOLFORGE_CORS_ORIGINS", "").split(",")
    if o.strip()
]
if _CORS_ORIGINS:
    if "*" in _CORS_ORIGINS:
        logger.warning(
            "MOLFORGE_CORS_ORIGINS is '*': every origin may call this bridge from a "
            "browser. Set it to the exact front-end origin(s) instead."
        )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_CORS_ORIGINS,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type"],
        expose_headers=["X-A2A-Extensions"],
    )
    logger.info(f"CORS enabled for origins: {_CORS_ORIGINS}")
else:
    logger.info("CORS disabled (MOLFORGE_CORS_ORIGINS unset) — server-to-server only.")

_clients = {}


def get_agent(engine_id: str):
    if engine_id not in _clients:
        import vertexai
        client = vertexai.Client(project=PROJECT_ID, location=LOCATION)
        resource = f"projects/{PROJECT_ID}/locations/{LOCATION}/reasoningEngines/{engine_id}"
        _clients[engine_id] = client.agent_engines.get(name=resource)
        logger.info(f"Connected to agent: {resource}")
    return _clients[engine_id]


def _get_or_create_ae_session(agent, user_id: str) -> str | None:
    """Get an existing Agent Runtime session for this user_id, or create a new one.

    Used to implement multi-turn memory on top of the ADK Agent Runtime session store.
    First turn for a given user_id creates a fresh session; subsequent turns reuse it,
    which gives the orchestrator full conversation history automatically.

    Returns the session_id as a string, or None if Agent Runtime session APIs
    are not available (fall back to stateless stream_query).
    """
    try:
        sessions = agent.list_sessions(user_id=user_id)
        # list_sessions may return a generator, list, or dict with "sessions" key
        session_list = []
        if hasattr(sessions, "__iter__") and not isinstance(sessions, dict):
            session_list = list(sessions)
        elif isinstance(sessions, dict):
            session_list = sessions.get("sessions", []) or sessions.get("session_list", [])
        if session_list:
            s = session_list[0]
            session_id = s.get("id") if isinstance(s, dict) else getattr(s, "id", None)
            if session_id:
                logger.info(f"[A2A SESSION] reused session_id={session_id} for user_id={user_id}")
                return session_id
    except Exception as e:
        logger.warning(f"[A2A SESSION] list_sessions failed for {user_id}: {e}")

    try:
        session = agent.create_session(user_id=user_id)
        session_id = session.get("id") if isinstance(session, dict) else getattr(session, "id", None)
        if session_id:
            logger.info(f"[A2A SESSION] created session_id={session_id} for user_id={user_id}")
            return session_id
    except Exception as e:
        logger.error(f"[A2A SESSION] create_session failed for {user_id}: {e}")

    return None


AGENT_CARD = {
    "protocolVersion": "0.2.1",
    "name": "MolForge",
    "description": "MolForge is an agentic AI drug discovery platform powered by NVIDIA Nemotron, GenMol, DiffDock, ESMFold, and ADMET-AI on Google Cloud.",
    "version": "1.0.0",
    "url": SERVER_URL,
    "provider": {"organization": "Google Cloud × NVIDIA", "url": "https://cloud.google.com"},
    "capabilities": {
        "streaming": True, "pushNotifications": False, "stateTransitionHistory": True,
        # A2UI negotiated via this extension (only when enabled), per the A2UI v0.8 spec.
        **({"extensions": [{"uri": A2UI_EXT, "description": "A2UI v0.8 progressive UI"}]}
           if A2UI_ENABLED else {}),
    },
    "defaultInputModes": ["text/plain"],
    "defaultOutputModes": ["text/plain", "application/json"],
    "skills": [
        {
            "id": "optimize_lead_compound",
            "name": "Optimize Lead Compound",
            "description": "Generate optimized molecular variants of a lead compound. Powered by NVIDIA.",
            "tags": ["drug-discovery", "molecular-generation", "lead-optimization", "nvidia-genmol"],
            "examples": ["Optimize Imatinib for KIT D816V mutation"],
        },
        {
            "id": "screen_admet_safety",
            "name": "Screen ADMET Safety",
            "description": "Run candidate molecules through 41 ADMET endpoints using ADMET-AI v2.",
            "tags": ["drug-discovery", "admet", "safety", "toxicology"],
            "examples": ["Screen these 10 candidates for CNS drug safety"],
        },
        {
            "id": "run_drug_discovery_pipeline",
            "name": "Run End-to-End Drug Discovery Pipeline",
            "description": "Execute the complete MolForge pipeline.",
            "tags": ["drug-discovery", "pipeline", "end-to-end"],
            "examples": ["Run full pipeline for BRAF V600E"],
        },
    ],
}


@app.get("/.well-known/agent.json")
async def agent_card():
    return AGENT_CARD


@app.get("/health")
async def health():
    return {"status": "healthy", "service": "molforge-a2a", "orchestrator": ORCHESTRATOR_ENGINE_ID}


# Reasoning engines to keep resident (defeat Agent Runtime cold-start). The orchestrator is
# always warmed; sub-agents are warmed too when their IDs are present in the bridge env.
WARMUP_ENGINE_IDS = [e for e in (
    ORCHESTRATOR_ENGINE_ID,
    os.getenv("LEAD_OPTIMIZER_ENGINE_ID", ""),
    os.getenv("ADMET_SAFETY_ENGINE_ID", ""),
) if e]


@app.get("/warmup-engines")
def warmup_engines():
    """Keep the Agent Runtime reasoning engines resident so the first request after
    idle doesn't pay a ~minute cold-start (the 'hi takes a minute' symptom). Fires a trivial
    stream_query at each configured engine — consuming ONE event is enough to spin the runtime
    up. Meant to be pinged every ~10 min by Cloud Scheduler. Sync def so FastAPI runs it in a
    threadpool (stream_query is blocking). Returns per-engine warm status + latency.
    """
    import time as _t
    results = []
    for eid in WARMUP_ENGINE_IDS:
        t0 = _t.time()
        try:
            agent = get_agent(eid)
            for _ in agent.stream_query(user_id="warmup", message="ping"):
                break  # one event = runtime is up; don't drain the whole reply
            results.append({"engine_id": eid, "status": "warm",
                            "ms": int((_t.time() - t0) * 1000)})
        except Exception as e:
            results.append({"engine_id": eid, "status": "error",
                            "error": str(e)[:200], "ms": int((_t.time() - t0) * 1000)})
    logger.info(f"[WARMUP] {results}")
    return {"warmed": results}


# ──────────────────────────────────────────────────────────────────
# GKE service registry + warmup endpoints (proxy to bypass CORS)
# ──────────────────────────────────────────────────────────────────

GKE_SERVICES = {
    "genmol":   {"url": "http://136.113.102.37:8000",  "label": "GenMol"},
    "diffdock": {"url": "http://34.57.211.74:8000",    "label": "DiffDock"},
    "esmfold":  {"url": "http://34.63.2.114:8000",     "label": "ESMFold"},
    "rdkit":    {"url": "http://34.66.14.6:8080",      "label": "RDKit"},
    "admet":    {"url": "http://35.194.12.179:8080",   "label": "ADMET-AI"},
    "data":     {"url": "http://35.188.87.5:8080",     "label": "Data Retrieval"},
}


def _probe_service(name: str, info: dict) -> dict:
    """Probe a single GKE service /health endpoint and classify its status."""
    import time
    start = time.time()
    try:
        r = requests.get(f"{info['url']}/health", timeout=15)
        elapsed_ms = int((time.time() - start) * 1000)
        if r.status_code != 200:
            return {
                "name": name,
                "label": info["label"],
                "status": "unhealthy",
                "http_status": r.status_code,
                "latency_ms": elapsed_ms,
                "model_loaded": None,
            }
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        model_loaded = body.get("model_loaded")
        # 'cold' = pod is up but model has not finished loading yet
        # 'healthy' = pod is up AND model is loaded (or service has no model concept)
        if model_loaded is False:
            status = "cold"
        else:
            status = "healthy"
        return {
            "name": name,
            "label": info["label"],
            "status": status,
            "http_status": 200,
            "latency_ms": elapsed_ms,
            "model_loaded": model_loaded,
        }
    except Exception as e:
        elapsed_ms = int((time.time() - start) * 1000)
        return {
            "name": name,
            "label": info["label"],
            "status": "unhealthy",
            "http_status": None,
            "latency_ms": elapsed_ms,
            "model_loaded": None,
            "error": str(e)[:200],
        }


@app.get("/warmup/{service_name}")
async def warmup_service(service_name: str):
    """Probe a single GKE service /health and return its status."""
    info = GKE_SERVICES.get(service_name)
    if not info:
        return JSONResponse(
            content={"error": f"Unknown service: {service_name}", "valid": list(GKE_SERVICES.keys())},
            status_code=404,
        )
    return JSONResponse(content=_probe_service(service_name, info))


@app.get("/warmup-all")
async def warmup_all():
    """Probe all GKE services in parallel and return combined status."""
    import concurrent.futures

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(GKE_SERVICES)) as ex:
        futures = {
            ex.submit(_probe_service, name, info): name
            for name, info in GKE_SERVICES.items()
        }
        for fut in concurrent.futures.as_completed(futures):
            try:
                results.append(fut.result())
            except Exception as e:
                results.append({
                    "name": futures[fut],
                    "status": "unhealthy",
                    "error": str(e)[:200],
                })

    # Stable order: match GKE_SERVICES insertion order
    name_order = list(GKE_SERVICES.keys())
    results.sort(key=lambda r: name_order.index(r["name"]) if r["name"] in name_order else 999)

    healthy = sum(1 for r in results if r.get("status") == "healthy")
    cold = sum(1 for r in results if r.get("status") == "cold")
    unhealthy = sum(1 for r in results if r.get("status") == "unhealthy")

    return JSONResponse(content={
        "services": results,
        "summary": {
            "total": len(results),
            "healthy": healthy,
            "cold": cold,
            "unhealthy": unhealthy,
        },
        "checked_at": datetime.now(timezone.utc).isoformat(),
    })


# ──────────────────────────────────────────────────────────────────
# Timeline construction for the React Dashboard
# ──────────────────────────────────────────────────────────────────

def infer_provider(model_name: str) -> str:
    """Map a model identifier to its provider for dashboard color-coding."""
    if not model_name:
        return "Unknown"
    m = model_name.lower()
    if m.startswith("nvidia/") or "nemotron" in m:
        return "NVIDIA"
    if m.startswith("gemini") or "gemini" in m:
        return "Google"
    return "Unknown"


def _short(text: str, n: int = 200) -> str:
    """Truncate text for compact dashboard display."""
    if not text:
        return ""
    text = text.strip()
    return text if len(text) <= n else text[:n] + "…"


def build_timeline_entry(event) -> list:
    """Convert one ADK event into 0..N structured timeline entries for the dashboard.

    Each entry is a dict with:
        - ts: float epoch timestamp
        - agent: author name
        - kind: 'tool_call' | 'tool_response' | 'sub_agent_model' | 'model_text' | 'error'
        - name: tool name (for tool_call/tool_response) or model role (for sub_agent_model)
        - model: model identifier
        - provider: 'Google' | 'NVIDIA' | 'Unknown'
        - summary: short human-readable string
        - status: 'success' | 'error' | None
        - run_id: surfaced when present
    """
    entries = []
    if not isinstance(event, dict):
        return entries

    ts = event.get("timestamp") or datetime.now(timezone.utc).timestamp()
    agent = event.get("author", "unknown")
    invocation_id = event.get("invocation_id", "")
    orchestrator_model = event.get("model_version", "")

    if event.get("error_code") or event.get("error_message"):
        entries.append({
            "ts": ts,
            "agent": agent,
            "kind": "error",
            "name": event.get("error_code", "model_error"),
            "model": orchestrator_model,
            "provider": infer_provider(orchestrator_model),
            "summary": _short(event.get("error_message", ""), 300),
            "status": "error",
            "invocation_id": invocation_id,
        })
        return entries

    parts = (event.get("content") or {}).get("parts") or []
    if not isinstance(parts, list):
        return entries

    for p in parts:
        if not isinstance(p, dict):
            continue

        if p.get("function_call"):
            fc = p["function_call"]
            args = fc.get("args", {}) or {}
            arg_summary = ", ".join(
                f"{k}={_short(str(v), 60)}"
                for k, v in list(args.items())[:3]
            )
            entries.append({
                "ts": ts,
                "agent": agent,
                "kind": "tool_call",
                "name": fc.get("name", "unknown"),
                "model": orchestrator_model,
                "provider": infer_provider(orchestrator_model),
                "summary": _short(arg_summary, 220),
                "status": None,
                "invocation_id": invocation_id,
            })

        elif p.get("function_response"):
            fr = p["function_response"]
            resp = fr.get("response", {}) or {}
            tool_name = fr.get("name", "unknown")
            status = None
            summary = ""
            run_id = None
            tool_provider = "Google"
            tool_model = ""
            sub_agent_name = None
            sub_agent_models = []

            if isinstance(resp, dict):
                if resp.get("error"):
                    status = "error"
                    summary = _short(str(resp.get("error")), 300)
                else:
                    status = resp.get("status") or "success"
                    if resp.get("generation_model"):
                        tool_model = resp["generation_model"]
                        tool_provider = infer_provider(tool_model)
                    elif resp.get("model_provider") == "NVIDIA":
                        tool_provider = "NVIDIA"
                    run_id = resp.get("run_id")

                    sub_agent_obj = resp.get("sub_agent") or {}
                    if isinstance(sub_agent_obj, dict):
                        sub_agent_name = sub_agent_obj.get("name")
                    raw_sam = resp.get("sub_agent_models") or []
                    if isinstance(raw_sam, list):
                        sub_agent_models = [m for m in raw_sam if isinstance(m, dict)]

                    if resp.get("narrative"):
                        summary = _short(resp["narrative"], 300)
                    elif resp.get("executive_summary"):
                        summary = _short(resp["executive_summary"], 300)
                    elif resp.get("safety_narrative"):
                        summary = _short(resp["safety_narrative"], 300)
                    elif resp.get("sar_narrative"):
                        summary = _short(resp["sar_narrative"], 300)
                    elif resp.get("candidate_count") is not None:
                        summary = f"{resp.get('candidate_count')} candidates"
                    elif resp.get("molecule_count") is not None:
                        summary = f"{resp.get('molecule_count')} molecules"
                    else:
                        summary = _short(json.dumps(resp, default=str), 300)

            entries.append({
                "ts": ts,
                "agent": agent,
                "kind": "tool_response",
                "name": tool_name,
                "model": tool_model,
                "provider": tool_provider,
                "summary": summary,
                "status": status,
                "run_id": run_id,
                "sub_agent": sub_agent_name,
                "invocation_id": invocation_id,
            })

            for m in sub_agent_models:
                model_name = m.get("model", "")
                role = m.get("role", "")
                provider = m.get("provider") or infer_provider(model_name)
                entries.append({
                    "ts": ts,
                    "agent": sub_agent_name or tool_name,
                    "kind": "sub_agent_model",
                    "name": role,
                    "model": model_name,
                    "provider": provider,
                    "summary": f"{provider} {model_name} ({role}) inside {sub_agent_name or tool_name}",
                    "status": status,
                    "run_id": run_id,
                    "invocation_id": invocation_id,
                })

        elif p.get("text"):
            entries.append({
                "ts": ts,
                "agent": agent,
                "kind": "model_text",
                "name": "",
                "model": orchestrator_model,
                "provider": infer_provider(orchestrator_model),
                "summary": _short(p["text"], 400),
                "status": None,
                "invocation_id": invocation_id,
            })

    return entries



def extract_text_from_event(event) -> str:
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


# ──────────────────────────────────────────────────────────────────
# A2UI inline rendering — fetch run artifact, rasterize 2D, build parts
# ──────────────────────────────────────────────────────────────────

def _extract_run_id(timeline: list) -> str | None:
    """Most recent run_id surfaced by a delegation tool_response in the stream."""
    run_id = None
    for e in timeline or []:
        if isinstance(e, dict) and e.get("run_id"):
            run_id = e["run_id"]
    return run_id


def _extract_a2ui_catalog(params: dict, message: dict):
    """Best-effort extraction of GE's advertised A2UI component catalog.

    GE is expected to send the list of components it can render alongside the
    request. The exact location/shape is not yet confirmed (Phase 0 probe was
    deferred), so we scan a few plausible spots and return a set of component
    names, or None when absent. None => emit optimistically; the text part is
    always present as a fallback.
    """
    sources = [
        params or {},
        (params or {}).get("metadata") or {},
        (params or {}).get("configuration") or {},
        message or {},
        (message or {}).get("metadata") or {},
    ]
    raw = []
    for src in sources:
        if not isinstance(src, dict):
            continue
        for key in ("a2ui", "a2uiCatalog", "catalog", "acceptedComponents",
                    "components", "supportedComponents"):
            v = src.get(key)
            if isinstance(v, dict):
                v = v.get("components") or v.get("types") or list(v.keys())
            if isinstance(v, list) and v:
                raw = v
                break
        if raw:
            break
    if not raw:
        return None
    names = set()
    for c in raw:
        if isinstance(c, str):
            names.add(c)
        elif isinstance(c, dict):
            n = c.get("type") or c.get("name") or c.get("id")
            if n:
                names.add(n)
    return names or None


def _fetch_results_artifact(run_id: str):
    """Read the GCS results artifact for a run_id.

    opt_* => optimization_results.json, run_* => admet_results.json; unknown
    prefix tries both. Returns the parsed dict or None.
    """
    if not run_id:
        return None
    if run_id.startswith("opt_"):
        candidates = ["optimization_results.json"]
    elif run_id.startswith("run_"):
        candidates = ["admet_results.json"]
    else:
        candidates = ["optimization_results.json", "admet_results.json"]
    try:
        from google.cloud import storage
        client = storage.Client()
        bucket = client.bucket(GCS_BUCKET)
        for cand in candidates:
            blob = bucket.blob(f"{run_id}/{cand}")
            if blob.exists():
                return json.loads(blob.download_as_text())
    except Exception as e:
        logger.warning(f"[A2A A2UI] artifact fetch failed for {run_id}: {e}")
    return None


def _smiles_from_results(results: dict) -> list:
    """Candidate/molecule SMILES, in order, from a results artifact."""
    if not isinstance(results, dict):
        return []
    rows = results.get("candidates") or results.get("screening_results") or []
    return [r["smiles"] for r in rows if isinstance(r, dict) and r.get("smiles")]


def _render_smiles(smiles_list: list) -> list:
    """Rasterize SMILES -> 2D PNGs via the render-service. Graceful [] on failure."""
    if not RENDER_SERVICE_URL or not smiles_list:
        return []
    try:
        r = requests.post(
            f"{RENDER_SERVICE_URL}/render/2d",
            json={"smiles_list": smiles_list[:MAX_RENDER]},
            timeout=25,
        )
        if r.status_code == 200:
            return r.json().get("images", [])
        logger.warning(f"[A2A A2UI] render-service {r.status_code}: {r.text[:200]}")
    except Exception as e:
        logger.warning(f"[A2A A2UI] render-service call failed: {e}")
    return []


def _top_pose_path(results: dict) -> str:
    """First docked candidate's rank-1 pose SDF gs:// path, if any."""
    for c in results.get("candidates") or []:
        if isinstance(c, dict) and c.get("pose_path"):
            return c["pose_path"]
    return ""


def _render_structure(dock_id: str, pose_path: str):
    """Render an inline 3D snapshot of the docked complex via the render-service.

    protein = the chain-A PDB the DiffDock tool saved; ligand = the rank-1 pose.
    Returns the image dict {ok, png_b64, mime_type} or None (graceful).
    """
    if not (RENDER_SERVICE_URL and dock_id and pose_path):
        return None
    protein_uri = f"gs://{GCS_BUCKET}/docking/{dock_id}/protein.pdb"
    try:
        r = requests.post(
            f"{RENDER_SERVICE_URL}/render/3d",
            json={"protein_pdb": protein_uri, "ligand_sdf": pose_path,
                  "color_by": "chain", "mode": "snapshot", "size": 640},
            timeout=RENDER_3D_TIMEOUT,
        )
        if r.status_code == 200:
            out = r.json()
            return out if out.get("ok") else None
        logger.warning(f"[A2A A2UI] 3D render {r.status_code}: {r.text[:200]}")
    except Exception as e:
        logger.warning(f"[A2A A2UI] 3D render call failed: {e}")
    return None


def _prewarm_render(url: str, timeout: int = RENDER_3D_TIMEOUT) -> None:
    """Force the render-service to render + cache an inline image BEFORE we emit the
    A2UI surface, so GE fetches an already-warm (instant) image.

    Why: a brand-new structure's render is a cold cache miss (snapshot ~5s, turntable GIF
    ~15s+ scaling with size). If we emit the surface first, GE fetches the image while it's
    still rendering, sees an unresolved Image field, and shows "Form validation error.
    Please fix the highlighted fields before submitting." (then the image fills in once
    cached). A blocking GET here closes that race. Best-effort: any failure (incl. timeout)
    just falls back to the old behavior (GE renders the image cold, as before). Pass a
    longer `timeout` for turntable GIFs — see PREWARM_TURNTABLE_TIMEOUT.
    """
    if not url:
        return
    try:
        r = requests.get(url, timeout=timeout)
        logger.info(f"[A2A A2UI] prewarm {r.status_code} ({len(r.content)} bytes) {url[:90]}")
    except Exception as e:
        logger.warning(f"[A2A A2UI] prewarm failed (non-fatal): {e}")


def _dedup_paragraphs(text: str) -> str:
    """Drop duplicate paragraphs (ADK streaming can emit cumulative text → doubled narrative)."""
    if not text:
        return text
    seen, out = set(), []
    for para in text.split("\n\n"):
        k = para.strip()
        if k and k in seen:
            continue
        if k:
            seen.add(k)
        out.append(para)
    return "\n\n".join(out)


def _markdown_structures(results: dict) -> str:
    """Inline 2D structures as MARKDOWN images (GE renders the markdown text part,
    not our A2UI DataPart — confirmed via acceptedOutputModes=[]). Each image src is
    the public render-service PNG endpoint, so GE can fetch it directly.
    """
    import urllib.parse
    rows = results.get("candidates") or results.get("screening_results") or []
    run_id = results.get("run_id", "")
    blocks = []
    for i, r in enumerate(rows[:MAX_RENDER]):
        if not isinstance(r, dict):
            continue
        s = r.get("smiles")
        if not s:
            continue
        url = f"{RENDER_SERVICE_URL}/render/2d.png?smiles={urllib.parse.quote(s, safe='')}"
        cap = f"opt-{i+1}"
        sc = r.get("binding_score")
        if sc is not None:
            cap += f" — binding {sc}"
        blocks.append(f"**{cap}**\n\n![{cap}]({url})")
    return "\n\n".join(blocks)


def _extract_folded_structure(text: str):
    """Detect a standalone ESMFold result in the narrative → {gs, name, plddt} or None.

    Atomic folding produces no opt/admet artifact; the narrative carries the gs:// PDB
    path (".../structures/<name>.pdb") and the mean pLDDT, which is enough to render the
    protein inline.
    """
    import re
    m = re.search(r"gs://[^\s)\]\"']+/structures/[^\s)\]\"']+\.pdb", text or "")
    if not m:
        return None
    gs = m.group(0)
    name = gs.rsplit("/", 1)[-1][:-4]  # filename without .pdb
    plddt = None
    pm = re.search(r"pLDDT[:\s*]*([0-9]+(?:\.[0-9]+)?)", text, re.I)
    if pm:
        plddt = pm.group(1)
    return {"gs": gs, "name": name, "plddt": plddt}


def _resolve_rank1_pose_gs(dock_id: str) -> str:
    """List a docking run's GCS prefix and return the rank-1 pose SDF gs:// path.

    Poses are named lig<idx>_rank<r>_conf<c>.sdf; we prefer rank1 of the lowest ligand
    index. Returns "" if none found. This is what makes inline docking rendering robust:
    we derive the pose from the dock_id instead of trusting the LLM to echo the full
    gs:// SDF path in its narrative (it truncates the per-pose section, as seen in the
    field — the pipeline must resolve from the ID, never depend on a blank/echoed path).
    """
    if not dock_id:
        return ""
    try:
        from google.cloud import storage
        names = [b.name for b in storage.Client().list_blobs(
            GCS_BUCKET, prefix=f"docking/{dock_id}/") if b.name.endswith(".sdf")]
        if not names:
            return ""
        ranked = sorted(n for n in names if "_rank1_" in n or "_rank1." in n) or sorted(names)
        return f"gs://{GCS_BUCKET}/{ranked[0]}"
    except Exception as e:
        logger.warning(f"[A2A A2UI] pose resolve failed for {dock_id}: {e}")
        return ""


def _extract_docked_pose(text: str):
    """Detect a standalone DiffDock result in the narrative → {pose_gs, protein_gs,
    dock_id, target, confidence} or None.

    Atomic docking has no opt/admet artifact. Robust detection keys off the dock_id,
    which the narrative ALWAYS carries ("Run ID: dock_YYYYMMDD_HHMMSS_<hex>"), and
    resolves the rank-1 pose SDF + protein PDB from the deterministic GCS layout
    (docking/<dock_id>/...). We do NOT depend on the LLM echoing the full gs:// SDF
    path — it truncates the per-pose section (observed in the field). Falls back to an
    explicit SDF path when the model does emit one.
    """
    import re
    pose_gs, dock_id = None, None
    m = re.search(r"gs://[^\s)\]\"']+/docking/([^/\s]+)/[^\s)\]\"']+\.sdf", text or "")
    if m:
        pose_gs, dock_id = m.group(0), m.group(1)
    else:
        dm = re.search(r"\bdock_\d{8}_\d{6}_[0-9a-fA-F]{4,}\b", text or "")
        if not dm:
            return None
        dock_id = dm.group(0)
        pose_gs = _resolve_rank1_pose_gs(dock_id)
        if not pose_gs:
            return None
    protein_gs = f"gs://{GCS_BUCKET}/docking/{dock_id}/protein.pdb"
    target = None
    tm = re.search(r"Target[:*\s]+([^\n(]+)", text)  # tolerate markdown bold (**Target:**)
    if tm:
        target = tm.group(1).strip().strip("*").strip().rstrip(".")
        if target.startswith("gs://"):  # show a readable name, not the bucket path
            target = target.rstrip("/").rsplit("/", 1)[-1].rsplit(".", 1)[0]
    confidence = None
    cm = re.search(r"confidence[:*\s]+(-?[0-9]+(?:\.[0-9]+)?)", text, re.I)
    if cm:
        confidence = cm.group(1)
    return {"pose_gs": pose_gs, "protein_gs": protein_gs, "dock_id": dock_id,
            "target": target, "confidence": confidence}


def _a2ui_part(msg: dict) -> dict:
    """Wrap one A2UI v0.8 message as an A2A DataPart (mimeType goes in metadata)."""
    return {"kind": "data", "data": msg, "metadata": {"mimeType": "application/json+a2ui"}}


def _build_rich_parts(run_id: str, response_text: str, catalog):
    """Return A2A message parts.

    The text part (de-duplicated narrative) is the fallback GE renders for non-A2UI
    clients and as the chat bubble. When A2UI is enabled, each A2UI v0.8 message
    (surfaceUpdate → beginRendering) is prepended as its own DataPart with
    metadata.mimeType=application/json+a2ui — the exact wrapper GE's A2UI renderer
    reads (negotiated via the AgentCard extension + X-A2A-Extensions header). The
    inline structure images source from the public render-service PNG endpoint.
    Returns (parts, a2ui_present).
    """
    import urllib.parse
    text_part = {"kind": "text", "text": _dedup_paragraphs(response_text)}
    if not (A2UI_ENABLED and a2ui):
        return [text_part], False

    # 1) Full-pipeline artifact (optimization / admet) → candidate structures + 3D pose.
    results = _fetch_results_artifact(run_id) if run_id else None
    if results:
        structure_url = None
        if RENDER_3D_ENABLED:
            dock_id = results.get("dock_id")
            pose = _top_pose_path(results)
            if dock_id and pose and RENDER_SERVICE_URL:
                protein_uri = f"gs://{GCS_BUCKET}/docking/{dock_id}/protein.pdb"
                structure_url = (f"{RENDER_SERVICE_URL}/render/3d.png"
                                 f"?protein={urllib.parse.quote(protein_uri, safe='')}"
                                 f"&ligand={urllib.parse.quote(pose, safe='')}"
                                 f"&mode=turntable")  # PyMOL ray-traced rotating GIF (cached)
        # Pre-warm the pose GIF so GE fetches a cached image — same cold-render banner race
        # as folds; the docked pose is freshly rendered (dock_id just minted). See _prewarm_render.
        if structure_url:
            _prewarm_render(structure_url, timeout=PREWARM_TURNTABLE_TIMEOUT)
        try:
            messages = a2ui.build_messages_for_artifact(
                results, RENDER_SERVICE_URL, structure_url=structure_url)
            if messages:
                parts = [_a2ui_part(m) for m in messages] + [text_part]
                logger.info(f"[A2A A2UI] {len(messages)} v0.8 messages for {run_id}")
                return parts, True
        except Exception as e:
            logger.warning(f"[A2A A2UI] build failed for {run_id}: {e}")

    # 2) Atomic DiffDock — render the docked pose inline. Checked BEFORE fold: a docking
    #    narrative also carries the target's ".../structures/<x>.pdb" path, which the fold
    #    detector would otherwise grab and render as a bare protein. A fold narrative never
    #    carries a dock_id, so dock-first (keyed off the dock_id) is unambiguous.
    dock = _extract_docked_pose(response_text)
    if dock and RENDER_SERVICE_URL:
        structure_url = (f"{RENDER_SERVICE_URL}/render/3d.png"
                         f"?protein={urllib.parse.quote(dock['protein_gs'], safe='')}"
                         f"&ligand={urllib.parse.quote(dock['pose_gs'], safe='')}"
                         f"&mode=turntable")
        # Pre-warm the pose GIF before emit (cold-render banner race, same as folds).
        _prewarm_render(structure_url, timeout=PREWARM_TURNTABLE_TIMEOUT)
        try:
            messages = a2ui.build_docked_pose_messages(
                dock["target"], dock["confidence"], structure_url)
            parts = [_a2ui_part(m) for m in messages] + [text_part]
            logger.info(f"[A2A A2UI] docked-pose surface for {dock['dock_id']}")
            return parts, True
        except Exception as e:
            logger.warning(f"[A2A A2UI] dock surface failed: {e}")

    # 3) Atomic ESMFold — render the folded protein inline (gs:// PDB from the narrative).
    fold = _extract_folded_structure(response_text)
    if fold and RENDER_SERVICE_URL:
        structure_url = (f"{RENDER_SERVICE_URL}/render/3d.png"
                         f"?protein={urllib.parse.quote(fold['gs'], safe='')}"
                         f"&color_by=plddt&mode=turntable")  # pLDDT-colored spinning cartoon
        # Pre-warm the GIF so GE fetches a cached (instant) image — a fold always mints a
        # NEW structure, so the inline image is otherwise a guaranteed cold miss and GE flags
        # the unresolved Image as a form-validation error. Blocks until the spin is cached
        # (longer budget than a snapshot since the GIF scales with size). See _prewarm_render.
        _prewarm_render(structure_url, timeout=PREWARM_TURNTABLE_TIMEOUT)
        try:
            messages = a2ui.build_protein_structure_messages(
                fold["name"], fold["plddt"], structure_url)
            parts = [_a2ui_part(m) for m in messages] + [text_part]
            logger.info(f"[A2A A2UI] folded-structure surface for {fold['name']}")
            return parts, True
        except Exception as e:
            logger.warning(f"[A2A A2UI] fold surface failed: {e}")

    return [text_part], False


# ──────────────────────────────────────────────────────────────────
# A2A streaming-event constructors (SSE)
# ──────────────────────────────────────────────────────────────────

def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _task_event(request_id, task_id, context_id, state) -> dict:
    return {
        "jsonrpc": "2.0", "id": request_id,
        "result": {
            "kind": "task", "id": task_id, "contextId": context_id,
            "status": {"state": state, "timestamp": _now()},
        },
    }


def _status_update(request_id, task_id, context_id, state,
                   text=None, timeline_delta=None, parts=None, final=False) -> dict:
    status = {"state": state, "timestamp": _now()}
    msg_parts = parts if parts is not None else ([{"kind": "text", "text": text}] if text else None)
    if msg_parts:
        status["message"] = {
            "kind": "message", "messageId": str(uuid.uuid4()),
            "role": "agent", "parts": msg_parts,
            "contextId": context_id, "taskId": task_id,
        }
    result = {
        "kind": "status-update", "taskId": task_id, "contextId": context_id,
        "status": status, "final": final,
    }
    if timeline_delta:
        result["meta"] = {"timeline_delta": timeline_delta}
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _artifact_update(request_id, task_id, context_id, parts) -> dict:
    return {
        "jsonrpc": "2.0", "id": request_id,
        "result": {
            "kind": "artifact-update", "taskId": task_id, "contextId": context_id,
            "artifact": {
                "artifactId": str(uuid.uuid4()),
                "name": "molforge_response", "parts": parts,
            },
            "lastChunk": True,
        },
    }


@app.post("/")
async def jsonrpc_handler(request: Request):
    # ──────── Multi-turn diagnostic: log headers + incoming identifiers ────────
    try:
        headers_dict = {k: v for k, v in request.headers.items()}
        # Redact sensitive values but show their presence + length
        safe_headers = {}
        for k, v in headers_dict.items():
            kl = k.lower()
            if kl in ("authorization", "cookie", "x-goog-iap-jwt-assertion", "x-serverless-authorization"):
                safe_headers[k] = f"[REDACTED {len(v)} chars]"
            else:
                safe_headers[k] = v
        logger.info(f"[A2A HEADERS] {json.dumps(safe_headers)[:2500]}")
    except Exception as he:
        logger.warning(f"[A2A HEADERS] extraction failed: {he}")

    try:
        body = await request.json()
        logger.info(f"[A2A REQUEST] keys={list(body.keys())}")
        logger.info(f"[A2A FULL BODY] {json.dumps(body)[:2000]}")
        # Explicitly surface every possible multi-turn identifier so we can grep logs cleanly
        _params = body.get("params", {}) or {}
        _msg = _params.get("message", {}) or {}
        logger.info(
            f"[A2A IDENTIFIERS] "
            f"params.contextId={_params.get('contextId')} "
            f"params.taskId={_params.get('taskId')} "
            f"message.messageId={_msg.get('messageId')} "
            f"metadata={json.dumps(_params.get('metadata', {}))}"
        )
    except Exception as e:
        return JSONResponse(status_code=400, content={
            "jsonrpc": "2.0", "error": {"code": -32700, "message": f"Parse error: {e}"}, "id": None,
        })

    request_id = body.get("id", str(uuid.uuid4()))
    method = body.get("method", "")
    params = body.get("params", {})

    if method not in ("tasks/send", "message/send", "message/stream"):
        return JSONResponse(content={
            "jsonrpc": "2.0",
            "error": {"code": -32601, "message": f"Method not found: {method}"},
            "id": request_id,
        })

    message = params.get("message", {})
    parts = message.get("parts", [])
    user_text = "".join(p.get("text", "") for p in parts if p.get("kind") == "text")

    if not user_text:
        return JSONResponse(content={
            "jsonrpc": "2.0",
            "error": {"code": -32602, "message": "No text content in message parts"},
            "id": request_id,
        })

    task_id = params.get("taskId", str(uuid.uuid4()))

    # ──────── Multi-turn stable identifier extraction ────────
    # A2A 0.2.1: contextId is nested at params.message.contextId (Gemini Enterprise puts it there).
    # Some clients also set params.contextId. If absent on turn 1, we generate and return it;
    # GE will echo it back on subsequent turns, giving us a stable conversation id.
    incoming_ctx = (
        (message.get("contextId") if isinstance(message, dict) else None)
        or params.get("contextId")
    )
    context_id = incoming_ctx or str(uuid.uuid4())
    logger.info(f"[A2A CONTEXT] incoming={incoming_ctx} stable_context_id={context_id}")

    # GE's advertised A2UI component catalog (None => emit optimistically)
    catalog = _extract_a2ui_catalog(params, message)

    try:
        orchestrator = get_agent(ORCHESTRATOR_ENGINE_ID)

        # Agent Runtime session — first turn creates, later turns reuse
        ae_user_id = f"a2a-{context_id}"
        ae_session_id = _get_or_create_ae_session(orchestrator, ae_user_id)

        stream_kwargs = {"user_id": ae_user_id, "message": user_text}
        if ae_session_id:
            stream_kwargs["session_id"] = ae_session_id

        # ──────── Streaming path (message/stream): progressive SSE, R1–R3 ────────
        # Emit a Task immediately, a status-update per orchestrator event (so the
        # user watches folding → generation → docking → SAR happen live), then an
        # artifact-update carrying the rich A2UI + a final completed status-update.
        if method == "message/stream":
            logger.info("[A2A RESPONSE MODE] streaming SSE (progressive)")

            def sse_stream():
                text_chunks = []
                timeline = []
                yield _sse(_task_event(request_id, task_id, context_id, "working"))
                try:
                    for event in orchestrator.stream_query(**stream_kwargs):
                        text = extract_text_from_event(event)
                        if text:
                            text_chunks.append(text)
                        try:
                            delta = build_timeline_entry(event)
                        except Exception as te:
                            logger.warning(f"Timeline build failed for one event: {te}")
                            delta = []
                        timeline.extend(delta)
                        # Progress ONLY — no message text in interim updates. GE renders
                        # every status message, and the orchestrator repeats its narrative
                        # across delegation steps; streaming text here triples it. The full
                        # (de-duplicated) text is sent once, at completion.
                        if delta:
                            yield _sse(_status_update(
                                request_id, task_id, context_id, "working",
                                timeline_delta=delta,
                            ))

                    response_text = "\n".join(text_chunks).strip() or \
                        "(No text response received from orchestrator)"
                    run_id = _extract_run_id(timeline)
                    parts, a2ui_present = _build_rich_parts(run_id, response_text, catalog)
                    # GE's A2UI renderer engages the surface from interim 'working'
                    # status-updates — NOT the terminal 'completed' message (which it treats
                    # as the final chat bubble → text only). So emit each A2UI DataPart as its
                    # own progressive 'working' update FIRST (surfaceUpdate then beginRendering),
                    # matching the known-good Catalyst contract; the 'completed' message then
                    # carries the FULL content (all DataParts + text) for the final commit.
                    # (Only DataParts go in the working updates — never the narrative text — so
                    # there is no text-tripling.) This is what makes inline rendering actually
                    # appear in GE over SSE; sending A2UI only in 'completed' silently no-ops.
                    for ap in parts:
                        if ap.get("metadata", {}).get("mimeType") == "application/json+a2ui":
                            yield _sse(_status_update(
                                request_id, task_id, context_id, "working",
                                parts=[ap],
                            ))
                    yield _sse(_status_update(
                        request_id, task_id, context_id, "completed",
                        parts=parts, final=True,
                    ))
                    logger.info(f"[A2A STREAM DONE] run_id={run_id} a2ui={a2ui_present} "
                                f"timeline_entries={len(timeline)}")
                except Exception as e:
                    logger.error(f"[A2A STREAM ERROR] {e}", exc_info=True)
                    yield _sse(_status_update(
                        request_id, task_id, context_id, "failed",
                        text=f"Internal error: {e}", final=True,
                    ))

            return StreamingResponse(
                sse_stream(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                    # A2UI negotiation header GE reads to engage its A2UI renderer.
                    **({"X-A2A-Extensions": A2UI_EXT} if A2UI_ENABLED else {}),
                },
            )

        # ──────── Non-streaming path (message/send, tasks/send) ────────
        text_chunks = []
        timeline = []
        for event in orchestrator.stream_query(**stream_kwargs):
            text = extract_text_from_event(event)
            if text:
                text_chunks.append(text)
            try:
                timeline.extend(build_timeline_entry(event))
            except Exception as te:
                logger.warning(f"Timeline build failed for one event: {te}")

        response_text = "\n".join(text_chunks).strip() or "(No text response received from orchestrator)"
        run_id = _extract_run_id(timeline)
        parts, a2ui_present = _build_rich_parts(run_id, response_text, catalog)

        response_content = {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "kind": "task",
                "id": task_id,
                "contextId": context_id,
                "status": {
                    "state": "completed",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "message": {
                        "kind": "message",
                        "messageId": str(uuid.uuid4()),
                        "role": "agent",
                        "parts": parts,
                    },
                },
                "artifacts": [{
                    "artifactId": str(uuid.uuid4()),
                    "name": "molforge_response",
                    "parts": parts,
                }],
            },
            "meta": {
                "timeline": timeline,
                "orchestrator_engine_id": ORCHESTRATOR_ENGINE_ID,
                "a2ui_present": a2ui_present,
                "run_id": run_id,
                "completed_at": datetime.now(timezone.utc).isoformat(),
            },
        }
        logger.info(f"[A2A RESPONSE SHAPE] keys={list(response_content['result'].keys())} a2ui={a2ui_present}")
        logger.info("[A2A RESPONSE MODE] plain JSON")
        return JSONResponse(
            content=response_content,
            headers=({"X-A2A-Extensions": A2UI_EXT} if A2UI_ENABLED else {}),
        )

    except Exception as e:
        logger.error(f"Orchestrator query failed: {e}", exc_info=True)
        return JSONResponse(content={
            "jsonrpc": "2.0", "id": request_id,
            "error": {"code": -32603, "message": f"Internal error: {str(e)}"},
        })


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8080")))
