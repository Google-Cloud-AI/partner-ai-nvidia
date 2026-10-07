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

"""Shared pytest configuration.

The agents are deployed as self-contained bundles rather than an installed
package, so `agents/` goes on the path to make `lead_optimizer.tools...`
importable the same way the Agent Runtime sees it.
"""
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

for path in (REPO_ROOT, REPO_ROOT / "agents"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

# The tool modules require GOOGLE_CLOUD_PROJECT at import (no hardcoded project
# fallback), so supply an obviously-fake one. `setdefault`, not an assignment:
# it must not shadow a real value if someone runs the suite against a project.
# The value must stay fake -- nothing here should reach a live API, and a test
# that starts passing only because a real project leaked in is a broken test.
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "test-project-not-real")
os.environ.setdefault("A2A_SERVER_URL", "https://test-bridge.invalid")
# The engine IDs are required at import for the same reason -- `adk deploy` mints
# a fresh one every time, so there is no sane default to fall back to.
os.environ.setdefault("ORCHESTRATOR_ENGINE_ID", "0000000000000000000")
os.environ.setdefault("LEAD_OPTIMIZER_ENGINE_ID", "0000000000000000001")
os.environ.setdefault("ADMET_SAFETY_ENGINE_ID", "0000000000000000002")
