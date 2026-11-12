"""Browser smoke test of the Streamlit app (paths the unit tests cannot reach).

Usage (needs Playwright + Chromium):
    streamlit run app.py --server.headless true --server.port 8601 &
    python tests/ui_smoke.py

Checks: (0) the process diagrams are drawn as inline SVG in the browser (Workflow step 1 flowsheet,
Dashboard T* diagram); ``st.html`` sanitises ``<svg>`` away, which streamlit.testing does not see.
(0b) the two TEA report buttons of the Dashboard download a PDF and a Word file (written on click, in a
separate thread, which streamlit.testing does not run).
Data input: (4) a saved project file reopens the edited inputs after a case change; (5) an Aspen Plus export
(zip of tests/fixtures/aspen_export) goes through Guided extraction to a stream table with the known Q̇c,min.
Workflow page: (1) uploading a stream CSV gives targets; (2) a CSV with missing columns
gives an input message, not a crash; (3) editing a cell of the stream table
re-computes the targets (four-stream example: CP of Reactor 1 feed 0.2 -> 0.3
moves Q̇h,min from 7.5 to 13.5 MW, the problem-table answer).
Verified 2026-10-14.
"""

import asyncio
import tempfile
import zipfile
from pathlib import Path

from playwright.async_api import async_playwright

URL = "http://localhost:8601"   # streamlit run app.py --server.port 8601
ROOT = Path(__file__).resolve().parents[1]   # repository root


async def _metric(pg) -> str:
    t = await pg.inner_text("body")
    i = t.find("Q̇h,min")
    return t[i:i + 22].replace("\n", " ")


async def _svgs(pg) -> list[str]:
    return await pg.evaluate("Array.from(document.querySelectorAll('svg[role=img] > title')).map(t => t.textContent)")


def _uploader(pg, label: str):
    """The file input of the uploader whose label contains ``label`` (several uploaders share the page)."""
    return pg.locator('[data-testid="stFileUploader"]').filter(has_text=label).locator('input[type="file"]')


async def main() -> None:
    async with async_playwright() as p:
        b = await p.chromium.launch()
        pg = await b.new_page(viewport={"width": 1500, "height": 1300})
        await pg.goto(URL)
        await pg.wait_for_timeout(15000)
        # 0: diagrams visible (brewery flowsheet; T* diagram on the Dashboard)
        assert any(t.startswith("Simplified flowsheet") for t in await _svgs(pg)), await _svgs(pg)
        await pg.get_by_text("Dashboard", exact=True).first.click()
        await pg.wait_for_timeout(20000)
        assert any(t.startswith("Streams on the shifted") for t in await _svgs(pg)), await _svgs(pg)
        # 0b: TEA report downloads
        for label, magic in (("TEA report (PDF)", b"%PDF-"), ("TEA report (Word)", b"PK")):
            async with pg.expect_download(timeout=120000) as dl:
                await pg.get_by_role("button", name=label).click()
            data = Path(await (await dl.value).path()).read_bytes()
            assert data[:len(magic)] == magic and len(data) > 100_000, (label, len(data))
        await pg.get_by_text("Workflow", exact=True).first.click()
        await pg.wait_for_timeout(8000)
        case_box = pg.locator('[data-testid="stSelectbox"]').first
        # 1-2: upload a CSV, then a malformed one (step 1, left panel)
        await case_box.click()
        await pg.get_by_text("Upload my own stream table").click()
        await pg.wait_for_timeout(3000)
        await _uploader(pg, "Stream table (CSV)").set_input_files(str(ROOT / "data" / "four_stream_process_streams.csv"))
        await pg.wait_for_timeout(9000)
        await pg.get_by_text("2 Targets", exact=True).first.click()
        await pg.wait_for_timeout(7000)
        assert "7.5" in await _metric(pg), await _metric(pg)
        await pg.get_by_text("1 Streams", exact=True).first.click()
        await pg.wait_for_timeout(4000)
        bad = Path(tempfile.mkdtemp()) / "bad.csv"
        bad.write_text("stream,type,T_in_C\nA,hot,100\n")
        await _uploader(pg, "Stream table (CSV)").set_input_files(str(bad))
        await pg.wait_for_timeout(7000)
        t = await pg.inner_text("body")
        assert "Input problem" in t and "missing columns" in t, "bad CSV not reported"
        # 3: published four-stream case, edit a cell, check the targets
        await case_box.click()
        await pg.get_by_role("option", name="Four-stream chemical process").click()
        await pg.wait_for_timeout(9000)
        assert "Four-stream chemical process" in await pg.inner_text("body")
        grid = await pg.locator('[data-testid="stDataFrameResizable"]:visible').last.bounding_box()
        await pg.mouse.click(grid["x"] + 80, grid["y"] + 54)          # first cell of the first row
        await pg.wait_for_timeout(500)
        for _ in range(4):                                             # -> CP column (5th)
            await pg.keyboard.press("ArrowRight")
        await pg.keyboard.press("Enter")
        await pg.wait_for_timeout(500)
        await pg.keyboard.press("Control+A")
        await pg.keyboard.type("0.3")
        await pg.wait_for_timeout(500)
        await pg.keyboard.press("Enter")
        await pg.wait_for_timeout(8000)
        await pg.get_by_text("2 Targets", exact=True).first.click()
        await pg.wait_for_timeout(7000)
        assert "13.5" in await _metric(pg), await _metric(pg)
        # 4: save the edited project, switch case, reopen it
        await pg.get_by_text("1 Streams", exact=True).first.click()
        await pg.wait_for_timeout(5000)
        await pg.get_by_text("Project file", exact=True).first.click()
        await pg.wait_for_timeout(1000)
        async with pg.expect_download(timeout=60000) as dl:
            await pg.get_by_role("button", name="Save project (.json)").click()
        saved = Path(tempfile.mkdtemp()) / "four_stream_project.json"
        saved.write_bytes(Path(await (await dl.value).path()).read_bytes())
        assert b'"format": "heatpump-pinch project"' in saved.read_bytes()
        await case_box.click()
        await pg.get_by_role("option", name="Brewery").first.click()
        await pg.wait_for_timeout(9000)
        await _uploader(pg, "Open a project").set_input_files(str(saved))
        await pg.wait_for_timeout(9000)
        await pg.get_by_text("2 Targets", exact=True).first.click()
        await pg.wait_for_timeout(7000)
        assert "13.5" in await _metric(pg), ("project not reopened", await _metric(pg))
        # 5: Aspen Plus export -> guided extraction -> stream table
        await pg.get_by_text("1 Streams", exact=True).first.click()
        await pg.wait_for_timeout(5000)
        export = ROOT / "tests" / "fixtures" / "aspen_export"
        zpath = Path(tempfile.mkdtemp()) / "export.zip"
        with zipfile.ZipFile(zpath, "w") as z:
            for f in export.rglob("*.csv"):
                z.write(f, f"export/{f.relative_to(export).as_posix()}")
        await pg.get_by_role("tab", name="Import from Aspen Plus").click()
        await _uploader(pg, "Export folder (.zip)").set_input_files(str(zpath))
        await pg.wait_for_timeout(4000)
        await pg.get_by_role("button", name="Load the candidate streams into Guided extraction").click()
        await pg.wait_for_timeout(5000)
        assert "4 candidate streams, 1 left out" in await pg.inner_text("body")
        await pg.get_by_role("tab", name="Guided extraction").click()
        await pg.get_by_role("button", name="Use as stream table").click()
        await pg.wait_for_timeout(9000)
        await pg.get_by_text("2 Targets", exact=True).first.click()
        await pg.wait_for_timeout(7000)
        body = await pg.inner_text("body")
        i = body.find("Q̇c,min")
        assert i >= 0 and "500" in body[i:i + 30], body[i:i + 30]
        await b.close()
    print("UI smoke test passed: diagrams, TEA report downloads, upload, bad input, cell edit, project file, "
          "Aspen import")


if __name__ == "__main__":
    asyncio.run(main())
