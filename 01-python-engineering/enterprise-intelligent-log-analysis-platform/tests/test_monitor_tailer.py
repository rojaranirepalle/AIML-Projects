import os
from pathlib import Path

from app.monitoring.tailer import LogTailer

EXCEPTION = (
    '[2026-10-25T07:00:01+00:00] main.CRITICAL: Boom {"exception":"[object] (Acme\\\\BarException(code: 0): Boom at /x.php:1)\n'
    "[stacktrace]\n#0 /a.php(1): x()\n#1 {main}\"} []\n"
)


def line(message: str, level: str = "INFO", second: int = 0) -> str:
    return f"[2026-10-25T07:00:{second:02d}+00:00] main.{level}: {message} [] []\n"


def append(path: Path, text: str) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(text)


def test_new_lines_and_partial_line(tmp_path):
    log = tmp_path / "system.log"
    log.write_text(line("one"))
    tailer = LogTailer(tmp_path, flush_after=0)
    assert [r.text for r in tailer.poll(now=10)] == [line("one").strip()]

    append(log, line("two") + "[2026-10-25T07:00:09+00:00] main.INFO: half")  # no newline yet
    assert [r.text for r in tailer.poll(now=20)] == [line("two").strip()]
    append(log, " written [] []\n")
    assert [r.text for r in tailer.poll(now=30)] == ["[2026-10-25T07:00:09+00:00] main.INFO: half written [] []"]


def test_multiline_record_is_held_until_complete(tmp_path):
    log = tmp_path / "exception.log"
    log.write_text("")
    tailer = LogTailer(tmp_path, flush_after=5)
    tailer.poll(now=0)
    append(log, EXCEPTION)
    assert tailer.poll(now=1) == []  # may still be receiving stack frames
    append(log, line("next", second=2))
    records = tailer.poll(now=2)
    assert len(records) == 1 and records[0].text.count("\n") == 3  # 4 lines: whole stack trace, one record
    assert tailer.poll(now=10)[0].text == line("next", second=2).strip()  # flushed after quiet period


def test_truncation_and_rotation_restart_from_zero(tmp_path):
    log = tmp_path / "system.log"
    log.write_text(line("a") + line("b"))
    tailer = LogTailer(tmp_path, flush_after=0)
    assert len(tailer.poll(now=1)) == 2

    log.write_text(line("after truncate"))  # shorter than the old offset
    assert [r.text for r in tailer.poll(now=2)] == [line("after truncate").strip()]

    os.rename(log, tmp_path / "system.log.1")  # rotated away (does not match *.log)
    log.write_text(line("fresh file"))
    assert [r.text for r in tailer.poll(now=3)] == [line("fresh file").strip()]


def test_resume_from_saved_offsets_without_duplicates(tmp_path):
    log = tmp_path / "system.log"
    log.write_text(line("a") + line("b"))
    first = LogTailer(tmp_path, flush_after=0)
    first.poll(now=1)
    saved = first.offsets()

    append(log, line("c"))
    second = LogTailer(tmp_path, flush_after=0, saved_offsets=saved)
    assert [r.text for r in second.poll(now=2)] == [line("c").strip()]


def test_baseline_only_for_history_present_at_startup(tmp_path):
    (tmp_path / "system.log").write_text(line("history"))
    tailer = LogTailer(tmp_path, flush_after=0)
    assert [r.baseline for r in tailer.poll(now=1)] == [True]

    append(tmp_path / "system.log", line("live"))
    (tmp_path / "new.log").write_text(line("new file"))  # created after start-up: live
    assert {r.text: r.baseline for r in tailer.poll(now=2)} == {line("live").strip(): False, line("new file").strip(): False}


def test_non_log_files_are_ignored(tmp_path):
    (tmp_path / "notes.txt").write_text("INFO - not a log\n")
    assert LogTailer(tmp_path).poll(now=1) == []
