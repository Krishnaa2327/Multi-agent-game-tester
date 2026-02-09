# backend/agents/game_analyzer.py

from playwright.async_api import async_playwright
import ollama
import base64
import json
import asyncio
from typing import Dict
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class GameAnalyzerAgent:
    def __init__(self, vision_model: str = "llava:7b"):
        self.vision_model = vision_model
        self.page_timeout = 15000  # 15 seconds

    async def analyze_game(self, url: str) -> Dict:
        """
        Main entry point:
        - Uses vision model for game understanding
        - Uses Playwright for high-level UI capability detection
        """
        logger.info(f"Analyzing game at {url}")

        try:
            screenshot = await self._capture_screenshot(url)
            game_understanding = await self._analyze_with_vision(screenshot)
            ui_capabilities = await self._detect_ui_capabilities(url)

            return {
                "url": url,
                "type": game_understanding.get("type", "unknown"),
                "rules": game_understanding.get("rules", "No rules extracted"),
                "win_condition": game_understanding.get(
                    "win_condition", "Unknown"
                ),
                "ui_capabilities": ui_capabilities
            }

        except Exception as e:
            logger.error(f"Game analysis failed: {e}")
            return {
                "url": url,
                "type": "error",
                "rules": "Analysis failed",
                "win_condition": "unknown",
                "ui_capabilities": {}
            }

    async def _capture_screenshot(self, url: str) -> bytes:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                viewport={"width": 1280, "height": 720}
            )
            page = await context.new_page()

            try:
                await page.goto(
                    url,
                    timeout=self.page_timeout,
                    wait_until="networkidle"
                )
                await asyncio.sleep(2)
                return await page.screenshot(full_page=False)
            finally:
                await browser.close()

    async def _analyze_with_vision(self, screenshot_bytes: bytes) -> Dict:
        image_b64 = base64.b64encode(screenshot_bytes).decode()

        prompt = """
Analyze this game screenshot and respond ONLY with valid JSON.

Identify:
1. Game Type (e.g., "number puzzle", "math game")
2. Rules (how the game works)
3. Win Condition (what defines success)

Return exactly:
{
  "type": "...",
  "rules": "...",
  "win_condition": "..."
}
"""

        try:
            response = ollama.chat(
                model=self.vision_model,
                messages=[{
                    "role": "user",
                    "content": prompt,
                    "images": [image_b64]
                }]
            )

            text = response["message"]["content"]

            if "```" in text:
                text = text.split("```")[1]

            return json.loads(text.strip())

        except Exception as e:
            logger.warning(f"Vision analysis fallback used: {e}")
            return {
                "type": "puzzle game",
                "rules": "Interact with elements to solve the puzzle",
                "win_condition": "Reach the game objective"
            }

    async def _detect_ui_capabilities(self, url: str) -> Dict:
        """
        Detects high-level UI capabilities.
        No selectors. No element metadata.
        """
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()

            try:
                await page.goto(
                    url,
                    timeout=self.page_timeout,
                    wait_until="networkidle"
                )
                await asyncio.sleep(2)

                return {
                    "has_buttons": bool(
                        await page.query_selector("button")
                    ),
                    "has_inputs": bool(
                        await page.query_selector("input")
                    ),
                    "has_canvas": bool(
                        await page.query_selector("canvas")
                    ),
                    "has_grid_like_ui": bool(
                        await page.query_selector(
                            '[class*="grid"], [id*="grid"]'
                        )
                    )
                }

            finally:
                await browser.close()
