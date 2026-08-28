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

    @property
    def short(self) -> str:
        return self.commit[:7] if self.commit else "unknown"

    @property
    def known(self) -> bool:
        return bool(self.commit)

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


def _commit_time(commit: str) -> str:
    """The commit's timestamp, if it can be had cheaply.

    Loose object files are zlib-compressed and packed objects are not
    readable without implementing packfile parsing, which is far more
    machinery than a footer line justifies. So this tries the loose object
    and gives up quietly otherwise — the commit hash alone answers the
    question that matters.
    """
    if len(commit) < 40:
        return ""
    loose = GIT_DIR / "objects" / commit[:2] / commit[2:]
    if not loose.exists():
        return ""
    try:
        import zlib

        raw = zlib.decompress(loose.read_bytes()).decode("utf-8", "replace")
    except Exception:
        return ""
    for line in raw.splitlines():
        if line.startswith("committer "):
            parts = line.split()
            for token in reversed(parts):
                if token.isdigit():
                    stamp = datetime.fromtimestamp(int(token), tz=timezone.utc)
                    return stamp.strftime("%d %b %Y · %H:%M UTC")
    return ""


def current() -> Version:
    """The deployed commit, branch and time, best effort."""
    # Streamlit Cloud sets nothing useful of its own, but a self-hosted or
    # CI context often does — prefer an explicit value when one exists.
    for key in ("STREAMLIT_COMMIT_SHA", "GIT_COMMIT", "SOURCE_COMMIT"):
        value = os.environ.get(key)
        if value:
            return Version(commit=value, branch=os.environ.get("GIT_BRANCH", ""),
                           committed_at=_commit_time(value))

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

    return Version(commit=commit, branch=branch, committed_at=_commit_time(commit))
