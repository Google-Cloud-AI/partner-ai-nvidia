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

"""ADMET field mapping contract.

The service publishes named properties backed by ADMET-AI models. Two published
fields backed by the SAME model means one of them reports a property that was
never predicted -- the failure that shipped `pgp_substrate` as an alias of
Pgp_Broccatelli and `bioavailability_f30` as an alias of Bioavailability_Ma.
A chemist saw four numbers where the model produced two, and Nemotron wrote a
safety narrative over them.

These tests pin the mapping, and pin the viewer and agent docstring to it, since
the fiction reached the user through those layers.
"""
import collections
import importlib.util
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SERVICE_APP = REPO_ROOT / "services" / "admet_ai" / "app.py"
VIEWER_MAP = REPO_ROOT / "viewer" / "src" / "lib" / "admetMappings.js"
AGENT_TOOL = REPO_ROOT / "agents" / "admet_safety_agent" / "tools" / "admet_predict.py"

# Models ADMET-AI actually exposes, captured from the deployed service
# (POST /predict returns every raw key in `drugbank_percentiles`).
# Refresh this if the ADMET-AI version changes.
ADMET_AI_MODELS = frozenset({
    "AMES", "BBB_Martins", "BRENK_alert", "Bioavailability_Ma", "CYP1A2_Veith",
    "CYP2C19_Veith", "CYP2C9_Substrate_CarbonMangels", "CYP2C9_Veith",
    "CYP2D6_Substrate_CarbonMangels", "CYP2D6_Veith",
    "CYP3A4_Substrate_CarbonMangels", "CYP3A4_Veith", "Caco2_Wang",
    "Carcinogens_Lagunin", "Clearance_Hepatocyte_AZ", "Clearance_Microsome_AZ",
    "ClinTox", "DILI", "HIA_Hou", "Half_Life_Obach",
    "HydrationFreeEnergy_FreeSolv", "LD50_Zhu", "Lipinski",
    "Lipophilicity_AstraZeneca", "NIH_alert", "NR-AR", "NR-AR-LBD", "NR-AhR",
    "NR-Aromatase", "NR-ER", "NR-ER-LBD", "NR-PPAR-gamma", "PAINS_alert",
    "PAMPA_NCATS", "PPBR_AZ", "Pgp_Broccatelli", "QED", "SR-ARE", "SR-ATAD5",
    "SR-HSE", "SR-MMP", "SR-p53", "Skin_Reaction", "Solubility_AqSolDB",
    "VDss_Lombardo", "hERG", "hydrogen_bond_acceptors", "hydrogen_bond_donors",
    "logP", "molecular_weight", "stereo_centers", "tpsa",
})


def _load_field_map():
    """Import the service module by path (it is not an installed package)."""
    spec = importlib.util.spec_from_file_location("molforge_admet_app", SERVICE_APP)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.ADMET_FIELD_MAP


FIELD_MAP = _load_field_map()
FLAT = {field: model for fields in FIELD_MAP.values() for field, model in fields.items()}


def test_no_two_fields_share_a_model():
    """The core invariant. One published property per underlying model."""
    counts = collections.Counter(FLAT.values())
    shared = {model: n for model, n in counts.items() if n > 1}
    assert not shared, (
        f"fields aliased onto the same model: {shared}. Each published property "
        "must come from its own model, or it reports a prediction that was never made."
    )


def test_every_field_name_is_unique():
    flat_pairs = [f for fields in FIELD_MAP.values() for f in fields]
    assert len(flat_pairs) == len(set(flat_pairs))


def test_every_mapped_model_exists_in_admet_ai():
    """Guards against typos and against inventing a model that does not exist."""
    unknown = sorted(set(FLAT.values()) - ADMET_AI_MODELS)
    assert not unknown, f"mapped models absent from ADMET-AI: {unknown}"


@pytest.mark.parametrize("phantom", ["pgp_substrate", "bioavailability_f30"])
def test_known_phantom_fields_stay_gone(phantom):
    """ADMET-AI has no P-gp substrate model and no F30 model."""
    assert phantom not in FLAT


def test_viewer_endpoint_keys_match_the_service():
    """The viewer renders one card per key; a key the service stopped emitting
    would render as an empty card, and one it emits but the viewer lacks is
    silently dropped from the chemist's view."""
    js = VIEWER_MAP.read_text()
    viewer_keys = set(re.findall(r"\{\s*key:\s*'([^']+)'", js))
    service_keys = set(FLAT)
    assert viewer_keys == service_keys, (
        f"viewer-only: {sorted(viewer_keys - service_keys)}; "
        f"service-only: {sorted(service_keys - viewer_keys)}"
    )


def test_viewer_percentile_keys_match_the_service_models():
    js = VIEWER_MAP.read_text()
    pairs = re.findall(r"\{\s*key:\s*'([^']+)'.*?percentileKey:\s*'([^']+)'", js)
    mismatched = {k: (v, FLAT[k]) for k, v in pairs if k in FLAT and v != FLAT[k]}
    assert not mismatched, f"viewer points at a different model than the service: {mismatched}"


def test_agent_docstring_documents_exactly_the_published_fields():
    """The docstring is the tool contract the LLM reads. When it described
    pgp_substrate as a distinct property, that is what reached the chemist."""
    doc = AGENT_TOOL.read_text()
    documented = set(re.findall(r"^\s+- (\w+):", doc, re.MULTILINE))
    missing = set(FLAT) - documented
    assert not missing, f"published but undocumented for the LLM: {sorted(missing)}"
    for phantom in ("pgp_substrate", "bioavailability_f30"):
        assert phantom not in documented, f"docstring still promises {phantom}"
