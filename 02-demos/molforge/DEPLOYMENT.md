# Deploying MolForge by hand

`bash setup.sh` does everything on this page, in this order, and handles the traps documented
here on your behalf. Read this if you would rather drive the deployment yourself, if the script
failed part way and you want to finish the job, or if something is behaving strangely and you
want to know what the script would have done.

See the [README](README.md) for prerequisites — they are the same, and this page assumes you
have met them.

---

## Project setup

Every snippet below assumes these:

```bash
export PROJECT_ID=<your-project-id>
export REGION=us-central1
export BUCKET=<your-artifacts-bucket>        # bare name, no gs:// prefix

gcloud services enable aiplatform.googleapis.com run.googleapis.com container.googleapis.com \
  cloudbuild.googleapis.com artifactregistry.googleapis.com secretmanager.googleapis.com \
  storage.googleapis.com --project="${PROJECT_ID}"

gcloud storage buckets create "gs://${BUCKET}" --location="${REGION}"
gcloud artifacts repositories create molforge --repository-format=docker --location="${REGION}"
```

## The NVIDIA key

It goes to Secret Manager and nowhere else — never into a `.env` file or a deployed image. The
agents fetch it at runtime, so the runtime identity needs to be able to read it:

```bash
printf '%s' "$NGC_API_KEY" | gcloud secrets create molforge-nvidia-api-key --data-file=-

# The Agent Runtime service agent is created lazily, so provision it before binding to it.
gcloud beta services identity create --service=aiplatform.googleapis.com --project="${PROJECT_ID}"
PROJECT_NUMBER="$(gcloud projects describe "${PROJECT_ID}" --format='value(projectNumber)')"
RE_SA="service-${PROJECT_NUMBER}@gcp-sa-aiplatform-re.iam.gserviceaccount.com"

gcloud secrets add-iam-policy-binding molforge-nvidia-api-key \
  --member="serviceAccount:${RE_SA}" --role="roles/secretmanager.secretAccessor"
gcloud storage buckets add-iam-policy-binding "gs://${BUCKET}" \
  --member="serviceAccount:${RE_SA}" --role="roles/storage.objectAdmin"
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${RE_SA}" --role="roles/aiplatform.user" --condition=None
```

> **Skip the secret and the stack still comes up — it just doesn't work.** GenMol and DiffDock are
> hosted NIMs that read this key on every call, so without it the two headline tools return 401 and
> say nothing useful about why. If the IAM binding fails because the service agent does not exist
> yet, deploy the agents first and then re-run these three bindings.

## CPU services

Note the exact service names, because the bridge and the agents are configured with these URLs:

```bash
gcloud run deploy molforge-rdkit          --source=services/rdkit_service   --region="${REGION}" --allow-unauthenticated
gcloud run deploy molforge-admet-ai       --source=services/admet_ai        --region="${REGION}" --allow-unauthenticated --cpu=2 --memory=4Gi
gcloud run deploy molforge-data-retrieval --source=services/data_retrieval  --region="${REGION}" --allow-unauthenticated \
  --set-env-vars="MOLFORGE_ARTIFACTS_BUCKET=${BUCKET}"
```

## Render service

It needs its PyMOL variant, which is a separate Dockerfile — the default one has
no PyMOL, and `mol3d.py` quietly falls back to matplotlib rather than failing, so building the
wrong one gives you a working service that draws worse pictures:

```bash
gcloud builds submit --config=services/render_service/cloudbuild.pymol.yaml
gcloud run deploy molforge-render \
  --image="${REGION}-docker.pkg.dev/${PROJECT_ID}/molforge/molforge-render-pymol:latest" \
  --region="${REGION}" --allow-unauthenticated --cpu=4 --memory=4Gi \
  --set-env-vars="MOLFORGE_ARTIFACTS_BUCKET=${BUCKET}"
```

## ESMFold and the GPU tier

ESMFold is the only local GPU workload, and the only thing on the cluster. GenMol and DiffDock
need no deployment at all — they are NVIDIA-hosted NIMs, which is the agents' code default. The
cluster and its Blackwell pool are the one piece worth letting the script do, because the machine
type needs a specific disk type and capacity is usually only obtainable through a reservation:

```bash
bash setup.sh --only gke          # cluster + the single g4 / RTX PRO 6000 pool
kubectl apply -f services/esmfold/deployment.yaml
```

Skip this entirely if you do not need protein folding — nothing else in the stack depends on the
cluster.

## Agents

Each one reads a `.env` file from its own directory, which is **not** in the repository — only
`.env.example` templates are. Create all three from the templates and fill in the service URLs
you just deployed:

```bash
for a in orchestrator lead_optimizer admet_safety_agent; do
  cp "agents/$a/.env.example" "agents/$a/.env"
done
# then edit each one: GOOGLE_CLOUD_PROJECT, MOLFORGE_ARTIFACTS_BUCKET,
# and the MOLFORGE_*_URL values for the services above
```

> **The build fails without these**, deliberately. Both cloudbuild files assert that each `.env`
> exists and carries a non-empty `GOOGLE_CLOUD_PROJECT` before running `adk deploy`. Without that
> check the deploy *succeeds* and the agent then fails to boot, which reads as an ADK bug rather
> than a missing file. A second trap: an empty value is worse than an absent one, because
> `os.getenv(key, default)` returns `""` for a variable that is set-but-empty — so delete the lines
> you are not setting rather than leaving them blank.

```bash
gcloud builds submit . --config=agents/cloudbuild-subagents.yaml   # lead optimizer + ADMET
gcloud builds submit . --config=agents/cloudbuild-deploy.yaml      # orchestrator
```

> `gcloud builds submit` detaches after about two minutes and looks like it failed. It has not —
> it is still running. Re-running it deploys a **second** set of agents, each billing separately.
> Watch the build in Cloud Build rather than resubmitting.

> **Each agent deploy mints a new Agent Runtime ID.** Deploy the sub-agents first, record their IDs
> into `agents/orchestrator/.env`, then deploy the orchestrator, then set its ID as
> `ORCHESTRATOR_ENGINE_ID` on the bridge. Deploying in this order means you propagate IDs once.

## Bridge and viewer

Every variable below has a default in `a2a/server.py`, and every one of those defaults is a value
from the reference deployment — wrong anywhere else, and wrong silently. Set them all:

```bash
gcloud run deploy molforge-viewer --source=viewer --region="${REGION}" --allow-unauthenticated

gcloud run deploy molforge-a2a --source=a2a --region="${REGION}" --allow-unauthenticated \
  --set-env-vars="ORCHESTRATOR_ENGINE_ID=<id>,MOLFORGE_A2UI=1,\
MOLFORGE_GCS_BUCKET=${BUCKET},MOLFORGE_VIEWER_URL=<viewer url>,MOLFORGE_RENDER_URL=<render url>"
```

`MOLFORGE_A2UI` defaults to off, so leaving it out costs you every inline render.

Once the bridge is up, follow **Verify before registering** in the [README](README.md#verify-before-registering)
before you involve Gemini Enterprise.

