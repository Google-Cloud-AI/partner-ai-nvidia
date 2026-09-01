# 01 — Quickstarts

Minimal, runnable quickstarts for getting up and running with NVIDIA models on Google Cloud.

---

## 🚀 Available Quickstarts

### 1. [NVIDIA Nemotron Suite on Gemini Enterprise Agent Platform](./nemotron/)
A curated collection of 5 progressive, production-grade Jupyter notebooks demonstrating enterprise agentic workloads with the **NVIDIA Nemotron & NeMo** foundation model family on **Google Cloud Gemini Enterprise Agent Platform**:

| # | Notebook | Primary Model Tier | Target GPU Profile | Core Enterprise Workload |
| :--- | :--- | :--- | :--- | :--- |
| **00** | [`00_nemotron_interactive_agentic_quickstart.ipynb`](./nemotron/00_nemotron_interactive_agentic_quickstart.ipynb) | **Universal Nemotron** | `g4-standard-48` / `g2-standard-16` | **Interactive Multi-Tool ReAct Agent**: Interactive conversational loop with Python REPL calculator, GCP machine specs lookup, and cloud knowledge base search. |
| **01** | [`01_nemotron_lightning_realtime_incident_triage.ipynb`](./nemotron/01_nemotron_lightning_realtime_incident_triage.ipynb) | **Nemotron-3.5 Lightning** | `g4-standard-48` / `g2-standard-16` | **Sub-Second DevOps Incident Triage**: High-velocity log parsing, cascade failure mapping, and TTFT latency benchmarking (< 500ms). |
| **02** | [`02_nemotron_nano_edge_telemetry_dispatcher.ipynb`](./nemotron/02_nemotron_nano_edge_telemetry_dispatcher.ipynb) | **Nemotron-3 Nano (30B/3B MoE)** | `g4-standard-48` / `g2-standard-16` | **Edge Telemetry & JSON Dispatcher**: Schema-enforced Pydantic extraction for industrial IoT sensor streams with automated event routing. |
| **03** | [`03_nemotron_super_infra_terraform_refactoring.ipynb`](./nemotron/03_nemotron_super_infra_terraform_refactoring.ipynb) | **Nemotron-3 Super (120B/12B MoE)** | `g4-standard-384` / `g2-standard-96` | **Autonomous Infra & Terraform Refactoring**: Refactors unhardened docker-compose configurations into production Google Cloud Terraform architectures with CIS security scoring. |
| **04** | [`04_nemotron_ultra_long_context_compliance_rlaif.ipynb`](./nemotron/04_nemotron_ultra_long_context_compliance_rlaif.ipynb) | **Nemotron-3 Ultra (550B/55B MoE)** | `a4-highgpu-8g` / `a3-ultragpu-8g` | **256K Context Compliance Audit & RLAIF Studio**: Full-repository HIPAA/SOC 2 compliance audit, patch diff generation, and 5-attribute synthetic reward scoring judge. |

For detailed setup, 3-mode endpoint options, and automated testing, see [`nemotron/README.md`](./nemotron/README.md).
