import pandas as pd

from app.parsers.template_miner import add_templates, mine_templates


def test_variable_values_collapse_into_one_template():
    ids, templates = mine_templates(
        [
            "Receiving block blk_-1608999687919862906 src: /10.250.19.102:54106 dest: /10.250.19.102:50010",
            "Receiving block blk_7503483334202473044 src: /10.251.215.16:55695 dest: /10.251.215.16:50010",
            "Deleting block blk_123 file /mnt/hadoop/dfs/data/current/blk_123",
        ]
    )
    assert ids[0] == ids[1] != ids[2]
    assert templates[0] == "Receiving block <BLK> src: /<IP> dest: /<IP>"


def test_block_lists_are_masked_as_one_token():
    _, templates = mine_templates(["ask 10.0.0.1:50010 to delete blk_1 blk_-2 blk_3"])
    assert templates[0] == "ask <IP> to delete <BLK_LIST>"


def test_add_templates_keeps_rows_and_handles_empty():
    df = pd.DataFrame({"message": ["size 10", "size 20"], "level": ["INFO", "INFO"]})
    result = add_templates(df)
    assert list(result.columns[-2:]) == ["template_id", "template"]
    assert result["template_id"].nunique() == 1
    assert "template" not in df  # input is not mutated

    empty = add_templates(pd.DataFrame(columns=["message", "level"]))
    assert empty.empty and {"template_id", "template"} <= set(empty.columns)


def test_hdfs_sample_reduces_to_few_templates(hdfs_log):
    messages = [line.split(" ", 4)[-1] for line in hdfs_log.read_text().splitlines() if line.strip()]
    ids, _ = mine_templates(messages)
    assert len(messages) == 2000
    assert len(set(ids)) < 30
