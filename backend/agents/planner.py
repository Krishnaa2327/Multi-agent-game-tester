# backend/agents/planner.py

from langchain.prompts import PromptTemplate
from langchain_community.llms import Ollama
from langchain.chains import LLMChain
import json
import os
from typing import List, Dict
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class PlannerAgent:
    def __init__(self, memory_file: str = "backend/memory/history.json"):
        self.llm = Ollama(model="llama3.2:3b", temperature=0.7)
        self.memory_file = memory_file
        self._ensure_memory_exists()

    def _ensure_memory_exists(self):
        os.makedirs(os.path.dirname(self.memory_file), exist_ok=True)
        if not os.path.exists(self.memory_file):
            with open(self.memory_file, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "successful_tests": [],
                        "failed_patterns": []
                    },
                    f,
                    indent=2
                )

    def generate_and_rank_tests(self, game_info: Dict) -> List[Dict]:
        logger.info(f"Generating tests for {game_info.get('type', 'unknown')}")

        memory = self._load_memory()
        tests = self._generate_tests(game_info, memory)

        while len(tests) < 20:
            tests.append(self._create_fallback_test(len(tests) + 1))

        ranked = self._rank_tests(tests)
        top_10 = self._select_diverse_top_tests(ranked, limit=10)

        logger.info("Generated 20 tests, selected diverse top 10")
        return top_10

    def _generate_tests(self, game_info: Dict, memory: Dict) -> List[Dict]:
        prompt = PromptTemplate(
            input_variables=["game_type", "rules", "win_condition"],
            template="""Generate exactly 20 test cases for this game.

Game Type: {game_type}
Rules: {rules}
Win Condition: {win_condition}

Rules:
- Each test must have 3–5 steps max
- Categories:
  Happy Path (6)
  Edge Case (6)
  Invalid Input (4)
  Stress Test (4)

Format EXACTLY:
TEST_01|Happy Path|HIGH|step1 > step2 > step3|expected result

Generate TEST_01 through TEST_20:"""
        )

        try:
            chain = LLMChain(llm=self.llm, prompt=prompt)
            output = chain.run(
                game_type=game_info.get("type", "game"),
                rules=game_info.get("rules", ""),
                win_condition=game_info.get("win_condition", "")
            )
            return self._parse_tests(output)
        except Exception as e:
            logger.error(f"LLM generation failed: {e}")
            return [self._create_fallback_test(i) for i in range(1, 21)]

    def _parse_tests(self, text: str) -> List[Dict]:
        tests = []
        for line in text.splitlines():
            if not line.strip().startswith("TEST_"):
                continue

            parts = [p.strip() for p in line.split("|")]
            if len(parts) < 5:
                continue

            tests.append({
                "id": parts[0],
                "category": parts[1],
                "priority": parts[2],
                "steps": [s.strip() for s in parts[3].split(">")],
                "expected": parts[4],
                "score": 0
            })

        return tests

    def _create_fallback_test(self, num: int) -> Dict:
        categories = ["Happy Path", "Edge Case", "Invalid Input", "Stress Test"]
        priorities = ["HIGH", "MEDIUM", "LOW"]

        return {
            "id": f"TEST_{num:02d}",
            "category": categories[num % 4],
            "priority": priorities[num % 3],
            "steps": ["Open game", "Perform action", "Check result"],
            "expected": "Should behave correctly",
            "score": 0
        }

    def _rank_tests(self, tests: List[Dict]) -> List[Dict]:
        for t in tests:
            score = 0
            score += {"HIGH": 10, "MEDIUM": 5, "LOW": 2}.get(t["priority"], 2)
            score += {
                "Happy Path": 8,
                "Edge Case": 7,
                "Invalid Input": 6,
                "Stress Test": 5
            }.get(t["category"], 3)
            score += min(len(t["steps"]), 5)
            t["score"] = score

        return sorted(tests, key=lambda x: x["score"], reverse=True)

    def _select_diverse_top_tests(self, tests: List[Dict], limit: int) -> List[Dict]:
        selected = []
        category_count = {}

        for t in tests:
            cat = t["category"]
            if category_count.get(cat, 0) >= 4:
                continue

            selected.append(t)
            category_count[cat] = category_count.get(cat, 0) + 1

            if len(selected) == limit:
                break

        return selected

    def _load_memory(self) -> Dict:
        try:
            with open(self.memory_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {
                "successful_tests": [],
                "failed_patterns": []
            }
