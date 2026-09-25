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

"""Bridge CORS policy.

The bridge used to run allow_origins=["*"] with allow_credentials=True. That
reads as "public read-only API", but Starlette may not send a literal "*"
together with credentials -- it echoes the caller's Origin instead. The
deployed server answered `Access-Control-Allow-Origin: <caller>` plus
`Access-Control-Allow-Credentials: true` for ANY origin.

The trap is that the misconfiguration is invisible unless you send an Origin
header: curl without one shows nothing, and the wildcard in the source reads as
harmless. These tests send Origins, and assert on the response headers rather
than on the middleware arguments, because the arguments are exactly what looked
fine before.
"""
import importlib.util
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

EVIL = "https://evil.example.com"
GOOD = "https://molforge-dashboard.example.run.app"

BRIDGE_DIR = Path(__file__).resolve().parent.parent / "a2a"


def _client(monkeypatch, origins):
    """Load the bridge with MOLFORGE_CORS_ORIGINS set, and return a client.

    Loaded from its path, not as `a2a.server`: the installed A2A SDK owns the
    top-level `a2a` name and would shadow the repo directory. Loaded fresh per
    case because the middleware is attached at import time.
    """
    if origins is None:
        monkeypatch.delenv("MOLFORGE_CORS_ORIGINS", raising=False)
    else:
        monkeypatch.setenv("MOLFORGE_CORS_ORIGINS", origins)

    monkeypatch.syspath_prepend(str(BRIDGE_DIR))  # sibling imports (a2ui)
    spec = importlib.util.spec_from_file_location(
        "molforge_bridge_under_test", BRIDGE_DIR / "server.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)
    return TestClient(module.app)


def _preflight(client, origin):
    return client.options(
        "/",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )


def test_default_is_no_cors_at_all(monkeypatch):
    """Unset means server-to-server only: no grant to anybody, including GET."""
    client = _client(monkeypatch, None)
    resp = client.get("/health", headers={"Origin": EVIL})
    assert "access-control-allow-origin" not in resp.headers
    assert "access-control-allow-credentials" not in resp.headers


def test_unlisted_origin_is_not_granted(monkeypatch):
    client = _client(monkeypatch, GOOD)
    resp = client.get("/health", headers={"Origin": EVIL})
    # The request still succeeds -- CORS is enforced by the browser, not the
    # server. What matters is that no grant header comes back for EVIL.
    assert resp.headers.get("access-control-allow-origin") != EVIL

    pre = _preflight(client, EVIL)
    assert pre.headers.get("access-control-allow-origin") != EVIL


def test_listed_origin_is_granted(monkeypatch):
    client = _client(monkeypatch, GOOD)
    resp = client.get("/health", headers={"Origin": GOOD})
    assert resp.headers.get("access-control-allow-origin") == GOOD

    pre = _preflight(client, GOOD)
    assert pre.status_code == 200
    assert pre.headers.get("access-control-allow-origin") == GOOD


@pytest.mark.parametrize("origins", [GOOD, "*", f"{GOOD},{EVIL}"])
def test_credentials_are_never_allowed(monkeypatch, origins):
    """The regression that mattered.

    Credentials are what turn a wildcard into per-origin echo, and nothing here
    authenticates by cookie, so no configuration may switch them back on.
    """
    client = _client(monkeypatch, origins)
    for origin in (GOOD, EVIL):
        assert "access-control-allow-credentials" not in client.get(
            "/health", headers={"Origin": origin}
        ).headers
        assert "access-control-allow-credentials" not in _preflight(
            client, origin
        ).headers


def test_multiple_origins_are_parsed_and_trimmed(monkeypatch):
    """Whitespace and trailing slashes are common in hand-set env vars."""
    client = _client(monkeypatch, f" {GOOD}/ ,  {EVIL} ")
    assert client.get("/health", headers={"Origin": GOOD}).headers.get(
        "access-control-allow-origin"
    ) == GOOD
    assert client.get("/health", headers={"Origin": EVIL}).headers.get(
        "access-control-allow-origin"
    ) == EVIL


def test_wildcard_is_honoured_but_without_credentials(monkeypatch):
    """"*" stays available as a deliberate opt-out, minus the dangerous half."""
    client = _client(monkeypatch, "*")
    resp = client.get("/health", headers={"Origin": EVIL})
    assert resp.headers.get("access-control-allow-origin") == "*"
    assert "access-control-allow-credentials" not in resp.headers
