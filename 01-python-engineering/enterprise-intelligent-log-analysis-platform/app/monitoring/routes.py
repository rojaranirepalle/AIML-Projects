"""REST and Server-Sent Events endpoints for the live monitor."""

import asyncio
import json
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from datetime import timedelta

import pandas as pd

from app.analytics.access_analytics import analyze_access, records_from_raw
from app.analytics.forecasting import forecast_log_volume
from app.analytics.pandas_analytics import filter_levels, generate_summary
from app.models.log_model import expand_levels
from app.config.settings import settings
from app.monitoring.monitor import LogMonitor

router = APIRouter(prefix="/monitor", tags=["monitoring"])

FORECAST_HOURS = 72
NOT_RUNNING = "Live monitoring is not running. Start it with: python main.py --monitor --log-dir <magento>/var/log"


def get_monitor(request: Request) -> LogMonitor:
    monitor = getattr(request.app.state, "monitor", None)
    if monitor is None:
        raise HTTPException(status_code=409, detail=NOT_RUNNING)
    return monitor


@router.get("/status")
async def status(request: Request) -> dict:
    monitor = getattr(request.app.state, "monitor", None)
    if monitor is None:
        return {"running": False, "configured": bool(settings.magento_log_dir), "detail": NOT_RUNNING}
    return await asyncio.to_thread(monitor.status)


def _dashboard_snapshot(monitor: LogMonitor, limit: int, level: Optional[str] = None) -> dict:
    all_records = monitor.store.records_frame(limit=limit)
    frame = filter_levels(all_records, level)
    summary = generate_summary(frame, contamination=settings.anomaly_contamination)
    summary["source_distribution"] = frame["source"].value_counts().to_dict() if not frame.empty else {}
    # Forecast from recent activity only, so old history and long idle gaps do not flatten the trend.
    if not frame.empty:
        event_times = pd.to_datetime(frame["event_time"], utc=True, errors="coerce", format="ISO8601")
        recent = frame.assign(timestamp=event_times)[event_times >= event_times.max() - timedelta(hours=FORECAST_HOURS)]
        summary["forecast"] = {**forecast_log_volume(recent), "window_hours": FORECAST_HOURS}
    summary["access"] = analyze_access(records_from_raw(monitor.store.raw_for_channel("nginx")))
    if expand_levels(level) is not None:
        summary["level_filter"] = {"spec": level, "matched": len(frame), "total": len(all_records)}
    recent = frame.tail(100)
    items = [
        {
            "timestamp": row.event_time,
            "level": row.level,
            "message": row.message,
            "source": row.source,
            "exception": row.exception,
        }
        for row in recent.itertuples()
    ]
    return {
        "mode": "live",
        "summary": summary,
        "total": len(frame),
        "items": items,
        "alerts": monitor.store.list_alerts(limit=20),
        "status": monitor.status(),
    }


@router.get("/dashboard-data")
async def dashboard_data(
    request: Request,
    limit: int = Query(default=50000, ge=100, le=500000),
    level: Optional[str] = Query(default=None, description="Level groups or levels, e.g. error,warning"),
) -> dict:
    """Analytics over the most recent stored records, plus alerts and monitor status."""
    monitor = get_monitor(request)
    try:
        return await asyncio.to_thread(_dashboard_snapshot, monitor, limit, level)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.get("/alerts")
async def alerts(request: Request, limit: int = Query(default=50, ge=1, le=500), open_only: bool = False) -> dict:
    monitor = get_monitor(request)
    items = await asyncio.to_thread(monitor.store.list_alerts, limit, open_only)
    return {"items": items}


@router.post("/alerts/{alert_id}/ack")
async def acknowledge(request: Request, alert_id: int) -> dict:
    monitor = get_monitor(request)
    if not await asyncio.to_thread(monitor.store.acknowledge, alert_id):
        raise HTTPException(status_code=404, detail=f"Alert {alert_id} not found")
    return {"id": alert_id, "acknowledged": True}


@router.get("/records")
async def records(
    request: Request,
    limit: int = Query(default=100, ge=1, le=1000),
    level: Optional[str] = Query(default=None, description="Exact level, e.g. CRITICAL"),
) -> dict:
    monitor = get_monitor(request)
    frame = await asyncio.to_thread(monitor.store.records_frame, 5000 if level else limit)
    if level:
        frame = frame[frame["level"] == level.upper()]
    frame = frame.tail(limit)
    columns = ["event_time", "level", "source", "channel", "message", "exception", "template_id", "template"]
    out = frame.reset_index()[["id", *columns]]
    out = out.astype(object).where(out.notna(), None)  # NaN -> null in JSON
    return {"items": out.to_dict(orient="records")}


@router.get("/stream")
async def stream(request: Request) -> StreamingResponse:
    """Server-Sent Events: ``records`` when new lines arrive, ``alert`` when a rule fires."""
    monitor = get_monitor(request)
    queue = monitor.bus.subscribe()

    async def events():
        try:
            yield "event: hello\ndata: {}\n\n"
            while monitor.running and not await request.is_disconnected():
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                yield f"event: {event['type']}\ndata: {json.dumps(event, default=str)}\n\n"
        finally:
            monitor.bus.unsubscribe(queue)

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})
