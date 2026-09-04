"""The deployment path, tested as infrastructure.

The live app stopped updating itself. The git layer was fine — every push
had landed — so the failure was further along: a boot that could not
survive the FPL API refusing a datacentre IP. An exception escaping the
startup script does not merely show an error; the platform records the
build as failed and keeps serving the previous one, which looks exactly
like "it stopped deploying".

These tests hold that shut.
"""
import json
import time
from pathlib import Path

import pytest
import requests

from fpl_assistant import api, cache, version

ROOT = Path(__file__).resolve().parent.parent


# --- a transient refusal must not cost a deployment ---------------------

def test_the_api_retries_before_giving_up(monkeypatch):
    attempts = []

    def flaky(url, timeout=None):
        attempts.append(url)
        if len(attempts) < 3:
            raise requests.ConnectionError("tunnel refused")
        return _Response({"ok": True})

    monkeypatch.setattr(api._session, "get", flaky)
    monkeypatch.setattr(api, "BACKOFF_SECONDS", (0, 0, 0))
    assert api._get("/bootstrap-static/") == {"ok": True}
    assert len(attempts) == 3


def test_a_rate_limit_is_retried_but_a_not_found_is_not(monkeypatch):
    for status, expected_attempts in ((429, 3), (403, 3), (404, 1)):
        attempts = []

        def refuse(url, timeout=None, _status=status):
            attempts.append(url)
            raise _HTTPError(_status)

        monkeypatch.setattr(api._session, "get", refuse)
        monkeypatch.setattr(api, "BACKOFF_SECONDS", (0, 0, 0))
        with pytest.raises(requests.RequestException):
            api._get("/whatever/")
        assert len(attempts) == expected_attempts, status


def test_a_stale_cache_is_served_rather_than_raising(monkeypatch, tmp_path):
    """Serving hour-old data is a small inaccuracy. Raising at startup
    aborts the deployment."""
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    path = tmp_path / "thing.json"
    path.write_text(json.dumps({"cached": True}))
    # Age it well past any TTL.
    old = time.time() - 100000
    import os
    os.utime(path, (old, old))

    def unreachable():
        raise requests.ConnectionError("no route to host")

    assert cache.cached_fetch("thing", 60, unreachable) == {"cached": True}


def test_with_no_cache_at_all_the_error_still_surfaces(monkeypatch, tmp_path):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)

    def unreachable():
        raise requests.ConnectionError("no route to host")

    with pytest.raises(requests.ConnectionError):
        cache.cached_fetch("missing", 60, unreachable)


# --- the build marker is the proof a deploy landed ----------------------

def test_the_build_marker_is_read_from_git_not_hard_coded():
    build = version.current()
    assert build.known, "no commit could be read"
    assert len(build.short) == 7
    source = (ROOT / "fpl_assistant" / "version.py").read_text()
    assert build.commit not in source, "the marker is hard-coded"


def test_the_marker_prefers_an_explicit_environment_commit(monkeypatch):
    monkeypatch.setenv("STREAMLIT_COMMIT_SHA", "abcdef1234567")
    assert version.current().short == "abcdef1"


def test_the_marker_survives_a_packed_ref_clone():
    """A fresh deploy is a fresh clone, where refs are packed rather than
    loose — the case that would otherwise read as 'unknown'."""
    from fpl_assistant.version import GIT_DIR
    assert (GIT_DIR / "HEAD").exists()
    assert version.current().commit


# --- the workflows must not fight the deployment ------------------------

WORKFLOWS = ROOT / ".github" / "workflows"


def test_no_workflow_force_pushes_the_deployed_branch():
    for path in WORKFLOWS.glob("*.yml"):
        text = path.read_text()
        assert "--force" not in text and "-f origin" not in text, path.name


def test_the_data_workflows_do_not_commit_pure_noise():
    """Each commit is a rebuild. Committing a timestamp eight times a day
    is eight rebuilds of the live app for nothing."""
    for name in ("snapshot.yml", "research.yml"):
        text = (WORKFLOWS / name).read_text()
        assert "Discard a refresh that changed nothing" in text, name
        assert "fetched_at" in text and "selected_by_percent" in text, name


def test_every_workflow_pushes_to_the_branch_it_was_run_from():
    """A workflow that hard-codes a different branch would silently move
    the deployment target."""
    for path in WORKFLOWS.glob("*.yml"):
        text = path.read_text()
        for line in text.splitlines():
            if "git push" in line and "GITHUB_REF_NAME" not in line:
                assert "origin" not in line or "HEAD:" not in line, (
                    f"{path.name}: {line.strip()}")


def test_the_deploy_check_reports_rather_than_failing_the_run():
    """The hosting platform is outside this repository's control; a red
    workflow would say nothing the warning does not."""
    text = (ROOT / "scripts" / "check_deploy.py").read_text()
    assert "return 0" in text
    assert "::warning" in text


def test_the_verify_workflow_only_runs_on_code_changes():
    """Verifying a deployment forty times a day, once per data commit, is
    its own kind of waste."""
    text = (WORKFLOWS / "verify-deploy.yml").read_text()
    assert "paths:" in text
    assert "fpl_assistant/**" in text
    assert "data/**" not in text


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _HTTPError(requests.HTTPError):
    def __init__(self, status):
        super().__init__(f"{status} error")
        self.response = _Status(status)


class _Status:
    def __init__(self, status_code):
        self.status_code = status_code
