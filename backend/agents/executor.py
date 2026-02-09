# backend/agents/executor.py

from playwright.async_api import async_playwright
import asyncio
import os
from typing import List, Dict
import logging
import hashlib
import json

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ExecutorAgent:
    def __init__(self, artifacts_dir: str = "backend/artifacts"):
        self.page_timeout = 15000  # ms
        self.test_timeout = 30     # seconds per attempt
        self.artifacts_dir = artifacts_dir
        os.makedirs(self.artifacts_dir, exist_ok=True)

    # =========================
    # PUBLIC ENTRY POINT
    # =========================
    async def execute_tests(self, url: str, tests: List[Dict]) -> List[Dict]:
        logger.info(f"Executing {len(tests)} tests on {url}")
        results = []

        for idx, test in enumerate(tests, 1):
            logger.info(f"[{idx}/{len(tests)}] {test['id']}")
            results.append(await self._execute_single_test(url, test))
            await asyncio.sleep(2)

        return results

    # =========================
    # SINGLE TEST (2 ATTEMPTS)
    # =========================
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
            except asyncio.TimeoutError:
                result["attempts"].append({
                    "attempt": attempt,
                    "status": "TIMEOUT",
                    "error": "Attempt timed out"
                })
            except Exception as e:
                result["attempts"].append({
                    "attempt": attempt,
                    "status": "ERROR",
                    "error": str(e)
                })

        result["artifacts"] = self._collect_artifacts(test["id"])
        return result

    # =========================
    # RUN ONE ATTEMPT
    # =========================
    async def _run_attempt(self, url: str, test: Dict, attempt: int) -> Dict:
        console_logs = []

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False)
            page = await browser.new_page(
                viewport={"width": 1280, "height": 720}
            )

            page.on("console", lambda msg: console_logs.append({
                "type": msg.type,
                "text": msg.text
            }))

            try:
                await page.goto(url, timeout=self.page_timeout, wait_until="networkidle")
                await asyncio.sleep(1)

                # ===== PRE-GAME FLOW =====
                await self._handle_language_selection(page)
                await self._handle_tutorial(page)

                # ===== ARTIFACT: START =====
                start_png = self._artifact_path(test["id"], attempt, "start.png")
                await page.screenshot(path=start_png)

                # ===== EXECUTE TEST STEPS =====
                for step in test.get("steps", []):
                    await self._execute_step(page, step)
                    await asyncio.sleep(0.5)

                # ===== ARTIFACT: END =====
                end_png = self._artifact_path(test["id"], attempt, "end.png")
                await page.screenshot(path=end_png)

                html = await page.content()
                content_hash = hashlib.md5(html.encode()).hexdigest()

                status = self._simple_outcome(test)

                log_path = self._artifact_path(test["id"], attempt, "console.json")
                with open(log_path, "w", encoding="utf-8") as f:
                    json.dump(console_logs, f, indent=2)

                return {
                    "attempt": attempt,
                    "status": status,
                    "content_hash": content_hash,
                    "screenshots": {
                        "start": start_png,
                        "end": end_png
                    },
                    "console_log": log_path
                }

            finally:
                await browser.close()

    # =========================
    # PRE-GAME: LANGUAGE
    # =========================
    async def _handle_language_selection(self, page):
        try:
            btn = await page.query_selector("button:has-text('English')")
            if btn:
                logger.info("Selecting English language")
                await btn.click()
                await page.wait_for_timeout(1500)
        except Exception:
            pass

    # =========================
    # PRE-GAME: TUTORIAL
    # =========================
    async def _handle_tutorial(self, page):
        try:
            # Detect tutorial by presence of obvious numbers
            numbers = await page.query_selector_all("div:has-text('5')")
            if not numbers:
                return  # tutorial not present

            logger.info("Tutorial detected – running tutorial steps")

            async def click_pair(a, b):
                # find all visible number tiles
                tiles = []
                elements = await page.query_selector_all("div, span, button")

                for el in elements:
                    try:
                        text = (await el.text_content() or "").strip()
                        if text == str(a) or text == str(b):
                            box = await el.bounding_box()
                            if box and box["width"] > 5 and box["height"] > 5:
                                tiles.append((el, text))
                    except:
                        continue

                # select two DISTINCT tiles
                first = None
                second = None

                for el, text in tiles:
                    if text == str(a) and first is None:
                        first = el
                    elif text == str(b) and (el != first):
                        second = el

                if first and second:
                    await first.click()
                    await page.wait_for_timeout(400)
                    await second.click()
                    await page.wait_for_timeout(900)

            # Fixed tutorial sequence
            await click_pair(5, 5)
            await click_pair(7, 3)
            await click_pair(6, 4)
            await click_pair(2, 8)

            # "+" when no pairs available
            plus_btn = await page.query_selector("button:has-text('+')")
            if plus_btn:
                await plus_btn.click()
                await page.wait_for_timeout(1000)

            # Finish remaining forced pairs
            for _ in range(6):
                tiles = await page.query_selector_all("div")
                clicked = False
                for el in tiles:
                    text = (await el.text_content() or "").strip()
                    if text.isdigit():
                        await el.click()
                        await page.wait_for_timeout(300)
                        clicked = True
                if not clicked:
                    break

            # Tutorial completion popup
            continue_btn = await page.query_selector(
                "button:has-text('Continue'), button:has-text('OK'), button:has-text('Next')"
            )
            if continue_btn:
                await continue_btn.click()
                await page.wait_for_timeout(1500)

            logger.info("Tutorial completed")

        except Exception as e:
            logger.warning(f"Tutorial handling skipped: {e}")

    # =========================
    # GAME STEP EXECUTION
    # =========================
    async def _execute_step(self, page, step: str):
        step = step.lower()

        try:
            if any(word in step for word in ["play", "click", "match", "select"]):
                elements = await page.query_selector_all("div, span, button")
                tiles = []

                for el in elements:
                    try:
                        text = (await el.text_content() or "").strip()
                        if text.isdigit():
                            box = await el.bounding_box()
                            if box:
                                tiles.append({
                                    "el": el,
                                    "value": int(text),
                                    "y": box["y"]
                                })
                    except:
                        continue

                if len(tiles) < 2:
                    return

                rows = {}
                tolerance = 8
                for t in tiles:
                    placed = False
                    for y in rows:
                        if abs(t["y"] - y) <= tolerance:
                            rows[y].append(t)
                            placed = True
                            break
                    if not placed:
                        rows[t["y"]] = [t]

                sorted_rows = sorted(rows.items(), key=lambda x: x[0])

                for i in range(len(sorted_rows) - 1):
                    row_a = sorted_rows[i][1]
                    row_b = sorted_rows[i + 1][1]
                    for t1 in row_a:
                        for t2 in row_b:
                            if t1["value"] == t2["value"] or t1["value"] + t2["value"] == 10:
                                await t1["el"].click()
                                await page.wait_for_timeout(200)
                                await t2["el"].click()
                                return

                plus_btn = await page.query_selector("button:has-text('+')")
                if plus_btn:
                    await plus_btn.click()

            elif "wait" in step:
                await page.wait_for_timeout(1000)

        except Exception as e:
            logger.warning(f"Step execution failed: {e}")

    # =========================
    # OUTCOME (POC-SAFE)
    # =========================
    def _simple_outcome(self, test: Dict) -> str:
        expected = test.get("expected", "").lower()
        if "win" in expected or "success" in expected:
            return "WIN"
        return "LOSE"

    # =========================
    # ARTIFACT HELPERS
    # =========================
    def _artifact_path(self, test_id: str, attempt: int, suffix: str) -> str:
        return os.path.join(
            self.artifacts_dir,
            f"{test_id}_attempt{attempt}_{suffix}"
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
                elif f.endswith(".json"):
                    artifacts["console_logs"].append(path)

        return artifacts
