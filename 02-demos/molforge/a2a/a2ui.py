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

"""
A2UI v0.8 builders for the MolForge A2A bridge.

Ported from a known-good, GE-rendered implementation (Project Catalyst). Key facts
that took a working reference to learn:
  - GE negotiates A2UI via an A2A *extension* declared on the AgentCard
    (capabilities.extensions[uri=…/a2ui/v0.8]) + an `X-A2A-Extensions` response header
    — NOT via defaultOutputModes.
  - Each A2UI message is its own A2A DataPart: {kind:"data", data:<message>,
    metadata:{mimeType:"application/json+a2ui"}}  (mimeType in metadata, not top-level).
  - GE resolves INLINED surfaceUpdate literal values and SCALAR data-model bindings, but
    NOT nested/structured bindings — so everything here is emitted as inlined literals.
  - Components are a FLAT adjacency list addressed by id; containers reference children by
    id; Image sources its URL (we point it at the public render-service PNG endpoint).

Each builder returns an ordered list of A2UI v0.8 messages (surfaceUpdate → beginRendering).
Branding: "Powered by NVIDIA" — no GPU-model names.
"""
from typing import List, Optional
import urllib.parse
import uuid

A2UI_MIME = "application/json+a2ui"
SURFACE = "molforge_result"
POWERED_BY = "Powered by NVIDIA"
MAX_SHOW = 8


# ── component constructors (v0.8 standard catalog) ─────────────────────────
def _text(cid, literal="", path=None, hint=None):
    val = {"path": path} if path else {"literalString": literal or ""}
    comp = {"text": val}
    if hint:
        comp["usageHint"] = hint
    return {"id": cid, "component": {"Text": comp}}


def _image(cid, url, width=320, height=320, fit="contain"):
    return {"id": cid, "component": {"Image": {
        "url": {"literalString": url},
        "width": {"literalNumber": width},
        "height": {"literalNumber": height},
        "fit": fit}}}


def _col(cid, children, alignment="start"):
    return {"id": cid, "component": {"Column": {"alignment": alignment,
            "children": {"explicitList": children}}}}


def _card(cid, child):
    return {"id": cid, "component": {"Card": {"child": child}}}


def _render_2d_url(render_base: str, smiles: str) -> str:
    return f"{render_base}/render/2d.png?smiles={urllib.parse.quote(smiles, safe='')}"


def _emit(components, root="root"):
    """Wrap components into a uniquely-surfaced [surfaceUpdate, beginRendering] pair.

    A FRESH surfaceId per result is load-bearing for MULTI-TURN: GE renders a given
    surfaceId once per conversation, so reusing a constant id (the old `SURFACE`) makes
    the 2nd+ inline render in the same chat a silent no-op — only the text bubble shows.
    This is why fresh-conversation wire tests passed while a real multi-turn GE session
    failed on the follow-up render. A unique id per call makes every result its own
    surface that GE actually renders.
    """
    sid = f"molforge_{uuid.uuid4().hex[:12]}"
    return [{"surfaceUpdate": {"surfaceId": sid, "components": components}},
            {"beginRendering": {"surfaceId": sid, "root": root}}]


# ── builders ───────────────────────────────────────────────────────────────
def build_optimization_messages(results: dict, render_base: str,
                                structure_url: Optional[str] = None) -> List[dict]:
    """A2UI surface for an optimization_results artifact: header + (optional 3D pose) +
    a card per candidate (caption + inline 2D structure image)."""
    target = results.get("target_name") or results.get("target") or "target"
    count = results.get("candidate_count") or len(results.get("candidates") or [])
    candidates = (results.get("candidates") or [])[:MAX_SHOW]

    comps = [
        _text("hdr", literal=f"Lead Optimization — {target} · {POWERED_BY}", hint="h2"),
        _text("sub", literal=f"{count} candidate variants · NVIDIA Nemotron SAR below"),
    ]
    root_children = ["hdr", "sub"]

    if structure_url:
        comps += [
            _text("pose_cap", literal="Top docked pose (3D)", hint="h3"),
            _image("pose_img", structure_url, width=480, height=360),
            _col("pose_col", ["pose_cap", "pose_img"]),
            _card("pose_card", "pose_col"),
        ]
        root_children.append("pose_card")

    for i, c in enumerate(candidates):
        s = c.get("smiles") if isinstance(c, dict) else None
        if not s:
            continue
        cap = f"opt-{i+1}"
        score = c.get("binding_score")
        if score is not None:
            cap += f" · binding {score}"
        comps += [
            _text(f"c{i}_cap", literal=cap),
            _image(f"c{i}_img", _render_2d_url(render_base, s)),
            _col(f"c{i}_col", [f"c{i}_cap", f"c{i}_img"]),
            _card(f"c{i}_card", f"c{i}_col"),
        ]
        root_children.append(f"c{i}_card")

    comps.append(_col("root", root_children))
    return _emit(comps)


def build_admet_messages(results: dict, render_base: str) -> List[dict]:
    """A2UI surface for an admet_results artifact: header + a card per screened molecule."""
    area = results.get("therapeutic_area") or "—"
    rows = (results.get("screening_results") or [])[:MAX_SHOW]
    count = results.get("molecule_count") or len(rows)

    comps = [
        _text("hdr", literal=f"ADMET Safety Screen — {area} · {POWERED_BY}", hint="h2"),
        _text("sub", literal=f"{count} molecules screened · NVIDIA Nemotron assessment below"),
    ]
    root_children = ["hdr", "sub"]
    for i, r in enumerate(rows):
        s = r.get("smiles") if isinstance(r, dict) else None
        if not s:
            continue
        cap = f"mol-{i+1}"
        v = r.get("verdict") or r.get("overall_verdict")
        if v:
            cap += f" · {v}"
        comps += [
            _text(f"m{i}_cap", literal=cap),
            _image(f"m{i}_img", _render_2d_url(render_base, s)),
            _col(f"m{i}_col", [f"m{i}_cap", f"m{i}_img"]),
            _card(f"m{i}_card", f"m{i}_col"),
        ]
        root_children.append(f"m{i}_card")
    comps.append(_col("root", root_children))
    return _emit(comps)


def build_protein_structure_messages(protein_name: str, plddt, structure_url: str) -> List[dict]:
    """A2UI surface for a standalone folded protein (atomic ESMFold): header + the
    pLDDT-colored 3D structure image."""
    comps = [_text("hdr", literal=f"Predicted structure — {protein_name} · {POWERED_BY}", hint="h2")]
    root_children = ["hdr"]
    if plddt is not None:
        comps.append(_text("sub", literal=f"ESMFold · mean pLDDT {plddt} (confidence-colored)"))
        root_children.append("sub")
    comps += [
        _text("struct_cap", literal="3D structure", hint="h3"),
        _image("struct_img", structure_url, width=480, height=420),
        _col("struct_col", ["struct_cap", "struct_img"]),
        _card("struct_card", "struct_col"),
    ]
    root_children.append("struct_card")
    comps.append(_col("root", root_children))
    return _emit(comps)


def build_docked_pose_messages(target, confidence, structure_url: str) -> List[dict]:
    """A2UI surface for a standalone docked pose (atomic DiffDock): header + the 3D pose."""
    comps = [_text("hdr", literal=f"Docked pose — {target or 'target'} · {POWERED_BY}", hint="h2")]
    root_children = ["hdr"]
    if confidence is not None:
        comps.append(_text("sub", literal=f"NVIDIA DiffDock · rank-1 confidence {confidence}"))
        root_children.append("sub")
    comps += [
        _text("pose_cap", literal="Top docked pose (3D)", hint="h3"),
        _image("pose_img", structure_url, width=480, height=420),
        _col("pose_col", ["pose_cap", "pose_img"]),
        _card("pose_card", "pose_col"),
    ]
    root_children.append("pose_card")
    comps.append(_col("root", root_children))
    return _emit(comps)


def build_messages_for_artifact(results: dict, render_base: str,
                                structure_url: Optional[str] = None) -> Optional[List[dict]]:
    """Dispatch on artifact_type → ordered list of A2UI v0.8 messages, or None."""
    if not isinstance(results, dict):
        return None
    atype = results.get("artifact_type")
    if atype == "optimization_results":
        return build_optimization_messages(results, render_base, structure_url=structure_url)
    if atype == "admet_results":
        return build_admet_messages(results, render_base)
    return None
