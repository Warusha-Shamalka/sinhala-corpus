"""Shared terminal progress and atomic, read-only-inspectable run snapshots."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import time
from uuid import uuid4


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def safe_text(value, maximum=100) -> str:
    return " ".join("".join(c if c.isprintable() else " " for c in str(value)).split())[:maximum]


def size_text(value) -> str:
    return f"{value / 1048576:.1f} MiB"


class ProgressReporter:
    """Observation only: snapshot/display failures never change pipeline outcomes."""

    def __init__(self, stage: str, *, run_id=None, path: Path | None = None,
                 mode="auto", interval=1.0, stream=None, clock=time.monotonic, wall_clock=utc_now):
        if mode not in {"auto", "plain", "off"} or not math.isfinite(interval) or interval < 0:
            raise ValueError("Invalid progress mode or interval")
        self.path, self.mode, self.interval = path, mode, interval
        self.stream = sys.stderr if stream is None else stream
        self.clock, self.wall_clock = clock, wall_clock
        self.started = clock()
        self.last_publish = float("-inf")
        self.transfer_started = None
        self.line_width = 0
        self.snapshot_disabled = False
        self.display_disabled = False
        try:
            self.tty = mode == "auto" and bool(getattr(self.stream, "isatty", lambda: False)())
        except (OSError, ValueError):
            self.tty = False
            self.display_disabled = True
        self.state = {"schema_version": "pipeline-progress-1", "run_id": run_id or uuid4().hex,
                      "stage": stage, "pid": os.getpid(), "status": "running", "phase": "starting",
                      "started_at_utc": wall_clock().isoformat(), "counts": {}, "item": {}, "transfer": {}}
        self.update(force=True)

    def update(self, *, force=False, **fields):
        counts = fields.pop("counts", None)
        if counts is not None:
            self.state["counts"].update(counts)
        self.state.update(fields)
        now = self.clock()
        self.state["elapsed_seconds"] = max(0, now - self.started)
        if not force and now - self.last_publish < self.interval:
            return
        self.last_publish = now
        self.state["updated_at_utc"] = self.wall_clock().isoformat()
        self._persist()
        self._display()

    def begin_transfer(self, total_bytes: int | None):
        self.transfer_started = self.clock()
        self.update(phase="transferring", transfer={"bytes_received": 0, "total_bytes": total_bytes,
                    "percent": 0.0 if total_bytes else None, "bytes_per_second": None, "eta_seconds": None}, force=True)

    def transfer(self, received: int, total: int | None):
        elapsed = max(0, self.clock() - self.transfer_started) if self.transfer_started is not None else 0
        speed = received / elapsed if elapsed > 0 and received > 0 else None
        known = total is not None and total > 0
        self.update(phase="transferring", transfer={"bytes_received": received, "total_bytes": total,
                    "percent": min(100, received * 100 / total) if known else None,
                    "bytes_per_second": speed,
                    "eta_seconds": max(0, total - received) / speed if known and speed else None})

    def finish(self, status="completed", **fields):
        if status not in {"completed", "partial", "failed", "skipped", "interrupted"}:
            raise ValueError("Invalid final progress status")
        self.update(force=True, status=status, phase="finished", finished_at_utc=self.wall_clock().isoformat(), **fields)

    def _persist(self):
        if self.path is None or self.snapshot_disabled:
            return
        temporary = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, name = tempfile.mkstemp(prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent)
            temporary = Path(name)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(self.state, stream, ensure_ascii=False)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        except OSError as exc:
            self.snapshot_disabled = True
            self.state["snapshot_error"] = str(exc)
            if self.mode != "off":
                try:
                    self.stream.write(f"Progress snapshot unavailable: {safe_text(exc)}\n")
                except (OSError, ValueError):
                    self.display_disabled = True
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass

    def _display(self):
        if self.mode == "off" or self.display_disabled:
            return
        line = format_status(self.state)
        try:
            if self.tty:
                self.stream.write("\r" + line.ljust(self.line_width))
                self.line_width = len(line)
                if self.state["status"] != "running":
                    self.stream.write("\n")
            else:
                self.stream.write(line + "\n")
            self.stream.flush()
        except (OSError, ValueError):
            self.display_disabled = True


def format_status(state: dict) -> str:
    counts = state.get("counts", {})
    item = state.get("item", {})
    pieces = [f"[{safe_text(state['stage'])}]", safe_text(state["status"]), safe_text(state.get("phase", ""))]
    if state.get("source_id"):
        pieces.append("source=" + safe_text(state["source_id"]))
    if "jobs_total" in counts:
        pieces.append(f"jobs={counts.get('jobs_completed', 0)}/{counts['jobs_total']}")
    if item.get("doc_id"):
        pieces.append(safe_text(item["doc_id"]))
    if item.get("title") or item.get("url"):
        pieces.append(safe_text(item.get("title") or item["url"], 72))
    for key in ("pages_visited", "queued", "candidates", "rejected", "requests", "retries", "deferred",
                "downloaded", "verified_existing", "recovered", "failed", "catalog_conflict"):
        if key in counts:
            pieces.append(f"{key}={counts[key]}")
    transfer = state.get("transfer", {})
    if transfer:
        pieces.append(size_text(transfer["bytes_received"]))
        if transfer.get("total_bytes") is not None:
            pieces.append("of " + size_text(transfer["total_bytes"]))
        if transfer.get("percent") is not None:
            pieces.append(f"{transfer['percent']:.0f}%")
        if transfer.get("bytes_per_second") is not None:
            pieces.append(size_text(transfer["bytes_per_second"]) + "/s")
        if transfer.get("eta_seconds") is not None:
            pieces.append(f"ETA {transfer['eta_seconds']:.0f}s")
    if state.get("phase") in {"retry_wait", "rate_wait"}:
        pieces.append(f"wait={state.get('wait_seconds', 0):.1f}s")
    if state.get("robots_outcome"):
        pieces.append("robots=" + safe_text(state["robots_outcome"]))
    if state.get("stop_reason"):
        pieces.append("stop=" + safe_text(state["stop_reason"]))
    pieces.append(f"elapsed={state.get('elapsed_seconds', 0):.0f}s")
    return " | ".join(pieces)


def read_status(path: Path, *, stale_after=120.0, now=None) -> dict:
    if not math.isfinite(stale_after) or stale_after <= 0:
        raise ValueError("stale-after must be a positive finite duration")
    state = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(state, dict) or state.get("schema_version") != "pipeline-progress-1":
        raise ValueError("Unsupported progress snapshot")
    if not isinstance(state.get("stage"), str) or state.get("status") not in {"running", "completed", "partial", "failed", "skipped", "interrupted"}:
        raise ValueError("Invalid progress stage/status")
    if any(not isinstance(state.get(key, {}), dict) for key in ("counts", "item", "transfer")):
        raise ValueError("Invalid progress counters/item/transfer")
    updated = datetime.fromisoformat(state["updated_at_utc"])
    if updated.tzinfo is None:
        raise ValueError("Progress timestamp requires a timezone")
    age = max(0, ((now or utc_now()) - updated).total_seconds())
    result = {**state, "seconds_since_update": age, "observed_status": state["status"]}
    if state["status"] == "running" and age > stale_after:
        result["observed_status"] = "possibly_stale"
        result["status_note"] = "No recent update; a slow operation or stopped process may explain this. This is not proof of failure."
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Read a pipeline progress snapshot without changing the run.")
    parser.add_argument("path", type=Path, help="Path to a run's .progress.json file")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--stale-after", type=float, default=120)
    args = parser.parse_args()
    try:
        state = read_status(args.path, stale_after=args.stale_after)
        if args.json:
            print(json.dumps(state, ensure_ascii=False, indent=2))
        else:
            print(format_status(state))
            print(f"Observed status: {state['observed_status']}; last update {state['seconds_since_update']:.0f}s ago")
            if state.get("status_note"):
                print(state["status_note"])
        return 0
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        parser.exit(2, f"Cannot read progress snapshot: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
