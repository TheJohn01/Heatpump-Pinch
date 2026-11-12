"""Run provenance: which version of the tool and which inputs produced a result (software QA).

A result handed to a client or a reviewer must be traceable to the code and the data behind it
(Wilson et al. 2017, PLOS Comput. Biol. 13, e1005510, "Software" and "Keeping track of changes";
Barker et al. 2022, Sci. Data 9, 622, FAIR4RS principles F1-F4 and R1: identifiers, metadata, version).
Two records are kept apart, because committed outputs must stay byte-for-byte reproducible
(``regenerate_outputs.py --check``):

* ``deterministic_record`` goes into ``summary.json``: tool version and SHA-256 of every input file.
  It changes only when the code version or an input changes.
* ``run_record`` goes into ``run_metadata.json`` next to it, which git ignores: time, git commit,
  whether the working tree was clean, Python and library versions, platform.

Hashes are taken after normalising line endings (CRLF -> LF), so a checkout on Windows gives the
same hash as on Linux.
"""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
#: Libraries whose versions can change a number.
LIBRARIES = ("numpy", "pandas", "scipy", "matplotlib", "CoolProp", "openpyxl")


def tool_version() -> str:
    from pinch import __version__
    return __version__


def file_sha256(path: str | Path) -> str:
    """SHA-256 of a file's bytes with CRLF normalised to LF."""
    data = Path(path).read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def _label(path: Path) -> str:
    p = Path(path).resolve()
    try:
        return p.relative_to(ROOT).as_posix()
    except ValueError:
        return p.name


def deterministic_record(input_files: list[str | Path]) -> dict:
    """Tool version and input hashes (stable for the same code version and inputs)."""
    files = sorted({Path(f).resolve() for f in input_files if f is not None and Path(f).exists()})
    return {"tool_version": tool_version(), "inputs_sha256": {_label(f): file_sha256(f) for f in files}}


def _git(*args: str) -> str | None:
    try:
        r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=10, check=True)
        return r.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


def run_record(input_files: list[str | Path]) -> dict:
    """Everything in ``deterministic_record`` plus time, commit, environment (changes on every run)."""
    libs: dict[str, str | None] = {}
    for name in LIBRARIES:
        try:
            libs[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            libs[name] = None
    status = _git("status", "--porcelain")
    return {**deterministic_record(input_files),
            "utc_time": datetime.now(UTC).isoformat(timespec="seconds"),
            "git_commit": _git("rev-parse", "HEAD"),
            "git_tree_clean": None if status is None else status == "",
            "python": sys.version.split()[0], "platform": platform.platform(), "libraries": libs}


def write_run_record(out_dir: str | Path, input_files: list[str | Path]) -> Path:
    """Write ``run_metadata.json`` (git-ignored) to ``out_dir``."""
    out = Path(out_dir) / "run_metadata.json"
    out.write_text(json.dumps(run_record(input_files), indent=2), encoding="utf-8")
    return out
