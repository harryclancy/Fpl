"""Checks that must pass before anything reaches the deployed branch.

Streamlit Community Cloud redeploys automatically on push. That is the
behaviour we want, and it is also why a broken push is worse here than in
a normal repo: there is no staging step between the commit and the live
site. A syntax error reaches the app before anyone notices.

So this is the gate. It is deliberately fast and dependency-free — the
whole point is that it runs every time rather than being skipped because
it takes a minute.

Free: it runs locally or in GitHub Actions' free tier and calls no
external service.
"""
import ast
import importlib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Imported to prove they load. The dashboard is the one that actually
# matters — a NameError in a rendering function only raises when Streamlit
# executes it, which is on the live site.
CRITICAL_MODULES = (
    "fpl_assistant.api",
    "fpl_assistant.config",
    "fpl_assistant.models",
    "fpl_assistant.version",
    "fpl_assistant.analysis.dossier",
    "fpl_assistant.analysis.freshness",
    "fpl_assistant.analysis.optimiser",
    "fpl_assistant.analysis.squad_builder",
    "fpl_assistant.analysis.transfer_case",
    "fpl_assistant.research.completeness",
    "fpl_assistant.research.sources",
)

ENTRY_POINT = ROOT / "fpl_assistant" / "dashboard" / "app.py"


def check_syntax() -> list[str]:
    problems = []
    for path in ROOT.rglob("*.py"):
        if any(part in ("__pycache__", ".venv", "venv") for part in path.parts):
            continue
        try:
            ast.parse(path.read_text())
        except SyntaxError as exc:
            problems.append(f"{path.relative_to(ROOT)}: {exc}")
    return problems


def check_imports() -> list[str]:
    problems = []
    sys.path.insert(0, str(ROOT))
    for name in CRITICAL_MODULES:
        try:
            importlib.import_module(name)
        except Exception as exc:
            problems.append(f"{name}: {type(exc).__name__}: {exc}")
    return problems


def check_requirements() -> list[str]:
    """Every third-party import in the app is declared.

    A package that happens to be installed locally but missing from
    requirements.txt works perfectly here and fails on deploy — which is
    the exact class of error that sends someone to the Reboot button.
    """
    path = ROOT / "requirements.txt"
    if not path.exists():
        return ["requirements.txt is missing"]
    declared = {
        line.split("=")[0].split(">")[0].split("<")[0].split("[")[0].strip().lower()
        for line in path.read_text().splitlines()
        if line.strip() and not line.startswith("#")
    }
    aliases = {"pulp": "pulp", "streamlit": "streamlit", "pandas": "pandas",
               "requests": "requests", "dotenv": "python-dotenv", "numpy": "pandas"}
    problems = []
    for source in ROOT.joinpath("fpl_assistant").rglob("*.py"):
        try:
            tree = ast.parse(source.read_text())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module.split(".")[0]]
            for name in names:
                if name in ("fpl_assistant",) or name in sys.stdlib_module_names:
                    continue
                package = aliases.get(name, name)
                if package.lower() not in declared:
                    problems.append(f"{source.relative_to(ROOT)} imports {name!r}, not in requirements.txt")
    return sorted(set(problems))


def check_entry_point() -> list[str]:
    if not ENTRY_POINT.exists():
        return [f"entry point missing: {ENTRY_POINT.relative_to(ROOT)}"]
    source = ENTRY_POINT.read_text()
    if "def main(" not in source:
        return ["the entry point has no main()"]
    return []


def check_smoke() -> list[str]:
    """The one test that actually executes every rendering path."""
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_app_smoke.py", "-q", "--no-header"],
        cwd=ROOT, capture_output=True, text=True,
    )
    if result.returncode != 0:
        tail = (result.stdout or result.stderr).strip().splitlines()[-6:]
        return ["the app smoke test failed:"] + [f"    {line}" for line in tail]
    return []


CHECKS = (
    ("Python syntax", check_syntax),
    ("Critical imports", check_imports),
    ("Requirements complete", check_requirements),
    ("Streamlit entry point", check_entry_point),
    ("App smoke test", check_smoke),
)


def main() -> int:
    failures = 0
    for label, check in CHECKS:
        problems = check()
        if problems:
            failures += 1
            print(f"✗ {label}")
            for problem in problems:
                print(f"    {problem}")
        else:
            print(f"✓ {label}")
    if failures:
        print(f"\n{failures} check(s) failed — do NOT push. "
              f"Streamlit deploys automatically, so this would go straight to the live app.")
        return 1
    print("\nAll preflight checks passed — safe to push.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
