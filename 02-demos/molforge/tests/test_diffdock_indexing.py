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

"""DiffDock batch response mapping.

Blank SMILES are dropped from the request, so the NIM's response arrays are
indexed by position in the FILTERED list. Walking the caller's unfiltered list
against that response pairs each ligand after a blank with the NEXT ligand's
pose and confidence -- silently, with no error, and the wrong score then flows
into the SAR ranking. These tests pin the mapping.
"""
import pytest

from lead_optimizer.tools import diffdock

# Minimal single-chain protein; dock_molecules accepts inline PDB content.
STUB_PDB = "\n".join([
    "ATOM      1  N   ALA A   1      11.104   6.134  -6.504  1.00 20.00           N",
    "ATOM      2  CA  ALA A   1      11.639   6.071  -5.147  1.00 20.00           C",
    "ATOM      3  C   ALA A   1      12.000   5.000  -5.000  1.00 20.00           C",
    "ATOM      4  CA  GLY A   2      13.000   7.000  -4.000  1.00 20.00           C",
])


@pytest.fixture
def stub_nim(monkeypatch):
    """Stub the NIM call and GCS writes; capture what was actually submitted."""
    sent = {}

    class FakeResponse:
        status_code = 200

        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

        def raise_for_status(self):
            return None

        @property
        def text(self):
            return str(self._payload)

    def fake_post(url, **kwargs):
        payload = kwargs.get("json") or {}
        sent["ligand"] = payload.get("ligand", "")
        ligands = [l for l in sent["ligand"].split("\n") if l.strip()]
        # One pose + one confidence per ligand actually submitted. The
        # confidence encodes the ligand so a mis-pairing is unambiguous.
        return FakeResponse({
            "status": "success",
            "ligand_positions": [[f"SDF::{lig}"] for lig in ligands],
            "position_confidence": [[-1.0 - i] for i, _ in enumerate(ligands)],
        })

    monkeypatch.setattr(diffdock.requests, "post", fake_post)
    monkeypatch.setattr(diffdock, "_save_protein_to_gcs", lambda *a, **k: "gs://stub/protein.pdb")
    monkeypatch.setattr(diffdock, "_save_manifest_to_gcs", lambda *a, **k: "gs://stub/manifest.json")
    # Encode the ligand index into the pose path so filename numbering is checkable.
    monkeypatch.setattr(
        diffdock, "_save_pose_to_gcs",
        lambda dock_id, idx, rank, conf, sdf: f"gs://stub/lig{idx:03d}_rank{rank}::{sdf}",
    )
    return sent


def _dock(smiles_list):
    return diffdock.dock_molecules(
        protein_pdb_path=STUB_PDB, ligand_smiles_list=smiles_list, num_poses=1)


def test_blank_in_middle_does_not_shift_poses(stub_nim):
    """The regression: a blank at index 1 must not shift B and C's results."""
    out = _dock(["CCO", "", "CCN", "CCC"])
    by_smiles = {r["smiles"]: r for r in out["results"] if r["smiles"]}

    # Each ligand keeps the pose generated from its OWN structure.
    assert by_smiles["CCO"]["all_poses"][0]["pose_gcs_path"].endswith("SDF::CCO")
    assert by_smiles["CCN"]["all_poses"][0]["pose_gcs_path"].endswith("SDF::CCN")
    assert by_smiles["CCC"]["all_poses"][0]["pose_gcs_path"].endswith("SDF::CCC")

    # Confidences follow submission order (0, 1, 2), not caller index.
    assert by_smiles["CCO"]["confidence"] == -1.0
    assert by_smiles["CCN"]["confidence"] == -2.0
    assert by_smiles["CCC"]["confidence"] == -3.0


def test_blank_reported_failed_without_consuming_a_pose(stub_nim):
    out = _dock(["CCO", "", "CCN"])
    blank = out["results"][1]
    assert blank["smiles"] == ""
    assert blank["status"] == "failed"
    assert blank["confidence"] is None
    assert blank["pose_path"] == ""
    # The last real ligand must NOT be starved of its result.
    assert out["results"][2]["smiles"] == "CCN"
    assert out["results"][2]["confidence"] is not None


def test_only_non_blank_smiles_are_submitted(stub_nim):
    _dock(["CCO", "", "  ", "CCN"])
    assert stub_nim["ligand"].split("\n") == ["CCO", "CCN"]


def test_results_align_with_input_order_and_length(stub_nim):
    smiles = ["CCO", "", "CCN", "  ", "CCC"]
    out = _dock(smiles)
    assert len(out["results"]) == len(smiles)
    assert [r["smiles"] for r in out["results"]] == smiles


def test_pose_filenames_use_caller_index(stub_nim):
    """Pose objects are resolved positionally by the A2A bridge, so the
    filename index must be the caller's index, not the submission position."""
    out = _dock(["CCO", "", "CCN"])
    assert "lig000_rank1" in out["results"][0]["all_poses"][0]["pose_gcs_path"]
    assert "lig002_rank1" in out["results"][2]["all_poses"][0]["pose_gcs_path"]


def test_no_blanks_is_unaffected(stub_nim):
    out = _dock(["CCO", "CCN", "CCC"])
    assert out["docked_count"] == 3
    assert out["status"] == "success"
    for r in out["results"]:
        assert r["all_poses"][0]["pose_gcs_path"].endswith(f"SDF::{r['smiles']}")


def test_short_response_marks_trailing_ligands_failed(stub_nim, monkeypatch):
    """If the NIM returns fewer entries than submitted, the shortfall must land
    on the trailing ligands rather than silently shifting every pairing."""
    real_post = diffdock.requests.post

    def truncating_post(url, **kwargs):
        resp = real_post(url, **kwargs)
        data = resp.json()
        data["ligand_positions"] = data["ligand_positions"][:1]
        data["position_confidence"] = data["position_confidence"][:1]
        return type(resp)(data)

    monkeypatch.setattr(diffdock.requests, "post", truncating_post)
    out = _dock(["CCO", "CCN"])
    assert out["results"][0]["all_poses"][0]["pose_gcs_path"].endswith("SDF::CCO")
    assert out["results"][1]["confidence"] is None
    assert out["results"][1]["status"] == "failed"
