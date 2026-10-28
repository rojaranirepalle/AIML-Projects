"""Incremental, rotation-aware tailing of every ``*.log`` file in a directory.

Only complete lines are consumed. Magento/Monolog records can span several
lines (stack traces), so the last record of a file is held back until the next
record starts or the file has been quiet for ``flush_after`` seconds. Saved
offsets always point at the start of a held-back record, so a restart never
loses or duplicates one.
"""

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from app.parsers.log_parser import _MONOLOG_START, is_record_start

MAX_BYTES_PER_POLL = 64 * 1024 * 1024


@dataclass
class TailedRecord:
    source: str
    text: str
    baseline: bool = False


@dataclass
class _FileState:
    inode: int
    offset: int  # bytes consumed from the file
    committed: int  # offset of the first unflushed byte (start of the pending record)
    baseline: bool = False
    pending: List[str] = field(default_factory=list)
    pending_bytes: int = 0
    last_data: float = 0.0


class LogTailer:
    def __init__(
        self,
        directory: Path,
        pattern: str = "*.log",
        flush_after: float = 2.0,
        saved_offsets: Optional[Dict[str, Tuple[int, int]]] = None,
        baseline_unknown_files: bool = True,
    ) -> None:
        self.directory = Path(directory)
        self.pattern = pattern
        self.flush_after = flush_after
        self._saved = dict(saved_offsets or {})
        self._baseline_unknown = baseline_unknown_files
        self._states: Dict[str, _FileState] = {}
        self._first_poll = True

    # -- public API -----------------------------------------------------
    def poll(self, now: Optional[float] = None) -> List[TailedRecord]:
        """Read new data from every matching file and return completed records."""
        now = time.time() if now is None else now
        records: List[TailedRecord] = []
        present = set()
        for path in sorted(self.directory.glob(self.pattern)):
            if not path.is_file():
                continue
            present.add(path.name)
            records.extend(self._poll_file(path, now))
        for name in list(self._states):
            if name not in present:  # deleted or rotated away
                state = self._states.pop(name)
                records.extend(self._flush(name, state))
        self._first_poll = False
        return records

    def offsets(self) -> Dict[str, Tuple[int, int]]:
        """``{file name: (inode, committed offset)}`` for persistence."""
        return {name: (state.inode, state.committed) for name, state in self._states.items()}

    def watched_files(self) -> List[str]:
        return sorted(self._states)

    # -- internals ------------------------------------------------------
    def _poll_file(self, path: Path, now: float) -> List[TailedRecord]:
        stat = path.stat()
        name = path.name
        state = self._states.get(name)
        records: List[TailedRecord] = []

        if state is None:
            saved = self._saved.pop(name, None)
            if saved and saved[0] == stat.st_ino and saved[1] <= stat.st_size:
                state = _FileState(inode=stat.st_ino, offset=saved[1], committed=saved[1])
            else:
                baseline = self._first_poll and self._baseline_unknown and saved is None
                state = _FileState(inode=stat.st_ino, offset=0, committed=0, baseline=baseline)
            self._states[name] = state
        elif stat.st_ino != state.inode or stat.st_size < state.offset:
            # Rotated (new inode) or truncated (e.g. `rm var/log/*` or log clean-up).
            records.extend(self._flush(name, state))
            state = _FileState(inode=stat.st_ino, offset=0, committed=0)
            self._states[name] = state

        if stat.st_size > state.offset:
            with path.open("rb") as handle:
                handle.seek(state.offset)
                chunk = handle.read(min(stat.st_size - state.offset, MAX_BYTES_PER_POLL))
            end = chunk.rfind(b"\n")
            if end >= 0:
                complete = chunk[: end + 1]
                state.offset += len(complete)
                state.last_data = now
                records.extend(self._consume(name, state, complete))

        if state.pending and now - state.last_data >= self.flush_after:
            records.extend(self._flush(name, state))
        if state.baseline and not state.pending and state.offset >= stat.st_size:
            state.baseline = False  # caught up with history; everything after is live
        return records

    def _consume(self, name: str, state: _FileState, data: bytes) -> List[TailedRecord]:
        records: List[TailedRecord] = []
        for raw in data.splitlines(keepends=True):
            line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
            if not line.strip():
                if state.pending:
                    state.pending_bytes += len(raw)
                else:
                    state.committed += len(raw)
                continue
            continues = bool(state.pending) and _MONOLOG_START.match(state.pending[0]) and not is_record_start(line)
            if continues:
                state.pending.append(line)
                state.pending_bytes += len(raw)
                continue
            records.extend(self._flush(name, state))
            state.pending = [line]
            state.pending_bytes = len(raw)
            # Only Monolog records can continue; anything else is complete now.
            if not _MONOLOG_START.match(line):
                records.extend(self._flush(name, state))
        return records

    def _flush(self, name: str, state: _FileState) -> List[TailedRecord]:
        if not state.pending:
            return []
        record = TailedRecord(source=name, text="\n".join(state.pending), baseline=state.baseline)
        state.committed += state.pending_bytes
        state.pending, state.pending_bytes = [], 0
        return [record]
