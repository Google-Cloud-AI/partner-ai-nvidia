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
3D molecular rendering for the MolForge render-service (Phase 2).

Produces a server-side raster (PNG snapshot, optional GIF turntable) of a docked
complex (protein + ligand pose) or a folded protein (pLDDT-colored), so the A2A
bridge can embed inline 3D in Gemini Enterprise via A2UI's `Image` component.

Two renderers, same output contract:
  • PyMOL (preferred) — ray-traced, publication quality. Not pip-installable;
    shipped via Dockerfile.pymol (micromamba + pymol-open-source).
  • matplotlib (fallback) — Cα ribbon + ligand sticks; pip-installable, used when
    PyMOL is unavailable. Lower fidelity but always works on plain Cloud Run.

resolve_uri() accepts inline content or gs:// (via google-cloud-storage) — so the
bridge passes the GCS paths the DiffDock/ESMFold tools wrote. Remote inputs are
allowlisted; see the input-resolution policy below.

Author: Schneider Larbi — Google Cloud
"""
import os
import io
import base64
import logging

logger = logging.getLogger("molforge-render.mol3d")

# ── Input resolution policy ────────────────────────────────────────────────
# resolve_uri() runs behind a public endpoint but reads with the *service's own*
# credentials, so an unrestricted resolver is a confused deputy: a caller could
# name any bucket or host the service can reach and have the service fetch it.
# Both remote schemes are therefore default-deny allowlists.
#
# This also contains a subtler path: the bridge scrapes gs:// URIs out of
# model-generated narrative text, so the bucket named here is not always
# operator-controlled. The allowlist bounds that too.
#
#   MOLFORGE_ALLOWED_BUCKETS     comma-separated buckets resolve_uri may read.
#                                Defaults to the artifacts bucket.
#   MOLFORGE_ALLOWED_HTTP_HOSTS  comma-separated hosts for http(s):// inputs.
#                                Empty (the default) disables remote fetch.
_ALLOWED_BUCKETS = frozenset(
    b.strip() for b in os.getenv(
        "MOLFORGE_ALLOWED_BUCKETS",
        os.getenv("MOLFORGE_ARTIFACTS_BUCKET", "molforge-artifacts"),
    ).split(",") if b.strip()
)
_ALLOWED_HTTP_HOSTS = frozenset(
    h.strip().lower()
    for h in os.getenv("MOLFORGE_ALLOWED_HTTP_HOSTS", "").split(",") if h.strip()
)

# A protein PDB is a few MB at worst. Cloud Run's filesystem and buffers are
# memory, so an unbounded read is an OOM waiting to happen.
MAX_STRUCTURE_BYTES = int(
    os.getenv("MOLFORGE_MAX_STRUCTURE_BYTES", str(32 * 1024 * 1024)))


class StructureResolutionError(ValueError):
    """A structure input could not be resolved.

    Messages are deliberately coarse: this surfaces to an unauthenticated
    caller, and a precise one ("404 on gs://other-bucket/x") would make the
    renderer an object-existence oracle. Details go to the log instead.
    """

# CPK-ish element colors for the matplotlib fallback.
_ELEMENT_COLORS = {
    "C": "#909090", "N": "#3050F8", "O": "#FF0D0D", "S": "#FFFF30",
    "P": "#FF8000", "H": "#FFFFFF", "F": "#90E050", "Cl": "#1FF01F",
    "Br": "#A62929", "I": "#940094",
}


def _read_gcs(uri: str) -> str:
    """Read an allowlisted gs:// object as text."""
    from google.cloud import storage

    bucket_name, _, blob_path = uri[5:].partition("/")
    if not bucket_name or not blob_path:
        raise StructureResolutionError("invalid GCS path")
    if bucket_name not in _ALLOWED_BUCKETS:
        logger.warning(f"blocked gs:// read of non-allowlisted bucket: {bucket_name}")
        raise StructureResolutionError("bucket not permitted")

    blob = storage.Client().bucket(bucket_name).blob(blob_path)
    try:
        blob.reload()  # metadata only — gives us .size before we pull bytes
    except Exception as e:
        logger.warning(f"gs:// read failed for {uri}: {e}")
        raise StructureResolutionError("structure not found") from None
    if blob.size and blob.size > MAX_STRUCTURE_BYTES:
        raise StructureResolutionError("structure exceeds the size limit")
    return blob.download_as_text()


def _read_http(url: str) -> str:
    """Fetch an allowlisted http(s) URL as text."""
    from urllib.parse import urlparse

    import requests

    # .hostname strips userinfo and port, so "https://ok.example@evil.tld/"
    # correctly resolves to evil.tld rather than the decoy prefix.
    host = (urlparse(url).hostname or "").lower()
    if not host or host not in _ALLOWED_HTTP_HOSTS:
        logger.warning(f"blocked http(s) fetch of non-allowlisted host: {host or '?'}")
        raise StructureResolutionError("host not permitted")

    # Redirects are not followed: an allowlisted host could otherwise bounce the
    # request to an internal address and re-open the hole the allowlist closes.
    r = requests.get(url, timeout=60, stream=True, allow_redirects=False)
    r.raise_for_status()
    body = r.raw.read(MAX_STRUCTURE_BYTES + 1, decode_content=True)
    if len(body) > MAX_STRUCTURE_BYTES:
        raise StructureResolutionError("structure exceeds the size limit")
    return body.decode(r.encoding or "utf-8", errors="replace")


def resolve_uri(s: str) -> str:
    """Resolve a structure input to text content.

    Accepts inline PDB/SDF content, gs:// (allowlisted buckets), and http(s)://
    (allowlisted hosts). Mirrors the DiffDock tool's resolver so the same gs://
    paths work end to end.

    Local filesystem paths are deliberately NOT resolved. Nothing legitimate
    passes one -- every caller supplies gs:// or inline content -- and honouring
    them would turn a caller-supplied string into an arbitrary file read.
    """
    s = (s or "").strip()
    if not s:
        raise StructureResolutionError("empty structure URI")
    if s.startswith(("HEADER", "ATOM", "HETATM")) or "\n" in s:
        return s  # inline content
    if s.startswith("gs://"):
        return _read_gcs(s)
    if s.startswith(("http://", "https://")):
        return _read_http(s)
    return s  # assume inline


# ── PDB / SDF parsing (for the matplotlib fallback) ────────────────────────
def _parse_ca(pdb_text: str):
    """Return (coords[list of (x,y,z)], bfactors[list], chains[list]) for Cα atoms."""
    coords, bf, chains = [], [], []
    for line in pdb_text.splitlines():
        if line.startswith("ATOM") and len(line) >= 54 and line[12:16].strip() == "CA":
            try:
                x, y, z = float(line[30:38]), float(line[38:46]), float(line[46:54])
            except ValueError:
                continue
            b = 0.0
            if len(line) >= 66:
                try:
                    b = float(line[60:66])
                except ValueError:
                    b = 0.0
            coords.append((x, y, z))
            bf.append(b)
            chains.append(line[21] if len(line) > 21 else "A")
    return coords, bf, chains


def _parse_ligand(sdf_text: str):
    """Return (atoms[list of (x,y,z,symbol)], bonds[list of (i,j)]) from the first SDF record."""
    from rdkit import Chem

    block = sdf_text.split("$$$$")[0]
    mol = Chem.MolFromMolBlock(block, sanitize=False, removeHs=False)
    if mol is None or mol.GetNumConformers() == 0:
        return [], []
    conf = mol.GetConformer()
    atoms = []
    for i, a in enumerate(mol.GetAtoms()):
        p = conf.GetAtomPosition(i)
        atoms.append((p.x, p.y, p.z, a.GetSymbol()))
    bonds = [(b.GetBeginAtomIdx(), b.GetEndAtomIdx()) for b in mol.GetBonds()]
    return atoms, bonds


# ── matplotlib fallback renderer ───────────────────────────────────────────
def _frame_to_png(fig) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", pad_inches=0, transparent=False)
    buf.seek(0)
    return buf.read()


def _render_matplotlib(protein_pdb, ligand_sdf, color_by, size, mode):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import cm

    ca, bf, _chains = _parse_ca(protein_pdb) if protein_pdb else ([], [], [])
    atoms, bonds = _parse_ligand(ligand_sdf) if ligand_sdf else ([], [])
    if not ca and not atoms:
        return {"ok": False, "error": "no renderable atoms (no Cα or ligand)"}

    all_pts = list(ca) + [(a[0], a[1], a[2]) for a in atoms]
    cx = sum(p[0] for p in all_pts) / len(all_pts)
    cy = sum(p[1] for p in all_pts) / len(all_pts)
    cz = sum(p[2] for p in all_pts) / len(all_pts)
    span = max(
        (max(p[i] for p in all_pts) - min(p[i] for p in all_pts) for i in range(3)),
        default=10.0,
    ) or 10.0
    half = span / 2 * 1.1

    def draw(azim):
        fig = plt.figure(figsize=(size / 100, size / 100), dpi=100)
        ax = fig.add_subplot(111, projection="3d")
        ax.set_axis_off()
        if ca:
            xs = [p[0] for p in ca]; ys = [p[1] for p in ca]; zs = [p[2] for p in ca]
            if color_by == "plddt" and any(bf):
                colors = cm.RdYlBu([min(max(b, 0), 100) / 100.0 for b in bf])
                ax.plot(xs, ys, zs, color="#666666", linewidth=1.0, alpha=0.5)
                ax.scatter(xs, ys, zs, c=colors, s=12, depthshade=True)
            else:
                ax.plot(xs, ys, zs, color="#1f77b4", linewidth=2.0)
        for i, j in bonds:
            xi = [atoms[i][0], atoms[j][0]]
            yi = [atoms[i][1], atoms[j][1]]
            zi = [atoms[i][2], atoms[j][2]]
            ax.plot(xi, yi, zi, color="#404040", linewidth=2.5)
        if atoms:
            ax.scatter(
                [a[0] for a in atoms], [a[1] for a in atoms], [a[2] for a in atoms],
                c=[_ELEMENT_COLORS.get(a[3], "#FF00FF") for a in atoms],
                s=60, edgecolors="black", linewidths=0.4, depthshade=False,
            )
        ax.set_xlim(cx - half, cx + half)
        ax.set_ylim(cy - half, cy + half)
        ax.set_zlim(cz - half, cz + half)
        try:
            ax.set_box_aspect((1, 1, 1))
        except Exception:
            pass
        ax.view_init(elev=15, azim=azim)
        png = _frame_to_png(fig)
        plt.close(fig)
        return png

    if mode == "turntable":
        from PIL import Image
        # 16 frames (22.5° steps) + 300 ms/frame = smooth, slow rotation (matplotlib fallback).
        frames = [Image.open(io.BytesIO(draw(i * 22.5))).convert("RGB") for i in range(16)]
        buf = io.BytesIO()
        frames[0].save(buf, format="GIF", save_all=True, append_images=frames[1:],
                       duration=300, loop=0)
        return {"ok": True, "png_b64": base64.b64encode(buf.getvalue()).decode("ascii"),
                "mime_type": "image/gif", "renderer": "matplotlib"}

    png = draw(35)
    return {"ok": True, "png_b64": base64.b64encode(png).decode("ascii"),
            "mime_type": "image/png", "renderer": "matplotlib"}


# ── PyMOL preferred renderer ───────────────────────────────────────────────
def _render_pymol(protein_pdb, ligand_sdf, color_by, size, mode):
    import tempfile
    import pymol2

    # TemporaryDirectory, not mkdtemp: a turntable writes 16 ray-traced frames
    # plus the inputs, and Cloud Run's /tmp is a memory-backed tmpfs -- leaking
    # one of these per request walks the instance into an OOM kill.
    with pymol2.PyMOL() as p, tempfile.TemporaryDirectory() as tmp:
        cmd = p.cmd
        if protein_pdb:
            pp = os.path.join(tmp, "prot.pdb")
            with open(pp, "w") as f:
                f.write(protein_pdb)
            cmd.load(pp, "prot")
            cmd.hide("everything", "prot")
            cmd.show("cartoon", "prot")
            if color_by == "plddt":
                cmd.spectrum("b", "red_yellow_green", "prot")  # pLDDT: low→high
            else:
                cmd.color("cyan", "prot")
        if ligand_sdf:
            lp = os.path.join(tmp, "lig.sdf")
            with open(lp, "w") as f:
                f.write(ligand_sdf)
            cmd.load(lp, "lig")
            cmd.show("sticks", "lig")
            cmd.color("yellow", "lig and elem C")
        cmd.bg_color("white")
        cmd.set("ray_opaque_background", 1)
        cmd.orient()

        def shoot(angle=0):
            if angle:
                cmd.turn("y", angle)
            out = os.path.join(tmp, f"f{angle}.png")
            cmd.ray(size, size)
            cmd.png(out, dpi=150)
            with open(out, "rb") as f:
                return f.read()

        if mode == "turntable":
            from PIL import Image
            # 16 frames × 22.5° = smooth full rotation; 300 ms/frame = gentle slow spin.
            frames = [Image.open(io.BytesIO(shoot(22.5))).convert("RGB") for _ in range(16)]
            buf = io.BytesIO()
            frames[0].save(buf, format="GIF", save_all=True, append_images=frames[1:],
                           duration=300, loop=0)
            return {"ok": True, "png_b64": base64.b64encode(buf.getvalue()).decode("ascii"),
                    "mime_type": "image/gif", "renderer": "pymol"}
        png = shoot(0)
        return {"ok": True, "png_b64": base64.b64encode(png).decode("ascii"),
                "mime_type": "image/png", "renderer": "pymol"}


def render_structure(protein_pdb=None, ligand_sdf=None, color_by="chain",
                     size=640, mode="snapshot") -> dict:
    """Render a 3D structure. Prefers PyMOL, falls back to matplotlib.

    Returns {ok, png_b64, mime_type, renderer} or {ok: False, error}.
    """
    size = max(128, min(int(size or 640), 1600))
    if not protein_pdb and not ligand_sdf:
        return {"ok": False, "error": "no protein or ligand provided"}
    try:
        return _render_pymol(protein_pdb, ligand_sdf, color_by, size, mode)
    except ImportError:
        logger.info("PyMOL not available; using matplotlib fallback")
    except Exception as e:
        logger.warning(f"PyMOL render failed ({e}); using matplotlib fallback")
    try:
        return _render_matplotlib(protein_pdb, ligand_sdf, color_by, size, mode)
    except Exception as e:
        logger.error(f"matplotlib render failed: {e}")
        return {"ok": False, "error": str(e)[:200]}
