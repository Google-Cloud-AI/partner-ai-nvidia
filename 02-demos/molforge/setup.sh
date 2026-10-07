#!/usr/bin/env bash
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

#
# ============================================================================
#  MolForge — One-shot, idempotent, ground-up build for Google Cloud Shell
# ============================================================================
#
#  Builds the entire MolForge agentic drug-discovery platform from zero into a
#  fresh (or partially-built) GCP project:
#
#    Foundation : APIs · Artifact Registry · GCS bucket · NGC secrets · IAM/WI
#    Execution  : GKE cluster + one Blackwell (g4) GPU pool + CPU pool
#                 ESMFold (Blackwell) — the only local GPU workload
#                 GenMol, DiffDock — NVIDIA-hosted NIMs, nothing to deploy
#    Bridge/UI  : A2A 0.2.1 bridge, Mol* viewer, render service, ADMET-AI,
#                 RDKit, Data-Retrieval, React dashboard (all Cloud Run)
#    Agents     : Orchestrator, Lead Optimizer, ADMET Safety (Agent Runtime)
#    GE         : Gemini Enterprise app + A2A agent registration (best-effort API)
#
#  Design goals
#    * IDEMPOTENT  — every step is "describe-or-create"; safe to re-run.
#    * PARAMETERIZED — prompts for project/region/NGC key/etc; nothing hardcoded.
#    * SELF-CONTAINED — generates the K8s manifests + cloudbuild configs inline.
#    * HONEST — pre-flights the things it cannot create (GPU quota, NGC access)
#               and degrades GE registration to printed steps if the API balks.
#
#  Usage
#    bash setup.sh                 # interactive (prompts, saves answers)
#    bash setup.sh --yes           # non-interactive (uses saved/env values)
#    bash setup.sh --skip-gpu      # control-plane only (no GKE/GPU tier)
#    bash setup.sh --rotate-ngc    # re-add the NGC key as a new secret version
#    bash setup.sh --only <phase>  # run a single phase (see PHASES below)
#
#  Answers persist to ./.molforge-setup.conf so re-runs don't re-prompt.
# ============================================================================

set -Eeuo pipefail

# ---------------------------------------------------------------------------
# 0. Globals, logging, helpers
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONF_FILE="${SCRIPT_DIR}/.molforge-setup.conf"
BUILD_DIR="${SCRIPT_DIR}/.molforge-build"
K8S_DIR="${BUILD_DIR}/k8s"
LOG_DIR="${BUILD_DIR}/logs"
mkdir -p "${K8S_DIR}" "${LOG_DIR}"

# The one google-adk version known to deploy an engine that actually boots.
# Keep this in step with the pins in each agent's requirements.txt and in
# agents/cloudbuild-*.yaml — see ensure_adk for what each version breaks.
ADK_VERSION="2.1.0"

# Flags
ASSUME_YES=0; SKIP_GPU=0; ROTATE_NGC=0; ONLY_PHASE=""
for arg in "$@"; do
  case "$arg" in
    --yes|-y)        ASSUME_YES=1 ;;
    --skip-gpu)      SKIP_GPU=1 ;;
    --rotate-ngc)    ROTATE_NGC=1 ;;
    --only)          ONLY_PHASE="__next__" ;;
    *) if [[ "${ONLY_PHASE}" == "__next__" ]]; then ONLY_PHASE="$arg"; fi ;;
  esac
done

if [[ -t 1 ]]; then
  C_RESET="\033[0m"; C_BOLD="\033[1m"; C_DIM="\033[2m"
  C_BLU="\033[34m"; C_GRN="\033[32m"; C_YEL="\033[33m"; C_RED="\033[31m"; C_CYN="\033[36m"
else
  C_RESET=""; C_BOLD=""; C_DIM=""; C_BLU=""; C_GRN=""; C_YEL=""; C_RED=""; C_CYN=""
fi

log()   { echo -e "${C_DIM}$(date +%H:%M:%S)${C_RESET} ${C_BLU}▸${C_RESET} $*"; }
ok()    { echo -e "${C_DIM}$(date +%H:%M:%S)${C_RESET} ${C_GRN}✓${C_RESET} $*"; }
warn()  { echo -e "${C_DIM}$(date +%H:%M:%S)${C_RESET} ${C_YEL}!${C_RESET} $*"; }
err()   { echo -e "${C_DIM}$(date +%H:%M:%S)${C_RESET} ${C_RED}✗${C_RESET} $*" >&2; }
die()   { err "$*"; exit 1; }
phase() { echo; echo -e "${C_BOLD}${C_CYN}━━━ $* ━━━${C_RESET}"; }

trap 'err "Failed at line $LINENO. Re-run the script — it resumes idempotently."' ERR

confirm() {
  # confirm "message" ; returns 0 to proceed
  [[ "${ASSUME_YES}" == "1" ]] && return 0
  local reply
  read -r -p "$(echo -e "${C_YEL}?${C_RESET} $1 [y/N] ")" reply
  [[ "${reply}" =~ ^[Yy]$ ]]
}

ask() {
  # ask VARNAME "Prompt" "default" [secret]
  local var="$1" prompt="$2" def="${3:-}" secret="${4:-}"
  local cur="${!var:-}"
  if [[ -n "${cur}" ]]; then return 0; fi          # already set (env or conf)
  if [[ "${ASSUME_YES}" == "1" ]]; then
    [[ -n "${def}" ]] || die "Missing required value for ${var} in non-interactive mode"
    printf -v "$var" '%s' "${def}"; return 0
  fi
  local input
  if [[ "${secret}" == "secret" ]]; then
    read -r -s -p "$(echo -e "${C_YEL}?${C_RESET} ${prompt}: ")" input; echo
  else
    read -r -p "$(echo -e "${C_YEL}?${C_RESET} ${prompt}${def:+ [${def}]}: ")" input
  fi
  printf -v "$var" '%s' "${input:-$def}"
}

need() { command -v "$1" >/dev/null 2>&1 || die "Required tool '$1' not found. (Cloud Shell ships it; locally: install gcloud/kubectl/jq.)"; }

save_conf() {
  cat > "${CONF_FILE}" <<EOF
# MolForge setup — saved $( : "stamp omitted; values only" )
PROJECT_ID="${PROJECT_ID}"
REGION="${REGION}"
GKE_ZONE="${GKE_ZONE}"
BLACKWELL_ZONE="${BLACKWELL_ZONE}"
AR_REPO="${AR_REPO}"
BUCKET="${BUCKET}"
CLUSTER="${CLUSTER}"
GSA_NAME="${GSA_NAME}"
SA_PREFIX="${SA_PREFIX}"
GE_APP_ID="${GE_APP_ID}"
GE_APP_NAME="${GE_APP_NAME}"
GE_LOCATION="${GE_LOCATION}"
BLACKWELL_POOL_FLAGS="${BLACKWELL_POOL_FLAGS}"
EOF
  ok "Saved configuration to ${CONF_FILE} (NGC key is NOT stored here)."
}

# ---------------------------------------------------------------------------
# 0b. Prerequisites banner (shown BEFORE any parameters are collected)
# ---------------------------------------------------------------------------
show_prerequisites() {
  cat <<EOF

${C_BOLD}${C_CYN}╭───────────────────────────────────────────────────────────────────────╮
│  MolForge — ground-up build for Google Cloud                            │
╰───────────────────────────────────────────────────────────────────────╯${C_RESET}

This script builds the entire MolForge agentic platform into your project:
ESMFold on one GKE Blackwell GPU + CPU services on Cloud Run + 3 Agent Runtime
agents + A2A bridge + viewer + dashboard, and registers it in Gemini Enterprise.
(GenMol and DiffDock are NVIDIA-hosted NIMs — nothing to deploy for those.)

${C_BOLD}PREREQUISITES — please confirm these BEFORE continuing:${C_RESET}

  ${C_YEL}1. Environment${C_RESET}
     • Run in Google Cloud Shell (ships gcloud, kubectl, jq, docker, python3),
       or a shell with those tools installed.
     • Authenticated:  gcloud auth login   (and: gcloud auth application-default login)

  ${C_YEL}2. GCP project${C_RESET}
     • A project you own with BILLING ENABLED.
     • IAM: Owner or (Editor + Project IAM Admin + Service Account Admin).

  ${C_YEL}3. NVIDIA NGC API key  (needed even with --skip-gpu)${C_RESET}
     • An 'nvapi-…' key from https://ngc.nvidia.com  with NIM / NGC catalog access.
     • Two jobs: pulling the NGC PyTorch base image that ESMFold builds on, and
       authenticating the hosted GenMol/DiffDock NIM calls at runtime.
     • Only the first job is a GPU thing. --skip-gpu does not prompt for the key,
       but without it GenMol and DiffDock return 401 and optimize fails at step
       one — so pass NGC_API_KEY=nvapi-… in the environment even when skipping GPU.
     • You'll paste it at the prompt; it goes only into Secret Manager, never to disk.

  ${C_YEL}4. GPU quota in your region  (required unless --skip-gpu)${C_RESET}
     • NVIDIA RTX PRO 6000 (Blackwell, g4 machines) — ESMFold, and nothing else.
       GenMol and DiffDock are hosted by NVIDIA, so they need no quota at all.
     • Request via Console → IAM & Admin → Quotas. Grants can take hours/days.
     • This script pre-flights quota but CANNOT grant it.

  ${C_YEL}5. Gemini Enterprise / Agentspace${C_RESET}
     • Available in your org (Discovery Engine API — the script enables it).
     • Final agent registration is best-effort via API; falls back to printed
       console steps if the (alpha) API doesn't confirm.

${C_BOLD}WHAT IT COSTS / CHANGES:${C_RESET} creates a GKE cluster + one GPU node pool (scale-to-zero
when idle), Cloud Run services, Agent Runtime reasoning engines, an Artifact
Registry repo, a GCS bucket, and Secret Manager secrets. Re-runnable & idempotent.

${C_BOLD}WHAT IT LEAVES OPEN:${C_RESET} every service it deploys is --allow-unauthenticated, so
anyone with a URL can call it. That is deliberate for a reference build you can
drive the same afternoon, and it is the one thing to close before real use.

${C_DIM}Tip: run with --skip-gpu to build just the control plane (no GPU quota / NGC key).${C_RESET}

EOF
  confirm "Have you met the prerequisites above and want to continue?" \
    || die "Aborted. Meet the prerequisites above, then re-run:  bash setup.sh"
  echo
}

# ---------------------------------------------------------------------------
# 1. Parameters
# ---------------------------------------------------------------------------
collect_params() {
  phase "Parameters"
  [[ -f "${CONF_FILE}" ]] && { log "Loading saved answers from ${CONF_FILE}"; source "${CONF_FILE}"; }

  local gcloud_proj; gcloud_proj="$(gcloud config get-value project 2>/dev/null || true)"

  ask PROJECT_ID      "GCP project ID"                         "${gcloud_proj}"
  ask REGION          "Region (Cloud Run / Agent Runtime / AR)" "us-central1"
  ask GKE_ZONE        "Zone for the CPU default pool"          "${REGION}-c"
  ask BLACKWELL_ZONE  "Zone for the Blackwell (g4) pool"       "${REGION}-b"
  ask AR_REPO         "Artifact Registry repo name"            "molforge-repo"
  ask BUCKET          "GCS artifacts bucket (globally unique)" "${PROJECT_ID}-molforge-artifacts"
  ask CLUSTER         "GKE cluster name"                       "molforge-gke"
  ask GSA_NAME        "GKE workload service account name"      "molforge-gke-sa"
  ask SA_PREFIX       "Service-account name prefix"            "molforge"
  ask GE_APP_ID       "Gemini Enterprise app ID"               "molforge"
  ask GE_APP_NAME     "Gemini Enterprise app display name"     "MolForge"
  ask GE_LOCATION     "Gemini Enterprise location"             "global"

  # GPU node-pool flags are exposed as an overridable string because exact
  # accelerator names / machine shapes drift with GCP GPU availability.
  # Adjust here if `gcloud container node-pools create` rejects them.
  # g4 REQUIRES hyperdisk-balanced; the create call fails outright without it.
  : "${BLACKWELL_POOL_FLAGS:=--machine-type=g4-standard-48 --accelerator=type=nvidia-rtx-pro-6000,count=1,gpu-driver-version=LATEST --disk-type=hyperdisk-balanced}"

  # NGC key — required for the NVIDIA NIM / NGC base images. Never persisted to disk.
  if [[ "${SKIP_GPU}" != "1" ]]; then
    ask NGC_API_KEY "NVIDIA NGC API key (nvapi-… ; input hidden)" "" secret
    [[ -n "${NGC_API_KEY:-}" ]] || die "NGC API key is required for the GPU/NIM tier. Get one at ngc.nvidia.com, or run with --skip-gpu."
  fi

  REPO_HOST="${REGION}-docker.pkg.dev"
  REPO_PATH="${REPO_HOST}/${PROJECT_ID}/${AR_REPO}"
  GSA_EMAIL="${GSA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

  # Service-account IDs are capped at 30 chars and the longest suffix we append
  # is "-dashboard-sa" (13). Caught here rather than as a gcloud error partway
  # through the foundation phase, with some accounts already created.
  [[ "${#SA_PREFIX}" -le 17 ]] \
    || die "SA_PREFIX '${SA_PREFIX}' is ${#SA_PREFIX} chars; must be 17 or fewer (service-account IDs are capped at 30 and we append up to '-dashboard-sa')."
  [[ "${SA_PREFIX}" =~ ^[a-z][a-z0-9-]*$ ]] \
    || die "SA_PREFIX '${SA_PREFIX}' must start with a lowercase letter and contain only lowercase letters, digits and hyphens."

  save_conf

  echo
  log "Project        : ${PROJECT_ID}"
  log "Region         : ${REGION}  (GKE zone ${GKE_ZONE}, Blackwell zone ${BLACKWELL_ZONE})"
  log "Artifact Reg.  : ${REPO_PATH}"
  log "Bucket         : gs://${BUCKET}"
  log "GKE cluster    : ${CLUSTER}"
  log "GPU tier       : $([[ "${SKIP_GPU}" == 1 ]] && echo 'SKIPPED (--skip-gpu)' || echo 'ENABLED')"
}

# ---------------------------------------------------------------------------
# 2. Pre-flight
# ---------------------------------------------------------------------------
preflight() {
  phase "Pre-flight checks"
  need gcloud; need jq; need kubectl
  command -v adk >/dev/null 2>&1 || warn "'adk' CLI not found yet — phase 'agents' will pip-install google-adk into a venv."

  gcloud auth print-access-token >/dev/null 2>&1 || die "Not authenticated. Run: gcloud auth login"
  gcloud projects describe "${PROJECT_ID}" >/dev/null 2>&1 || die "Project ${PROJECT_ID} not found or no access."
  gcloud config set project "${PROJECT_ID}" >/dev/null 2>&1
  ok "Authenticated; project ${PROJECT_ID} reachable."

  # Billing
  local ba
  ba="$(gcloud beta billing projects describe "${PROJECT_ID}" --format='value(billingEnabled)' 2>/dev/null || echo 'unknown')"
  [[ "${ba}" == "True" ]] && ok "Billing enabled." || warn "Could not confirm billing is enabled — GKE/GPU/Run will fail without it."

  if [[ "${SKIP_GPU}" != "1" ]]; then
    # NGC key sanity (login test against nvcr.io via token endpoint).
    if echo "${NGC_API_KEY}" | docker login nvcr.io -u '$oauthtoken' --password-stdin >/dev/null 2>&1; then
      ok "NGC API key authenticates to nvcr.io."
      docker logout nvcr.io >/dev/null 2>&1 || true
    else
      warn "Could not verify NGC key locally (no docker, or key issue). Cloud Build will be the real test."
    fi
    # Blackwell (g4) capacity — informational pre-flight, deliberately honest
    # about what it can and cannot tell you.
    #
    # There is no G4 quota check to do here. `gcloud compute regions describe`
    # returns only the legacy quota list — it carries no RTX PRO 6000 / g4 metric
    # at all, verified in a project that IS running a g4 pool. The old check
    # grepped that list for GPU|NVIDIA, matched the K80/P100/V100 rows every
    # region carries, and printed them as success: false reassurance about
    # precisely the quota it claimed to be checking. The real numbers live in the
    # Cloud Quotas API, which needs an ADC quota project configured, so it is not
    # a dependency this script can take.
    #
    # What IS checkable and actionable is capacity: RTX PRO 6000 is severely
    # supply-constrained, and a specific reservation is the race-free way to hold
    # it. Without one, the pool creation below usually fails with a stockout.
    log "Checking Blackwell (g4) capacity in ${BLACKWELL_ZONE} (informational)…"
    local rsv
    rsv="$(gcloud compute reservations list --zones="${BLACKWELL_ZONE}" \
      --format="value(name)" 2>/dev/null || true)"
    if [[ -n "${rsv}" ]]; then
      ok "Reservation(s) in ${BLACKWELL_ZONE}: ${rsv//$'\n'/, }"
      log "  To consume one, add --reservation-affinity=specific --reservation=<name> to BLACKWELL_POOL_FLAGS."
    else
      warn "No reservation in ${BLACKWELL_ZONE}. RTX PRO 6000 is supply-constrained — pool creation may fail with a stockout."
      warn "  Race-free path: gcloud compute reservations create molforge-g4-rsv --zone=${BLACKWELL_ZONE} \\"
      warn "      --machine-type=g4-standard-48 --accelerator=type=nvidia-rtx-pro-6000,count=1 --require-specific-reservation"
      warn "  then add --reservation-affinity=specific --reservation=molforge-g4-rsv to BLACKWELL_POOL_FLAGS."
      warn "  A held reservation bills continuously, whether or not a node is attached."
      warn "  G4 quota is NOT visible via 'gcloud compute regions describe' — check IAM & Admin → Quotas if creation fails."
    fi
  fi
}

# ---------------------------------------------------------------------------
# 3. APIs
# ---------------------------------------------------------------------------
enable_apis() {
  phase "Enable APIs"
  local apis=(
    aiplatform.googleapis.com run.googleapis.com container.googleapis.com
    cloudbuild.googleapis.com artifactregistry.googleapis.com
    secretmanager.googleapis.com storage.googleapis.com compute.googleapis.com
    iam.googleapis.com iamcredentials.googleapis.com discoveryengine.googleapis.com
  )
  log "Enabling: ${apis[*]}"
  gcloud services enable "${apis[@]}" --project "${PROJECT_ID}"
  ok "APIs enabled."
}

# ---------------------------------------------------------------------------
# 4. Foundation — AR, bucket, secrets, service accounts, IAM
# ---------------------------------------------------------------------------
foundation() {
  phase "Foundation (Artifact Registry · Bucket · Secrets · IAM)"

  # Artifact Registry
  if gcloud artifacts repositories describe "${AR_REPO}" --location "${REGION}" >/dev/null 2>&1; then
    ok "Artifact Registry '${AR_REPO}' exists."
  else
    gcloud artifacts repositories create "${AR_REPO}" \
      --repository-format=docker --location="${REGION}" \
      --description="MolForge images"
    ok "Created Artifact Registry '${AR_REPO}'."
  fi
  gcloud auth configure-docker "${REPO_HOST}" --quiet >/dev/null 2>&1 || true

  # GCS bucket
  if gcloud storage buckets describe "gs://${BUCKET}" >/dev/null 2>&1; then
    ok "Bucket gs://${BUCKET} exists."
  else
    gcloud storage buckets create "gs://${BUCKET}" --location="${REGION}" --uniform-bucket-level-access
    ok "Created bucket gs://${BUCKET}."
  fi

  # Two secrets, same NVIDIA key, different consumers:
  #
  #   ngc-api-key             Cloud Build, to `docker login nvcr.io` for the
  #                           ESMFold image's NGC PyTorch base. Build-time only.
  #   molforge-nvidia-api-key The lead-optimizer agent at RUNTIME, as the bearer
  #                           token for the hosted GenMol and DiffDock NIMs.
  #
  # The second one is not optional now that GenMol and DiffDock are hosted: with
  # no key the agent gets 401s from health.api.nvidia.com and the whole optimize
  # pipeline fails at its first step. tools/_nvidia.py builds the secret path
  # from GOOGLE_CLOUD_PROJECT, so the NAME here has to match exactly.
  #
  # Note this is deliberately NOT written into any agent .env -- the agent reads
  # it from Secret Manager at runtime, so the key never lands in a deployed
  # artifact. Only the grant below makes that work.
  #
  # Gated on having a key, NOT on --skip-gpu. --skip-gpu skips the LOCAL GPU
  # tier; GenMol and DiffDock are hosted by NVIDIA and still need this key at
  # runtime, so tying the secret to the GPU flag quietly produced a stack whose
  # two headline tools 401 on every call. --skip-gpu does not prompt for a key,
  # but one passed in the environment is honoured, and its absence is now said
  # out loud instead of being inferred from a flag about something else.
  if [[ -n "${NGC_API_KEY:-}" ]]; then
    for sname in ngc-api-key molforge-nvidia-api-key; do
      if gcloud secrets describe "${sname}" >/dev/null 2>&1; then
        if [[ "${ROTATE_NGC}" == "1" ]]; then
          printf '%s' "${NGC_API_KEY}" | gcloud secrets versions add "${sname}" --data-file=-
          ok "Rotated secret '${sname}' (new version)."
        else
          ok "Secret '${sname}' exists (use --rotate-ngc to update)."
        fi
      else
        gcloud secrets create "${sname}" --replication-policy=automatic
        printf '%s' "${NGC_API_KEY}" | gcloud secrets versions add "${sname}" --data-file=-
        ok "Created secret '${sname}'."
      fi
    done

    # Cloud Build reads ngc-api-key through `availableSecrets` to log in to
    # nvcr.io for the ESMFold base image. Neither builder identity gets
    # secretAccessor by default -- roles/cloudbuild.builds.builder does not
    # include it -- so without this the ESMFold build fails on a permission
    # error against the secret rather than anything to do with the key itself.
    # Which identity runs the build depends on project age, so grant both; the
    # binding is scoped to this one secret.
    local pnum builder
    pnum="$(gcloud projects describe "${PROJECT_ID}" --format='value(projectNumber)' 2>/dev/null || true)"
    if [[ -n "${pnum}" ]]; then
      for builder in "${pnum}@cloudbuild.gserviceaccount.com" \
                     "${pnum}-compute@developer.gserviceaccount.com"; do
        gcloud secrets add-iam-policy-binding ngc-api-key \
          --member="serviceAccount:${builder}" \
          --role=roles/secretmanager.secretAccessor >/dev/null 2>&1 \
          && ok "Cloud Build identity ${builder} can read ngc-api-key." \
          || warn "Could not grant ${builder} access to ngc-api-key (it may not exist in this project — harmless if the other one took)."
      done
    fi
  else
    warn "No NVIDIA key supplied, so molforge-nvidia-api-key was not created."
    warn "  GenMol and DiffDock are hosted NIMs and read it at runtime — without it the optimize pipeline 401s at its first step."
    warn "  Re-run: NGC_API_KEY=nvapi-… bash setup.sh --only foundation"
  fi

  # Service accounts
  ensure_sa "${GSA_NAME}" "MolForge GKE workload SA"

  # IAM — GKE workload SA: read/write artifacts; Cloud Build SA already has roles by default.
  grant "${GSA_EMAIL}" roles/storage.objectAdmin "gs://${BUCKET}"

  # One service account per Cloud Run service, each granted only what its code
  # actually calls (see the table in run_sa()). Two reasons this is not a single
  # shared account:
  #   - a shared account is the union of every service's needs, so the static
  #     nginx dashboard ends up holding the bridge's Agent Platform permissions;
  #   - MolForge is commonly installed into a project that hosts other demos,
  #     where a project-wide grant reaches buckets that are not ours. Storage is
  #     therefore bound on gs://${BUCKET} only, never project-wide.
  local svc
  for svc in a2a viewer render dashboard rdkit admet dataretr; do
    ensure_sa "$(sa_name "${svc}")" "MolForge ${svc} (Cloud Run)"
  done

  # Storage, bucket-scoped. objectViewer = get+list; objectUser also creates and
  # overwrites (render rewrites its PNG/GIF cache entries in place, and
  # data-retrieval re-caches a PDB it has already fetched once).
  grant "$(run_sa a2a)"      roles/storage.objectViewer "gs://${BUCKET}"
  grant "$(run_sa viewer)"   roles/storage.objectViewer "gs://${BUCKET}"
  grant "$(run_sa render)"   roles/storage.objectUser   "gs://${BUCKET}"
  grant "$(run_sa dataretr)" roles/storage.objectUser   "gs://${BUCKET}"
  # dashboard: static nginx bundle, no GCP API calls at all — no storage grant.
  # rdkit / admet: pure compute over SMILES in the request body, no GCS either.

  # The bridge is the only Cloud Run service that calls Agent Runtime.
  grant_project "$(run_sa a2a)" roles/aiplatform.user

  # Cloud Run does not grant these implicitly. The old shared account inherited
  # them from roles/editor, so dropping to least privilege without adding them
  # back makes a service go silent in Cloud Logging while still serving traffic
  # -- which reads as "logging is broken", not as an IAM change.
  for svc in a2a viewer render dashboard rdkit admet dataretr; do
    grant_project "$(run_sa "${svc}")" roles/logging.logWriter
    grant_project "$(run_sa "${svc}")" roles/monitoring.metricWriter
  done

  # The Agent Runtime service agent needs to read/write artifacts too.
  local proj_num; proj_num="$(gcloud projects describe "${PROJECT_ID}" --format='value(projectNumber)')"
  local re_sa="service-${proj_num}@gcp-sa-aiplatform-re.iam.gserviceaccount.com"
  gcloud storage buckets add-iam-policy-binding "gs://${BUCKET}" \
    --member="serviceAccount:${re_sa}" --role=roles/storage.objectAdmin >/dev/null 2>&1 \
    && ok "Reasoning-Engine SA granted bucket access." \
    || warn "Could not bind Reasoning-Engine SA (created lazily on first agent deploy — re-run this phase later if agents can't write artifacts)."

  # ...and to read the NVIDIA key, because the agents run AS this account. The
  # grant is on the one secret, not project-wide: this identity is shared by
  # every reasoning engine in the project, MolForge's or not.
  if gcloud secrets describe molforge-nvidia-api-key >/dev/null 2>&1; then
    gcloud secrets add-iam-policy-binding molforge-nvidia-api-key \
      --member="serviceAccount:${re_sa}" --role=roles/secretmanager.secretAccessor >/dev/null 2>&1 \
      && ok "Reasoning-Engine SA granted access to molforge-nvidia-api-key." \
      || warn "Could not grant the Reasoning-Engine SA access to molforge-nvidia-api-key (the account is created lazily on first agent deploy — re-run 'foundation' afterwards, or GenMol/DiffDock will 401)."
  fi
}

# Per-service Cloud Run identities. Keep this list and the grants in
# foundation() in step -- the whole point is that each name maps to exactly one
# service's access:
#
#   a2a        reads artifacts (list + download), calls Agent Runtime
#   viewer     reads artifacts (download + list under docking/)
#   render     reads structures, writes its own render cache
#   dataretr   caches PDBs it fetches from RCSB (writes, and overwrites)
#   rdkit      nothing -- descriptors computed from SMILES in the request body
#   admet      nothing -- predictions computed in-process
#   dashboard  nothing -- static nginx, no GCP API calls
sa_name() { printf '%s-%s-sa' "${SA_PREFIX}" "$1"; }
run_sa()  { printf '%s@%s.iam.gserviceaccount.com' "$(sa_name "$1")" "${PROJECT_ID}"; }

ensure_sa() {
  local name="$1" disp="$2" email="${1}@${PROJECT_ID}.iam.gserviceaccount.com"
  if gcloud iam service-accounts describe "${email}" >/dev/null 2>&1; then
    ok "Service account ${name} exists."
  else
    gcloud iam service-accounts create "${name}" --display-name="${disp}"
    ok "Created service account ${name}."
  fi
}

grant() {  # grant SA ROLE BUCKET  (bucket-scoped)
  gcloud storage buckets add-iam-policy-binding "$3" \
    --member="serviceAccount:$1" --role="$2" >/dev/null 2>&1 \
    && ok "Granted $2 to $1 on $3" || warn "Could not grant $2 to $1 on $3"
}
grant_project() {  # grant SA ROLE  (project-scoped)
  gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:$1" --role="$2" --condition=None >/dev/null 2>&1 \
    && ok "Granted $2 to $1 (project)" || warn "Could not grant $2 to $1"
}

# ---------------------------------------------------------------------------
# 5. GKE cluster + node pools
# ---------------------------------------------------------------------------
gke_cluster() {
  [[ "${SKIP_GPU}" == "1" ]] && { log "Skipping GKE (--skip-gpu)."; return 0; }
  phase "GKE cluster + node pools"

  echo -e "${C_YEL}This creates a GKE cluster with ONE Blackwell (g4) GPU pool, for ESMFold.${C_RESET}"
  echo -e "${C_DIM}GenMol and DiffDock are NVIDIA-hosted NIMs and need no cluster capacity.${C_RESET}"
  echo -e "${C_DIM}The pool scales to zero when idle; cost accrues only while serving.${C_RESET}"
  confirm "Create/verify the GKE cluster and GPU node pool now?" || { warn "Skipping GKE provisioning."; return 0; }

  if gcloud container clusters describe "${CLUSTER}" --region "${REGION}" >/dev/null 2>&1; then
    ok "Cluster ${CLUSTER} exists."
  else
    log "Creating regional cluster ${CLUSTER} (CPU default pool)…"
    gcloud container clusters create "${CLUSTER}" \
      --region "${REGION}" \
      --release-channel=regular \
      --workload-pool="${PROJECT_ID}.svc.id.goog" \
      --num-nodes=1 --machine-type=e2-standard-4 \
      --enable-autoscaling --min-nodes=1 --max-nodes=3 \
      --node-locations="${GKE_ZONE}"
    ok "Cluster created."
  fi

  gcloud container clusters get-credentials "${CLUSTER}" --region "${REGION}"

  # ONE GPU pool. ESMFold is the only workload that runs on local silicon --
  # GenMol and DiffDock are consumed as NVIDIA-hosted NIMs, which is what removed
  # the A100 pool (DiffDock NIM 2.2.0 has no Blackwell sm_120 build, so a
  # self-hosted DiffDock needed a second, different GPU) and the second Blackwell
  # pool with it. Keeping one scarce GPU busy with the workload that most needs
  # it beats holding three.
  ensure_pool gpu-esm  "${BLACKWELL_ZONE}" "${BLACKWELL_POOL_FLAGS}"

  # NVIDIA driver installer DaemonSet (no-op if GKE auto-installs; harmless to re-apply).
  kubectl apply -f https://raw.githubusercontent.com/GoogleCloudPlatform/container-engine-accelerators/master/nvidia-driver-installer/cos/daemonset-preloaded-latest.yaml >/dev/null 2>&1 \
    && ok "GPU driver installer applied." || warn "Driver DaemonSet apply skipped (GKE may auto-manage drivers)."
}

ensure_pool() {  # ensure_pool NAME ZONE "EXTRA_FLAGS"
  local name="$1" zone="$2" flags="$3"
  if gcloud container node-pools describe "${name}" --cluster "${CLUSTER}" --region "${REGION}" >/dev/null 2>&1; then
    ok "Node pool ${name} exists."; return 0
  fi
  log "Creating node pool ${name} in ${zone} …"
  echo -e "${C_DIM}  gcloud container node-pools create ${name} --cluster ${CLUSTER} --region ${REGION} --node-locations ${zone} ${flags} --num-nodes=0 --enable-autoscaling --min-nodes=0 --max-nodes=2${C_RESET}"
  # shellcheck disable=SC2086
  gcloud container node-pools create "${name}" \
    --cluster "${CLUSTER}" --region "${REGION}" \
    --node-locations "${zone}" \
    ${flags} \
    --num-nodes=0 --enable-autoscaling --min-nodes=0 --max-nodes=2 \
    && ok "Node pool ${name} created." \
    || die "Node pool ${name} failed — likely GPU quota/availability in ${zone}. Adjust *_POOL_FLAGS in ${CONF_FILE} or request quota, then re-run."
}

# ---------------------------------------------------------------------------
# 6. Build images (Cloud Build)
# ---------------------------------------------------------------------------
build_images() {
  phase "Build container images (Cloud Build → ${REPO_PATH})"

  # Plain images (public base) — build directly.
  build_plain admet_ai        molforge-admet-ai
  build_plain rdkit_service   molforge-rdkit
  build_plain data_retrieval  molforge-data-retrieval
  build_plain ../a2a          molforge-a2a       # a2a lives at repo root
  build_plain ../viewer       molforge-viewer
  build_render
  # NOT the dashboard: Vite bakes the bridge URL into the bundle at build time,
  # so it cannot be built until the a2a bridge exists and its URL is known.
  # build_dashboard runs from deploy_cloud_run instead.

  # NGC-base image (needs nvcr.io login via Secret Manager) — the one local
  # GPU service. GenMol and DiffDock are NOT built: both are consumed as
  # NVIDIA-hosted NIMs at health.api.nvidia.com, which is also why there is no
  # longer a services/genmol image in the deployed set.
  if [[ "${SKIP_GPU}" != "1" ]]; then
    build_ngc esmfold molforge-esmfold
  fi
}

build_plain() {  # build_plain SRC_SUBDIR IMAGE_NAME   (SRC relative to services/)
  local src="${SCRIPT_DIR}/services/$1"; [[ "$1" == ../* ]] && src="${SCRIPT_DIR}/${1#../}"
  local img="${REPO_PATH}/$2:latest"
  [[ -d "${src}" ]] || { warn "Source ${src} not found — skipping $2."; return 0; }
  log "Building $2 from ${src} …"
  # 20 minutes rather than Cloud Build's 10-minute default: admet_ai pulls
  # torch and the Chemprop model weights, which regularly runs past it.
  gcloud builds submit "${src}" --tag "${img}" --timeout=1200s \
    --gcs-log-dir="gs://${BUCKET}/_cloudbuild_logs" >/dev/null \
    && ok "Built ${img}" || die "Build failed for $2 (see Cloud Build logs)."
}

build_dashboard() {  # build_dashboard A2A_URL
  # Separate from build_plain because the dashboard needs a --build-arg, and
  # `gcloud builds submit --tag` cannot pass one. The URL is a BUILD input, not
  # a runtime one: Vite substitutes import.meta.env.VITE_A2A_URL during
  # `npm run build` and the result is a static bundle behind nginx. Setting
  # VITE_A2A_URL with `gcloud run deploy --set-env-vars` (as this script used
  # to) reaches nothing — the deployed dashboard keeps whatever URL it was
  # built with, which for a fresh clone was the reference project's bridge.
  local a2a_url="$1"
  local src="${SCRIPT_DIR}/dashboard"
  local img="${REPO_PATH}/molforge-dashboard:latest"
  [[ -d "${src}" ]] || { warn "Source ${src} not found — skipping dashboard."; return 0; }
  [[ -n "${a2a_url}" ]] || die "build_dashboard: no A2A URL — deploy the bridge first."

  local cb="${BUILD_DIR}/cloudbuild-dashboard.yaml"
  cat > "${cb}" <<'YAML'
steps:
  - name: 'gcr.io/cloud-builders/docker'
    args: ['build', '--build-arg', 'VITE_A2A_URL=${_A2A_URL}', '-t', '${_IMAGE}', '.']
images: ['${_IMAGE}']
YAML
  log "Building molforge-dashboard against ${a2a_url} …"
  gcloud builds submit "${src}" --config "${cb}" \
    --substitutions "_IMAGE=${img},_A2A_URL=${a2a_url}" \
    --gcs-log-dir="gs://${BUCKET}/_cloudbuild_logs" >/dev/null \
    && ok "Built ${img}" || die "Build failed for dashboard (see Cloud Build logs)."
}

build_render() {
  # Separate from build_plain for two reasons: the render service has TWO
  # Dockerfiles and we want the non-default one, and the PyMOL build is far too
  # slow for Cloud Build's 10-minute default timeout.
  #
  # Dockerfile.pymol installs PyMOL, which ray-traces the 3D protein/pose
  # images. `Dockerfile` (the default, and the one `--tag` would pick) has no
  # PyMOL: mol3d.py detects that and silently falls back to matplotlib, which
  # renders recognisably worse pictures. Nothing errors, so building the wrong
  # one produces a working service whose output just looks cheap.
  local src="${SCRIPT_DIR}/services/render_service"
  local img="${REPO_PATH}/molforge-render:latest"
  [[ -d "${src}" ]] || { warn "Source ${src} not found — skipping render service."; return 0; }

  # Mirrors services/render_service/cloudbuild.pymol.yaml, but parameterized on
  # REGION/AR_REPO through _IMAGE instead of hardcoding the reference
  # deployment's registry path.
  local cb="${BUILD_DIR}/cloudbuild-render.yaml"
  cat > "${cb}" <<'YAML'
steps:
  - name: 'gcr.io/cloud-builders/docker'
    args: ['build', '-f', 'Dockerfile.pymol', '-t', '${_IMAGE}', '.']
images: ['${_IMAGE}']
options:
  machineType: 'E2_HIGHCPU_8'
  diskSizeGb: 100
timeout: 2400s
YAML
  log "Building molforge-render (PyMOL base — this one takes a while) …"
  gcloud builds submit "${src}" --config "${cb}" \
    --substitutions "_IMAGE=${img}" \
    --gcs-log-dir="gs://${BUCKET}/_cloudbuild_logs" >/dev/null \
    && ok "Built ${img}" || die "Build failed for render service (see Cloud Build logs)."
}

build_ngc() {  # build_ngc SERVICE_SUBDIR IMAGE_NAME
  local src="${SCRIPT_DIR}/services/$1"
  local img="${REPO_PATH}/$2:latest"
  local secret="projects/${PROJECT_ID}/secrets/ngc-api-key/versions/latest"
  [[ -d "${src}" ]] || { warn "Source ${src} not found — skipping $2."; return 0; }

  # Generate a parameterized cloudbuild config (verbatim NGC-login idiom from the repo).
  local cb="${BUILD_DIR}/cloudbuild-$1.yaml"
  cat > "${cb}" <<'YAML'
steps:
  - name: 'gcr.io/cloud-builders/docker'
    entrypoint: 'bash'
    args: ['-c', 'echo "$$NGC_API_KEY" | docker login nvcr.io --username=\$oauthtoken --password-stdin']
    secretEnv: ['NGC_API_KEY']
  - name: 'gcr.io/cloud-builders/docker'
    args: ['build', '-t', '${_IMAGE}', '.']
images: ['${_IMAGE}']
availableSecrets:
  secretManager:
    - versionName: ${_SECRET}
      env: 'NGC_API_KEY'
options:
  machineType: 'E2_HIGHCPU_8'
  diskSizeGb: 100
# Cloud Build's default is 10 minutes. The NGC PyTorch base alone is tens of
# gigabytes, so the pull outlasts that on its own and the build gets killed
# mid-download -- reported as a timeout, which reads like a network problem.
timeout: 3600s
YAML
  log "Building $2 (NGC base) from ${src} …"
  gcloud builds submit "${src}" --config "${cb}" \
    --substitutions "_IMAGE=${img},_SECRET=${secret}" \
    --gcs-log-dir="gs://${BUCKET}/_cloudbuild_logs" >/dev/null \
    && ok "Built ${img}" || die "NGC build failed for $2 (check NGC key + Cloud Build logs)."
}

# ---------------------------------------------------------------------------
# 7. Deploy GKE workloads (manifests generated inline → kubectl apply)
# ---------------------------------------------------------------------------
deploy_gke_workloads() {
  [[ "${SKIP_GPU}" == "1" ]] && { log "Skipping GKE workloads (--skip-gpu)."; return 0; }
  phase "Deploy GKE workloads"

  gcloud container clusters get-credentials "${CLUSTER}" --region "${REGION}" >/dev/null 2>&1

  # No NGC k8s secrets. The only workload left pulls molforge-esmfold from our
  # own Artifact Registry, so there is no nvcr.io image-pull secret to create,
  # and no NIM downloads a model at runtime any more (that was DiffDock, now
  # hosted). The NGC key is still needed at BUILD time -- see build_ngc.

  # Workload Identity binding so GKE pods write to GCS as the GKE SA.
  kubectl annotate serviceaccount default \
    "iam.gke.io/gcp-service-account=${GSA_EMAIL}" --overwrite >/dev/null
  gcloud iam service-accounts add-iam-policy-binding "${GSA_EMAIL}" \
    --role=roles/iam.workloadIdentityUser \
    --member="serviceAccount:${PROJECT_ID}.svc.id.goog[default/default]" >/dev/null 2>&1 \
    && ok "Workload Identity bound (default KSA → ${GSA_NAME})." \
    || warn "WI binding may already exist."

  # Wipe the generated manifests first. ${K8S_DIR} lives in the repo and survives
  # between runs, and the apply below is a whole-directory apply -- so a manifest
  # left over from a run of an older setup.sh (genmol, diffdock, the three CPU
  # services) would be silently re-applied to the cluster.
  rm -f "${K8S_DIR}"/*.yaml

  # ESMFold is the ONLY thing on the cluster. rdkit / admet-ai / data-retrieval
  # moved to Cloud Run (they are CPU FastAPI services with no reason to hold a
  # node), GenMol and DiffDock are hosted NIMs.
  gen_gpu_manifest esmfold molforge-esmfold gpu-esm 8000 /health

  # Upgrading an older deployment? Those retired workloads are still running and
  # still holding nodes -- including `esmfold-service`, which this script now
  # deploys under the shorter name `esmfold` to match the reference cluster, so
  # the two would otherwise coexist. Removing them is your call, not the script's.
  local stale
  stale="$(kubectl get deploy -o name 2>/dev/null \
    | grep -E 'genmol-service|diffdock-service|admet-ai-service|rdkit-service|data-retrieval-service|esmfold-service' || true)"
  [[ -n "${stale}" ]] && warn "Retired workloads still on the cluster (now served elsewhere) — delete when ready:"$'\n'"${stale}"

  log "Applying manifests…"
  kubectl apply -f "${K8S_DIR}/" >/dev/null
  ok "Workload applied. (The GPU pod cold-starts in ~3–10 min while the pool scales up.)"
}

gen_gpu_manifest() {  # name image pool port health
  local name="$1" img="${REPO_PATH}/$2:latest" pool="$3" port="$4" health="$5"
  cat > "${K8S_DIR}/${name}.yaml" <<EOF
apiVersion: apps/v1
kind: Deployment
metadata: { name: ${name}, labels: { app: ${name}, molforge.provider: nvidia } }
spec:
  replicas: 1
  strategy: { type: Recreate }
  selector: { matchLabels: { app: ${name} } }
  template:
    metadata: { labels: { app: ${name}, molforge.provider: nvidia } }
    spec:
      nodeSelector: { cloud.google.com/gke-nodepool: ${pool} }
      tolerations:
      - { key: nvidia.com/gpu, operator: Exists, effect: NoSchedule }
      volumes:
      - { name: dshm, emptyDir: { medium: Memory, sizeLimit: 8Gi } }
      containers:
      - name: ${name}
        image: ${img}
        ports: [ { containerPort: ${port} } ]
        env:
        - { name: GOOGLE_CLOUD_PROJECT,       value: "${PROJECT_ID}" }
        - { name: MOLFORGE_GCS_BUCKET,        value: "${BUCKET}" }
        - { name: MOLFORGE_ARTIFACTS_BUCKET,  value: "${BUCKET}" }
        volumeMounts: [ { name: dshm, mountPath: /dev/shm } ]
        resources:
          requests: { nvidia.com/gpu: "1", cpu: "4", memory: "16Gi" }
          limits:   { nvidia.com/gpu: "1", cpu: "8", memory: "32Gi" }
        startupProbe:
          httpGet: { path: ${health}, port: ${port} }
          initialDelaySeconds: 60
          periodSeconds: 15
          failureThreshold: 80
        readinessProbe:
          httpGet: { path: ${health}, port: ${port} }
          periodSeconds: 30
---
apiVersion: v1
kind: Service
metadata: { name: ${name} }
spec:
  type: LoadBalancer
  selector: { app: ${name} }
  ports: [ { port: ${port}, targetPort: ${port} } ]
EOF
}

wait_lb_ip() {  # wait_lb_ip SERVICE_NAME  → echoes external IP
  local svc="$1" ip="" tries=0
  while [[ -z "${ip}" && ${tries} -lt 60 ]]; do
    ip="$(kubectl get svc "${svc}" -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null || true)"
    [[ -n "${ip}" ]] && break
    sleep 10; tries=$((tries+1))
  done
  echo "${ip}"
}

resolve_gke_urls() {
  [[ "${SKIP_GPU}" == "1" ]] && return 0
  phase "Resolve GKE service URLs (LoadBalancer IPs)"
  log "Waiting for the external IP (can take a couple of minutes)…"
  # One URL, because one workload. Everything else the agents call is either a
  # Cloud Run service (resolved in deploy_cloud_run) or a hosted endpoint whose
  # address is a code default we deliberately do not override.
  ESMFOLD_URL="http://$(wait_lb_ip esmfold):8000"
  [[ "${ESMFOLD_URL}" == http://:* ]] \
    && warn "ESMFOLD_URL has no IP yet — re-run phase 'agents' once it's assigned." \
    || ok "ESMFOLD_URL=${ESMFOLD_URL}"
}

# ---------------------------------------------------------------------------
# 8. Cloud Run — CPU services, viewer, render, a2a bridge, dashboard
# ---------------------------------------------------------------------------
deploy_cloud_run() {
  phase "Deploy Cloud Run services"

  # --- CPU compute services -------------------------------------------------
  # rdkit / admet-ai / data-retrieval are stateless FastAPI apps that hold no
  # GPU and no long-lived state, so they run here rather than on the cluster:
  # scale-to-zero costs nothing between demos, and it keeps the GKE cluster to
  # the single Blackwell workload it exists for.
  #
  # rdkit and admet-ai get no env at all -- both compute from the SMILES in the
  # request body and touch no bucket, which is also why their service accounts
  # carry no storage grant (see the IAM block in foundation()).
  log "Deploying rdkit…"
  gcloud run deploy molforge-rdkit \
    --image "${REPO_PATH}/molforge-rdkit:latest" \
    --region "${REGION}" --platform managed --allow-unauthenticated \
    --service-account "$(run_sa rdkit)" \
    --cpu 1 --memory 1Gi --timeout 300 \
    --port 8080 >/dev/null
  RDKIT_URL="$(gcloud run services describe molforge-rdkit --region "${REGION}" --format='value(status.url)')"
  ok "rdkit → ${RDKIT_URL}"

  # 4Gi because ADMET-AI loads its Chemprop model set into memory at import.
  log "Deploying admet-ai…"
  gcloud run deploy molforge-admet-ai \
    --image "${REPO_PATH}/molforge-admet-ai:latest" \
    --region "${REGION}" --platform managed --allow-unauthenticated \
    --service-account "$(run_sa admet)" \
    --cpu 2 --memory 4Gi --timeout 300 \
    --port 8080 >/dev/null
  ADMET_URL="$(gcloud run services describe molforge-admet-ai --region "${REGION}" --format='value(status.url)')"
  ok "admet-ai → ${ADMET_URL}"

  # This one DOES need the bucket: it caches every PDB it pulls from RCSB to
  # gs://<bucket>/structures/<id>.pdb and hands that path back to the
  # orchestrator. The default is the reference deployment's bucket name, so
  # leaving it unset writes -- or rather, fails to write -- somewhere else.
  log "Deploying data-retrieval…"
  gcloud run deploy molforge-data-retrieval \
    --image "${REPO_PATH}/molforge-data-retrieval:latest" \
    --region "${REGION}" --platform managed --allow-unauthenticated \
    --service-account "$(run_sa dataretr)" \
    --set-env-vars "GOOGLE_CLOUD_PROJECT=${PROJECT_ID},MOLFORGE_ARTIFACTS_BUCKET=${BUCKET}" \
    --cpu 1 --memory 1Gi --timeout 300 \
    --port 8080 >/dev/null
  DATARETR_URL="$(gcloud run services describe molforge-data-retrieval --region "${REGION}" --format='value(status.url)')"
  ok "data-retrieval → ${DATARETR_URL}"

  log "Deploying viewer…"
  gcloud run deploy molforge-viewer \
    --image "${REPO_PATH}/molforge-viewer:latest" \
    --region "${REGION}" --platform managed --allow-unauthenticated \
    --service-account "$(run_sa viewer)" \
    --set-env-vars "GOOGLE_CLOUD_PROJECT=${PROJECT_ID},MOLFORGE_GCS_BUCKET=${BUCKET}" \
    --port 8080 >/dev/null
  VIEWER_URL="$(gcloud run services describe molforge-viewer --region "${REGION}" --format='value(status.url)')"
  ok "viewer → ${VIEWER_URL}"

  # Render service — must exist before the bridge, whose MOLFORGE_RENDER_URL is
  # set from this URL. MOLFORGE_ARTIFACTS_BUCKET is not optional: it is both the
  # render cache destination AND mol3d.py's read allowlist, and it defaults to
  # the literal "molforge-artifacts" (the reference deployment's bucket). Left
  # unset in any other project, every 3D render is refused as an unlisted
  # bucket. 4 CPU / 4Gi is sized for PyMOL ray-tracing; a cold turntable GIF is
  # a couple of minutes of CPU, hence the explicit request timeout too.
  log "Deploying render service…"
  gcloud run deploy molforge-render \
    --image "${REPO_PATH}/molforge-render:latest" \
    --region "${REGION}" --platform managed --allow-unauthenticated \
    --service-account "$(run_sa render)" \
    --set-env-vars "GOOGLE_CLOUD_PROJECT=${PROJECT_ID},MOLFORGE_ARTIFACTS_BUCKET=${BUCKET}" \
    --cpu 4 --memory 4Gi --timeout 300 \
    --port 8080 >/dev/null
  RENDER_URL="$(gcloud run services describe molforge-render --region "${REGION}" --format='value(status.url)')"
  ok "render → ${RENDER_URL}"

  # A2A bridge — deploy first (ORCHESTRATOR_ENGINE_ID patched in phase 'agents').
  #
  # Everything after GOOGLE_CLOUD_LOCATION has a default in server.py, and every
  # one of those defaults is wrong outside the reference project — each failure
  # is silent, so they are set together rather than left to be discovered:
  #   MOLFORGE_GCS_BUCKET   defaults to "molforge-artifacts", so pipeline results
  #                         would be read from a bucket in someone else's project.
  #   MOLFORGE_VIEWER_URL   defaults to https://molforge-viewer.run.app, which is
  #                         not a real host — every viewer link would 404.
  #   MOLFORGE_A2UI         defaults to OFF, so Gemini Enterprise would get plain
  #                         text and none of the inline rendering below.
  #   MOLFORGE_RENDER_URL   defaults to empty, which disables image parts.
  # A2A_SERVER_URL has to be seeded, not just patched afterwards. server.py
  # raises at import if it is unset, so a first deploy without it never starts
  # listening, the deploy fails, and the post-deploy patch below is never
  # reached — the URL is a property of a service that cannot come up without it.
  # Break the cycle by predicting it: Cloud Run URLs are deterministic
  # (<service>-<project-number>.<region>.run.app). On a re-run the live URL is
  # authoritative instead. Either way it is reconciled against status.url below,
  # since Cloud Run may hand back the equivalent -<hash>-uc.a.run.app form.
  local pnum a2a_seed
  pnum="$(gcloud projects describe "${PROJECT_ID}" --format='value(projectNumber)')"
  a2a_seed="$(run_url molforge-a2a)"
  : "${a2a_seed:=https://molforge-a2a-${pnum}.${REGION}.run.app}"

  log "Deploying a2a bridge…"
  gcloud run deploy molforge-a2a \
    --image "${REPO_PATH}/molforge-a2a:latest" \
    --region "${REGION}" --platform managed --allow-unauthenticated \
    --service-account "$(run_sa a2a)" \
    --set-env-vars "GOOGLE_CLOUD_PROJECT=${PROJECT_ID},GOOGLE_CLOUD_LOCATION=${REGION},A2A_SERVER_URL=${a2a_seed},MOLFORGE_GCS_BUCKET=${BUCKET},MOLFORGE_VIEWER_URL=${VIEWER_URL},MOLFORGE_RENDER_URL=${RENDER_URL},MOLFORGE_A2UI=1" \
    --port 8080 >/dev/null
  A2A_URL="$(gcloud run services describe molforge-a2a --region "${REGION}" --format='value(status.url)')"
  # Reconcile the self-URL so the AgentCard advertises the address Cloud Run
  # actually assigned. No-op on re-runs, where the seed already came from here.
  if [[ "${A2A_URL}" != "${a2a_seed}" ]]; then
    gcloud run services update molforge-a2a --region "${REGION}" \
      --update-env-vars "A2A_SERVER_URL=${A2A_URL}" >/dev/null
  fi
  ok "a2a → ${A2A_URL}  (AgentCard at ${A2A_URL}/.well-known/agent.json)"

  # Built here, not in phase 'build': the bridge URL above is a build input.
  build_dashboard "${A2A_URL}"

  log "Deploying dashboard…"
  # Explicit account with no data access. Omitting --service-account falls back
  # to the Compute Engine default account, which in a shared project is a
  # broadly-privileged identity handed to a container that needs none.
  gcloud run deploy molforge-dashboard \
    --image "${REPO_PATH}/molforge-dashboard:latest" \
    --region "${REGION}" --platform managed --allow-unauthenticated \
    --service-account "$(run_sa dashboard)" \
    --port 8080 >/dev/null
  DASHBOARD_URL="$(gcloud run services describe molforge-dashboard --region "${REGION}" --format='value(status.url)')"
  ok "dashboard → ${DASHBOARD_URL}"

  # The dashboard is the only browser client of the bridge, and its origin does
  # not exist until the line above. The bridge ships with CORS off, so without
  # this patch every dashboard fetch fails preflight.
  gcloud run services update molforge-a2a --region "${REGION}" \
    --update-env-vars "MOLFORGE_CORS_ORIGINS=${DASHBOARD_URL}" >/dev/null
  ok "bridge CORS allowlist → ${DASHBOARD_URL}"
}

# ---------------------------------------------------------------------------
# 9. Agents — write .env, deploy to Agent Runtime, resolve Engine IDs (2 passes)
# ---------------------------------------------------------------------------
ensure_adk() {
  # Pin the version, and do not trust whatever `adk` happens to be on PATH.
  #
  # Both directions hurt. google-adk 2.2.0 deploys an engine that then reports
  # "failed to start and cannot serve traffic" — the agent builds fine, the
  # runtime just never boots. Older CLIs fail the other way: 1.20.0 rejects the
  # repo-root invocation deploy_agent uses with "Please deploy from the project
  # dir", so the deploy dies before it starts. This used to accept any ambient
  # adk and otherwise pip-install unpinned, i.e. it picked one of those two
  # failures depending on the machine.
  #
  # This pins the CLI doing the deploying. The version the engine RUNS is
  # whatever each agent's requirements.txt pins — pin both, they are separate.
  local found=""
  command -v adk >/dev/null 2>&1 && found="$(adk --version 2>/dev/null | head -1)"
  [[ "${found}" == *"${ADK_VERSION}"* ]] && return 0

  if [[ -x "${BUILD_DIR}/venv/bin/adk" ]] \
     && "${BUILD_DIR}/venv/bin/adk" --version 2>/dev/null | grep -q "${ADK_VERSION}"; then
    # shellcheck disable=SC1091
    source "${BUILD_DIR}/venv/bin/activate"
    ok "Using pinned google-adk ${ADK_VERSION} from ${BUILD_DIR}/venv."
    return 0
  fi

  log "Installing google-adk==${ADK_VERSION} into a venv (on PATH: ${found:-none})…"
  python3 -m venv "${BUILD_DIR}/venv"
  # shellcheck disable=SC1091
  source "${BUILD_DIR}/venv/bin/activate"
  pip install --quiet --upgrade pip
  pip install --quiet "google-adk==${ADK_VERSION}" \
    "google-cloud-aiplatform[agent_engines]==${ADK_VERSION}"
  ok "google-adk ${ADK_VERSION} installed."
}

run_url() {  # run_url SERVICE  → echoes the Cloud Run URL, or empty
  gcloud run services describe "$1" --region "${REGION}" \
    --format='value(status.url)' 2>/dev/null || true
}

resolve_service_urls() {
  # Re-derive anything deploy_cloud_run would have set, so that `--only agents`
  # is a legitimate standalone entry point. Without this, a targeted re-run
  # writes `MOLFORGE_RDKIT_URL=` into the .env -- and an empty-but-SET variable
  # beats the code default in os.getenv(), so the agent deploys clean and then
  # fails every call at runtime. Cheap describes; skipped if already known.
  : "${RDKIT_URL:=$(run_url molforge-rdkit)}"
  : "${ADMET_URL:=$(run_url molforge-admet-ai)}"
  : "${DATARETR_URL:=$(run_url molforge-data-retrieval)}"
  : "${VIEWER_URL:=$(run_url molforge-viewer)}"
  : "${RENDER_URL:=$(run_url molforge-render)}"
  if [[ "${SKIP_GPU}" != "1" && -z "${ESMFOLD_URL:-}" ]]; then
    gcloud container clusters get-credentials "${CLUSTER}" --region "${REGION}" >/dev/null 2>&1 \
      && ESMFOLD_URL="http://$(wait_lb_ip esmfold):8000"
    [[ "${ESMFOLD_URL:-}" == http://:* ]] && ESMFOLD_URL=""
  fi
  local v required=(RDKIT_URL ADMET_URL DATARETR_URL VIEWER_URL)
  [[ "${SKIP_GPU}" != "1" ]] && required+=(ESMFOLD_URL)
  for v in "${required[@]}"; do
    [[ -z "${!v:-}" ]] && warn "${v} is unresolved — the agents will be deployed without it, and the calls that need it will fail. Run the 'run'/'gke-workloads' phases first."
  done
  return 0
}

write_env() {  # write_env DIR  k=v ...
  local dir="$1"; shift
  : > "${dir}/.env"
  printf 'GOOGLE_GENAI_USE_VERTEXAI=1\n' >> "${dir}/.env"
  printf 'GOOGLE_CLOUD_PROJECT=%s\n'  "${PROJECT_ID}" >> "${dir}/.env"
  printf 'GOOGLE_CLOUD_LOCATION=%s\n' "${REGION}"     >> "${dir}/.env"
  # Both spellings, in every agent. The codebase reads the artifacts bucket under
  # two names -- tools/artifacts.py wants MOLFORGE_GCS_BUCKET, while diffdock.py
  # and esmfold.py want MOLFORGE_ARTIFACTS_BUCKET -- and both default to the
  # literal "molforge-artifacts". Setting only one leaves the other pointing at
  # the reference deployment's bucket, which in a fresh project fails as a
  # permission error from a bucket name the operator never chose. Writing both
  # here is cheaper than making every caller agree.
  printf 'MOLFORGE_GCS_BUCKET=%s\n'       "${BUCKET}" >> "${dir}/.env"
  printf 'MOLFORGE_ARTIFACTS_BUCKET=%s\n' "${BUCKET}" >> "${dir}/.env"
  # Skip k=v pairs with an empty value: writing `KEY=` is not the same as leaving
  # KEY unset. os.getenv("KEY", default) hands back "" for the former, so an empty
  # line here overrides the code default with something guaranteed not to work.
  local kv
  for kv in "$@"; do
    [[ "${kv#*=}" == "" ]] && continue
    printf '%s\n' "${kv}" >> "${dir}/.env"
  done
}

engine_id_by_name() {  # echo numeric engine id for a display name, or empty
  local disp="$1"
  curl -s -H "Authorization: Bearer $(gcloud auth print-access-token)" \
    "https://${REGION}-aiplatform.googleapis.com/v1/projects/${PROJECT_ID}/locations/${REGION}/reasoningEngines" \
    | jq -r --arg d "${disp}" '.reasoningEngines[]? | select(.displayName==$d) | .name' \
    | head -1 | grep -oE '[0-9]+$' || true
}

deploy_agent() {  # deploy_agent DIR "Display Name"  → echoes engine id
  local dir="$1" disp="$2"
  local existing; existing="$(engine_id_by_name "${disp}")"
  if [[ -n "${existing}" ]]; then
    ok "Agent '${disp}' already deployed (engine ${existing}); .env refreshed, skipping redeploy." >&2
    echo "${existing}"; return 0
  fi
  log "Deploying '${disp}' to Agent Runtime…" >&2
  ( cd "${SCRIPT_DIR}" && adk deploy agent_engine "${dir}" \
      --display_name "${disp}" --project "${PROJECT_ID}" --region "${REGION}" ) \
      > "${LOG_DIR}/deploy-$(basename "${dir}").log" 2>&1 || { err "adk deploy failed for ${disp}; see ${LOG_DIR}/deploy-$(basename "${dir}").log"; return 1; }
  local id; id="$(grep -oE 'reasoningEngines/[0-9]+' "${LOG_DIR}/deploy-$(basename "${dir}").log" | grep -oE '[0-9]+' | head -1)"
  [[ -z "${id}" ]] && id="$(engine_id_by_name "${disp}")"
  [[ -n "${id}" ]] && { ok "Deployed '${disp}' → engine ${id}" >&2; echo "${id}"; } || { err "Could not determine engine ID for ${disp}"; return 1; }
}

deploy_agents() {
  phase "Deploy agents to Agent Runtime"
  ensure_adk
  resolve_service_urls

  # Specialists first — they have no circular deps.
  #
  # No MOLFORGE_GENMOL_URL / MOLFORGE_DIFFDOCK_URL here, deliberately. Both tools
  # default to the NVIDIA-hosted NIMs at health.api.nvidia.com, which is where we
  # want them; setting either variable points the agent at a self-hosted NIM
  # instead. (DiffDock in particular needs MOLFORGE_DIFFDOCK_PATH set to match, so
  # a half-set override is worse than none.) Authentication for the hosted calls
  # is the molforge-nvidia-api-key secret, read at runtime -- never written here.
  write_env "${SCRIPT_DIR}/agents/lead_optimizer" \
    "MOLFORGE_ESMFOLD_URL=${ESMFOLD_URL:-}" \
    "MOLFORGE_RDKIT_URL=${RDKIT_URL:-}" \
    "MOLFORGE_VIEWER_URL=${VIEWER_URL:-}"
  write_env "${SCRIPT_DIR}/agents/admet_safety_agent" \
    "MOLFORGE_ADMET_AI_URL=${ADMET_URL:-}" \
    "MOLFORGE_RDKIT_URL=${RDKIT_URL:-}" \
    "MOLFORGE_VIEWER_URL=${VIEWER_URL:-}"

  LEAD_ID="$(deploy_agent agents/lead_optimizer    'MolForge Lead Optimizer')"
  # "… Agent" is not decoration: deploy_agent finds an existing engine by exact
  # displayName match, so a name that differs from the one cloudbuild-subagents
  # deploys under makes the lookup miss and deploys a duplicate engine beside it.
  ADMET_ID="$(deploy_agent agents/admet_safety_agent 'MolForge ADMET Safety Agent')"

  # Orchestrator depends on the two specialist Engine IDs.
  write_env "${SCRIPT_DIR}/agents/orchestrator" \
    "LEAD_OPTIMIZER_ENGINE_ID=${LEAD_ID}" \
    "ADMET_SAFETY_ENGINE_ID=${ADMET_ID}" \
    "MOLFORGE_DATA_RETRIEVAL_URL=${DATARETR_URL:-}" \
    "MOLFORGE_VIEWER_URL=${VIEWER_URL:-}" \
    "PHARMAPILOT_A2A_URL=${PHARMAPILOT_A2A_URL:-}"
  ORCH_ID="$(deploy_agent agents/orchestrator 'MolForge Orchestrator')"

  # Wire the orchestrator Engine ID into the live A2A bridge.
  if [[ -n "${ORCH_ID:-}" ]]; then
    gcloud run services update molforge-a2a --region "${REGION}" \
      --update-env-vars "ORCHESTRATOR_ENGINE_ID=${ORCH_ID}" >/dev/null
    ok "A2A bridge wired to orchestrator engine ${ORCH_ID}."
  fi

  command -v deactivate >/dev/null 2>&1 && deactivate || true
}

# ---------------------------------------------------------------------------
# 10. Gemini Enterprise registration (best-effort via Discovery Engine API)
# ---------------------------------------------------------------------------
register_gemini_enterprise() {
  phase "Gemini Enterprise — app + A2A agent registration (best-effort)"
  local token; token="$(gcloud auth print-access-token)"
  local base="https://discoveryengine.googleapis.com/v1alpha"
  local parent="projects/${PROJECT_ID}/locations/${GE_LOCATION}/collections/default_collection"
  local card="${A2A_URL:-}/.well-known/agent.json"

  # 1) Ensure the Agentspace/Gemini Enterprise app (engine) exists.
  local eng_url="${base}/${parent}/engines/${GE_APP_ID}"
  if curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer ${token}" "${eng_url}" | grep -q '^200$'; then
    ok "Gemini Enterprise app '${GE_APP_ID}' already exists."
  else
    log "Creating Gemini Enterprise app '${GE_APP_ID}'…"
    curl -s -X POST -H "Authorization: Bearer ${token}" -H "Content-Type: application/json" \
      -H "X-Goog-User-Project: ${PROJECT_ID}" \
      "${base}/${parent}/engines?engineId=${GE_APP_ID}" \
      -d "{\"displayName\":\"${GE_APP_NAME}\",\"solutionType\":\"SOLUTION_TYPE_CHAT\",\"chatEngineConfig\":{\"agentCreationConfig\":{\"business\":\"${GE_APP_NAME}\"}}}" \
      > "${LOG_DIR}/ge-app.json" 2>&1
    if jq -e '.name' "${LOG_DIR}/ge-app.json" >/dev/null 2>&1; then
      ok "Created GE app '${GE_APP_ID}'."
    else
      warn "GE app create did not confirm (API is alpha/region-gated). Response: $(head -c 300 "${LOG_DIR}/ge-app.json")"
    fi
  fi

  # 2) Register the A2A agent against the app, pointing at the AgentCard.
  if [[ -n "${A2A_URL:-}" ]]; then
    log "Registering A2A agent (card: ${card})…"
    curl -s -X POST -H "Authorization: Bearer ${token}" -H "Content-Type: application/json" \
      -H "X-Goog-User-Project: ${PROJECT_ID}" \
      "${base}/${parent}/engines/${GE_APP_ID}/assistants/default_assistant/agents" \
      -d "{\"displayName\":\"${GE_APP_NAME}\",\"description\":\"MolForge agentic drug discovery\",\"a2aAgentDefinition\":{\"jsonAgentCard\":\"\",\"agentCardUri\":\"${card}\"}}" \
      > "${LOG_DIR}/ge-agent.json" 2>&1
    if jq -e '.name' "${LOG_DIR}/ge-agent.json" >/dev/null 2>&1; then
      ok "A2A agent registered in Gemini Enterprise."
    else
      warn "Automated agent registration didn't confirm — finish it in the console (steps below)."
      print_ge_manual_steps "${card}"
    fi
  else
    warn "No A2A URL available; skipping GE agent registration."
  fi
}

print_ge_manual_steps() {
  local card="$1"
  cat <<EOF

${C_BOLD}Manual Gemini Enterprise wiring (if the API step didn't fully apply):${C_RESET}
  1. Console → AI Applications / Agentspace → your app '${GE_APP_NAME}'.
  2. Agents → Add agent → "A2A agent".
  3. Agent card URL:  ${card}
  4. Authentication: public (prototype) or attach the A2A bridge service account.
  5. Save, then test from the GE chat:  "Optimize Imatinib for KIT D816V mutation".
EOF
}

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
summary() {
  phase "Done — MolForge endpoints"
  echo -e "${C_BOLD}Project${C_RESET}        ${PROJECT_ID}  (${REGION})"
  echo -e "${C_BOLD}Bucket${C_RESET}         gs://${BUCKET}"
  echo -e "${C_BOLD}Viewer${C_RESET}         ${VIEWER_URL:-n/a}"
  echo -e "${C_BOLD}Render${C_RESET}         ${RENDER_URL:-n/a}"
  echo -e "${C_BOLD}RDKit${C_RESET}          ${RDKIT_URL:-n/a}"
  echo -e "${C_BOLD}ADMET-AI${C_RESET}       ${ADMET_URL:-n/a}"
  echo -e "${C_BOLD}Data retrieval${C_RESET} ${DATARETR_URL:-n/a}"
  echo -e "${C_BOLD}A2A bridge${C_RESET}     ${A2A_URL:-n/a}"
  echo -e "${C_BOLD}AgentCard${C_RESET}      ${A2A_URL:-n/a}/.well-known/agent.json"
  echo -e "${C_BOLD}Dashboard${C_RESET}      ${DASHBOARD_URL:-n/a}"
  echo -e "${C_BOLD}Orchestrator${C_RESET}   engine ${ORCH_ID:-n/a}"
  echo -e "${C_BOLD}Lead Optimizer${C_RESET} engine ${LEAD_ID:-n/a}"
  echo -e "${C_BOLD}ADMET Safety${C_RESET}   engine ${ADMET_ID:-n/a}"
  if [[ "${SKIP_GPU}" != "1" ]]; then
    echo -e "${C_BOLD}ESMFold${C_RESET}        ${ESMFOLD_URL:-pending}  ${C_DIM}(GKE, Blackwell)${C_RESET}"
  fi
  echo -e "${C_BOLD}GenMol${C_RESET}         ${C_DIM}NVIDIA-hosted NIM (health.api.nvidia.com)${C_RESET}"
  echo -e "${C_BOLD}DiffDock${C_RESET}       ${C_DIM}NVIDIA-hosted NIM (health.api.nvidia.com)${C_RESET}"
  echo
  ok "Re-run any phase with:  bash setup.sh --only <phase>"
  echo -e "${C_DIM}phases: apis foundation gke build gke-workloads gke-urls run agents ge${C_RESET}"
}

# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
run_phase() {
  case "$1" in
    apis)          enable_apis ;;
    foundation)    foundation ;;
    gke)           gke_cluster ;;
    build)         build_images ;;
    gke-workloads) deploy_gke_workloads ;;
    gke-urls)      resolve_gke_urls ;;
    run)           deploy_cloud_run ;;
    agents)        deploy_agents ;;
    ge)            register_gemini_enterprise ;;
    *) die "Unknown phase '$1'. Valid: apis foundation gke build gke-workloads gke-urls run agents ge" ;;
  esac
}

main() {
  show_prerequisites
  collect_params
  preflight

  if [[ -n "${ONLY_PHASE}" ]]; then
    run_phase "${ONLY_PHASE}"
    exit 0
  fi

  enable_apis
  foundation
  gke_cluster
  build_images
  deploy_gke_workloads
  resolve_gke_urls
  deploy_cloud_run
  deploy_agents
  register_gemini_enterprise
  summary
}

main "$@"
