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

"""Fail fast when the workshop environment does not match the tested stack."""

from __future__ import annotations

import shutil
import subprocess
import sys
from importlib.metadata import PackageNotFoundError, version

EXPECTED_PYTHON = (3, 12)
EXPECTED_PACKAGES = {
    "ipywidgets": "8.1.9",
    "jax": "0.9.2",
    "jupyterlab": "4.6.3",
    "matplotlib": "3.11.1",
    "nvtx": "0.2.16",
    "setuptools": "69.5.1",
    "tensorboard": "2.21.0",
    "tensorflow": "2.21.0",
    "xprof": "2.23.1",
}
BASE_PACKAGES = (
    "flax",
    "optax",
    "orbax-checkpoint",
    "transformer-engine",
)
REQUIRED_EXECUTABLES = (
    "jupyter",
    "jupyter-lab",
    "nvidia-smi",
    "nsys",
    "xprof",
)
IMPORT_CHECKS = {
    "Flax/Optax/Orbax": "import flax; import optax; import orbax.checkpoint",
    "JAX export": "from jax import export",
    "JAX-to-TensorFlow export": "from jax.experimental import jax2tf; import tensorflow",
    "NVTX": "import nvtx",
    "TransformerEngine JAX": "import transformer_engine.jax",
}


def package_version(distribution: str) -> str | None:
    try:
        return version(distribution)
    except PackageNotFoundError:
        return None


def main() -> int:
    errors: list[str] = []

    if sys.version_info[:2] != EXPECTED_PYTHON:
        errors.append(
            "Python "
            f"{EXPECTED_PYTHON[0]}.{EXPECTED_PYTHON[1]} is required; "
            f"found {sys.version_info.major}.{sys.version_info.minor}."
        )

    print(f"Python: {sys.version.split()[0]}")

    for distribution, expected in EXPECTED_PACKAGES.items():
        installed = package_version(distribution)
        print(f"{distribution}: {installed or 'missing'}")
        if installed != expected:
            errors.append(
                f"{distribution}=={expected} is required; "
                f"found {installed or 'not installed'}."
            )

    for distribution in BASE_PACKAGES:
        installed = package_version(distribution)
        print(f"{distribution}: {installed or 'missing'}")
        if installed is None:
            errors.append(
                f"Required base package {distribution!r} is not installed."
            )

    for executable in REQUIRED_EXECUTABLES:
        path = shutil.which(executable)
        print(f"{executable}: {path or 'missing'}")
        if path is None:
            errors.append(f"Required executable {executable!r} is not on PATH.")

    for label, code in IMPORT_CHECKS.items():
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            check=False,
            text=True,
        )
        print(f"{label} import: {'OK' if result.returncode == 0 else 'failed'}")
        if result.returncode != 0:
            detail = result.stderr.strip().splitlines()
            suffix = f" Last error: {detail[-1]}" if detail else ""
            errors.append(f"{label} could not be imported.{suffix}")

    if errors:
        print("\nEnvironment verification failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    print("\nWorkshop environment verification passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
