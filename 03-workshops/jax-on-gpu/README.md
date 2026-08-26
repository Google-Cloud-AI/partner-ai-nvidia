# JAX AI Stack on GPU: Practical Introduction

A practical introduction to using JAX on NVIDIA GPUs for AI workloads. Learners will understand how JAX runs on GPU, how JIT compilation works, how to avoid common setup and performance pitfalls, and how to train and scale simple models using modern JAX tools.

## Notebooks

| # | Notebook | Topics |
|---|----------|--------|
| 1 | [`01_getting_started_with_jax.ipynb`](./01_getting_started_with_jax.ipynb) | JAX basics, arrays, random keys, GPU verification |
| 2 | [`02_jit_and_compilation.ipynb`](./02_jit_and_compilation.ipynb) | `jax.jit`, tracing, static vs traced args, compilation cache |
| 3 | [`03_profiling_and_debugging.ipynb`](./03_profiling_and_debugging.ipynb) | Profiler, `block_until_ready`, async dispatch, memory |
| 4 | [`04_building_a_simple_training_loop_on_gpu.ipynb`](./04_building_a_simple_training_loop_on_gpu.ipynb) | Raw JAX parameters, training loop, loss/grad, Optax |
| 5 | [`05_attention_on_gpu.ipynb`](./05_attention_on_gpu.ipynb) | Attention from scratch, FlashAttention, cuDNN fusion |
| 6 | [`06_multi_gpu_training.ipynb`](./06_multi_gpu_training.ipynb) | `Mesh`, `NamedSharding`, data parallelism |
| 7 | [`07_transformer_end_to_end.ipynb`](./07_transformer_end_to_end.ipynb) | Transformer model, training on Shakespeare, text generation |
| 8 | [`08_serving_and_next_steps.ipynb`](./08_serving_and_next_steps.ipynb) | Checkpointing, AOT compilation, `jax.export`, TF SavedModel |

## Prerequisites

- A machine with one or more NVIDIA GPUs (L4, A100, H100, etc.)
- NVIDIA drivers and the [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html)
- Lessons 1-5 and 8 run on a single GPU. Lessons 6 and 7 require 2+ GPUs.

## Running the notebooks

### Option 1: Local Docker (single machine with GPUs)

```bash
git clone https://github.com/Google-Cloud-AI/partner-ai-nvidia.git
cd partner-ai-nvidia/03-workshops/jax-on-gpu

docker run -it --rm \
  --gpus=all \
  -p 8884:8884 \
  -p 6006:6006 \
  -p 6007:6007 \
  --shm-size=16g \
  --ulimit memlock=-1 \
  -e LD_LIBRARY_PATH=/opt/nvidia/cudnn/lib \
  -v "$(pwd)":/workspace \
  -w /workspace \
  nvcr.io/nvidia/jax:26.04-maxtext-py3 \
  bash -lc '
    python -m pip install --no-cache-dir \
      --requirement deploy/requirements-workshop.txt &&
    python deploy/verify_environment.py &&
    jupyter lab \
      --ip=0.0.0.0 \
      --port=8884 \
      --no-browser \
      --allow-root
  '
```

Open `http://localhost:8884` in your browser.

### Option 2: GKE with NVIDIA GPUs

Provision a GKE cluster with GPU nodes using the included Terraform config.

**Requirements:**

- `gcloud` CLI, `terraform`, and `kubectl`
- A GCP project with billing enabled and [GPU quota](https://cloud.google.com/compute/docs/gpus/create-vm#check-quota) for L4 (or your chosen GPU type)
- Caller permissions to enable services and create the network, GKE cluster, service account, and IAM bindings. The required predefined roles are Service Usage Admin (`roles/serviceusage.serviceUsageAdmin`), Kubernetes Engine Admin (`roles/container.admin`), Compute Network Admin (`roles/compute.networkAdmin`), Service Account Admin (`roles/iam.serviceAccountAdmin`), Service Account User (`roles/iam.serviceAccountUser`), and Project IAM Admin (`roles/resourcemanager.projectIamAdmin`), or equivalent permissions.

Authenticate the Google Cloud CLI, configure Application Default Credentials for Terraform, and enable the required APIs:

```bash
gcloud auth login
gcloud auth application-default login
gcloud services enable \
  compute.googleapis.com \
  container.googleapis.com \
  --project=YOUR_PROJECT_ID
```

```bash
git clone https://github.com/Google-Cloud-AI/partner-ai-nvidia.git
cd partner-ai-nvidia/03-workshops/jax-on-gpu

# 1. Configure your project
cd terraform
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars — set project_id to your GCP project

# 2. Provision the cluster
terraform init
terraform apply

# 3. Get cluster credentials
$(terraform output -raw get_credentials_command)

# 4. Create the pinned environment ConfigMap and deploy Jupyter
kubectl apply -k ../deploy

# 5. Wait for the external IP, then open http://<EXTERNAL-IP>:8884
kubectl get svc jax-jupyter-svc -w
```

Upload the notebooks to the Jupyter instance or clone the repo from inside the pod.

**Teardown:**

```bash
kubectl delete -k ../deploy
terraform destroy
```

**Changing GPU count:** Update `gpu_count` in `terraform/terraform.tfvars` and `nvidia.com/gpu` in `deploy/jupyter.yaml` to match. Use `g2-standard-48` for 4 L4s.
