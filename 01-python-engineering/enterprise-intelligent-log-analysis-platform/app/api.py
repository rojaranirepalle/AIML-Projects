import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Dict, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import pandas as pd
from pydantic import BaseModel, Field

from app.analytics.pandas_analytics import filter_levels, generate_summary
from app.config.settings import settings
from app.config.log_source import get_log_path, save_log_path
from app.config.llm_settings import router as llm_settings_router
from app.models.log_model import expand_levels
from app.services.incident_summarizer import SummarizationError, summarize_incident
from app.core.logger import logger
from app.monitoring.monitor import create_monitor
from app.assistant import router as assistant_router
from app.explorer import router as explorer_router
from app.knowledge.routes import router as knowledge_router
from app.monitoring.routes import router as monitor_router
from app.services.log_service import process_log_file


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start the live monitor when enabled (python main.py --monitor)."""
    app.state.monitor = None
    if settings.monitor_enabled:
        app.state.monitor = create_monitor(settings)
        app.state.monitor.start()
    yield
    monitor = app.state.monitor
    if monitor is not None:
        logger.info("Stopping monitor")
        monitor.stop()
        monitor.store.close()


app = FastAPI(
    title=settings.app_name,
    description="Local dashboard and API for log ingestion, analytics, anomaly indicators, reports and live monitoring.",
    version="1.1.0",
    lifespan=lifespan,
)
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
app.include_router(llm_settings_router)
app.include_router(monitor_router)
app.include_router(explorer_router)
app.include_router(knowledge_router)
app.include_router(assistant_router)


class AnalyzeRequest(BaseModel):
    input_path: Path = Field(default_factory=get_log_path)
    report_path: Optional[Path] = settings.report_file_path
    summary_path: Optional[Path] = settings.summary_file_path


class LogsRequest(BaseModel):
    input_path: Path = Field(default_factory=get_log_path)
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=100, ge=1, le=1000)


class IncidentSummaryRequest(BaseModel):
    input_path: Path = Field(default_factory=get_log_path)


@app.get("/dashboard", response_class=FileResponse, include_in_schema=False)
async def dashboard() -> FileResponse:
    return FileResponse(Path(__file__).parent / "static" / "dashboard.html")


@app.get("/explorer", response_class=FileResponse, include_in_schema=False)
async def explorer_page() -> FileResponse:
    return FileResponse(Path(__file__).parent / "static" / "explorer.html")


@app.get("/dashboard-data")
async def dashboard_data(
    input_path: Optional[Path] = Query(default=None),
    level: Optional[str] = Query(default=None, description="Level groups or levels, e.g. error,warning or CRITICAL"),
) -> dict:
    """Return one analyzed snapshot for the dashboard, optionally limited to some levels."""

    def run() -> dict:
        result = process_log_file(input_path or get_log_path())
        summary, records = result["summary"], result["records"]
        if expand_levels(level) is not None:
            frame = filter_levels(pd.DataFrame(records), level)
            filtered = generate_summary(frame, contamination=settings.anomaly_contamination)
            # Web traffic and file information always describe the whole input.
            for key in ("source_file", "source_files", "skipped_lines", "access"):
                filtered[key] = summary.get(key)
            filtered["source_distribution"] = frame["source"].value_counts().to_dict() if not frame.empty else {}
            filtered["level_filter"] = {"spec": level, "matched": len(frame), "total": len(records)}
            summary, records = filtered, frame.to_dict(orient="records")
        entries = [{k: v for k, v in record.items() if k != "raw"} for record in records[-100:]]
        return {"summary": summary, "total": len(records), "items": entries}

    try:
        return await asyncio.to_thread(run)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except OSError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.get("/health")
async def health() -> Dict[str, str]:
    return {"status": "ok", "service": settings.app_name}


@app.post("/analyze")
async def analyze(request: AnalyzeRequest) -> dict:
    try:
        result = await asyncio.to_thread(
            process_log_file,
            request.input_path,
            request.report_path,
            request.summary_path,
        )
        return result["summary"]
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except OSError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/logs")
async def logs(request: LogsRequest) -> dict:
    try:
        result = await asyncio.to_thread(process_log_file, request.input_path)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except OSError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    entries = result["records"]
    return {
        "total": len(entries),
        "offset": request.offset,
        "limit": request.limit,
        "items": entries[request.offset : request.offset + request.limit],
    }


@app.post("/incident-summary")
async def incident_summary(request: IncidentSummaryRequest) -> Dict[str, str]:
    try:
        result = await asyncio.to_thread(process_log_file, request.input_path)
        text = await asyncio.to_thread(summarize_incident, result["summary"])
        return {"summary": text}
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except SummarizationError as error:
        status = 503 if "disabled" not in str(error).lower() else 409
        raise HTTPException(status_code=status, detail=str(error)) from error
    except OSError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.get("/summary")
async def summary(
    input_path: Optional[Path] = Query(default=None),
) -> dict:
    try:
        result = await asyncio.to_thread(process_log_file, input_path or get_log_path())
        return result["summary"]
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except OSError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


class SourceSettingsRequest(BaseModel):
    log_file_path: str
    directory_only: bool = False


@app.get("/settings", response_class=FileResponse, include_in_schema=False)
async def settings_page() -> FileResponse:
    return FileResponse(Path(__file__).parent / "static" / "settings.html")


@app.get("/settings/log-source")
async def log_source_settings() -> dict:
    return {"log_file_path": str(get_log_path())}


@app.put("/settings/log-source")
async def update_log_source(body: SourceSettingsRequest) -> dict:
    try:
        path = await asyncio.to_thread(save_log_path, body.log_file_path, body.directory_only)
        return {"log_file_path": str(path)}
    except (ValueError, OSError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
