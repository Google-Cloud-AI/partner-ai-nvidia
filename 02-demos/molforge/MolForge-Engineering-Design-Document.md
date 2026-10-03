---
title: "MolForge"
subtitle: "Engineering Design Document — Agentic AI Drug Discovery Platform on NVIDIA × Google Cloud"
author: "Schneider Larbi, Senior Manager, Global Partner Technical Architecture (AI & SaaS ISVs), Google Cloud"
date: "April 2026"
version: "1.0"
classification: "Google Cloud Partner Confidential"
---

# MolForge — Engineering Design Document

**Agentic AI Drug Discovery Platform on NVIDIA × Google Cloud**

Schneider Larbi
Senior Manager, Global Partner Technical Architecture — AI & SaaS ISVs
Google Cloud

April 2026 · Version 1.0

Classification: Google Cloud Partner Confidential

> ⚠️ **SUPERSEDED — v1 reference (April 2026).** This document describes the **v1** architecture, in which DiffDock and GenMol ran as **self-hosted NVIDIA NIMs on a GKE A100 node pool** (`gpu-diffdock-a100`). **v2 (June 2026) supersedes it:** GenMol and DiffDock are now consumed as **NVIDIA-hosted NIMs** (`build.nvidia.com`) — **there is no A100 node pool** — and only ESM-2 / ESMFold runs locally, on a single **RTX PRO 6000 Blackwell** GPU. Any "A100", `gpu-diffdock-a100`, or self-hosted-DiffDock references below are **v1-historical and intentionally preserved**. For the current architecture see **`README.md`**.

---

## Document Control

| Version | Date | Author | Status | Distribution |
|---------|------|--------|--------|-------------|
| 1.0 | April 2026 | Schneider Larbi | Final | NVIDIA Partner Engineering, Google Cloud Field CTO Office, Customer Technical Architecture Teams |

This document will be revised at each major phase completion or architectural decision change. Minor corrections are tracked via the source repository's git history.

---

## Section 1 — Executive Summary

MolForge is a production-deployed agentic AI drug discovery platform that enables medicinal chemists to optimize lead compounds, predict molecular binding, and screen for pharmacokinetic safety through natural-language interaction. It is the reference implementation of NVIDIA × Google Cloud co-innovation in life sciences: NVIDIA provides the scientific reasoning (Nemotron), biological compute (GenMol, DiffDock, ESMFold), and inference infrastructure (NIM, BioNeMo Framework), while Google Cloud provides the orchestration (Gemini 2.5 Pro via ADK Agent Runtime), enterprise integration (Gemini Enterprise via A2A), and production infrastructure (GKE, Cloud Run, Cloud Storage).

### Co-Innovation Thesis

The pharmaceutical industry needs AI systems that combine orchestration intelligence (decompose complex multi-step workflows) with domain-specific scientific reasoning (structure-activity analysis, pharmacological safety assessment). Neither capability alone is sufficient. MolForge demonstrates that Gemini excels at orchestration and tool dispatch while NVIDIA Nemotron excels at scientific reasoning and narrative generation — and that composing them through Google's Agent Development Kit produces a system greater than the sum of its parts.

### Target Audience and Use Cases

MolForge serves medicinal chemists and computational pharmacologists working in lead optimization and preclinical safety screening. Three validated use cases:

1. **Lead optimization** — Given a lead compound SMILES and a target protein, generate structurally diverse variants, dock them against the target, compute drug-likeness properties, and produce a ranked SAR analysis with scientific rationale.
2. **ADMET safety screening** — Given candidate molecules, predict 41 ADMET endpoints, contextualize scores against DrugBank-approved drugs, and produce traffic-light verdicts with pharmacological narrative.
3. **Atomic operations** — Single-step protein folding (ESMFold) or molecular docking (DiffDock) for scientists who need one result, not a full pipeline.

### Validated Results (Phase 1–3)

| Phase | Scope | Key Metrics |
|-------|-------|-------------|
| Phase 1 | Base delegation — Orchestrator → Lead Optimizer → ADMET Safety | Full pipeline returns ranked candidates with Nemotron SAR narrative |
| Phase 2 | Atomic delegations with verbatim-field-surfacing instructions | atomic_dock: 1.91s latency, confidence 0.043; atomic_fold: pLDDT scores populated; full pipeline: 32 candidates with Nemotron SAR |
| Phase 3 | ESMFold GCS upload via Workload Identity; Mol* viewer pages (/protein, /docking) | End-to-end from natural language to interactive 3D viewer links surfaced in Gemini Enterprise |

### Architecture Summary

MolForge is a four-tier system: a presentation tier (React dashboard, Mol* viewer, Gemini Enterprise), an orchestration tier (three ADK agents on Agent Runtime communicating via tool calls), an execution tier (six GPU/CPU microservices on GKE), and a persistence tier (Cloud Storage for artifacts, Artifact Registry for images). An A2A JSON-RPC 2.0 bridge on Cloud Run connects the orchestration tier to external consumers. The system runs heterogeneous NVIDIA compute: RTX PRO 6000 Blackwell for GenMol and ESMFold, A100 for DiffDock NIM, CPU for ADMET-AI and RDKit.

### Status

Production-deployed and validated in Gemini Enterprise. All three build phases complete. Agent Runtime IDs stable. GKE services healthy with scale-to-zero economics on all GPU pools.

---

## Section 2 — Solution Overview and Business Context

### The Drug Discovery Problem Space

Lead optimization and ADMET safety screening are the two most computationally intensive stages of early-phase drug discovery. A medicinal chemist starts with a hit compound (typically identified from a high-throughput screen or literature) and must systematically modify it to improve binding affinity, selectivity, drug-likeness, and safety — while maintaining synthetic accessibility. This process traditionally involves:

- Manual design of 5–20 molecular variants per cycle
- Weeks of synthesis and wet-lab testing per iteration
- Separate teams for chemistry (lead optimization) and pharmacology (ADMET screening)
- Disconnected tooling: docking software, property calculators, ADMET predictors, literature databases

A single lead-to-candidate campaign typically spans 12–18 months and costs $2–5M in personnel and consumables before a molecule enters preclinical development.

### Why Agentic AI Fits This Domain

Drug discovery is inherently multi-step, multi-tool, and judgment-intensive. A medicinal chemist does not simply run one computation — they orchestrate a sequence of decisions: generate variants, score them, filter by properties, assess binding, evaluate safety, compare to known drugs, and decide what to synthesize next. This is precisely the pattern that agentic AI excels at: decompose a complex goal into tool-mediated steps, execute them, synthesize results, and present actionable recommendations.

The critical requirement is that scientific judgment (which candidates are promising, which should be killed, what structural modifications explain observed activity) must come from a model trained on chemistry, not from a general-purpose LLM making things up. MolForge solves this by separating orchestration (Gemini) from reasoning (Nemotron): Gemini decides what to do next, Nemotron decides what the results mean.

### How MolForge Accelerates the Process

MolForge compresses the lead optimization cycle from weeks to minutes:

- **50 molecular variants** generated in a single GenMol call (seconds-scale on Blackwell)
- **Batch docking** of all 50 against the target protein in one DiffDock NIM call (validated: 1.91s for 10 poses on A100)
- **Physicochemical properties** for all 50 computed by RDKit in <1 second
- **SAR analysis** by Nemotron Super 49B v1.5 ranking and explaining the full candidate set (seconds-scale)
- **ADMET screening** of top candidates with 41 endpoints and pharmacological narrative (seconds-scale)

Total wall-clock time for a complete optimization cycle: under 60 seconds (estimated; individual steps validated in Phase 2, end-to-end aggregate not independently timed). The scientist receives a ranked shortlist with binding scores, drug-likeness profiles, safety verdicts, and a written scientific rationale — plus interactive 3D viewer links for every docking pose.

### Enterprise Entry Point: Gemini Enterprise

MolForge is accessed through Gemini Enterprise via the A2A protocol. This is a deliberate architectural choice: the enterprise entry point is already deployed and governed in the customer's Google Workspace environment. Scientists interact with MolForge using natural language in the same interface they use for email, documents, and other enterprise AI capabilities. No separate application to install, no credentials to manage, no UI to learn.

### PharmaPilot as Downstream Consumer

PharmaPilot is an external peer system (literature research assistant) that consumes MolForge capabilities via A2A. This demonstrates the composability of the A2A protocol: MolForge is both a consumer of A2A (receiving requests from Gemini Enterprise) and a provider to other sovereign systems.

---

## Section 3 — Architecture Overview

### Four-Tier Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        PRESENTATION TIER                                 │
│                                                                          │
│  ┌──────────────┐  ┌──────────────────┐  ┌───────────────────────────┐  │
│  │   Gemini     │  │  React Dashboard │  │  molforge-viewer          │  │
│  │  Enterprise  │  │  (Cloud Run)     │  │  (Cloud Run, Mol*)        │  │
│  └──────┬───────┘  └────────┬─────────┘  └───────────────────────────┘  │
│         │                   │                                            │
└─────────┼───────────────────┼────────────────────────────────────────────┘
          │ A2A 0.2.1         │ A2A 0.2.1
          ▼                   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                       ORCHESTRATION TIER                                  │
│                                                                          │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │              A2A Bridge (Cloud Run, FastAPI)                       │   │
│  │              JSON-RPC 2.0 → Agent Runtime stream_query()          │   │
│  └──────────────────────────────┬───────────────────────────────────┘   │
│                                 │ Agent Platform SDK                     │
│                                 ▼                                        │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │         Orchestrator Agent (Gemini 2.5 Pro on Agent Runtime)      │   │
│  │         Engine ID: 1768657362010243072                            │   │
│  └─────────────┬───────────────────────────────────┬────────────────┘   │
│                │ tool call (delegation)             │ tool call           │
│                ▼                                    ▼                     │
│  ┌─────────────────────────┐    ┌──────────────────────────────────┐    │
│  │  Lead Optimizer Agent   │    │  ADMET Safety Agent              │    │
│  │  (Nemotron Super 49B)   │    │  (Nemotron Nano 8B)              │    │
│  │  Engine: 406549317...   │    │  Engine: 502011555...            │    │
│  └─────────────┬───────────┘    └──────────────┬───────────────────┘    │
│                │                                │                        │
└────────────────┼────────────────────────────────┼────────────────────────┘
                 │ HTTP tool calls                 │ HTTP tool calls
                 ▼                                 ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                        EXECUTION TIER (GKE)                               │
│                                                                          │
│  ┌────────────┐ ┌────────────┐ ┌────────────┐   GPU (Blackwell/A100)    │
│  │   GenMol   │ │  ESMFold   │ │  DiffDock  │                           │
│  │ Blackwell  │ │ Blackwell  │ │   A100     │                           │
│  └────────────┘ └────────────┘ └────────────┘                           │
│                                                                          │
│  ┌────────────┐ ┌────────────┐ ┌──────────────┐   CPU                   │
│  │   RDKit    │ │  ADMET-AI  │ │Data Retrieval│                          │
│  └────────────┘ └────────────┘ └──────────────┘                          │
└─────────────────────────────────────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                       PERSISTENCE TIER                                    │
│                                                                          │
│  ┌─────────────────────┐  ┌──────────────────┐  ┌───────────────────┐  │
│  │ gs://molforge-       │  │ Artifact Registry│  │ BigQuery (planned)│  │
│  │ artifacts            │  │ molforge-repo    │  │ audit dataset     │  │
│  └─────────────────────┘  └──────────────────┘  └───────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
```

### High-Level Data Flow

1. A scientist sends a natural-language request via Gemini Enterprise (or the React Dashboard).
2. The A2A bridge receives the JSON-RPC 2.0 message and forwards it to the Orchestrator Agent Runtime via `stream_query()`.
3. The Orchestrator (Gemini 2.5 Pro) decomposes the request into tool calls — optionally gathering context from the Data Retrieval service first (RCSB PDB, UniProt, ChEMBL, ZINC20).
4. The Orchestrator delegates to a specialist agent (Lead Optimizer or ADMET Safety) via a delegation tool that internally calls `stream_query()` on the specialist's Agent Runtime.
5. The specialist agent calls its primary single-shot tool (`optimize_lead_complete` or `screen_molecules_complete`) which internally chains multiple GPU/CPU service HTTP calls.
6. Results are persisted to `gs://molforge-artifacts/{run_id}/` as JSON with embedded SMILES, scores, and narratives.
7. The specialist returns a structured response including a viewer URL back through the delegation chain.
8. The Orchestrator surfaces the specialist's narrative verbatim to the scientist, along with viewer links.

### Trust Boundaries

> **As deployed, the external boundary is not enforced.** Every Cloud Run service and the ESMFold
> LoadBalancer run `--allow-unauthenticated`, so the boundaries below describe the intended design,
> not the running demo. This was opened on purpose — a reference implementation that requires an
> identity story before it will answer a single request does not get stood up — and it is the one
> boundary that **must** be closed before this design is used for real work. See §11, Security
> Posture.

- **External boundary**: Gemini Enterprise → A2A Bridge (Cloud Run IAM, allow-unauthenticated for prototype; production would use IAP or service-account auth).
- **Agent Runtime boundary**: A2A Bridge → Agent Runtimes (Agent Platform SDK with Application Default Credentials).
- **GKE internal boundary**: Agent tool code → GKE services (cluster-internal HTTP, no auth; services are not exposed externally in production — LoadBalancer IPs are for workshop convenience only).
- **GCS boundary**: GKE pods → Cloud Storage (Workload Identity binding, no service-account keys).
- **NGC boundary**: GKE → nvcr.io (image-pull secret `ngc-secret`) and NIM → NGC model registry (runtime secret `ngc-runtime-key`).

### Where State Lives

- **Conversation state**: Agent Runtime session store (keyed by A2A contextId).
- **Run artifacts**: `gs://molforge-artifacts/{run_id}/` — optimization_results.json, admet_results.json, docking poses, predicted PDB files.
- **Model weights**: Cached in pod memory (GenMol, ESMFold, ADMET-AI) or downloaded at startup from NGC (DiffDock NIM cache at /opt/nim/.cache).
- **Container images**: Artifact Registry `molforge-repo`.

### Where Compute Happens

| Workload | Runtime | GPU | Node Pool |
|----------|---------|-----|-----------|
| GenMol (molecule generation) | GKE, NGC PyTorch 26.02 | RTX PRO 6000 Blackwell 96GB | gpu-genmol |
| ESMFold (protein folding) | GKE, NGC PyTorch 26.02 | RTX PRO 6000 Blackwell 96GB | gpu-esmfold |
| DiffDock NIM (molecular docking) | GKE, NIM container | A100 40GB | gpu-diffdock-a100 |
| RDKit, ADMET-AI, Data Retrieval | GKE, python:3.12-slim | None (CPU) | default-pool |
| ADK Agents | Agent Runtime | N/A (serverless) | Managed by Agent Platform |
| A2A Bridge, Viewer, Dashboard | Cloud Run | N/A (serverless) | Managed by Cloud Run |

### Where Decisions Are Made

All scientific decisions (ranking, filtering, safety verdicts, SAR interpretation) are made by NVIDIA Nemotron models via system instructions — never by hardcoded thresholds in Python code. Orchestration decisions (what to do next, which agent to delegate to) are made by Gemini 2.5 Pro. This separation is load-bearing and intentional.

---

## Section 4 — Component Design

### 4.1 Orchestrator Agent

**Purpose.** The Orchestrator is the Principal Investigator of MolForge. It receives natural-language requests from scientists, decomposes them into actionable steps, gathers context from public databases, delegates to specialist agents, and synthesizes results into a coherent response.

**Technology choice.** Gemini 2.5 Pro on Agent Runtime (ADK). Gemini was chosen for orchestration because it excels at instruction-following, multi-step tool dispatch, and structured output formatting. It does not perform scientific reasoning — that is delegated entirely to Nemotron.

**Engine ID.** 1768657362010243072

**Internal structure.** The agent is defined in `agents/orchestrator/agent.py` as an ADK `Agent` instance with:

- A detailed system instruction (~120 lines) that specifies: role definition, team composition, atomic delegation patterns (ATOMIC DOCKING, ATOMIC FOLDING), the four-step workflow (acknowledge → gather context → delegate → compile), and behavioral rules (verbatim narrative surfacing, no self-generated run_ids).
- Ten registered tools across three categories: data retrieval (4), delegation (5), artifact management (1).

**Inputs/Outputs.**

- Input: Natural-language message from the A2A bridge (via `stream_query()`).
- Output: Streamed events containing text responses with embedded viewer URLs, run_ids, and structured metadata for the dashboard timeline.

**Dependencies.** Agent Runtime; Lead Optimizer Engine (ID 4065493171969196032); ADMET Safety Engine (ID 5020115555483385856); Data Retrieval service (HTTP); PharmaPilot A2A server (HTTP, optional).

**Configuration surface.** Environment variables in `.env`: `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION`, `LEAD_OPTIMIZER_ENGINE_ID`, `ADMET_SAFETY_ENGINE_ID`, `MOLFORGE_DATA_RETRIEVAL_URL`, `MOLFORGE_VIEWER_URL`, `PHARMAPILOT_A2A_URL`.

**Scaling.** Managed by Agent Runtime — auto-scales based on request volume. Stateless per-request; session state lives in Agent Runtime's session store.

**Failure modes.** (1) Sub-agent Engine unreachable → delegation tool returns error dict, Orchestrator informs scientist. (2) Data Retrieval service down → context gathering fails gracefully, delegation proceeds without structure. (3) MALFORMED_FUNCTION_CALL from Gemini → architecture prevents this by collapsing tool chains inside specialist agents.

### 4.2 Lead Optimizer Agent

**Purpose.** The Lead Optimizer is MolForge's medicinal chemist. It generates optimized molecular variants, predicts their binding affinity, computes drug-likeness, and produces a ranked SAR analysis. It also supports atomic single-step operations (docking only, folding only) when the Orchestrator delegates with specific message prefixes.

**Technology choice.** Nemotron Super 49B v1.5 (`nvidia/llama-3.3-nemotron-super-49b-v1.5`) on Agent Runtime. Nemotron was chosen because SAR reasoning requires deep chemistry knowledge that general-purpose models lack. The 49B parameter count provides sufficient capacity for multi-candidate comparative analysis with structural rationale.

**Engine ID.** 4065493171969196032

**Note on codebase vs production configuration.** The codebase's `agent.py` shows `model="gemini-2.5-pro"` from an earlier build phase. The production deployment was reconfigured to Nemotron Super 49B v1.5 via Agent Runtime model override at deployment time. The Engine ID above reflects the production configuration.

**Internal structure.** Defined in `agents/lead_optimizer/agent.py`. The system instruction specifies:

- A primary tool (`optimize_lead_complete`) that the LLM must always call for optimization requests — one tool call, no chaining.
- Atomic mode instructions (ATOMIC DOCKING, ATOMIC FOLDING) triggered by message prefix.
- Explicit rules for verbatim field surfacing: dock_id, confidence scores, plddt_mean, viewer URLs must be presented as numbers, not prose.
- Eight registered tools: `optimize_lead_complete` (primary), plus six backup tools for fallback and two atomic tools (`dock_molecules`, `predict_structure`).

**The single-tool pattern.** `optimize_lead_complete` (in `tools/optimize_complete.py`) internally chains: ESMFold → GenMol → DiffDock → RDKit → Nemotron SAR → GCS storage. This pattern exists because Gemini (and Nemotron) produce MALFORMED_FUNCTION_CALL errors when asked to chain multiple tool calls with large structured outputs. Collapsing the chain into one Python function eliminates this failure mode entirely.

**Inputs/Outputs.**

- Input: Message from Orchestrator's delegation tool (via `stream_query()`), containing lead SMILES, target info, objectives, therapeutic area.
- Output: Structured dict with run_id, candidate list (SMILES + binding scores + properties), full Nemotron SAR narrative, executive summary, viewer URLs.

**Dependencies.** GenMol service (HTTP :8000), DiffDock service (HTTP :8000), ESMFold service (HTTP :8000), RDKit service (HTTP :8080), Nemotron Super 49B Model Garden endpoint (HTTPS rawPredict), GCS bucket.

**Configuration surface.** `MOLFORGE_GENMOL_URL`, `MOLFORGE_DIFFDOCK_URL`, `MOLFORGE_ESMFOLD_URL`, `MOLFORGE_RDKIT_URL`, `MOLFORGE_VIEWER_URL`, `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION`.

**Scaling.** Agent Runtime managed. The bottleneck is the downstream GPU services, not the agent itself.

**Failure modes.** (1) GenMol failure → hard failure (no candidates to proceed with). (2) DiffDock failure → non-fatal (pipeline continues without docking scores). (3) ESMFold failure → non-fatal (pipeline proceeds without structure, skips docking). (4) Nemotron SAR failure → degraded output (candidates returned without narrative). All failures are collected in an `errors` list and surfaced to the Orchestrator.

### 4.3 ADMET Safety Agent

**Purpose.** The ADMET Safety Agent is MolForge's pharmacologist. It screens candidate molecules for safety across 41 ADMET endpoints and produces traffic-light verdicts (PROCEED / INVESTIGATE / KILL) with pharmacological narrative.

**Technology choice.** Nemotron Nano 8B on Agent Runtime. The smaller model is sufficient for ADMET narrative generation (which is less reasoning-intensive than SAR analysis) and provides faster response times.

**Engine ID.** 5020115555483385856

**Internal structure.** Defined in `agents/admet_safety_agent/agent.py`. Same single-tool pattern as the Lead Optimizer:

- Primary tool: `screen_molecules_complete` — internally chains ADMET-AI → RDKit → Nemotron Nano narrative → GCS storage.
- System instruction specifies therapeutic-area-aware interpretation (oncology drugs have wider safety margins; CNS drugs require BBB penetration and zero hERG tolerance).
- Backup tools for fallback: `predict_admet_properties`, `compute_properties`, `generate_safety_report`, `store_admet_results`.

**Inputs/Outputs.**

- Input: SMILES list, therapeutic area, optimization context, optional ATC filter.
- Output: Structured dict with run_id, per-molecule ADMET predictions, physicochemical properties, full Nemotron safety narrative, viewer URL.

**Dependencies.** ADMET-AI service (HTTP :8080), RDKit service (HTTP :8080), Nemotron Nano VL Model Garden endpoint (HTTPS rawPredict), GCS bucket.

**Failure modes.** (1) ADMET-AI failure → hard failure. (2) RDKit failure → non-fatal. (3) Nemotron narrative failure → degraded (raw predictions returned without interpretation).

### 4.4 GenMol GPU Service

**Purpose.** Generates structurally diverse molecular variants from a seed SMILES string using masked diffusion on SAFE-format representations.

**Technology choice.** BioNeMo Framework (with safe-mol fallback) on NGC PyTorch 26.02. BioNeMo Framework was chosen over GenMol NIM 1.0.1 because the NIM was Blackwell-incompatible at time of build. The Framework container (NGC PyTorch 26.02) ships with CUDA 13.1.1 and sm_120 kernels — the first NGC container to support Blackwell natively.

**Runtime.** GKE pod on `gpu-genmol` node pool (g4-standard-48, RTX PRO 6000 Blackwell 96GB).

**Internal structure.** `services/genmol/app.py` — FastAPI with lifespan-managed model loading. Supports four generation modes: `scaffold_decoration`, `motif_extension`, `linker_design`, `de_novo`. Falls back to safe-mol `SAFEDesign.load_default()` when BioNeMo GenMolInference is not available.

**API.** `POST /generate` — accepts seed_smiles, generation_mode, num_molecules, fragment_constraints. Returns generated SMILES with validity flags and scaffold-preservation indicators.

**Scaling.** Single replica (model cached in GPU memory). Scale-to-zero when idle. Cold start: ~60s (model download from HuggingFace).

### 4.5 ESMFold GPU Service

**Purpose.** Predicts protein 3D structure from amino-acid sequence. Used when no experimental structure exists in RCSB PDB.

**Technology choice.** HuggingFace `facebook/esmfold_v1` on NGC PyTorch 26.02. ESMFold was chosen because it predicts from single sequences without multiple sequence alignments (fast, no database dependency).

**Runtime.** GKE pod on `gpu-esmfold` node pool (g4-standard-48, RTX PRO 6000 Blackwell 96GB).

**Internal structure.** `services/esmfold/app.py` — FastAPI with lifespan-managed model loading. Loads EsmForProteinFolding in half-precision on CUDA. Uploads predicted PDB to GCS via Workload Identity binding.

**API.** `POST /predict` — accepts sequence and protein_name. Returns pdb_content, pdb_gcs_path, plddt_mean, plddt_per_residue, high_confidence_regions, viewer_url.

**Key dependency pin.** `transformers<4.47.0` — versions 4.47+ removed the `openfold_utils` module that ESMFold requires.

**Scaling.** Single replica. Scale-to-zero. Cold start: ~120s (model download + CUDA compilation).

### 4.6 DiffDock NIM Service

**Purpose.** Predicts ligand binding poses against a protein target using diffusion-based molecular docking. The highest-fidelity binding prediction in the pipeline.

**Technology choice.** NVIDIA DiffDock NIM 2.2.0 (`nvcr.io/nim/mit/diffdock:2.2.0`). Pre-built NIM container with PLINDER+SAIR-trained checkpoints and cuEquivariance optimizations.

**Runtime.** GKE pod on `gpu-diffdock-a100` node pool (a2-highgpu-1g, A100 40GB, us-central1-c).

**The heterogeneous-topology decision.** DiffDock NIM 2.2.0 ships with PyTorch built for CUDA sm_50–sm_90 (Volta through Hopper). Blackwell is sm_120 — not in the supported architecture list. Attempting to run on Blackwell produces either silent CPU-only fallback (catastrophic latency) or kernel launch failures. NVIDIA officially tests DiffDock NIM on A100 (sm_80), confirmed by the BioNeMo Blueprint reference architecture.

The practical consequence: MolForge runs a heterogeneous GPU topology. Five services run on Blackwell. One service — DiffDock — runs on A100. This is not a workaround; it mirrors how production pharma deployments route each workload to its optimal GPU class. When NVIDIA ships a Blackwell-compatible DiffDock NIM (2.3.x or 3.0), migration is one line: change the `nodeSelector` from `gpu-diffdock-a100` to `gpu-diffdock`.

**Required environment variables (driver compatibility).** GKE A100 nodes run NVIDIA driver 580+, which the NIM's NVIDIA_REQUIRE_CUDA metadata does not list. Three env vars are mandatory:

```yaml
NVIDIA_DISABLE_REQUIRE: "true"      # Skip driver-version constraint check
LD_LIBRARY_PATH: "/usr/local/nvidia/lib64:/usr/local/cuda/lib64"  # Find injected driver libs
PATH: "/usr/local/nvidia/bin:/usr/local/cuda/bin:..."             # Find nvidia-smi
```

**Two-secret pattern.** The deployment requires two K8s secrets: `ngc-secret` (docker-registry type, for pulling `nvcr.io/nim/mit/diffdock:2.2.0`) and `ngc-runtime-key` (opaque type, exposing `NGC_API_KEY` for model-checkpoint download at startup).

**API.** `POST /molecular-docking/diffdock/generate` — accepts ligand (SMILES text with real newlines), protein (PDB ATOM lines with real newlines), num_poses, time_divisions, steps. Returns ligand_positions (SDF per pose) and position_confidence (float per pose).

**Critical constraints.** (1) Single-chain PDB only — multi-chain crystals must be filtered to chain A before submission. (2) Newlines must be real (0x0A), not escaped backslash-n. (3) Batch mode: multiple SMILES separated by newlines dock in one call (10–15× faster than sequential).

**Performance.** ABL kinase (263 residues) + Imatinib: 10 poses in 1.91 seconds on A100 (Phase 2 validated). Top pose confidence: 0.043.

**Scaling.** Single replica. Scale-to-zero. Cold start: 5–10 minutes (8 GB checkpoint download from NGC).

### 4.7 ADMET-AI v2 CPU Service

**Purpose.** Predicts 41 ADMET (Absorption, Distribution, Metabolism, Excretion, Toxicity) properties using Chemprop-RDKit graph neural networks trained on Therapeutics Data Commons datasets.

**Technology choice.** Open-source `admet-ai` Python package. CPU-only — no NVIDIA NIM exists for ADMET prediction. The decision to accept CPU-only was deliberate: ADMET-AI inference is fast enough on CPU for batch sizes under 1000 molecules, and no GPU allocation is needed.

**Runtime.** GKE pod on `default-pool` (e2-standard-4, CPU).

**API.** `POST /predict` — accepts smiles_list and optional drugbank_atc_filter. Returns per-molecule predictions organized by category (absorption, distribution, metabolism, excretion, toxicity) plus DrugBank percentile context.

**Scaling.** Single replica. Lazy model loading on first request (avoids cold-start latency during pod scheduling).

### 4.8 RDKit CPU Service

**Purpose.** Computes physicochemical properties (molecular weight, LogP, HBD/HBA, TPSA, rotatable bonds, Lipinski violations, QED, synthetic accessibility score) and renders 2D structure SVGs.

**Technology choice.** RDKit open-source cheminformatics toolkit. CPU-only.

**Runtime.** GKE pod on `default-pool`.

**API.** `POST /properties` — accepts smiles_list, returns per-molecule property dict. `POST /render` — accepts SMILES + optional scaffold highlight, returns SVG markup.

### 4.9 Data Retrieval CPU Service

**Purpose.** Unified API for querying public biological databases. Provides the Orchestrator with grounded scientific context before delegation.

**Technology choice.** FastAPI wrapping four public APIs: RCSB PDB (protein 3D structures), UniProt (sequences and annotations), ChEMBL (known active compounds), ZINC20 (purchasable analogues).

**Runtime.** GKE pod on `default-pool`.

**API.** `POST /protein/structure`, `POST /protein/sequence`, `POST /compound/known-actives`, `POST /compound/purchasable-similar`.

### 4.10 A2A Bridge

**Purpose.** Exposes the Orchestrator Agent to external consumers via the A2A 0.2.1 protocol (JSON-RPC 2.0). Also provides GKE service health probes for the dashboard warmup bar.

**Technology choice.** FastAPI on Cloud Run. Implements the A2A protocol: `/.well-known/agent.json` (agent card), `POST /` (JSON-RPC handler for `tasks/send`, `message/send`, `message/stream`).

**Internal structure.** `a2a/server.py` — the largest single source file in the codebase. Key responsibilities:

1. **Agent card serving** — four skills: `protein_analysis`, `molecule_generation`, `molecular_docking`, `admet_prediction`.
2. **Session management** — maps A2A `contextId` to Agent Runtime sessions for multi-turn memory.
3. **Timeline construction** — parses every Agent Runtime event into provider-attributed timeline entries for the dashboard's Internal Orchestra panel.
4. **GKE warmup** — `/warmup-all` probes all six GKE services in parallel, classifying each as healthy/cold/unhealthy.
5. **SSE streaming** — `message/stream` returns Server-Sent Events per A2A 0.2.1 spec.

**Configuration.** `ORCHESTRATOR_ENGINE_ID`, `GKE_SERVICES` dict (six service URLs), `A2A_SERVER_URL`.

**Scaling.** Cloud Run auto-scaling. Stateless — session state lives in Agent Runtime.

### 4.11 molforge-viewer

**Purpose.** Rich content viewer for MolForge run artifacts. Exists because Gemini Enterprise's sanitizer blocks inline 3D content and inline images — the viewer-link pattern is the architecturally correct solution to surface interactive molecular visualizations.

**Technology choice.** Express.js backend (reads GCS) + React frontend (renders pages) on Cloud Run. Uses 3Dmol.js for 3D protein/ligand rendering and smiles-drawer for 2D structure diagrams.

**Pages.**

- `/gallery?id={run_id}` — 2D candidate grid with RDKit structures, Lipinski badges, Nemotron SAR narrative.
- `/docking?id={dock_id}` — 3D protein + ligand poses with confidence badges, Mol* auto-rotation.
- `/admet?id={run_id}` — ADMET endpoint table with DrugBank percentile bars and safety narrative.
- `/protein?file={name}.pdb` — Protein ribbon view colored by pLDDT confidence.

**API routes.** `/api/run/:runId`, `/api/dock/:dockId/manifest`, `/api/dock/:dockId/protein`, `/api/dock/:dockId/files`, `/api/dock/:dockId/pose/:filename`, `/api/structure/:filename`.

### 4.12 React Dashboard

**Purpose.** Direct chat interface for interacting with MolForge without going through Gemini Enterprise. Renders everything inline (unlike GE which requires viewer links). Provides real-time observability via the Internal Agent Orchestra panel.

**Technology choice.** React 18 + Vite + Tailwind CSS, served by Nginx on Cloud Run.

**Key panels.** (1) Chat column with markdown rendering (react-markdown + remark-gfm). (2) Internal Agent Orchestra (left sidebar) — color-coded timeline of tool calls and model invocations (NVIDIA green, Google blue). (3) External A2A Interactions (right sidebar) — peer system exchanges. (4) Infrastructure Warmup Bar — health pills for all six GKE services with click-to-probe.

**Configuration.** `A2A_URL` constant in `src/api.js` pointing to the A2A bridge Cloud Run URL.

### 4.13 Persistence Layer

**Purpose.** Durable storage for run artifacts, container images, and (planned) audit data.

**Components.**

- **gs://molforge-artifacts** — Run artifacts. Structure: `{run_id}/optimization_results.json`, `{run_id}/admet_results.json`, `structures/{name}.pdb`, `docking/{dock_id}/manifest.json`, `docking/{dock_id}/protein.pdb`, `docking/{dock_id}/lig{N}_rank{R}_conf{C}.sdf`.
- **Artifact Registry `molforge-repo`** — Container images for all services built via Cloud Build.
- **BigQuery (planned)** — Audit dataset for tracking all agent invocations, run metadata, and cost attribution. [GAP — neither the schema nor the ingestion pipeline is implemented in the codebase.]

---

## Section 5 — Inter-Component Communication

### Protocol Selection Rationale

MolForge uses three communication patterns, each chosen for a specific boundary:

| Boundary | Protocol | Reason |
|----------|----------|--------|
| External → Bridge | A2A 0.2.1 (JSON-RPC 2.0) | Standard Gemini Enterprise integration protocol; enables any A2A-compliant consumer |
| Bridge → Agent Runtime | Agent Platform SDK `stream_query()` | Native Python SDK; streaming events; session management built-in |
| Agent → Agent (internal) | Tool calls via `stream_query()` on sub-agent Engine | Same SDK; agents are isolated Agent Runtime instances called from within delegation tools |
| Agent → GPU/CPU Service | HTTP REST (FastAPI) | Simplest possible contract; no service mesh; cluster-internal networking |

### Why MCP Is Not Used

Model Context Protocol (MCP) was evaluated and rejected. MCP is designed for tool discovery and invocation between a model and its tool servers. In MolForge, tools are statically registered in each agent's ADK definition — there is no dynamic discovery requirement. MCP would add a protocol layer with no benefit: the agent already knows its tools at deployment time, and tool implementations are co-deployed Python functions that make HTTP calls internally. MCP is appropriate when tools are provided by third parties or change dynamically; neither condition applies here.

### Why A2A Is Inbound Only

A2A (Agent-to-Agent protocol) is used exclusively as the inbound entry point — how external systems reach MolForge. Internally, agents communicate via Agent Platform SDK tool calls, not A2A. The reasoning:

1. **Latency.** A2A adds HTTP round-trip + JSON-RPC overhead. Internal tool calls via `stream_query()` operate within Google's internal network with sub-millisecond overhead.
2. **State.** Agent Runtime sessions handle multi-turn state natively. A2A would require manual session stitching between agents.
3. **Simplicity.** Delegation tools are Python functions — they call `stream_query()` directly. Wrapping this in A2A JSON-RPC adds complexity without benefit.

A2A *is* appropriate for PharmaPilot (an external sovereign system with its own deployment lifecycle). The `delegate_literature_search` tool in the Orchestrator calls PharmaPilot via A2A HTTP POST — this is the correct boundary for A2A.

### Sequence Diagram: Full Pipeline Request

```
Scientist        GE           A2A Bridge    Orchestrator   Lead Optimizer   GenMol  DiffDock  RDKit  Nemotron  GCS
    |             |               |              |               |            |        |       |       |       |
    |--"Optimize"--->|            |              |               |            |        |       |       |       |
    |             |--A2A POST---->|              |               |            |        |       |       |       |
    |             |               |--stream_query()-->           |            |        |       |       |       |
    |             |               |              |               |            |        |       |       |       |
    |             |               |              |--fetch_protein_structure()------------------------------------>|
    |             |               |              |<-----------PDB context-----------------------------------------|
    |             |               |              |               |            |        |       |       |       |
    |             |               |              |--delegate_lead_optimization()-->    |       |       |       |
    |             |               |              |               |--stream_query()-->  |       |       |       |
    |             |               |              |               |                     |       |       |       |
    |             |               |              |               |--optimize_lead_complete()   |       |       |
    |             |               |              |               |   |--POST /generate-->|     |       |       |
    |             |               |              |               |   |<--50 SMILES-------|     |       |       |
    |             |               |              |               |   |--POST /generate-------->|       |       |
    |             |               |              |               |   |<--10 poses + conf-------|       |       |
    |             |               |              |               |   |--POST /properties-------------->|       |
    |             |               |              |               |   |<--properties--------------------|       |
    |             |               |              |               |   |--rawPredict (SAR)---------------------->|
    |             |               |              |               |   |<--SAR narrative-------------------------|
    |             |               |              |               |   |--upload results------------------------------------>|
    |             |               |              |               |   |<--gcs_path + viewer_url-------------------------- |
    |             |               |              |               |<--{run_id, candidates, sar_narrative, viewer_url}------|
    |             |               |              |<---narrative + viewer_url--|         |       |       |       |
    |             |               |<--events (text + timeline)---|               |     |       |       |       |
    |             |<--A2A response---|              |               |            |        |       |       |       |
    |<--"Here are your optimized..."--|            |               |            |        |       |       |       |
    |             |               |              |               |            |        |       |       |       |
```

---

## Section 6 — GPU and Compute Strategy

### Heterogeneous Topology Decision

MolForge's GPU topology is dictated by a single constraint: NVIDIA's DiffDock NIM 2.2.0 does not support Blackwell silicon. The decision tree:

1. **GenMol and ESMFold** — both run via BioNeMo Framework on NGC PyTorch 26.02, which is the first NGC container to ship sm_120 (Blackwell) kernels via CUDA 13.1.1. These run natively on RTX PRO 6000 Blackwell.

2. **DiffDock NIM 2.2.0** — ships with PyTorch built for sm_50–sm_90. Blackwell (sm_120) is not in the compiled kernel set. On Blackwell, the NIM either fails at kernel launch or silently falls back to CPU (producing catastrophic latency). A100 (sm_80) is in the supported set and is NVIDIA's officially tested configuration.

3. **ADMET-AI** — CPU-only. No NVIDIA NIM or GPU-accelerated version exists. Inference is fast enough on CPU for sub-1000-molecule batches.

### NIM vs BioNeMo Framework Decision Matrix

| Model | NIM Available? | Blackwell Compatible? | Choice | Rationale |
|-------|---------------|----------------------|--------|-----------|
| DiffDock | Yes (2.2.0) | No (sm_50–90 only) | NIM on A100 | NIM provides optimized inference; accept A100 requirement |
| GenMol | Yes (1.0.1) | No (at time of build) | BioNeMo Framework on Blackwell | NIM was incompatible; Framework on NGC PyTorch 26.02 works natively |
| ESMFold | No (HuggingFace model) | Yes (via NGC PyTorch 26.02) | Framework on Blackwell | No NIM exists; HuggingFace model on NGC PyTorch works |
| ADMET-AI | No | N/A | CPU | No GPU-accelerated option exists |

### Scale-to-Zero Economics

All three GPU node pools are configured for scale-to-zero autoscaling. This reduces prototype cost by approximately 90% compared to always-on GPU instances:

- RTX PRO 6000 Blackwell (g4-standard-48): ~$4.50/hour per node × 2 nodes = $9/hour when active, $0 when idle (on-demand pricing as of April 2026; verify current rates at cloud.google.com/compute/all-pricing).
- A100 40GB (a2-highgpu-1g): ~$3.67/hour per node × 1 node = $3.67/hour when active, $0 when idle (same caveat).
- Cold-start penalty: 3–10 minutes per node (instance provisioning + model loading). Acceptable for prototype/demo workloads; production would maintain warm capacity for the most frequently used pools.

### Hyperdisk-Balanced Requirement

The g4-standard machine type (used for Blackwell GPU pools) requires `hyperdisk-balanced` disk type — standard persistent disks are not supported. This is specified in the node pool creation command via `--disk-type=hyperdisk-balanced`. Omitting it causes node creation to fail with a non-obvious infrastructure error.

### Migration Path

When NVIDIA ships DiffDock NIM 2.3.x or 3.0 with Blackwell support:

1. Change `nodeSelector` in `services/diffdock-nim/deployment.yaml` from `gpu-diffdock-a100` to `gpu-diffdock` (or `gpu-genmol` to consolidate).
2. Delete the `gpu-diffdock-a100` node pool.
3. All GPU workloads now run on Blackwell — simplified topology, one GPU class, one vendor SKU.

---

## Section 7 — Configuration and Wiring

### How Components Find Each Other

MolForge's service discovery is explicit, not dynamic. Each component receives the addresses of its dependencies via environment variables at deployment time. There is no service mesh, no DNS-based discovery, and no configuration server. This is a deliberate simplicity choice for a prototype — production would use GKE internal DNS (ClusterIP service names) or a service mesh.

**Engine ID propagation.** The Orchestrator must know the Engine IDs of its two specialist agents. The Lead Optimizer and ADMET Safety agents are deployed first; their Engine IDs are captured and injected into the Orchestrator's `.env` file before the Orchestrator is deployed. The Orchestrator's Engine ID is then injected into the A2A bridge as the `ORCHESTRATOR_ENGINE_ID` environment variable.

**Service URL propagation.** Each agent's `.env` file contains the GKE service URLs (LoadBalancer external IPs for prototype; ClusterIP names for production). These are populated after GKE services are deployed and their IPs are known.

### Engine ID Reference

| Agent | Engine ID | Consumed By |
|-------|-----------|-------------|
| Orchestrator | 1768657362010243072 | A2A Bridge (`ORCHESTRATOR_ENGINE_ID`) |
| Lead Optimizer | 4065493171969196032 | Orchestrator (`LEAD_OPTIMIZER_ENGINE_ID`) |
| ADMET Safety | 5020115555483385856 | Orchestrator (`ADMET_SAFETY_ENGINE_ID`) |

### Workload Identity Binding for GCS Access

GKE pods that write to Cloud Storage (ESMFold uploading predicted PDBs, DiffDock tool uploading pose SDFs) use Workload Identity rather than service-account key files. The binding:

```
GKE Service Account (default namespace) → IAM Service Account → roles/storage.objectAdmin on gs://molforge-artifacts
```

This eliminates key rotation concerns and aligns with Google Cloud security best practices. The binding was implemented in Phase 3 to unblock ESMFold PDB uploads.

### NGC Secret Patterns

Two separate K8s secrets serve two different purposes:

| Secret Name | Type | Purpose | Consumed By |
|-------------|------|---------|-------------|
| `ngc-secret` | docker-registry | Authenticate `docker pull` from nvcr.io | DiffDock NIM pod (`imagePullSecrets`) |
| `ngc-runtime-key` | opaque | Expose `NGC_API_KEY` env var for NIM model download | DiffDock NIM pod (`secretKeyRef`) |

Merging these into one secret is possible but reduces clarity. The two-secret pattern makes the separation of concerns explicit: image pull authentication vs. runtime model authentication.

### AgentCard Contents

The A2A bridge serves the following AgentCard at `/.well-known/agent.json`:

```json
{
  "protocolVersion": "0.2.1",
  "name": "MolForge",
  "description": "Agentic AI drug discovery platform powered by NVIDIA Nemotron, GenMol, DiffDock, ESMFold, and ADMET-AI on Google Cloud",
  "version": "1.0.0",
  "capabilities": {"streaming": true, "pushNotifications": false, "stateTransitionHistory": true},
  "skills": [
    {"id": "protein_analysis", "name": "Protein Analysis"},
    {"id": "molecule_generation", "name": "Molecule Generation"},
    {"id": "molecular_docking", "name": "Molecular Docking"},
    {"id": "admet_prediction", "name": "ADMET Prediction"}
  ]
}
```

Gemini Enterprise discovers MolForge by fetching this card and registers the skills for user invocation.

---

## Section 8 — Deployment Pattern

### Three Deployment Categories

| Category | Components | Build Method | Deploy Target | Base Image |
|----------|-----------|-------------|---------------|------------|
| ADK Agents | Orchestrator, Lead Optimizer, ADMET Safety | Cloud Build (`adk deploy agent_engine`) | Agent Runtime | python:3.12-slim (inside Cloud Build step) |
| GPU/CPU Services | GenMol, ESMFold, DiffDock, RDKit, ADMET-AI, Data Retrieval | Cloud Build (Docker) or `gcloud builds submit` | GKE | NGC PyTorch 26.02 (GPU) or python:3.12-slim (CPU) |
| Web Tier | A2A Bridge, Viewer, Dashboard | `gcloud run deploy --source=.` | Cloud Run | python:3.12-slim (A2A) or node:20-alpine (Viewer, Dashboard) |

### ADK Agents via Cloud Build

The production deployment pattern for ADK agents uses Cloud Build rather than local `adk` CLI installation. The Cloud Build step:

```yaml
steps:
  - name: 'python:3.12-slim'
    entrypoint: 'bash'
    args:
      - '-c'
      - |
        pip install google-adk google-cloud-aiplatform
        adk deploy agent_engine agents/orchestrator \
          --display_name "MolForge Orchestrator" \
          --project {PROJECT_ID} \
          --region us-central1
```

**Why Cloud Build over local `adk`.** (1) Portability — no developer-machine Python environment required. (2) CI/CD friendliness — the deploy step is a declarative YAML, not a manual CLI session. (3) Reproducibility — the build runs in an identical container every time. (4) No local ADK installation conflicts with other Python projects.

### Why python:3.12-slim Is Mandatory

Google Cloud Buildpacks (used by `gcloud run deploy --source=.`) default to Python 3.14 as of early 2026. Python 3.14 breaks `google-adk` and several dependencies in the Agent Platform SDK. All Dockerfiles in MolForge explicitly use `python:3.12-slim` as the base image, and all Cloud Run deploys that include a Dockerfile will use that Dockerfile rather than Buildpacks.

**Risk.** If a directory contains both a `Dockerfile` and a `Procfile` (or `package.json` with a `start` script), Cloud Run's source-deploy heuristic may prefer Buildpacks. Mitigation: always pass `--dockerfile=Dockerfile` when deploying, or pre-build the image with Cloud Build and deploy by image tag.

### Build → Push → Deploy Flow

**GPU services (GenMol, ESMFold, DiffDock wrapper):**
1. Cloud Build authenticates to nvcr.io using the `ngc-api-key` secret.
2. Docker builds the image from the NGC PyTorch base.
3. Image is pushed to Artifact Registry `molforge-repo`.
4. `kubectl apply` deploys the K8s Deployment + Service manifest.

**DiffDock NIM:**
1. No build step — the image is `nvcr.io/nim/mit/diffdock:2.2.0` pulled directly.
2. `kubectl apply` deploys the manifest; the kubelet pulls from nvcr.io using `ngc-secret`.

**CPU services:**
1. `gcloud builds submit` builds from `python:3.12-slim` base.
2. Image pushed to Artifact Registry.
3. `kubectl apply` deploys the manifest.

**Cloud Run services:**
1. `gcloud run deploy --source=.` — Cloud Run builds from Dockerfile and deploys in one step.

---

## Section 9 — Security and IAM Design

### Service Account Topology

| Component | Service Account | Key Roles |
|-----------|----------------|-----------|
| Cloud Build | `{PROJECT_NUMBER}@cloudbuild.gserviceaccount.com` | `artifactregistry.writer`, `storage.admin`, `aiplatform.user`, `logging.logWriter`, `secretmanager.secretAccessor` |
| GKE default | `{PROJECT_NUMBER}-compute@developer.gserviceaccount.com` | `storage.objectAdmin` (on molforge-artifacts), `aiplatform.user` |
| Cloud Run (A2A, Viewer, Dashboard) | Default Compute SA (or Cloud Run SA) | `storage.objectViewer` (Viewer), `aiplatform.user` (A2A) |
| Agent Runtime | Managed by Agent Platform | Inherits project IAM; needs `storage.objectAdmin` for artifact writes |

### Least-Privilege Design

- GPU/CPU GKE pods access only the specific GCS bucket via Workload Identity — no broad storage roles.
- Cloud Build's `secretmanager.secretAccessor` is scoped to the `ngc-api-key` secret only (via IAM condition, recommended for production).
- Agent Runtime agents have no direct GCS access — they delegate to tool functions that run within the Agent Runtime SA context.

### NGC Secret Separation

The two-secret pattern (`ngc-secret` for image pull, `ngc-runtime-key` for runtime API key) provides:
- **Rotation independence** — the image-pull secret can be rotated without affecting running pods, and vice versa.
- **Scope clarity** — `ngc-secret` is consumed only by the kubelet; `ngc-runtime-key` is consumed only by the DiffDock process inside the pod.

### Gemini Enterprise Sanitizer Behavior

Gemini Enterprise sanitizes all agent responses before rendering to users. The sanitizer blocks:
- Inline images (base64 or URL-referenced)
- Inline 3D content (WebGL, Three.js, Mol*)
- Inline iframes
- Large HTML blocks

The **viewer-link pattern** is the architecturally correct solution: agents return clickable URLs to the molforge-viewer Cloud Run service, which renders the rich content in a separate browser tab. This is not a workaround — it is the intended integration pattern for any Gemini Enterprise agent that needs to surface visual content.

### CBA and ECP Developer Workstation Constraints

Certificate-Based Access (CBA) on corporate Linux workstations blocks certain CLI tools (notably `bq` for BigQuery DDL). Enterprise Certificate Proxy (ECP) emits noisy stderr on every `gcloud` invocation but does not block execution. Mitigations:
- BigQuery DDL operations shift to Google Cloud Shell.
- `gcloud` commands append `2>/dev/null` where ECP noise would confuse log parsing.
- These constraints are environmental, not architectural — they do not affect deployed services.

---

## Section 10 — Observability and Operations

### Logging

| Component | Log Destination | Key Log Lines |
|-----------|----------------|---------------|
| GKE pods | Cloud Logging (GKE container logs) | Health check results, model load status, inference latency, error traces |
| Cloud Run services | Cloud Logging (Cloud Run logs) | A2A request/response shapes, timeline construction, session management |
| Agent Runtime | Agent Platform logs | Agent events, tool call traces, model version |

The A2A bridge logs every inbound request with redacted headers (`[A2A HEADERS]`), full body excerpt (`[A2A FULL BODY]`), extracted identifiers (`[A2A IDENTIFIERS]`), and response shape (`[A2A RESPONSE SHAPE]`). These structured log lines enable grep-based debugging of multi-turn session issues.

### Health Checks and Warmup

Every GKE service exposes `GET /health` returning JSON with at minimum `{"status": "healthy"}`. GPU services additionally report `model_loaded` (boolean) and `gpu_available` (boolean). The A2A bridge's `/warmup-all` endpoint probes all six services in parallel and classifies each as:
- **healthy** — 200 response, model loaded (if applicable)
- **cold** — 200 response, model not yet loaded (pod is up but first-request latency will be high)
- **unhealthy** — non-200 or timeout

The React Dashboard polls `/warmup-all` every 60 seconds and renders the results as the Infrastructure Warmup Bar.

### Cloud Run Revision Strategy

Cloud Run services use the default revision strategy (latest revision serves 100% of traffic). Rollback is achieved by redeploying the previous source or redirecting traffic to a prior revision via `gcloud run services update-traffic`.

### Agent Runtime Session Tracing

The A2A bridge implements multi-turn session management by mapping each A2A `contextId` to an Agent Runtime session. The `_get_or_create_ae_session()` function in `a2a/server.py` creates a new session on the first turn and reuses it on subsequent turns. Session IDs are logged at `[A2A SESSION]` level.

### The Agent Orchestra Panel

### Alerting (Not Implemented)

Production deployments would add Cloud Monitoring uptime checks on each `/health` endpoint with PagerDuty or OpsGenie alerting at the 2-minute-unhealthy threshold. The prototype relies on manual monitoring via the Dashboard Warmup Bar (which polls every 60 seconds) and Cloud Logging queries. GPU node-pool health is monitored via GKE node-condition alerts. [GAP — alerting configuration not implemented; runbook references pending.]

### The Agent Orchestra Panel

The React Dashboard's Internal Agent Orchestra panel is a real-time observability surface. It renders the `meta.timeline` array returned by the A2A bridge, which is constructed by parsing every Agent Runtime event via `build_timeline_entry()`. Each entry carries: timestamp, agent name, kind (tool_call, tool_response, sub_agent_model, model_text, error), model identifier, provider attribution (NVIDIA or Google), summary text, and run_id. This provides visibility into exactly which models were invoked, in what order, for how long, and by which agent — without requiring separate observability tooling.

---

## Section 11 — Build Chronology and Validation Results

### Phase 1: Base Delegation

**Scope.** End-to-end pipeline: Orchestrator receives natural-language request → gathers protein context via Data Retrieval → delegates to Lead Optimizer (GenMol → DiffDock → RDKit → Nemotron SAR) → delegates to ADMET Safety (ADMET-AI → RDKit → Nemotron narrative) → compiles and returns results.

**Validation.** Full pipeline invoked via Gemini Enterprise with prompt "Optimize Imatinib for BCR-ABL kinase, oncology." Orchestrator correctly decomposed, delegated sequentially, and surfaced both the SAR narrative and ADMET safety narrative verbatim with viewer links.

**Outcome.** Base architecture validated. Key architectural decisions locked: single-tool pattern for specialist agents, verbatim narrative surfacing, viewer-link pattern for Gemini Enterprise.

### Phase 2: Atomic Delegations

**Scope.** Added two new delegation modes to the Orchestrator that bypass the full pipeline for single-step requests: `delegate_molecular_docking` (atomic dock) and `delegate_protein_folding` (atomic fold). Required updating system instructions with ATOMIC DOCKING / ATOMIC FOLDING message prefixes and same-turn-tool-call behavioral rules.

**Validated results.**

| Test | Metric | Result |
|------|--------|--------|
| Atomic dock (Imatinib vs 2HYY) | Latency | 1.91 seconds |
| Atomic dock (Imatinib vs 2HYY) | Rank-1 confidence | 0.043 |
| Atomic fold (BRAF kinase domain) | pLDDT populated | Yes (per-residue array returned) |
| Full pipeline (no structure) | Candidates generated | 32 |
| Full pipeline (no structure) | Nemotron SAR narrative | Complete 5-section analysis with ranked picks |

**Key implementation detail.** Phase 2 required adding verbatim-field-surfacing language to agent system instructions. Without these instructions, agents would paraphrase numeric results (confidence scores, pLDDT values, GCS paths) into prose, losing the precision scientists need. The instructions explicitly state: "You MUST surface the actual numeric values verbatim. Do NOT hide them inside prose."

### Phase 3: ESMFold GCS Upload and Viewer Pages

**Phase 3 Step 1: Workload Identity binding for ESMFold.**
The ESMFold service needed to upload predicted PDB files to `gs://molforge-artifacts/structures/`. This required binding the GKE service account to an IAM service account with `storage.objectAdmin` on the bucket. Before this binding, PDB uploads silently failed (non-fatal in the pipeline) and viewer links returned 404.

**Phase 3 Step 2: Mol* viewer pages.**
Implemented `/protein?file={name}.pdb` and `/docking?id={dock_id}` pages in the viewer, mirroring the existing `/admet` and `/gallery` patterns. Both use 3Dmol.js for interactive 3D rendering with auto-rotation. The docking page loads protein surface + ligand ball-and-stick from GCS-backed API endpoints.

**Outcome.** Complete end-to-end validated: natural language → agent pipeline → GCS artifacts → interactive 3D viewer links surfaced in Gemini Enterprise.

---

## Section 12 — Best Practices

Each practice below was derived from the actual MolForge build, not from generic guidance. The consequence column states what happens if you ignore the practice.

| # | Practice | Rationale | Consequence of Ignoring |
|---|----------|-----------|------------------------|
| 1 | Deploy ADK agents via Cloud Build, not local `adk` CLI | Portable, reproducible, CI/CD-friendly; no developer-machine Python conflicts | Works on your laptop, fails in CI; environment drift between developers |
| 2 | Use `python:3.12-slim` Dockerfiles, never Buildpacks | Buildpacks default to Python 3.14 which breaks google-adk and Agent Platform SDK | Import errors at runtime; silent failures in Cloud Run |
| 3 | Pin `marshmallow<4` in any BioNeMo/pymilvus stack | marshmallow 4.x breaks pymilvus serialization, a transitive dependency of `google-cloud-aiplatform[agent_engines]`. Failure surfaces during `adk deploy agent_engine` | Agent Runtime deployment fails with opaque schema-validation errors |
| 4 | Pin `transformers<4.47.0` for ESMFold | Versions 4.47+ removed `openfold_utils` module | ESMFold pod crash-loops with ImportError |
| 5 | Use Workload Identity for GCS writes from GKE | No service-account keys in pods; automatic credential rotation | Security audit failure; key rotation burden; secret sprawl |
| 6 | Two-secret pattern for NIM containers | Separate image-pull auth from runtime API-key auth | Rotation of one breaks the other; confused debugging |
| 7 | Single-chain PDB filter before any DiffDock submission | DiffDock NIM 2.2.0 cannot handle multi-chain crystals | Opaque "need at least one array to concatenate" error |
| 8 | Viewer-link pattern for Gemini Enterprise integrations | GE sanitizer blocks inline images, 3D, iframes | Scientists see stripped/empty responses; no visual content |
| 9 | A2A as inbound protocol only; internal agents use tool calls | A2A adds latency without benefit for co-located agents | Unnecessary HTTP round-trips; session-stitching complexity |
| 10 | No hardcoded thresholds in agents; all decisions via model system instructions | Threshold-based logic is brittle across therapeutic areas | Cardiovascular safety thresholds kill valid oncology compounds; false positives |
| 11 | Verbatim-field-surfacing instructions for deterministic output | Without explicit instructions, models paraphrase numeric data | Scientists lose confidence scores, pLDDT values, GCS paths |
| 12 | Document the GPU migration path when running heterogeneous topology | Future NIM releases will change the compatibility matrix | Team wastes time re-discovering why DiffDock is on A100 |
| 13 | Scale-to-zero on every GPU pool without warm-capacity requirements | GPU instances cost $3.67–$4.50/hour/node | Prototype costs 10× higher than necessary |

---

## Section 13 — Engineering Learnings

### 13.1 Blackwell sm_120 Kernel Support

**Observed.** Early NGC PyTorch containers (pre-26.02) did not include sm_120 kernels. Models loaded but silently used CPU fallback or failed at kernel launch.

**Why.** Blackwell (B-series, sm_120) is a new architecture. CUDA kernel compilation for sm_120 was first shipped in NGC PyTorch 26.02 (CUDA 13.1.1).

**Resolution.** Standardized on NGC PyTorch 26.02 as the minimum base image for all Blackwell GPU services.

**What we now do differently.** Always verify the NGC container's CUDA compute capabilities (`nvidia-smi --query-gpu=compute_cap`) against the GPU hardware before deploying.

### 13.2 GenMol NIM 1.0.1 Blackwell Incompatibility

**Observed.** GenMol NIM 1.0.1 failed on Blackwell with kernel-launch errors.

**Why.** The NIM was compiled for sm_50–sm_90, same as DiffDock NIM.

**Resolution.** Pivoted from GenMol NIM to BioNeMo Framework on NGC PyTorch 26.02, which provides `GenMolInference` with native Blackwell support. The safe-mol fallback (`SAFEDesign.load_default()`) provides identical functionality for the workshop use case.

**What we now do differently.** When a NIM is incompatible with target hardware, check whether the BioNeMo Framework provides the same model class before accepting a hardware downgrade.

### 13.3 DiffDock NIM Silent CPU Fallback

**Observed.** DiffDock NIM appeared to run on GKE A100 nodes but produced 60-second inference times instead of the expected 2–4 seconds.

**Why.** Without `NVIDIA_DISABLE_REQUIRE=true`, `libnvidia-container` refuses to inject GPU driver libraries because the driver version (580+) isn't in the NIM's allowed list. The NIM falls back to CPU without logging an error.

**Resolution.** Added the three-env-var workaround (NVIDIA_DISABLE_REQUIRE, LD_LIBRARY_PATH, PATH). Inference dropped from 60s to 1.91s.

**What we now do differently.** Any NIM deployment on GKE with driver versions newer than the NIM's metadata list gets the three-env-var treatment by default.

### 13.4 ADMET-AI Has No NVIDIA NIM

**Observed.** Searched NGC catalog, BioNeMo blueprints, and NVIDIA documentation for a GPU-accelerated ADMET prediction NIM.

**Why.** ADMET-AI's Chemprop-RDKit architecture is inherently CPU-efficient for small batches. NVIDIA has not prioritized a NIM for this workload.

**Resolution.** Accepted CPU-only deployment. Stopped searching. The CPU service predicts 1000 molecules in under 30 seconds — well within acceptable latency.

### 13.5 Buildpacks Default to Python 3.14

**Observed.** Cloud Run `--source=.` deploy without a Dockerfile used Buildpacks, which selected Python 3.14. The deployed service failed with `google-adk` import errors.

**Why.** Buildpacks auto-detect the latest stable Python. Python 3.14 has incompatibilities with several Google Cloud SDK packages.

**Resolution.** All services use explicit Dockerfiles with `python:3.12-slim`. Never rely on Buildpacks for MolForge components.

### 13.6 Certificate-Based Access Blocks bq CLI

**Observed.** `bq` CLI commands on the developer workstation fail with ECP/CBA authentication errors.

**Why.** Corporate Linux workstations enforce Certificate-Based Access which the `bq` CLI does not fully support.

**Resolution.** All BigQuery DDL operations execute in Google Cloud Shell. This is an environmental constraint, not an architectural one.

### 13.7 Gemini Enterprise Sanitizer

**Observed.** Agent responses containing inline molecular SVGs, 3D viewer HTML, or base64 images rendered as empty or stripped text in Gemini Enterprise.

**Why.** Gemini Enterprise's response sanitizer blocks all inline rich content as a security measure.

**Resolution.** The viewer-link pattern: agents return clickable URLs to the molforge-viewer Cloud Run service. This is not a workaround — it is the correct architecture for surfacing visual content through Gemini Enterprise.

### 13.8 A2A Internal Use Adds Latency

**Observed.** Early prototype attempted A2A calls between Orchestrator and specialist agents.

**Why.** A2A is designed for cross-system communication. Using it within a single platform adds HTTP round-trip overhead, JSON-RPC marshaling, and session-stitching complexity with no benefit.

**Resolution.** Internal agent-to-agent communication uses Agent Platform SDK `stream_query()` directly from delegation tool functions. A2A is reserved for the inbound boundary only.

### 13.9 Hardcoded Thresholds Cause False Positives

**Observed.** Early agent implementations used hardcoded drug-likeness thresholds (e.g., "reject if LogP > 5") which incorrectly killed valid oncology candidates.

**Why.** Drug-likeness thresholds are context-dependent. Oncology drugs routinely violate Lipinski's rules. A threshold that makes sense for cardiovascular drugs is wrong for CNS drugs.

**Resolution.** Removed all hardcoded thresholds from Python code. All decisions are made by Nemotron models via system instructions that include therapeutic-area context. The models reason from chemistry, not from rigid cutoffs.

### 13.10 DiffDock Multi-Chain PDB Failure

**Observed.** Submitting a crystal structure with multiple chains (e.g., 2HYY has 4 copies of ABL kinase) caused DiffDock NIM to return "Fail to generate complex graph — need at least one array to concatenate."

**Why.** DiffDock NIM 2.2.0 expects single-chain input. Multi-chain PDB content confuses the graph construction algorithm.

**Resolution.** `_filter_chain_a()` in `agents/lead_optimizer/tools/diffdock.py` extracts only chain A ATOM records before submission.

### 13.11 DiffDock Newline Encoding

**Observed.** DiffDock NIM returned zero poses with no error when protein field contained escaped newlines.

**Why.** NVIDIA's bash examples use `sed -z 's/\n/\\n/g'` which produces literal two-character `\n` in shell strings. In Python, `"\n".join(lines)` produces real newlines (0x0A). `json.dumps()` correctly escapes real newlines to `\n` in JSON wire format. Using the bash idiom literally in Python produces `\\n` which the NIM interprets as literal backslash-n and finds zero residues.

**Resolution.** Use Python's `"\n".join(atom_lines)` — real newlines, correctly JSON-escaped by the serializer. Never replicate bash string idioms in Python.

---

## Section 14 — Future Roadmap

### DiffDock NIM Blackwell Migration

When NVIDIA ships DiffDock NIM 2.3.x or 3.0 with sm_120 support: change one `nodeSelector` line, delete the A100 node pool, consolidate all GPU workloads on Blackwell. Estimated effort: 15 minutes.

### PharmaPilot A2A Integration

PharmaPilot (literature research assistant) is designed as an A2A peer system. The Orchestrator's `delegate_literature_search` tool is already implemented and calls PharmaPilot's A2A endpoint. Once PharmaPilot is deployed, MolForge will augment its pipeline with PubMed literature context, clinical trial data, and patent landscape analysis.

### BigQuery Audit Dataset

Planned: a BigQuery dataset capturing every agent invocation (timestamp, engine_id, user_id, tool calls, latency, model tokens consumed, run_id). This enables cost attribution, usage analytics, and compliance audit. [GAP — neither the schema nor the ingestion pipeline is implemented.]

### Scale-to-Zero Warm Pool Optimization

Current scale-to-zero provides maximum cost savings but incurs 3–10 minute cold starts. For production deployments with SLA requirements, maintain a warm pool of 1 node per GPU pool during business hours using GKE cluster autoscaler profiles with scheduled scaling.

---

## Appendix A — Component Inventory Table

| Component | Technology | Runtime | GPU/CPU | Scaling | Port |
|-----------|-----------|---------|---------|---------|------|
| Orchestrator Agent | ADK + Gemini 2.5 Pro | Agent Runtime | N/A (serverless) | Auto | N/A |
| Lead Optimizer Agent | ADK + Nemotron Super 49B v1.5 | Agent Runtime | N/A (serverless) | Auto | N/A |
| ADMET Safety Agent | ADK + Nemotron Nano 8B | Agent Runtime | N/A (serverless) | Auto | N/A |
| GenMol | FastAPI + BioNeMo/safe-mol | GKE (gpu-genmol) | RTX PRO 6000 Blackwell 96GB | Scale-to-zero | 8000 |
| ESMFold | FastAPI + HuggingFace transformers | GKE (gpu-esmfold) | RTX PRO 6000 Blackwell 96GB | Scale-to-zero | 8000 |
| DiffDock NIM | NVIDIA NIM 2.2.0 | GKE (gpu-diffdock-a100) | A100 40GB | Scale-to-zero | 8000 |
| ADMET-AI | FastAPI + admet-ai | GKE (default-pool) | CPU | Single replica | 8080 |
| RDKit | FastAPI + RDKit | GKE (default-pool) | CPU | Single replica | 8080 |
| Data Retrieval | FastAPI + requests | GKE (default-pool) | CPU | Single replica | 8080 |
| A2A Bridge | FastAPI + Agent Platform SDK | Cloud Run | N/A (serverless) | Auto (0–10) | 8080 |
| molforge-viewer | Express + React + 3Dmol.js | Cloud Run | N/A (serverless) | Auto (0–10) | 8080 |
| React Dashboard | React + Vite + Nginx | Cloud Run | N/A (serverless) | Auto (0–10) | 8080 |

---

## Appendix B — Engine IDs, Service URLs, and Infrastructure Reference

### Agent Runtime IDs

Engine IDs are **per-deployment and minted fresh by every `adk deploy`** — there
are no canonical values to quote here. Resolve yours with:

```
gcloud ai reasoning-engines list --project=$PROJECT_ID --region=us-central1
```

| Agent | Resource Name |
|-------|---------------|
| Orchestrator | `projects/$PROJECT_ID/locations/us-central1/reasoningEngines/{orchestrator_engine_id}` |
| Lead Optimizer | `projects/$PROJECT_ID/locations/us-central1/reasoningEngines/{lead_optimizer_engine_id}` |
| ADMET Safety | `projects/$PROJECT_ID/locations/us-central1/reasoningEngines/{admet_safety_engine_id}` |

### GKE Node Pools

| Pool Name | Machine Type | GPU | Zone | Disk Type |
|-----------|-------------|-----|------|-----------|
| default-pool | e2-standard-4 | None | us-central1-c | pd-balanced |
| gpu-genmol | g4-standard-48 | RTX PRO 6000 Blackwell 96GB | us-central1-c | hyperdisk-balanced |
| gpu-esmfold | g4-standard-48 | RTX PRO 6000 Blackwell 96GB | us-central1-c | hyperdisk-balanced |
| gpu-diffdock-a100 | a2-highgpu-1g | A100 40GB | us-central1-c | pd-balanced |

### GCS Paths

| Path Pattern | Content |
|-------------|---------|
| `gs://molforge-artifacts/{run_id}/optimization_results.json` | Lead optimization output |
| `gs://molforge-artifacts/{run_id}/admet_results.json` | ADMET screening output |
| `gs://molforge-artifacts/structures/{name}.pdb` | ESMFold predicted structures |
| `gs://molforge-artifacts/docking/{dock_id}/manifest.json` | Docking run metadata |
| `gs://molforge-artifacts/docking/{dock_id}/protein.pdb` | Chain-A filtered protein |
| `gs://molforge-artifacts/docking/{dock_id}/lig{N}_rank{R}_conf{C}.sdf` | Individual pose SDFs |

### Cloud Run Services

Cloud Run URLs embed your project number, so these are patterns, not addresses.
Resolve one with `gcloud run services describe <service> --region=us-central1
--format='value(status.url)'`.

| Service | URL Pattern |
|---------|-------------|
| A2A Bridge | `https://molforge-a2a-{project_number}.us-central1.run.app` |
| Viewer | `https://molforge-viewer-{project_number}.us-central1.run.app` |
| Dashboard | `https://molforge-dashboard-{project_number}.us-central1.run.app` |

---

## Appendix C — Environment Variable Reference

| Variable | Default/Example | Consumers | Purpose |
|----------|----------------|-----------|---------|
| `GOOGLE_GENAI_USE_VERTEXAI` | `TRUE` | All agents | Route ADK to Vertex AI |
| `GOOGLE_CLOUD_PROJECT` | **required, no default** | All agents, A2A, Viewer | Project for Agent Platform and GCS. Unset ⇒ the process fails at import/startup rather than falling back to a hardcoded project |
| `GOOGLE_CLOUD_LOCATION` | `us-central1` | All agents, A2A | Region for Agent Runtime |
| `ORCHESTRATOR_ENGINE_ID` | *(per-deployment)* | A2A Bridge | Which Engine the bridge calls |
| `LEAD_OPTIMIZER_ENGINE_ID` | *(per-deployment)* | Orchestrator | Sub-agent delegation target |
| `ADMET_SAFETY_ENGINE_ID` | *(per-deployment)* | Orchestrator | Sub-agent delegation target |
| `MOLFORGE_GENMOL_URL` | `http://{IP}:8000` | Lead Optimizer | GenMol service endpoint |
| `MOLFORGE_DIFFDOCK_URL` | `http://{IP}:8000` | Lead Optimizer | DiffDock service endpoint |
| `MOLFORGE_ESMFOLD_URL` | `http://{IP}:8000` | Lead Optimizer | ESMFold service endpoint |
| `MOLFORGE_RDKIT_URL` | `http://{IP}:8080` | Lead Opt + ADMET | RDKit service endpoint |
| `MOLFORGE_ADMET_AI_URL` | `http://{IP}:8080` | ADMET Safety | ADMET-AI service endpoint |
| `MOLFORGE_DATA_RETRIEVAL_URL` | `http://{IP}:8080` | Orchestrator | Data Retrieval endpoint |
| `MOLFORGE_ARTIFACTS_BUCKET` | `molforge-artifacts` | GPU services, Agent tools | GCS bucket for run artifacts (used by GKE pods and agent tool code) |
| `MOLFORGE_GCS_BUCKET` | `molforge-artifacts` | Viewer (Express server) | Same bucket, different env var name in the viewer codebase |
| `MOLFORGE_ARTIFACT_STORE_URL` | `http://placeholder:8080` | Lead Opt, ADMET (.env only) | Vestigial — planned artifact service replaced by direct GCS writes. Can be removed from .env files |
| `MOLFORGE_VIEWER_URL` | Cloud Run URL | Lead Opt + ADMET | Viewer URL for embedded links |
| `NGC_API_KEY` | Secret value | DiffDock NIM pod | NGC model download auth |
| `NVIDIA_DISABLE_REQUIRE` | `true` | DiffDock NIM pod | Skip driver-version check |
| `PHARMAPILOT_A2A_URL` | `http://pharmapilot:8080` | Orchestrator | External A2A peer (optional) |

---

## Appendix D — Glossary

| Term | Definition |
|------|-----------|
| **ADK** | Agent Development Kit — Google's Python framework for building agents deployed to Agent Runtime |
| **Agent Platform** | Gemini Enterprise Agent Platform — the product formerly called Vertex AI. Its SDK, API endpoint and REST resources still carry the legacy names (`vertexai`, `google-cloud-aiplatform`, `aiplatform.googleapis.com`, `reasoningEngines`), so code in this repo uses those identifiers while prose uses the current product names |
| **Agent Runtime** | The managed runtime that hosts the three ADK agents — formerly Agent Engine. Deployed with `adk deploy agent_engine`, which keeps the old spelling |
| **A2A** | Agent-to-Agent protocol (v0.2.1) — JSON-RPC 2.0 protocol for inter-agent communication, used by Gemini Enterprise |
| **ADMET** | Absorption, Distribution, Metabolism, Excretion, Toxicity — five dimensions of pharmacokinetic safety |
| **BioNeMo** | NVIDIA's framework for biomolecular AI model inference and training |
| **CBA** | Certificate-Based Access — corporate security control on developer workstations |
| **ECP** | Enterprise Certificate Proxy — corporate proxy that mediates TLS connections |
| **GCS** | Google Cloud Storage |
| **GKE** | Google Kubernetes Engine |
| **hERG** | Human Ether-à-go-go Related Gene — potassium channel whose inhibition causes cardiac arrhythmia |
| **Mol*** | Molecular visualization library for interactive 3D structure rendering (3Dmol.js variant) |
| **NGC** | NVIDIA GPU Cloud — container registry and model catalog |
| **NIM** | NVIDIA Inference Microservice — pre-built GPU-optimized inference container |
| **pLDDT** | Predicted Local Distance Difference Test — per-residue confidence score (0–100) from structure prediction |
| **RCSB** | Research Collaboratory for Structural Bioinformatics — hosts the Protein Data Bank |
| **SAFE** | Sequential Attachment-based Fragment Embedding — molecular representation for generative chemistry |
| **SAR** | Structure-Activity Relationship — relationship between molecular structure and biological activity |
| **TDC** | Therapeutics Data Commons — benchmark datasets for drug discovery ML |
| **Workload Identity** | GKE mechanism binding K8s service accounts to IAM service accounts without key files |
| **ZINC20** | Freely available database of commercially purchasable compounds for virtual screening (~1.4 billion molecules) |

---

## Appendix E — File Listing

Every source file in the MolForge repository (excluding node_modules, .venv, __pycache__, .git, dist, build, and *.bak.* files).

### Agents

| Path | Description |
|------|------------|
| `agents/orchestrator/__init__.py` | Package init, exports root_agent |
| `agents/orchestrator/agent.py` | Orchestrator ADK agent definition + system instruction |
| `agents/orchestrator/.env` | Engine IDs and service URL configuration |
| `agents/orchestrator/tools/__init__.py` | Tools package init |
| `agents/orchestrator/tools/delegation.py` | Five delegation tools (lead opt, ADMET, docking, folding, literature) |
| `agents/orchestrator/tools/data_retrieval.py` | Four data retrieval tools (PDB, UniProt, ChEMBL, ZINC20) |
| `agents/orchestrator/tools/artifacts.py` | Run ID generation and artifact storage |
| `agents/lead_optimizer/__init__.py` | Package init, exports root_agent |
| `agents/lead_optimizer/agent.py` | Lead Optimizer ADK agent definition + system instruction |
| `agents/lead_optimizer/.env` | Service URL configuration |
| `agents/lead_optimizer/tools/__init__.py` | Tools package init |
| `agents/lead_optimizer/tools/optimize_complete.py` | Primary single-call pipeline tool (ESMFold→GenMol→DiffDock→RDKit→Nemotron→GCS) |
| `agents/lead_optimizer/tools/genmol.py` | GenMol HTTP client |
| `agents/lead_optimizer/tools/diffdock.py` | DiffDock NIM HTTP client with PDB resolution, chain filter, batch mode, GCS persistence |
| `agents/lead_optimizer/tools/esmfold.py` | ESMFold HTTP client |
| `agents/lead_optimizer/tools/rdkit_props.py` | RDKit properties + rendering HTTP client |
| `agents/lead_optimizer/tools/sar_analysis.py` | Nemotron Super 49B v1.5 SAR reasoning via rawPredict |
| `agents/lead_optimizer/tools/artifacts.py` | GCS storage for optimization results |
| `agents/admet_safety_agent/__init__.py` | Package init, exports root_agent |
| `agents/admet_safety_agent/agent.py` | ADMET Safety ADK agent definition + system instruction |
| `agents/admet_safety_agent/.env` | Service URL configuration |
| `agents/admet_safety_agent/tools/__init__.py` | Tools package init |
| `agents/admet_safety_agent/tools/screen_complete.py` | Primary single-call pipeline tool (ADMET-AI→RDKit→Nemotron→GCS) |
| `agents/admet_safety_agent/tools/admet_predict.py` | ADMET-AI HTTP client |
| `agents/admet_safety_agent/tools/rdkit_props.py` | RDKit properties HTTP client |
| `agents/admet_safety_agent/tools/report_gen.py` | Nemotron Nano VL safety narrative via rawPredict |
| `agents/admet_safety_agent/tools/artifacts.py` | GCS storage for ADMET results |

### Services

| Path | Description |
|------|------------|
| `services/genmol/app.py` | GenMol FastAPI service (BioNeMo/safe-mol) |
| `services/genmol/Dockerfile` | NGC PyTorch 26.02 base + safe-mol |
| `services/genmol/cloudbuild.yaml` | Cloud Build with NGC auth |
| `services/esmfold/app.py` | ESMFold FastAPI service (HuggingFace) |
| `services/esmfold/Dockerfile` | NGC PyTorch 26.02 base + transformers<4.47.0 |
| `services/esmfold/cloudbuild.yaml` | Cloud Build with NGC auth |
| `services/diffdock/app.py` | DiffDock Python wrapper (mock mode fallback, not deployed) |
| `services/diffdock/Dockerfile` | NGC PyTorch 26.02 base (fallback wrapper) |
| `services/diffdock/cloudbuild.yaml` | Cloud Build for fallback wrapper |
| `services/diffdock-nim/deployment.yaml` | Production DiffDock NIM K8s deployment (A100, two secrets, three env vars) |
| `services/diffdock-nim/test/test_imatinib_abl.py` | Integration test: Imatinib vs ABL kinase |
| `services/diffdock-nim/test/output_reference.json` | Reference output for validation |
| `services/rdkit_service/app.py` | RDKit FastAPI service (properties + SVG rendering) |
| `services/rdkit_service/Dockerfile` | python:3.12-slim + rdkit |
| `services/admet_ai/app.py` | ADMET-AI FastAPI service (41 endpoints) |
| `services/admet_ai/Dockerfile` | python:3.12-slim + admet-ai |
| `services/data_retrieval/app.py` | Data Retrieval FastAPI service (RCSB, UniProt, ChEMBL, ZINC20) |
| `services/data_retrieval/Dockerfile` | python:3.12-slim + requests + rcsb-api |

### Infrastructure

| Path | Description |
|------|------------|
| `infra/gke/admet-ai-deployment.yaml` | K8s Deployment + Service for ADMET-AI (CPU, default-pool) |
| `infra/gke/rdkit-deployment.yaml` | K8s Deployment + Service for RDKit (CPU, default-pool) |
| `infra/gke/data-retrieval-deployment.yaml` | K8s Deployment + Service for Data Retrieval (CPU, default-pool) |

### A2A Bridge

| Path | Description |
|------|------------|
| `a2a/server.py` | A2A 0.2.1 FastAPI server (agent card, JSON-RPC, warmup, timeline) |
| `a2a/Dockerfile` | python:3.12-slim + FastAPI + Agent Platform SDK |
| `a2a/requirements.txt` | fastapi, uvicorn, google-cloud-aiplatform[agent_engines], google-auth |

### Viewer

| Path | Description |
|------|------------|
| `viewer/server.js` | Express backend (GCS proxy for run data, structures, docking poses) |
| `viewer/package.json` | Dependencies: React 18, Express, @google-cloud/storage, smiles-drawer, react-router-dom |
| `viewer/Dockerfile` | Multi-stage: Node 20 build → Node 20 runtime (Express serves API + static) |
| `viewer/vite.config.js` | Vite dev server on 5174 with /api proxy to Express |
| `viewer/tailwind.config.js` | NVIDIA/Google/verdict color palette |
| `viewer/index.html` | Entry HTML with RDKit WASM + 3Dmol.js CDN scripts |
| `viewer/src/App.jsx` | React Router: /, /admet, /gallery, /docking, /protein |
| `viewer/src/main.jsx` | React entry point with BrowserRouter |
| `viewer/src/api.js` | Client API: fetchRun, fetchStructure, fetchDockManifest, fetchDockProtein, fetchDockFiles, fetchDockPose |
| `viewer/src/pages/HomePage.jsx` | Landing page |
| `viewer/src/pages/GalleryPage.jsx` | 2D candidate grid with SAR narrative |
| `viewer/src/pages/DockingPage.jsx` | 3D docking pose viewer |
| `viewer/src/pages/AdmetPage.jsx` | ADMET endpoint table with percentile bars |
| `viewer/src/pages/ProteinPage.jsx` | Protein ribbon viewer colored by pLDDT |
| `viewer/src/components/*.jsx` | 12 UI components (CandidateCard, EndpointTable, MoleculeViewer3D, MoleculeStructure2D, PoseSelector, PercentileBar, NarrativeSection, RunHeader, Header, Footer, LoadingState, ErrorState) |
| `viewer/src/lib/rdkit.js` | RDKit WASM initialization |
| `viewer/src/lib/admetMappings.js` | ADMET endpoint metadata and display mappings |

### Dashboard

| Path | Description |
|------|------------|
| `dashboard/package.json` | Dependencies: React 18, react-markdown, remark-gfm, Vite, Tailwind |
| `dashboard/Dockerfile` | Multi-stage: Node 20 build → Nginx Alpine (static SPA) |
| `dashboard/nginx.conf` | Port 8080, SPA fallback, gzip, cache-control |
| `dashboard/vite.config.js` | Vite dev server on 5173 |
| `dashboard/tailwind.config.js` | NVIDIA/Google color palette |
| `dashboard/index.html` | Entry HTML with Inter + JetBrains Mono fonts |
| `dashboard/src/App.jsx` | Main app: chat state, warmup polling, message dispatch |
| `dashboard/src/main.jsx` | React entry point |
| `dashboard/src/api.js` | A2A client: sendMessage, probeAllServices, probeService |
| `dashboard/src/index.css` | Tailwind base + markdown typography + scrollbar styling |
| `dashboard/src/components/Header.jsx` | Brand header with NVIDIA/Google badges |
| `dashboard/src/components/ChatColumn.jsx` | Auto-scrolling message list |
| `dashboard/src/components/MessageBubble.jsx` | User/assistant message rendering with react-markdown |
| `dashboard/src/components/InputBar.jsx` | Text input with example prompts, Enter/Shift+Enter handling |
| `dashboard/src/components/InternalOrchestra.jsx` | Left sidebar: provider-attributed agent activity timeline |
| `dashboard/src/components/TimelineEntry.jsx` | Single timeline entry with NVIDIA/Google color coding |
| `dashboard/src/components/WarmupBar.jsx` | Infrastructure health pills with click-to-probe |
| `dashboard/src/components/ExternalA2A.jsx` | Right sidebar: peer system A2A exchanges (PharmaPilot) |

### Documentation

| Path | Description |
|------|------------|

### Other

| Path | Description |
|------|------------|
| `a2a_server/` | Empty directory — reserved for planned microservice consolidation. Not used in current architecture |

---

*Document authored by Schneider Larbi, Senior Manager, Global Partner Technical Architecture (AI & SaaS ISVs), Google Cloud. April 2026.*

