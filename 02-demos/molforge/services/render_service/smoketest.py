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

"""Build-time smoke test for the render service.

`render_structure` prefers PyMOL and silently falls back to matplotlib on
ImportError OR on any exception, logging one line and returning a perfectly
valid response. So a broken PyMOL does not fail a request, it quietly
downgrades every ray-traced render to a flat matplotlib plot -- and the only
evidence is the `renderer` field and a log nobody reads.

That is why this asserts renderer == "pymol" rather than merely importing
pymol2: it fails the BUILD on the exact degradation the fallback is designed
to hide. Run with an argument of "pymol" to require PyMOL, or "matplotlib" to
check only that the fallback path works (used by the non-PyMOL image).
"""
import sys

import mol3d

# Ten residues of poly-alanine backbone. Enough for cmd.orient() and a cartoon
# trace to have something real to ray-trace; small enough to render instantly.
_ATOMS = []
_serial = 1
for res in range(1, 11):
    z = res * 1.5
    for name, elem, dx in (("N", "N", 0.0), ("CA", "C", 1.4), ("C", "C", 2.4), ("O", "O", 3.0)):
        _ATOMS.append(
            f"ATOM  {_serial:>5} {name:<4} ALA A{res:>4}    "
            f"{dx:>8.3f}{0.0:>8.3f}{z:>8.3f}  1.00 50.00          {elem:>2}"
        )
        _serial += 1
STUB_PDB = "\n".join(_ATOMS) + "\nEND\n"


def main() -> int:
    want = sys.argv[1] if len(sys.argv) > 1 else "pymol"

    result = mol3d.render_structure(protein_pdb=STUB_PDB, size=128, mode="snapshot")

    if not result.get("ok"):
        print(f"smoke test FAILED: render returned {result.get('error')!r}", file=sys.stderr)
        return 1

    got = result.get("renderer")
    if got != want:
        print(
            f"smoke test FAILED: expected the {want} renderer, got {got!r}. "
            "For the PyMOL image this means pymol2 is missing or raising, and every "
            "render would silently downgrade to matplotlib.",
            file=sys.stderr,
        )
        return 1

    if not result.get("png_b64"):
        print("smoke test FAILED: renderer reported ok but produced no image", file=sys.stderr)
        return 1

    print(f"smoke test OK: {got} renderer produced {len(result['png_b64'])} b64 chars")
    return 0


if __name__ == "__main__":
    sys.exit(main())
