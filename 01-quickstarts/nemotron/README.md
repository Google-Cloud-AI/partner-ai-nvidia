# NVIDIA Nemotron on Google Cloud Gemini Enterprise Agent Platform

<!--
Copyright 2026 Google LLC

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    https://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
-->

A curated suite of 5 production-grade, reproducible Jupyter Notebooks demonstrating advanced enterprise workloads with the **NVIDIA Nemotron & NeMo** foundation model family on **Google Cloud Gemini Enterprise Agent Platform** and **Google Kubernetes Engine (GKE)**.

---

## 🚀 Notebook Suite Overview

| # | Notebook | Primary Model Tier | Target GPU Acceleration | Unique Enterprise Use Case |
| :--- | :--- | :--- | :--- | :--- |
| **00** | [`00_nemotron_interactive_agentic_quickstart.ipynb`](./00_nemotron_interactive_agentic_quickstart.ipynb) | **Universal Nemotron** | `g4-standard-48` / `g2-standard-16` | **Interactive Multi-Tool ReAct Agent**: Interactive conversational loop with Python REPL, GCP Resource Querying, and Cloud Docs Search. |
| **01** | [`01_nemotron_lightning_realtime_incident_triage.ipynb`](./01_nemotron_lightning_realtime_incident_triage.ipynb) | **Nemotron-3.5 Lightning** | `g4-standard-48` / `g2-standard-16` | **Sub-Second Streaming DevOps & Incident Triage**: Real-time log anomaly parsing, cascade failure mapping, and TTFT latency benchmarking (< 500ms). |
| **02** | [`02_nemotron_nano_edge_telemetry_dispatcher.ipynb`](./02_nemotron_nano_edge_telemetry_dispatcher.ipynb) | **Nemotron-3 Nano (30B/3B MoE)** | `g4-standard-48` / `g2-standard-16` | **High-Throughput Edge Telemetry & JSON Dispatcher**: Schema-enforced Pydantic extraction for industrial IoT and automated Cloud Function event routing. |
| **03** | [`03_nemotron_super_infra_terraform_refactoring.ipynb`](./03_nemotron_super_infra_terraform_refactoring.ipynb) | **Nemotron-3 Super (120B/12B MoE)** | `g4-standard-384` / `g2-standard-96` | **Autonomous Infrastructure & Terraform Refactoring**: Ingests monolithic docker-compose files and generates secure GCP Terraform architectures (Cloud SQL, Secret Manager, Cloud Armor). |
| **04** | [`04_nemotron_ultra_long_context_compliance_rlaif.ipynb`](./04_nemotron_ultra_long_context_compliance_rlaif.ipynb) | **Nemotron-3 Ultra (550B/55B MoE)** | `a4-highgpu-8g` / `a3-ultragpu-8g` | **256K Long-Context Compliance Audit & Multi-Attribute RLAIF Studio**: Full-repository HIPAA/SOC 2 audit and 5-attribute synthetic reward scoring judge. |

---

## 🛠️ Architecture & Flexible Endpoint Operations

Every notebook supports **3 flexible operation modes** out of the box:
1. **Mode 1 (`AUTO_DISCOVER`) [Default]**: Automatically scans active Vertex AI endpoints in your GCP project and attaches to the matching Model Garden Nemotron deployment in seconds.
2. **Mode 2 (`USE_EXISTING_ENDPOINT`)**: Directly binds to any custom endpoint, fine-tuned model, or private endpoint by setting `CUSTOM_ENDPOINT_ID = "<endpoint-id>"`.
3. **Mode 3 (`CREATE_CUSTOM_ENDPOINT`)**: Programmatically registers a custom model container image (e.g. vLLM or Triton) with optional GCS weights and provisions a new Vertex AI Endpoint directly from the notebook.
4. **Safe Lifecycle Management**: Includes safe teardown cells at the end of each notebook to undeploy scratch endpoints when testing is complete.

Supported Google Cloud Accelerator Profiles:
* **G4 Blackwell Series**: `g4-standard-48` (1x RTX PRO 6000 48GB), `g4-standard-96` (2x RTX PRO 6000), `g4-standard-384` (8x RTX PRO 6000 384GB)
* **G2 L4 Series**: `g2-standard-16` (1x L4 24GB), `g2-standard-24` (2x L4 48GB), `g2-standard-96` (8x L4 192GB)
* **A3 / A4 Series**: `a3-ultragpu-8g` (8x H200 1128GB), `a4-highgpu-8g` (8x B200 1536GB)

---

## 🧪 Testing & Verification

Run the automated regression test harness:
```bash
python test_notebooks.py
```

---

## 📄 License

Copyright 2026 Google LLC. Licensed under the Apache License, Version 2.0.
