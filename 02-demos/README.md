# 02 — Demos

End-to-end demos showcasing NVIDIA models on Google Cloud.

---

## Available demos

### [MolForge](./molforge/) — agentic AI drug discovery

A medicinal chemist asks for work in natural language through Gemini Enterprise; MolForge plans
it, fans it out across NVIDIA inference, and streams back a scientific narrative with 2D and 3D
molecular structures rendered inline in the chat.

| | |
|---|---|
| **Capabilities** | Lead optimization, ADMET screening, protein folding, molecular docking, target lookup |
| **NVIDIA** | GenMol and DiffDock (hosted NIMs), Nemotron Super 49B and Nano 12B (Model Garden), ESMFold on RTX PRO 6000 Blackwell |
| **Google Cloud** | Gemini Enterprise, Agent Runtime, Cloud Run, GKE, Cloud Storage |
| **Protocols** | A2A for the Gemini Enterprise interface, A2UI v0.8 for inline rendering |
| **Deploy** | `bash setup.sh` — one idempotent script for the whole stack |

See [`molforge/README.md`](./molforge/README.md) to deploy it.
