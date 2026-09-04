"""Which version of the code is actually running.

The problem this solves is not technical, it is epistemic. Streamlit
Community Cloud already redeploys automatically when the watched branch
receives a push — that is free, built-in behaviour and nothing here
changes it. But the app gave no way to tell WHICH commit was live, so the
only way to be sure a change had landed was to open the Streamlit
dashboard and press Reboot. Rebooting became the way to answer a question
rather than the way to fix a fault.

Showing the deployed commit turns the guess into a fact: if the marker
matches the last push, the deploy has landed and a reboot would achieve
nothing.

Read straight from `.git` rather than by shelling out. Streamlit Cloud
clones the repository, so the files are there, but `git` the binary is not
guaranteed to be on PATH in the app container — and a version marker that
throws is worse than none. Everything below degrades to "unknown" rather
than raising.
"""
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
GIT_DIR = REPO_ROOT / ".git"


@dataclass
class Version:
    commit: str = ""
    branch: str = ""
    committed_at: str = ""
    # The same moment as an ISO timestamp. `committed_at` is formatted for
    # a footer and cannot be parsed back, so the age was always unknown
    # even when the date was on the page.
    committed_iso: str = ""

    @property
    def short(self) -> str:
        return self.commit[:7] if self.commit else "unknown"

    @property
    def known(self) -> bool:
        return bool(self.commit)

    @property
    def age_hours(self) -> float | None:
        """How long this build has been the running one."""
        if not self.committed_iso:
            return None
        try:
            stamp = datetime.fromisoformat(self.committed_iso)
        except ValueError:
            return None
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - stamp).total_seconds() / 3600

    @property
    def age_display(self) -> str:
        """The build's age in words, which is what makes a stale one obvious.

        A commit hash tells you nothing until you go and compare it with
        the repository. "18 hours old" is readable at a glance, and a
        deployment that has quietly stopped following the branch announces
        itself the moment the number stops being small.
        """
        hours = self.age_hours
        if hours is None:
            return ""
        if hours < 1:
            return "just now"
        if hours < 24:
            return f"{hours:.0f}h old"
        return f"{hours / 24:.0f}d old"

    @property
    def display(self) -> str:
        if not self.known:
            return "version unknown"
        when = f" · {self.committed_at}" if self.committed_at else ""
        return f"build {self.short}{when}"


def _read(path: Path) -> str:
    try:
        return path.read_text().strip()
    except OSError:
        return ""


def _commit_time(commit: str) -> datetime | None:
    """When this build was made, by whichever route works on a clone.

    A DEPLOY IS A FRESH CLONE, and on one the objects are PACKED. The
    original implementation read the loose object only, so on the one
    machine whose age actually matters — the live server — it always came
    back empty and the footer never showed how old the running build was.

    Three routes, cheapest-reliable first:

        the reflog, which a clone writes and which carries plain unix
        timestamps, no decompression needed;
        the loose object, for a working checkout;
        and failing both, when HEAD was last written, which on a clone is
        when the deployment happened — arguably the more useful number
        anyway, since the question is "how old is what I am looking at".
    """
    stamp = _from_reflog(commit) or _from_loose_object(commit)
    if stamp:
        return stamp
    try:
        return datetime.fromtimestamp((GIT_DIR / "HEAD").stat().st_mtime,
                                      tz=timezone.utc)
    except OSError:
        return None


def _from_reflog(commit: str) -> datetime | None:
    """The clone's own log, which every clone writes and nothing packs."""
    for line in reversed(_read(GIT_DIR / "logs" / "HEAD").splitlines()):
        parts = line.split()
        if len(parts) < 5 or not commit.startswith(parts[1][:7]):
            continue
        for token in parts:
            if token.isdigit() and len(token) >= 9:
                return datetime.fromtimestamp(int(token), tz=timezone.utc)
    return None


def _from_loose_object(commit: str) -> datetime | None:
    if len(commit) < 40:
        return None
    loose = GIT_DIR / "objects" / commit[:2] / commit[2:]
    if not loose.exists():
        return None
    try:
        import zlib

        raw = zlib.decompress(loose.read_bytes()).decode("utf-8", "replace")
    except Exception:
        return None
    for line in raw.splitlines():
        if line.startswith("committer "):
            for token in reversed(line.split()):
                if token.isdigit():
                    return datetime.fromtimestamp(int(token), tz=timezone.utc)
    return None


def current() -> Version:
    """The deployed commit, branch and time, best effort."""
    # Streamlit Cloud sets nothing useful of its own, but a self-hosted or
    # CI context often does — prefer an explicit value when one exists.
    for key in ("STREAMLIT_COMMIT_SHA", "GIT_COMMIT", "SOURCE_COMMIT"):
        value = os.environ.get(key)
        if value:
            return _version(value, os.environ.get("GIT_BRANCH", ""))

    head = _read(GIT_DIR / "HEAD")
    if not head:
        return Version()

    if head.startswith("ref:"):
        ref = head.split(" ", 1)[1].strip()
        branch = ref.rsplit("/", 1)[-1]
        commit = _read(GIT_DIR / ref)
        if not commit:
            # A packed ref: the loose file is absent and the value lives in
            # packed-refs instead. Common on a fresh clone, which is exactly
            # what a Streamlit deploy is.
            for line in _read(GIT_DIR / "packed-refs").splitlines():
                if line.endswith(f" {ref}"):
                    commit = line.split()[0]
                    break
    else:
        branch, commit = "detached", head

    return _version(commit, branch)


def _version(commit: str, branch: str) -> Version:
    stamp = _commit_time(commit)
    return Version(
        commit=commit, branch=branch,
        committed_at=(stamp.strftime("%d %b %Y · %H:%M UTC") if stamp else ""),
        committed_iso=(stamp.isoformat() if stamp else ""))
