# NVIDIA on Google Cloud

---

### ⚠️ Disclaimer

This is not an officially supported Google product, nor an official NVIDIA product. This project is not eligible for the [Google Open Source Software Vulnerability Rewards Program](https://bughunters.google.com/open-source-security).

This project is intended for demonstration and educational purposes only — it is not intended for use in a production environment. The code, configurations, and architectures here are provided **"as is"**, without warranty of any kind, and may rely on preview or rapidly changing APIs. Running these workloads on Google Cloud will incur costs for which you are solely responsible. Review, test, and harden anything here before depending on it.

---

## About

This repository is a curated collection of integration work spanning **NVIDIA on Google Cloud**, covering Gemini Enterprise Agent Platform integrations, agentic AI patterns with ADK, MCP, A2A, model deployment and training, and deployment of NVIDIA-powered agents to **Gemini Enterprise Agent Platform**.

## Repository Structure

| Section | Description |
|---|---|
| [`01-quickstart/`](./01-quickstart/) | Minimal, runnable quickstarts to get up and running fast |
| [`02-demos/`](./02-demos/) | End-to-end demonstration applications |
| [`03-workshops/`](./03-workshops/) | Hands-on, guided workshops for building NVIDIA-accelerated AI workloads on Google Cloud. |

## Getting Started

1. Clone the repository:
   ```bash
   git clone https://github.com/Google-Cloud-AI/partner-ai-nvidia.git
   cd partner-ai-nvidia
   ```
2. Start with [`01-quickstart/`](./01-quickstart/) to get up and running.
3. Explore end-to-end examples in [`02-demos/`](./02-demos/).
4. Dive deep into workshops in [`03-workshops/`](./03-workshops/).

## Prerequisites

- A Google Cloud project with billing enabled
- Access to **NVIDIA models on Gemini Enterprise Agent Platform** (see [partner model deployment documentation](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/partner-models/deploy-partner-models))
- `gcloud` CLI installed and authenticated
- Python 3.11+ and Node.js 20+ for most modules

## Technology Stack

- **Models:** NVIDIA (via NVIDIA API and Gemini Enterprise Agent Platform), Gemini
- **Agent frameworks:** Google ADK, A2A, MCP, Agent Run time, Gemini Enterprise Agent Platform
- **Infrastructure:** GKE, Cloud Run, Gemini Enterprise Agent Platform, BigQuery, AlloyDB, JAX, CUDA, Flax/Optax
- **Tooling:** gcloud, Terraform (where applicable)

## Contributing

See [CONTRIBUTING.md](./CONTRIBUTING.md) for guidelines. All contributors must agree to the [Code of Conduct](./CODE_OF_CONDUCT.md).

## License

This project is licensed under the Apache License 2.0 — see [LICENSE](./LICENSE) for details.

## Maintainer

**Partner Technical Architecture Team**

---

*This repository is a team co-innovation effort and is not an official product of NVIDIA or Google Cloud.*

Onward. 🚀
