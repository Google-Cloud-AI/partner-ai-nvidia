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

"""Nemotron prompt payload budgets.

Both narrative tools used to slice `str(payload)` at a fixed byte offset while
the prompt header still announced the full molecule/candidate count. The safety
report fit ~1.4 molecules in 8000 chars, so a five-molecule screen asked
Nemotron for five traffic-light verdicts -- including KILL -- while showing it
one and a fragment. Nothing logged, nothing surfaced.

The rule these tests pin: drop WHOLE records, never a partial one, and always
tell both the model and the caller what was dropped.
"""
import pytest

from admet_safety_agent.tools import report_gen
from lead_optimizer.tools import sar_analysis

MODELS = ["Caco2_Wang", "HIA_Hou", "Pgp_Broccatelli", "hERG", "AMES", "DILI"]


def _molecule(smiles):
    """An ADMET result shaped like the service's response."""
    return {
        "smiles": smiles,
        "absorption": {"caco2_permeability": -4.7, "hia": 0.98, "pgp_inhibitor": 0.81},
        "toxicity": {"herg_inhibitor": 0.42, "ames_mutagenicity": 0.11, "dili": 0.35},
        "drugbank_percentiles": {
            **{m: 0.5 for m in MODELS},
            **{f"{m}_drugbank_approved_percentile": 61.2 for m in MODELS},
        },
    }


def _candidate(smiles, score=-8.4):
    return {
        "smiles": smiles,
        "binding_score": score,
        "binding_confidence": -1.23,
        "pose_path": f"gs://molforge-artifacts/docking/dock_x/{smiles}.sdf",
        "properties": {"smiles": smiles, "molecular_weight": 493.6, "logp": 3.5, "qed": 0.46},
    }


# --- shared invariant: no partial records ------------------------------------

@pytest.mark.parametrize(
    "fmt,make",
    [
        (report_gen._format_screening_data, _molecule),
        (sar_analysis._format_candidates, _candidate),
    ],
    ids=["admet", "sar"],
)
def test_tight_budget_drops_whole_records_not_bytes(fmt, make):
    items = [make(f"C{'C' * i}O") for i in range(8)]
    text, omitted = fmt(items, budget=400)

    assert omitted, "a 400-char budget must force omissions"
    # Every record that survived is intact: one header line per rendered record,
    # and no record header appears without its body.
    headers = [l for l in text.splitlines() if not l.startswith("  ")]
    assert len(headers) == len(items) - len(omitted)
    for line in text.splitlines():
        assert line.strip(), "no blank/garbled fragment lines"


@pytest.mark.parametrize(
    "fmt,make",
    [
        (report_gen._format_screening_data, _molecule),
        (sar_analysis._format_candidates, _candidate),
    ],
    ids=["admet", "sar"],
)
def test_nothing_omitted_when_everything_fits(fmt, make):
    items = [make("CCO"), make("CCN"), make("CCC")]
    text, omitted = fmt(items, budget=1_000_000)
    assert omitted == []
    for item in items:
        assert item["smiles"] in text


@pytest.mark.parametrize(
    "fmt,make",
    [
        (report_gen._format_screening_data, _molecule),
        (sar_analysis._format_candidates, _candidate),
    ],
    ids=["admet", "sar"],
)
def test_omitted_records_are_named_and_absent(fmt, make):
    items = [make(f"C{'C' * i}O") for i in range(8)]
    text, omitted = fmt(items, budget=400)
    rendered = {l.split(": ", 1)[1] for l in text.splitlines() if not l.startswith("  ")}
    assert set(omitted).isdisjoint(rendered), "an omitted record must not also be rendered"
    assert len(rendered) + len(omitted) == len(items), "every record is either rendered or reported"


@pytest.mark.parametrize(
    "fmt,make",
    [
        (report_gen._format_screening_data, _molecule),
        (sar_analysis._format_candidates, _candidate),
    ],
    ids=["admet", "sar"],
)
def test_one_oversized_record_still_renders(fmt, make):
    """Better to send one big record than an empty prompt."""
    text, omitted = fmt([make("CCO")], budget=1)
    assert "CCO" in text
    assert omitted == []


# --- ADMET-specific -----------------------------------------------------------

def test_admet_drops_the_duplicated_raw_percentile_keys():
    """`drugbank_percentiles` carries every value twice -- once under the model
    name, once under the percentile name. Only the percentiles belong here; the
    raw values are already printed per field."""
    text = report_gen._format_molecule(1, _molecule("CCO"))
    assert "Caco2_Wang=61.2" in text
    assert "Caco2_Wang=0.5" not in text, "raw duplicate leaked back into the prompt"


def test_admet_categories_are_read_off_the_record():
    """A new category added to the service must appear without editing this tool."""
    mol = _molecule("CCO")
    mol["excretion"] = {"half_life": 3.2}
    assert "excretion: half_life=3.2" in report_gen._format_molecule(1, mol)


def test_admet_failed_prediction_is_marked_not_silently_blank():
    text = report_gen._format_molecule(2, {"smiles": "bad", "error": "Invalid SMILES"})
    assert "PREDICTION FAILED" in text and "Invalid SMILES" in text


def test_admet_payload_is_materially_smaller_than_the_repr():
    mol = _molecule("CCO")
    assert len(report_gen._format_molecule(1, mol)) < len(str(mol)) / 2


# --- SAR-specific -------------------------------------------------------------

def test_sar_flags_candidates_with_no_evidence():
    """Docking is non-fatal in the pipeline, so a candidate can arrive bare.
    The model must be told, not left to infer a rank from silence."""
    text = sar_analysis._format_candidate(1, {"smiles": "CCO"})
    assert "do not rank on absent evidence" in text


def test_sar_keeps_binding_score_of_zero():
    """0.0 is a real score; a truthiness check would drop it."""
    text = sar_analysis._format_candidate(1, _candidate("CCO", score=0.0))
    assert "binding_score: 0.0" in text


def test_sar_zero_score_without_properties_is_not_called_evidence_free():
    """The no-evidence warning must key off absence, not falsiness."""
    text = sar_analysis._format_candidate(1, {"smiles": "CCO", "binding_score": 0.0})
    assert "binding_score: 0.0" in text
    assert "absent evidence" not in text
