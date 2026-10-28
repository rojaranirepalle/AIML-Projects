"""Log explorer: search and filter records from the live store or a log file/directory."""

import asyncio
from pathlib import Path
from typing import Dict, Optional, Tuple

import pandas as pd
from fastapi import APIRouter, HTTPException, Query, Request

from app.config.settings import settings
from app.config.log_source import get_log_path
from app.knowledge.magento import match_issues
from app.models.log_model import expand_levels
from app.services.log_service import list_log_files, process_log_file

router = APIRouter(prefix="/explorer", tags=["explorer"])

LIVE_LIMIT = 200_000
LIST_COLUMNS = ["time", "level", "source", "channel", "message", "exception", "template_id", "template", "stack_frames"]
_file_cache: Dict[str, Tuple[tuple, pd.DataFrame]] = {}


def _file_frame(path: Path) -> pd.DataFrame:
    """Parse a file or directory once and reuse it until any file changes."""
    files = list_log_files(path)
    signature = tuple((str(f), f.stat().st_mtime_ns, f.stat().st_size) for f in files)
    cached = _file_cache.get(str(path))
    if cached and cached[0] == signature:
        return cached[1]
    frame = pd.DataFrame(process_log_file(path)["records"])
    if frame.empty:
        frame = pd.DataFrame(columns=[*LIST_COLUMNS, "raw"])
    frame["time"] = pd.to_datetime(frame.get("timestamp"), utc=True, errors="coerce")
    frame.index.name = "id"
    _file_cache.clear()  # keep one dataset in memory
    _file_cache[str(path)] = (signature, frame)
    return frame


def load_frame(request: Request, input_path: Optional[Path]) -> Tuple[pd.DataFrame, str]:
    monitor = getattr(request.app.state, "monitor", None)
    if input_path is None and monitor is not None:
        frame = monitor.store.records_frame(limit=LIVE_LIMIT, include_raw=True)
        frame["time"] = pd.to_datetime(frame["event_time"], utc=True, errors="coerce", format="ISO8601")
        return frame, "live"
    return _file_frame(Path(input_path or get_log_path())), "file"


def _utc(value: str) -> pd.Timestamp:
    """Parse an ISO time; naive values (e.g. from datetime-local inputs) are treated as UTC."""
    stamp = pd.Timestamp(value)
    return stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp.tz_convert("UTC")


def apply_filters(
    frame: pd.DataFrame,
    q: Optional[str] = None,
    level: Optional[str] = None,
    source: Optional[str] = None,
    exception: Optional[str] = None,
    template_id: Optional[int] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
) -> pd.DataFrame:
    mask = pd.Series(True, index=frame.index)
    if q:
        haystack = frame["message"].fillna("")
        for column in ("exception", "template"):
            if column in frame:
                haystack = haystack + " " + frame[column].fillna("").astype(str)
        mask &= haystack.str.contains(q, case=False, regex=False)
    levels = expand_levels(level)
    if levels is not None:
        mask &= frame["level"].isin(levels)
    if source:
        mask &= frame["source"].isin({item.strip() for item in source.split(",") if item.strip()})
    if exception:
        mask &= frame["exception"].fillna("") == exception
    if template_id is not None and "template_id" in frame:
        mask &= frame["template_id"] == template_id
    if since:
        mask &= frame["time"] >= _utc(since)
    if until:
        mask &= frame["time"] <= _utc(until)
    return frame[mask]


def facets(frame: pd.DataFrame) -> dict:
    def counts(column: str, limit: int = 30) -> dict:
        if column not in frame:
            return {}
        return frame[column].dropna().astype(str).value_counts().head(limit).to_dict()

    times = frame["time"].dropna()
    return {
        "level": counts("level"),
        "source": counts("source"),
        "exception": counts("exception"),
        "time_range": [times.min().isoformat(), times.max().isoformat()] if not times.empty else None,
    }


def _clean(value):
    if value is None or (isinstance(value, float) and pd.isna(value)) or value is pd.NaT:
        return None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if hasattr(value, "item"):  # numpy scalar
        return value.item()
    return value


def _rows(frame: pd.DataFrame) -> list:
    present = [column for column in LIST_COLUMNS if column in frame]
    return [
        {"id": _clean(index), **{column: _clean(row[column]) for column in present}}
        for index, row in frame[present].iterrows()
    ]


@router.get("/records")
async def records(
    request: Request,
    input_path: Optional[Path] = Query(default=None, description="File or directory; omitted = live store when monitoring"),
    q: Optional[str] = None,
    level: Optional[str] = Query(default=None, description="Comma-separated levels, e.g. ERROR,CRITICAL"),
    source: Optional[str] = None,
    exception: Optional[str] = None,
    template_id: Optional[int] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    order: str = Query(default="desc", pattern="^(asc|desc)$"),
) -> dict:
    def run():
        frame, mode = load_frame(request, input_path)
        filtered = apply_filters(frame, q, level, source, exception, template_id, since, until)
        ordered = filtered.iloc[::-1] if order == "desc" else filtered
        return {
            "mode": mode,
            "total": int(len(filtered)),
            "offset": offset,
            "limit": limit,
            "items": _rows(ordered.iloc[offset: offset + limit]),
            "facets": facets(frame),
        }

    try:
        return await asyncio.to_thread(run)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


def record_detail(frame: pd.DataFrame, record_id: int) -> dict:
    if record_id not in frame.index:
        raise KeyError(record_id)
    row = frame.loc[record_id]
    detail = {"id": record_id, **{column: _clean(row[column]) for column in frame.columns if column != "time"}}
    detail["time"] = _clean(row["time"])
    related = frame[frame["template_id"] == row["template_id"]] if "template_id" in frame else frame.iloc[0:0]
    times = related["time"].dropna()
    detail["related"] = {
        "template_count": int(len(related)),
        "first_seen": times.min().isoformat() if not times.empty else None,
        "last_seen": times.max().isoformat() if not times.empty else None,
        "sources": related["source"].value_counts().to_dict() if not related.empty else {},
    }
    detail["known_issues"] = [issue.to_dict() for issue in match_issues(detail.get("message"), detail.get("exception"), detail.get("template"))]
    return detail


@router.get("/records/{record_id}")
async def record(request: Request, record_id: int, input_path: Optional[Path] = None) -> dict:
    def run():
        frame, mode = load_frame(request, input_path)
        return {"mode": mode, **record_detail(frame, record_id)}

    try:
        return await asyncio.to_thread(run)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=f"Record {record_id} not found") from error
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
