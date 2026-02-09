# backend/agents/analyzer.py

import json
import os
from datetime import datetime
from typing import List, Dict
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class AnalyzerAgent:
    def __init__(self, reports_dir: str = "backend/reports"):
        self.reports_dir = reports_dir
        os.makedirs(self.reports_dir, exist_ok=True)

    def analyze_and_report(self, game_info: Dict, test_results: List[Dict]) -> Dict:
        """
        Main entry point:
        - Validates test results
        - Generates final JSON report
        """
        logger.info(f"Analyzing {len(test_results)} test results")

        validated_results = []
        for result in test_results:
            verdict_info = self._validate_test(result)
            validated_results.append({
                **result,
                "verdict": verdict_info["verdict"],
                "reproducibility_score": verdict_info["score"],
                "validation_notes": verdict_info["notes"]
            })

        report = self._generate_report(game_info, validated_results)

        report_path = os.path.join(
            self.reports_dir, f"{report['report_id']}.json"
        )
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)

        logger.info(f"Report saved at {report_path}")
        return report

    def _validate_test(self, result: Dict) -> Dict:
        """
        Validate a test using repeat execution (2 attempts).
        """
        attempts = result.get("attempts", [])

        if len(attempts) < 2:
            return {
                "verdict": "ERROR",
                "score": 0.0,
                "notes": "Insufficient attempts for validation"
            }

        a1, a2 = attempts[0], attempts[1]
        s1 = a1.get("status", "ERROR")
        s2 = a2.get("status", "ERROR")

        # Both attempts failed hard
        if s1 in ["ERROR", "TIMEOUT"] and s2 in ["ERROR", "TIMEOUT"]:
            return {
                "verdict": "ERROR",
                "score": 0.0,
                "notes": "Both attempts failed to execute"
            }

        # One failed, one succeeded
        if s1 in ["ERROR", "TIMEOUT"] or s2 in ["ERROR", "TIMEOUT"]:
            return {
                "verdict": "FLAKY",
                "score": 0.5,
                "notes": "One attempt failed, one succeeded"
            }

        # Same outcome
        if s1 == s2:
            if s1 == "WIN":
                verdict = "PASS"
                notes = "Test passed consistently"
            elif s1 == "LOSE":
                verdict = "FAIL"
                notes = "Test failed consistently"
            else:
                verdict = "ERROR"
                notes = "Consistent but invalid outcome"

            # Optional content hash check (non-blocking)
            h1 = a1.get("content_hash")
            h2 = a2.get("content_hash")

            if h1 and h2 and h1 == h2:
                score = 1.0
                notes += " (identical page state)"
            else:
                score = 0.8
                notes += " (state variation allowed)"

            return {
                "verdict": verdict,
                "score": score,
                "notes": notes
            }

        # Different outcomes → flaky
        return {
            "verdict": "FLAKY",
            "score": 0.0,
            "notes": f"Inconsistent results: {s1} vs {s2}"
        }

    def _generate_report(self, game_info: Dict, results: List[Dict]) -> Dict:
        timestamp = datetime.now()
        report_id = f"report_{timestamp.strftime('%Y%m%d_%H%M%S')}"

        verdicts = [r["verdict"] for r in results]

        summary = {
            "total_tests": len(results),
            "passed": verdicts.count("PASS"),
            "failed": verdicts.count("FAIL"),
            "flaky": verdicts.count("FLAKY"),
            "errors": verdicts.count("ERROR"),
            "avg_reproducibility": (
                sum(r.get("reproducibility_score", 0) for r in results) / len(results)
                if results else 0
            )
        }

        return {
            "report_id": report_id,
            "timestamp": timestamp.isoformat(),
            "game_url": game_info.get("url", "unknown"),
            "game_analysis": {
                "type": game_info.get("type", "unknown"),
                "rules": game_info.get("rules", "unknown"),
                "win_condition": game_info.get("win_condition", "unknown")
            },
            "summary": summary,
            "test_results": results,
            "triage_notes": self._generate_triage_notes(results),
            "recommendations": self._generate_recommendations(summary)
        }

    def _generate_triage_notes(self, results: List[Dict]) -> List[str]:
        notes = []

        for r in results:
            tid = r.get("test_id", "UNKNOWN")
            verdict = r.get("verdict", "UNKNOWN")
            v_notes = r.get("validation_notes", "")

            if verdict in ["FAIL", "FLAKY", "ERROR"]:
                notes.append(f"{tid} [{verdict}]: {v_notes}")

        if not notes:
            notes.append("No issues detected. All tests passed successfully.")

        return notes

    def _generate_recommendations(self, summary: Dict) -> List[str]:
        recs = []

        if summary["errors"] > summary["total_tests"] * 0.3:
            recs.append(
                "High error rate detected. Consider increasing timeouts "
                "and improving wait conditions."
            )

        if summary["flaky"] > summary["total_tests"] * 0.2:
            recs.append(
                "High flaky rate detected. Game behavior may be non-deterministic "
                "or tests may have timing issues."
            )

        if summary["failed"] > 0:
            recs.append(
                "Failing tests detected. Review artifacts and triage notes "
                "for potential bugs."
            )

        if summary["passed"] == summary["total_tests"]:
            recs.append(
                "All tests passed. Consider adding more edge or stress tests."
            )

        return recs
