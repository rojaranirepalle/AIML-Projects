"""Unsupervised anomaly detection over mined log templates.

Each record is described by two interpretable features:

* ``template_rarity`` = -log(share of records with the same template), and
* ``severity_rank``   = ordinal severity (DEBUG=0 ... FATAL=4).

An Isolation Forest isolates records whose event type is rare and/or severe.
Scores are batch-relative: the model is refit for every file, so they rank
records within a batch and are not calibrated alert probabilities.
"""

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest


MIN_RECORDS = 10
DEFAULT_CONTAMINATION = 0.02
MAX_LISTED = 100
METHOD = "template_rarity_isolation_forest"

SEVERITY_RANK = {
    "TRACE": 0, "DEBUG": 0,
    "INFO": 1, "NOTICE": 1, "UNKNOWN": 1,
    "WARN": 2, "WARNING": 2,
    "ERROR": 3, "ERR": 3,
    "FATAL": 4, "CRITICAL": 4, "SEVERE": 4, "ALERT": 4, "EMERGENCY": 4,
}


def _unavailable(reason: str) -> dict:
    return {
        "available": False,
        "method": METHOD,
        "reason": reason,
        "anomaly_count": 0,
        "anomalies": [],
        "anomalous_templates": [],
    }


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    """Return the per-record feature matrix used by the model."""
    keys = df["template_id"] if "template_id" in df else df["message"].fillna("").astype(str)
    share = keys.map(keys.value_counts(normalize=True)).astype(float)
    levels = df["level"].fillna("UNKNOWN").astype(str).str.upper()
    return pd.DataFrame(
        {
            "template_rarity": -np.log(share),
            "severity_rank": levels.map(SEVERITY_RANK).fillna(1).astype(float),
        },
        index=df.index,
    )


def detect_anomalies(df: pd.DataFrame, contamination: float = DEFAULT_CONTAMINATION) -> dict:
    """Fit an Isolation Forest to this batch; report when the batch is too small."""
    if len(df) < MIN_RECORDS:
        return _unavailable(f"At least {MIN_RECORDS} records are required; found {len(df)}.")

    features = build_features(df)
    if features.drop_duplicates().shape[0] < 2:
        return _unavailable("At least two distinct event types are required.")

    model = IsolationForest(
        n_estimators=200,
        contamination=contamination,
        random_state=42,
        n_jobs=-1,
    ).fit(features.to_numpy())
    is_anomaly = model.predict(features.to_numpy()) == -1
    scores = model.decision_function(features.to_numpy())

    levels = df["level"].fillna("UNKNOWN").astype(str).str.upper()
    scored = pd.DataFrame(
        {
            "level": levels,
            "message": df["message"].fillna("").astype(str),
            "template": df["template"] if "template" in df else df["message"],
            "score": scores,
        },
        index=df.index,
    )[is_anomaly].sort_values("score")

    anomalies = [
        {"row": int(index), "level": row.level, "score": round(float(row.score), 6), "message": row.message}
        for index, row in zip(scored.index[:MAX_LISTED], scored.head(MAX_LISTED).itertuples(index=False))
    ]
    by_template = (
        scored.groupby("template", sort=False)
        .agg(count=("score", "size"), level=("level", "first"), score=("score", "mean"))
        .sort_values("score")
        .reset_index()
    )
    anomalous_templates = [
        {"template": row.template, "count": int(row.count), "level": row.level, "score": round(float(row.score), 6)}
        for row in by_template.itertuples(index=False)
    ]
    return {
        "available": True,
        "method": METHOD,
        "features": list(features.columns),
        "contamination": contamination,
        "records_analyzed": len(df),
        "anomaly_count": int(is_anomaly.sum()),
        "anomalies": anomalies,
        "anomalies_truncated": int(is_anomaly.sum()) > MAX_LISTED,
        "anomalous_templates": anomalous_templates,
    }
