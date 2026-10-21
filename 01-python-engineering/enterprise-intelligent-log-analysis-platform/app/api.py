import asyncio
from pathlib import Path
from typing import Dict, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.config.settings import settings
from app.services.incident_summarizer import SummarizationError, summarize_incident
from app.services.log_service import process_log_file


app = FastAPI(
    title=settings.app_name,
    description="Local dashboard and API for log ingestion, analytics, anomaly indicators, and reports.",
    version="1.0.0",
)


class AnalyzeRequest(BaseModel):
    input_path: Path = settings.log_file_path
    report_path: Optional[Path] = settings.report_file_path
    summary_path: Optional[Path] = settings.summary_file_path


class LogsRequest(BaseModel):
    input_path: Path = settings.log_file_path
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=100, ge=1, le=1000)


class IncidentSummaryRequest(BaseModel):
    input_path: Path = settings.log_file_path


@app.get("/dashboard", response_class=FileResponse, include_in_schema=False)
async def dashboard() -> FileResponse:
    return FileResponse(Path(__file__).parent / "static" / "dashboard.html")


@app.get("/dashboard-data")
async def dashboard_data(
    input_path: Path = Query(default=settings.log_file_path),
) -> dict:
    """Return one analyzed snapshot for the dashboard to avoid duplicate ingestion."""
    try:
        result = await asyncio.to_thread(process_log_file, input_path)
        entries = result["records"]
        return {"summary": result["summary"], "total": len(entries), "items": entries[-100:]}
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
    input_path: Path = Query(default=settings.log_file_path),
) -> dict:
    try:
        result = await asyncio.to_thread(process_log_file, input_path)
        return result["summary"]
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except OSError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
