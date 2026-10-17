"""Browser smoke test of the Streamlit app (paths the unit tests cannot reach).

Usage (needs Playwright + Chromium):
    streamlit run app.py --server.headless true --server.port 8601 &
    python ui_smoke.py

Checks (Workflow page): (1) uploading a stream CSV gives targets; (2) a CSV with missing columns
gives an input message, not a crash; (3) editing a cell of the stream table
re-computes the targets (four-stream example: CP of Reactor 1 feed 0.2 -> 0.3
moves Q̇h,min from 7.5 to 13.5 MW, the problem-table answer).
Verified 2026-10-14.
"""

import asyncio
import tempfile
from pathlib import Path

from playwright.async_api import async_playwright

URL = "http://localhost:8601"   # streamlit run app.py --server.port 8601
ROOT = Path(__file__).resolve().parent


async def _metric(pg) -> str:
    t = await pg.inner_text("body")
    i = t.find("Q̇h,min")
    return t[i:i + 22].replace("\n", " ")


async def main() -> None:
    async with async_playwright() as p:
        b = await p.chromium.launch()
        pg = await b.new_page(viewport={"width": 1500, "height": 1300})
        await pg.goto(URL)
        await pg.wait_for_timeout(15000)
        case_box = pg.locator('[data-testid="stSelectbox"]').first
        # 1-2: upload a CSV, then a malformed one (step 1, left panel)
        await case_box.click()
        await pg.get_by_text("Upload my own stream table").click()
        await pg.wait_for_timeout(3000)
        await pg.locator('input[type="file"]').set_input_files(str(ROOT / "data" / "four_stream_process_streams.csv"))
        await pg.wait_for_timeout(9000)
        await pg.get_by_text("2 Targets", exact=True).first.click()
        await pg.wait_for_timeout(7000)
        assert "7.5" in await _metric(pg), await _metric(pg)
        await pg.get_by_text("1 Streams", exact=True).first.click()
        await pg.wait_for_timeout(4000)
        bad = Path(tempfile.mkdtemp()) / "bad.csv"
        bad.write_text("stream,type,T_in_C\nA,hot,100\n")
        await pg.locator('input[type="file"]').set_input_files(str(bad))
        await pg.wait_for_timeout(7000)
        t = await pg.inner_text("body")
        assert "Input problem" in t and "missing columns" in t, "bad CSV not reported"
        # 3: published four-stream case, edit a cell, check the targets
        await case_box.click()
        await pg.get_by_role("option", name="four_stream_process").click()
        await pg.wait_for_timeout(9000)
        assert "four_stream_process" in await pg.inner_text("body")
        grid = await pg.locator('[data-testid="stDataFrameResizable"]').first.bounding_box()
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
        await b.close()
    print("UI smoke test passed: upload, bad input, cell edit")


if __name__ == "__main__":
    asyncio.run(main())
