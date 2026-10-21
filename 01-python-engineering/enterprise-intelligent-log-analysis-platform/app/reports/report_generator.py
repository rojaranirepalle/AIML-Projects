import json
from pathlib import Path
from typing import Dict, Optional, Union

import pandas as pd


def export_report(
    df: pd.DataFrame,
    csv_path: Union[str, Path],
    summary: Optional[dict] = None,
    json_path: Optional[Union[str, Path]] = None,
) -> Dict[str, str]:
    """Write normalized records and, when requested, a JSON analytics summary."""
    csv_file = Path(csv_path)
    csv_file.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(csv_file, index=False)
    result = {"csv": str(csv_file)}

    if summary is not None and json_path is not None:
        json_file = Path(json_path)
        json_file.parent.mkdir(parents=True, exist_ok=True)
        json_file.write_text(json.dumps(summary, indent=2, default=str) + "\n", encoding="utf-8")
        result["json"] = str(json_file)
    return result
