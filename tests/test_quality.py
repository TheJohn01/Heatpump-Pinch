"""Software-quality checks run with the test suite (gap group 7): version consistency, lint, types,
provenance records.

* One version in pinch/__init__.py, pyproject.toml and CITATION.cff (FAIR4RS: Barker et al. 2022).
* ruff with the rule set in pyproject.toml over the whole repository.
* mypy over the modules that are type-clean (TYPED_MODULES); the others carry the recorded debt in
  docs/QUALITY.md, and this list may only grow.
* Provenance: deterministic records in summary.json match the input files; run metadata is git-ignored.
"""

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import pinch
from pinch.provenance import deterministic_record, file_sha256

ROOT = Path(__file__).resolve().parent.parent
TYPED_MODULES = ("area", "case", "charts", "curves", "exchanger_rating", "hen_design", "investment", "plotting",
                 "pressure_drop", "process_diagram",
                 "problem_table_algorithm", "provenance",
                 "reconciliation", "refrigerants", "restricted_matches", "results", "streams", "tariffs", "tespy_heat_pump", "theme",
                 "time_slices", "uncertainty", "utilities", "validation")


def test_one_version_everywhere():
    pyproject = re.search(r'^version = "([^"]+)"', (ROOT / "pyproject.toml").read_text(encoding="utf-8"), re.M)
    citation = re.search(r"^version: (\S+)", (ROOT / "CITATION.cff").read_text(encoding="utf-8"), re.M)
    assert pyproject and citation
    assert pinch.__version__ == pyproject.group(1) == citation.group(1)
    assert f"## {pinch.__version__}" in (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")


@pytest.mark.skipif(shutil.which("ruff") is None, reason="ruff not installed")
def test_ruff_clean():
    r = subprocess.run(["ruff", "check", "."], cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout


def test_mypy_typed_modules():
    pytest.importorskip("mypy")
    files = [str(ROOT / "pinch" / f"{m}.py") for m in TYPED_MODULES]
    r = subprocess.run([sys.executable, "-m", "mypy", "--follow-imports=silent", *files], cwd=ROOT,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout


def test_crlf_does_not_change_a_hash(tmp_path):
    a, b = tmp_path / "a.csv", tmp_path / "b.csv"
    a.write_bytes(b"x,y\n1,2\n")
    b.write_bytes(b"x,y\r\n1,2\r\n")
    assert file_sha256(a) == file_sha256(b)


def test_summary_records_version_and_input_hashes():
    s = json.loads((ROOT / "outputs" / "brewery" / "summary.json").read_text(encoding="utf-8"))
    run = s["run"]
    assert run["tool_version"] == pinch.__version__
    assert run["inputs_sha256"]["cases/brewery.json"] == file_sha256(ROOT / "cases" / "brewery.json")
    assert run["inputs_sha256"]["data/brewery_streams.csv"] == file_sha256(ROOT / "data" / "brewery_streams.csv")
    assert deterministic_record([ROOT / "cases" / "brewery.json"]) == deterministic_record([ROOT / "cases" / "brewery.json"])


def test_run_metadata_is_ignored_by_git():
    if shutil.which("git") is None or not (ROOT / ".git").exists():
        pytest.skip("not a git checkout")
    r = subprocess.run(["git", "check-ignore", "-q", "outputs/brewery/run_metadata.json"], cwd=ROOT)
    assert r.returncode == 0


def test_png_tolerance_separates_rasterisation_from_real_changes():
    """regenerate_outputs.png_change: text antialiasing passes, a moved curve or a size change fails."""
    import io as _io

    import numpy as np
    from PIL import Image, ImageDraw

    import regenerate_outputs as reg

    def png(img: Image.Image) -> bytes:
        buf = _io.BytesIO()
        img.save(buf, "PNG")
        return buf.getvalue()

    base = Image.new("L", (400, 300), 255)
    d = ImageDraw.Draw(base)
    d.line([(20, 250), (380, 40)], fill=0, width=2)
    d.text((50, 40), "Q_h,min 10.04 kWh/hl", fill=0)
    a = png(base)
    noisy = np.asarray(base, dtype=int).copy()
    rng = np.random.default_rng(0)                      # antialiasing: edge pixels shift by up to 60 levels
    edges = np.argwhere(noisy < 255)
    for y, x in edges[rng.choice(len(edges), len(edges) // 2, replace=False)]:
        noisy[y, x] = min(255, noisy[y, x] + 60)
    assert reg.png_change(a, png(Image.fromarray(noisy.astype("uint8")))) <= reg.PNG_TOLERANCE
    moved = base.copy()
    ImageDraw.Draw(moved).line([(20, 200), (380, 60)], fill=0, width=3)
    assert reg.png_change(a, png(moved)) > reg.PNG_TOLERANCE
    assert reg.png_change(a, png(base.resize((401, 300)))) == float("inf")
