"""Traffic analytics for parsed access-log records."""

from typing import Iterable, List

import pandas as pd

from app.parsers.access_log import AccessRecord, parse_access_line


def mask_ip(ip: str) -> str:
    if ip.count(".") == 3:
        return ".".join(ip.split(".")[:3]) + ".x"
    if ":" in ip:
        return ":".join(ip.split(":")[:3]) + ":…"
    return ip


def records_from_raw(lines: Iterable[str]) -> List[AccessRecord]:
    return [record for record in (parse_access_line(line) for line in lines if line) if record is not None]


def _percentile(series: pd.Series, q: float):
    series = series.dropna()
    return round(float(series.quantile(q)), 3) if not series.empty else None


def analyze_access(records: List[AccessRecord], top: int = 8) -> dict:
    if not records:
        return {"available": False, "reason": "No access-log records found."}
    df = pd.DataFrame([record.__dict__ for record in records])
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df["class"] = (df["status"] // 100).astype(str) + "xx"
    df["is_5xx"] = df["status"] >= 500
    df["is_4xx"] = df["status"].between(400, 499)
    total = len(df)

    span = df["timestamp"].max() - df["timestamp"].min()
    frequency = "min" if span <= pd.Timedelta(hours=6) else "h"
    buckets = df.set_index("timestamp").resample(frequency).agg({"status": "size", "is_5xx": "sum"})
    buckets.columns = ["requests", "errors_5xx"]

    hourly_frame = df.set_index("timestamp").resample("h")
    hourly = hourly_frame.agg({"status": "size", "is_5xx": "sum"})
    hourly.columns = ["requests", "errors_5xx"]
    hourly["p95"] = hourly_frame["response_time"].quantile(0.95)
    hourly = hourly.tail(24)

    def route_table(frame: pd.DataFrame, sort: str, min_count: int = 1) -> list:
        grouped = frame.groupby(["route", "area"]).agg(
            requests=("status", "size"), errors_5xx=("is_5xx", "sum"), p95=("response_time", lambda s: _percentile(s, 0.95))
        ).reset_index()
        grouped = grouped[grouped["requests"] >= min_count]
        if sort == "p95":
            grouped = grouped.dropna(subset=["p95"])
        rows = grouped.sort_values([sort, "requests"], ascending=False).head(top)
        return [
            {"route": r.route, "area": r.area, "requests": int(r.requests), "errors_5xx": int(r.errors_5xx), "p95": r.p95}
            for r in rows.itertuples(index=False)
        ]

    areas = df.groupby("area").agg(requests=("status", "size"), errors_5xx=("is_5xx", "sum")).sort_values("requests", ascending=False)
    clients = df.assign(client=df["ip"].map(mask_ip)).groupby("client").size().sort_values(ascending=False).head(5)
    return {
        "available": True,
        "requests": total,
        "start": df["timestamp"].min().isoformat(),
        "end": df["timestamp"].max().isoformat(),
        "status_classes": df["class"].value_counts().sort_index().to_dict(),
        "error_rate_5xx": round(float(df["is_5xx"].mean()), 4),
        "error_rate_4xx": round(float(df["is_4xx"].mean()), 4),
        "latency": {
            "available": bool(df["response_time"].notna().any()),
            "p50": _percentile(df["response_time"], 0.5),
            "p95": _percentile(df["response_time"], 0.95),
            "p99": _percentile(df["response_time"], 0.99),
        },
        "bot_share": round(float(df["is_bot"].mean()), 4),
        "peak_requests_per_bucket": int(buckets["requests"].max()) if not buckets.empty else 0,
        "timeline_frequency": "minute" if frequency == "min" else "hour",
        "timeline": [
            {"time": index.isoformat(), "requests": int(row.requests), "errors_5xx": int(row.errors_5xx)}
            for index, row in buckets.tail(240).iterrows()
        ],
        "hourly": [
            {
                "time": index.isoformat(),
                "requests": int(row.requests),
                "errors_5xx": int(row.errors_5xx),
                "p95": None if pd.isna(row.p95) else round(float(row.p95), 3),
            }
            for index, row in hourly.iterrows()
        ],
        "areas": [
            {"area": name, "requests": int(row.requests), "errors_5xx": int(row.errors_5xx)} for name, row in areas.iterrows()
        ],
        "top_routes": route_table(df, "requests"),
        "top_5xx_routes": [row for row in route_table(df, "errors_5xx") if row["errors_5xx"] > 0],
        "slowest_routes": route_table(df, "p95", min_count=5),
        # Client IPs are personal data: only masked prefixes are reported.
        "top_clients": [{"client": client, "requests": int(count)} for client, count in clients.items()],
    }
