# backend/api/main.py

from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, HttpUrl
import asyncio
import os
import sys
import logging

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from agents.game_analyzer import GameAnalyzerAgent
from agents.planner import PlannerAgent
from agents.executor import ExecutorAgent
from agents.analyzer import AnalyzerAgent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Multi-Agent Game Tester POC",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

class GameRequest(BaseModel):
    url: HttpUrl


class AppState:
    def __init__(self):
        self.status = "idle"
        self.game_info = None
        self.tests = None
        self.report = None

state = AppState()


@app.get("/")
async def root():
    return {"status": "online", "service": "Game Tester POC"}


@app.post("/api/analyze")
async def analyze_game(req: GameRequest):
    try:
        state.status = "analyzing"
        analyzer = GameAnalyzerAgent()
        state.game_info = await analyzer.analyze_game(str(req.url))
        state.status = "analyzed"
        return {"status": "success", "game_info": state.game_info}
    except Exception as e:
        state.status = "error"
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/generate-tests")
async def generate_tests():
    if not state.game_info:
        raise HTTPException(400, "Analyze game first")

    planner = PlannerAgent()
    state.tests = planner.generate_and_rank_tests(state.game_info)
    state.status = "tests_generated"

    return {
        "status": "success",
        "test_count": len(state.tests),
        "tests": state.tests
    }


@app.post("/api/execute-tests")
async def execute_tests(background_tasks: BackgroundTasks):
    if not state.tests:
        raise HTTPException(400, "Generate tests first")

    state.status = "executing"
    background_tasks.add_task(run_tests_background_sync)

    return {"status": "started"}

def run_tests_background_sync():
    asyncio.run(run_tests_background())


async def run_tests_background():
    try:
        executor = ExecutorAgent()
        results = await executor.execute_tests(
            state.game_info["url"],
            state.tests
        )

        analyzer = AnalyzerAgent()
        state.report = analyzer.analyze_and_report(
            state.game_info,
            results
        )

        state.status = "completed"
        logger.info("Test run completed")

    except Exception as e:
        state.status = "error"
        logger.error(f"Execution failed: {e}")


@app.get("/api/status")
async def get_status():
    return {
        "status": state.status,
        "has_game_info": state.game_info is not None,
        "has_tests": state.tests is not None,
        "has_report": state.report is not None,
        "report": state.report if state.status == "completed" else None
    }


@app.get("/reports/{report_id}")
async def get_report_file(report_id: str):
    path = f"backend/reports/{report_id}.json"
    if not os.path.exists(path):
        raise HTTPException(404, "Report not found")
    return FileResponse(path, media_type="application/json")


@app.get("/artifacts/{filename}")
async def get_artifact(filename: str):
    path = f"backend/artifacts/{filename}"
    if not os.path.exists(path):
        raise HTTPException(404, "Artifact not found")
    return FileResponse(path)


@app.post("/api/reset")
async def reset_state():
    global state
    state = AppState()
    return {"status": "reset"}
