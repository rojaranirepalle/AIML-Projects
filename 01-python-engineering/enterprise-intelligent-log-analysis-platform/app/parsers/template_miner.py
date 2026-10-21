"""Log template mining with Drain3.

Raw log messages embed variable values (block IDs, IP addresses, sizes), so
two lines describing the same event look different to text models. Drain3
groups messages into templates such as
``Receiving block <BLK> src: <IP> dest: <IP>`` so analytics and anomaly
detection operate on event *types* rather than unique strings.
"""

import logging
from typing import List, Tuple

import pandas as pd
from drain3 import TemplateMiner
from drain3.masking import MaskingInstruction
from drain3.template_miner_config import TemplateMinerConfig

# Drain3 logs its full configuration at INFO on every miner; keep request logs readable.
logging.getLogger("drain3").setLevel(logging.WARNING)


# Order matters: specific identifiers are masked before generic numbers.
MASKING_RULES = [
    (r"blk_-?\d+(?:\s+blk_-?\d+)+", "BLK_LIST"),
    (r"blk_-?\d+", "BLK"),
    (r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?::\d+)?(?![\w.])", "IP"),
    (r"\b0x[0-9a-fA-F]+\b", "HEX"),
    (r"(?<![\w.-])-?\d+(?:\.\d+)?(?![\w.])", "NUM"),
]


def build_miner(similarity_threshold: float = 0.4, depth: int = 4) -> TemplateMiner:
    """Create an in-memory Drain3 miner with identifier masking."""
    config = TemplateMinerConfig()
    config.drain_sim_th = similarity_threshold
    config.drain_depth = depth
    config.profiling_enabled = False
    config.masking_instructions = [MaskingInstruction(pattern, mask) for pattern, mask in MASKING_RULES]
    return TemplateMiner(persistence_handler=None, config=config)


def mine_templates(messages: List[str]) -> Tuple[List[int], List[str]]:
    """Return a template ID and template text for every message.

    Templates are learned in a first pass and resolved in a second pass, so
    early messages receive the final, most general template of their cluster.
    """
    miner = build_miner()
    for message in messages:
        miner.add_log_message(message)

    template_ids: List[int] = []
    templates: List[str] = []
    for message in messages:
        cluster = miner.match(message, full_search_strategy="fallback")
        if cluster is None:  # Defensive: every trained message should match.
            cluster = miner.drain.id_to_cluster[miner.add_log_message(message)["cluster_id"]]
        template_ids.append(int(cluster.cluster_id))
        templates.append(cluster.get_template())
    return template_ids, templates


def add_templates(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy of ``df`` with ``template_id`` and ``template`` columns."""
    result = df.copy()
    if result.empty:
        result["template_id"] = pd.Series(dtype="Int64")
        result["template"] = pd.Series(dtype="object")
        return result
    template_ids, templates = mine_templates(result["message"].fillna("").astype(str).tolist())
    result["template_id"] = template_ids
    result["template"] = templates
    return result
