"""Progress for long jobs, stored in the database so any page (and any
container) can show it.

A job is a list of stages (company data, each month of accounts, owners,
scoring, ...). Each stage reports a fraction done; overall progress and the
time remaining are worked out from that. Writes go through their own
autocommitted connection, at most every two seconds, so they are visible
immediately and never wait on the long-running load transaction.
"""
from __future__ import annotations

import json
import time
from datetime import datetime

from . import db


class Cancelled(Exception):
    pass


class Job:
    def __init__(self, kind: str, stages: list[str]):
        self.conn = db.connect()
        self.conn.autocommit = True
        self.stages = [{"name": s, "status": "waiting", "seconds": None} for s in stages]
        self.id = self.conn.execute(
            "insert into job (kind, stage_total, stages) values (%s, %s, %s) returning id",
            (kind, len(stages), json.dumps(self.stages)),
        ).fetchone()["id"]
        self.started = time.time()
        self.index = -1
        self.stage_started = self.started
        self.frac = 0.0
        self.detail = ""
        self.logs: list[str] = []
        self._last = 0.0
        self._lock = __import__("threading").Lock()
        self._alive = True
        __import__("threading").Thread(target=self._heartbeat, daemon=True).start()

    def _heartbeat(self):
        """Keep updated_at fresh during long single database steps, so the job
        is not mistaken for one that died."""
        while self._alive:
            time.sleep(30)
            if not self._alive:
                return
            try:
                with self._lock:
                    self.conn.execute("update job set updated_at = now() where id = %s and status = 'running'", (self.id,))
            except Exception:
                return

    # -- stages ------------------------------------------------------------
    def stage(self, name: str):
        """Move to the named stage (adding it if it was not planned)."""
        now = time.time()
        if 0 <= self.index < len(self.stages) and self.stages[self.index]["status"] == "running":
            self.stages[self.index].update(status="done", seconds=round(now - self.stage_started))
        names = [s["name"] for s in self.stages]
        if name in names:
            self.index = names.index(name)
        else:
            self.stages.append({"name": name, "status": "waiting", "seconds": None})
            self.index = len(self.stages) - 1
        self.stages[self.index]["status"] = "running"
        self.stage_started = now
        self.frac = 0.0
        self.detail = ""
        self.log(f"Started: {name}")
        self._write(force=True)

    def skip(self, name: str, why: str = "skipped"):
        for s in self.stages:
            if s["name"] == name:
                s["status"] = why
        self._write(force=True)

    def progress(self, frac: float | None = None, detail: str | None = None):
        if frac is not None:
            self.frac = max(0.0, min(1.0, frac))
        if detail is not None:
            self.detail = detail
        self._write()

    def log(self, msg: str):
        self.logs = (self.logs + [f"{datetime.now():%H:%M:%S} {msg}"])[-60:]
        self._write()

    # -- end ---------------------------------------------------------------
    def finish(self, result=None, status: str = "done", error: str | None = None):
        self._alive = False
        now = time.time()
        if 0 <= self.index < len(self.stages) and self.stages[self.index]["status"] == "running":
            self.stages[self.index].update(status="done" if status == "done" else status,
                                           seconds=round(now - self.stage_started))
        with self._lock:
          self.conn.execute(
            """update job set status = %s, result = %s, error = %s, finished_at = now(), updated_at = now(),
                   pct = case when %s = 'done' then 100 else pct end, eta_seconds = null, stages = %s, log = %s
               where id = %s""",
            (status, json.dumps(result, default=str) if result is not None else None, error, status,
             json.dumps(self.stages), json.dumps(self.logs), self.id),
          )
        self.conn.close()

    def check_cancel(self):
        with self._lock:
            row = self.conn.execute("select cancel_requested from job where id = %s", (self.id,)).fetchone()
        if row and row["cancel_requested"]:
            raise Cancelled("Stopped by you")

    # -- internals ---------------------------------------------------------
    def overall(self) -> float:
        done = sum(1 for s in self.stages if s["status"] in ("done", "skipped", "already loaded"))
        current = self.frac if 0 <= self.index < len(self.stages) and self.stages[self.index]["status"] == "running" else 0
        return min(1.0, (done + current) / max(len(self.stages), 1))

    def _write(self, force: bool = False):
        now = time.time()
        if not force and now - self._last < 2:
            return
        self._last = now
        pct = self.overall()
        elapsed = now - self.started
        eta = int(elapsed / pct * (1 - pct)) if pct > 0.02 and elapsed > 30 else None
        with self._lock:
          self.conn.execute(
            """update job set stage = %s, stage_index = %s, stage_total = %s, stage_pct = %s, pct = %s,
                   detail = %s, eta_seconds = %s, stages = %s, log = %s, updated_at = now()
               where id = %s""",
            (self.stages[self.index]["name"] if self.index >= 0 else None, max(self.index, 0), len(self.stages),
             round(self.frac * 100, 1), round(pct * 100, 1), self.detail, eta, json.dumps(self.stages),
             json.dumps(self.logs), self.id),
          )
        if now - getattr(self, "_last_cancel_check", 0) > 10:
            self._last_cancel_check = now
            self.check_cancel()


def current(conn) -> dict | None:
    """The running job, or the most recent one."""
    row = conn.execute(
        "select * from job order by (status = 'running') desc, started_at desc limit 1").fetchone()
    if row and row["status"] == "running" and (datetime.now(row["updated_at"].tzinfo) - row["updated_at"]).total_seconds() > 180:
        # No heartbeat (every 30s) for 3 minutes: the process running it has gone (e.g. a restart).
        conn.execute("update job set status = 'failed', error = 'Interrupted (the app restarted). Start it again (Download and load now on the Data page, or Refresh data on Home): files already loaded are skipped.', finished_at = now() where id = %s",
                     (row["id"],))
        row = conn.execute("select * from job where id = %s", (row["id"],)).fetchone()
    return row
