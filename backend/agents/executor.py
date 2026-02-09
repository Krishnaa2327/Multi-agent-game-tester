# backend/agents/executor.py

from playwright.async_api import async_playwright
import asyncio
import os
import hashlib
import logging
from typing import List, Dict

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ExecutorAgent:
    def __init__(self, artifacts_dir: str = "backend/artifacts"):
        self.page_timeout = 15000
        self.test_timeout = 30
        self.artifacts_dir = artifacts_dir
        os.makedirs(self.artifacts_dir, exist_ok=True)

    # =====================================================
    # PUBLIC ENTRY
    # =====================================================
    async def execute_tests(self, url: str, tests: List[Dict]) -> List[Dict]:
        results = []

        for idx, test in enumerate(tests, 1):
            logger.info(f"[{idx}/{len(tests)}] Executing {test['id']}")
            results.append(await self._execute_single_test(url, test))
            await asyncio.sleep(2)

        return results

    # =====================================================
    # SINGLE TEST (2 ATTEMPTS)
    # =====================================================
    async def _execute_single_test(self, url: str, test: Dict) -> Dict:
        result = {
            "test_id": test["id"],
            "test_name": test.get("category", ""),
            "steps": test.get("steps", []),
            "expected": test.get("expected", ""),
            "attempts": [],
            "artifacts": {}
        }

        for attempt in (1, 2):
            try:
                attempt_result = await asyncio.wait_for(
                    self._run_attempt(url, test, attempt),
                    timeout=self.test_timeout
                )
                result["attempts"].append(attempt_result)
            except Exception as e:
                result["attempts"].append({
                    "attempt": attempt,
                    "status": "ERROR",
                    "error": str(e)
                })

        result["artifacts"] = self._collect_artifacts(test["id"])
        return result

    # =====================================================
    # RUN ONE ATTEMPT
    # =====================================================
    async def _run_attempt(self, url: str, test: Dict, attempt: int) -> Dict:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page(viewport={"width": 1280, "height": 720})

            try:
                await page.goto(url, timeout=self.page_timeout, wait_until="networkidle")
                await asyncio.sleep(1)

                # Language selection (if present)
                await self._select_english(page)

                # Tutorial / gameplay uses same logic
                for _ in range(12):
                    moved = await self._play_one_valid_move(page)
                    if not moved:
                        plus = await page.query_selector("button:has-text('+')")
                        if plus:
                            await plus.click()
                            await page.wait_for_timeout(800)
                        else:
                            break

                start_png = self._artifact_path(test["id"], attempt, "start.png")
                await page.screenshot(path=start_png)

                for step in test.get("steps", []):
                    if any(w in step.lower() for w in ["play", "match", "click"]):
                        moved = await self._play_one_valid_move(page)
                        if not moved:
                            plus = await page.query_selector("button:has-text('+')")
                            if plus:
                                await plus.click()
                                await page.wait_for_timeout(800)
                    elif "wait" in step.lower():
                        await page.wait_for_timeout(1000)

                end_png = self._artifact_path(test["id"], attempt, "end.png")
                await page.screenshot(path=end_png)

                html = await page.content()
                content_hash = hashlib.md5(html.encode()).hexdigest()

                return {
                    "attempt": attempt,
                    "status": "PASS",
                    "content_hash": content_hash,
                    "screenshots": {
                        "start": start_png,
                        "end": end_png
                    }
                }

            finally:
                await browser.close()

    # =====================================================
    # LANGUAGE SELECTION
    # =====================================================
    async def _select_english(self, page):
        try:
            btn = await page.query_selector("button:has-text('English')")
            if btn:
                logger.info("Selecting English language")
                await btn.click()
                await page.wait_for_timeout(1500)
        except:
            pass

    # =====================================================
    # CORE GAME LOGIC (FINAL)
    # =====================================================
    async def _play_one_valid_move(self, page) -> bool:
        """
        Plays exactly ONE valid move according to locked game rules.
        Returns True if a pair was played, False if no valid pair exists.
        """

        elements = await page.query_selector_all("div, span, button")
        tiles = []

        # Collect ACTIVE tiles only
        for el in elements:
            try:
                text = (await el.text_content() or "").strip()
                if not text.isdigit():
                    continue

                box = await el.bounding_box()
                if not box or box["width"] < 10 or box["height"] < 10:
                    continue

                opacity = await el.evaluate(
                    "el => window.getComputedStyle(el).opacity"
                )
                if opacity and float(opacity) < 0.9:
                    continue  # inactive tile

                tiles.append({
                    "el": el,
                    "value": int(text),
                    "x": box["x"] + box["width"] / 2,
                    "y": box["y"] + box["height"] / 2
                })
            except:
                continue

        if len(tiles) < 2:
            return False

        best_pair = None
        best_dist = float("inf")

        # Find valid (A, B) pairs
        for i, a in enumerate(tiles):
            for j, b in enumerate(tiles):
                if i == j:
                    continue

                if not (a["value"] == b["value"] or a["value"] + b["value"] == 10):
                    continue

                dx = a["x"] - b["x"]
                dy = a["y"] - b["y"]
                dist = (dx * dx + dy * dy) ** 0.5

                if dist < best_dist:
                    best_dist = dist
                    best_pair = (a["el"], b["el"])

        if best_pair:
            first, second = best_pair
            await first.click()
            await page.wait_for_timeout(250)  # blue highlight
            await second.click()
            await page.wait_for_timeout(500)
            return True

        return False

    # =====================================================
    # ARTIFACT HELPERS
    # =====================================================
    def _artifact_path(self, test_id: str, attempt: int, name: str) -> str:
        return os.path.join(
            self.artifacts_dir,
            f"{test_id}_attempt{attempt}_{name}"
        )

    def _collect_artifacts(self, test_id: str) -> Dict:
        artifacts = {
            "screenshots": [],
            "console_logs": []
        }

        for f in os.listdir(self.artifacts_dir):
            if f.startswith(test_id):
                path = os.path.join(self.artifacts_dir, f)
                if f.endswith(".png"):
                    artifacts["screenshots"].append(path)

        return artifacts
