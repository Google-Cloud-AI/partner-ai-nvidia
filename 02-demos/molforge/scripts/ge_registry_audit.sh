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

# ge_registry_audit.sh — List MolForge's Gemini Enterprise A2A agent registrations,
# flag stale/duplicate entries, and print ready-to-run DELETE commands.
#
# READ-ONLY by default. It NEVER deletes anything itself — it prints the delete
# commands for you to review and run. This is deliberate: the GE registry is
# customer-facing shared state.
#
# Auth note: the Discovery Engine API rejects domain-restricted corp tokens
# (ACCESS_TOKEN_TYPE_UNSUPPORTED). Run this from Cloud Shell, or with a
# project-scoped identity that has discoveryengine.* + serviceusage.services.use.
#
# Usage:  bash scripts/ge_registry_audit.sh
set -euo pipefail

# Falls back to the active gcloud project rather than a hardcoded one: this
# script only ever reads/report on the registry of whatever project you are
# pointed at, so silently defaulting to somebody else's is the wrong answer.
PROJECT_ID="${PROJECT_ID:-$(gcloud config get-value project 2>/dev/null)}"
[[ -n "${PROJECT_ID}" && "${PROJECT_ID}" != "(unset)" ]] || {
  echo "PROJECT_ID is unset and no active gcloud project is configured." >&2
  echo "Run: gcloud config set project <your-project>   (or PROJECT_ID=… bash $0)" >&2
  exit 1
}
GE_LOCATION="${GE_LOCATION:-global}"
GE_APP_ID="${GE_APP_ID:-molforge}"
ASSISTANT="${ASSISTANT:-default_assistant}"
# The AgentCard URL the registry SHOULD point at (the live bridge). Entries
# pointing anywhere else are stale and get flagged.
# Resolved from Cloud Run rather than hardcoded — the bridge URL embeds the
# project number, so a literal here silently made the audit compare every
# registry entry against a different deployment's card and flag them all stale.
if [[ -z "${EXPECTED_CARD:-}" ]]; then
  _a2a_url="$(gcloud run services describe molforge-a2a \
      --project "${PROJECT_ID}" --region "${A2A_REGION:-us-central1}" \
      --format='value(status.url)' 2>/dev/null)"
  [[ -n "${_a2a_url}" ]] || {
    echo "Could not resolve the molforge-a2a Cloud Run URL in ${PROJECT_ID}." >&2
    echo "Set it explicitly: EXPECTED_CARD=https://…/.well-known/agent.json bash $0" >&2
    exit 1
  }
  EXPECTED_CARD="${_a2a_url}/.well-known/agent.json"
fi

BASE="https://discoveryengine.googleapis.com/v1alpha"
PARENT="projects/${PROJECT_ID}/locations/${GE_LOCATION}/collections/default_collection"
AGENTS_URL="${BASE}/${PARENT}/engines/${GE_APP_ID}/assistants/${ASSISTANT}/agents"

TOKEN="$(gcloud auth print-access-token)"

resp="$(curl -s -H "Authorization: Bearer ${TOKEN}" \
             -H "X-Goog-User-Project: ${PROJECT_ID}" \
             "${AGENTS_URL}")"

echo "$resp" | python3 - "$EXPECTED_CARD" "$BASE" "$TOKEN" "$PROJECT_ID" <<'PY'
import sys, json
resp = json.load(sys.stdin)
expected_card, base, token, project = sys.argv[1:5]

if "error" in resp:
    e = resp["error"]
    print(f"ERROR {e.get('code')}: {e.get('message','')[:300]}")
    sys.exit(1)

agents = resp.get("agents", [])
print(f"\n{len(agents)} agent(s) registered in the '{project}' GE app:\n")

def card_uri(a):
    return a.get("a2aAgentDefinition", {}).get("agentCardUri", "")

# Group by (displayName, agentCardUri) to find duplicates.
seen = {}
rows = []
for a in agents:
    name = a["name"]                       # full resource path (…/agents/<id>)
    aid = name.split("/")[-1]
    disp = a.get("displayName", "?")
    card = card_uri(a)
    updated = a.get("updateTime", a.get("createTime", ""))
    rows.append((updated, aid, disp, card, name))

rows.sort(reverse=True)  # newest first
for updated, aid, disp, card, name in rows:
    flags = []
    if card and card != expected_card:
        flags.append("STALE-CARD-URL")
    key = (disp, card)
    seen.setdefault(key, []).append((updated, name, aid))
    flag = ("  <-- " + ", ".join(flags)) if flags else ""
    print(f"  • {aid}  | {disp}")
    print(f"      card:    {card or '(none)'}{flag}")
    print(f"      updated: {updated or '?'}")

# Build delete list: duplicates (keep newest of each dup group) + stale-card entries.
to_delete = []
for key, entries in seen.items():
    entries.sort(reverse=True)
    # Keep the newest of each (displayName, card) group; mark the rest as dup deletes.
    for updated, name, aid in entries[1:]:
        to_delete.append((name, aid, "duplicate of newer entry"))
for updated, aid, disp, card, name in rows:
    if card and card != expected_card:
        if not any(n == name for n, *_ in to_delete):
            to_delete.append((name, aid, "stale agentCardUri"))

print("\n" + "=" * 60)
if not to_delete:
    print("No stale or duplicate registrations detected. Registry is clean. ✅")
else:
    print(f"{len(to_delete)} entry(ies) recommended for removal.")
    print("Review, then run the matching DELETE(s):\n")
    for name, aid, reason in to_delete:
        print(f"  # {aid} — {reason}")
        print(f"  curl -s -X DELETE -H \"Authorization: Bearer $(gcloud auth print-access-token)\" \\")
        print(f"       -H \"X-Goog-User-Project: {project}\" \\")
        print(f"       \"{base}/{name}\"\n")
PY
