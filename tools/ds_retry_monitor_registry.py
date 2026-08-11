#!/usr/bin/env python3
"""Per-country active DS retry monitor registry with a local circuit breaker."""

from __future__ import annotations

import fcntl
import json
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator


def process_alive(pid: int) -> bool:
    if int(pid or 0) <= 0:
        return False
    try:
        os.kill(int(pid), 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False


class CountryMonitorRegistry:
    def __init__(
        self,
        path: Path,
        *,
        active_limit: int = 10,
        circuit_seconds: int = 1800,
        stale_seconds: int = 300,
        clock: Callable[[], float] = time.time,
        process_alive: Callable[[int], bool] = process_alive,
    ) -> None:
        self.path = Path(path)
        self.lock_path = self.path.with_suffix(self.path.suffix + ".lock")
        self.active_limit = max(1, int(active_limit))
        self.circuit_seconds = max(1, int(circuit_seconds))
        self.stale_seconds = max(1, int(stale_seconds))
        self.clock = clock
        self.process_alive = process_alive

    @staticmethod
    def _empty_state() -> dict[str, Any]:
        return {
            "circuit_open_until": 0.0,
            "circuit_alert_sent_at": 0.0,
            "monitors": {},
        }

    def _load_state(self) -> dict[str, Any]:
        if not self.path.exists():
            return self._empty_state()
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(loaded, dict):
                raise ValueError("registry root must be an object")
        except (OSError, ValueError, json.JSONDecodeError):
            backup = self.path.with_name(
                f"{self.path.name}.corrupt.{int(self.clock())}.{os.getpid()}"
            )
            try:
                os.replace(self.path, backup)
            except OSError:
                pass
            return self._empty_state()

        monitors = loaded.get("monitors")
        loaded["monitors"] = monitors if isinstance(monitors, dict) else {}
        loaded["circuit_open_until"] = float(loaded.get("circuit_open_until") or 0.0)
        loaded["circuit_alert_sent_at"] = float(loaded.get("circuit_alert_sent_at") or 0.0)
        return loaded

    def _write_state(self, state: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
        temporary.write_text(
            json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        os.replace(temporary, self.path)

    @contextmanager
    def _locked_state(self) -> Iterator[dict[str, Any]]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.lock_path.open("a+", encoding="utf-8")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            state = self._load_state()
            yield state
            self._write_state(state)
        finally:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            finally:
                handle.close()

    def _cleanup_stale(self, state: dict[str, Any], now: float) -> None:
        monitors = state["monitors"]
        stale_keys = []
        for retry_key, monitor in monitors.items():
            if not isinstance(monitor, dict):
                stale_keys.append(retry_key)
                continue
            pid = int(monitor.get("pid") or 0)
            heartbeat = float(monitor.get("last_heartbeat_at") or 0.0)
            expired = now - heartbeat > self.stale_seconds
            try:
                alive = self.process_alive(pid)
            except Exception:
                if expired:
                    stale_keys.append(retry_key)
                continue
            if not alive:
                stale_keys.append(retry_key)
        for retry_key in stale_keys:
            monitors.pop(retry_key, None)

    def _refresh_expired_circuit(self, state: dict[str, Any], now: float) -> None:
        open_until = float(state.get("circuit_open_until") or 0.0)
        if not open_until or now < open_until:
            return
        if len(state["monitors"]) < self.active_limit:
            state["circuit_open_until"] = 0.0
            state["circuit_alert_sent_at"] = 0.0
        else:
            state["circuit_open_until"] = now + self.circuit_seconds

    @staticmethod
    def _is_open(state: dict[str, Any], now: float) -> bool:
        return float(state.get("circuit_open_until") or 0.0) > now

    def _decision(
        self,
        state: dict[str, Any],
        now: float,
        *,
        accepted: bool,
        alert_required: bool = False,
    ) -> dict[str, Any]:
        return {
            "accepted": bool(accepted),
            "circuit_open": self._is_open(state, now),
            "alert_required": bool(alert_required),
            "active_count": len(state["monitors"]),
            "circuit_open_until": float(state.get("circuit_open_until") or 0.0),
        }

    def register(
        self,
        retry_key: str,
        *,
        pid: int,
        request_id: str = "",
        instance_id: str = "",
    ) -> dict[str, Any]:
        now = float(self.clock())
        with self._locked_state() as state:
            self._cleanup_stale(state, now)
            self._refresh_expired_circuit(state, now)
            if self._is_open(state, now):
                return self._decision(state, now, accepted=False)

            existing = state["monitors"].get(retry_key)
            started_at = float(existing.get("started_at") or now) if isinstance(existing, dict) else now
            state["monitors"][retry_key] = {
                "pid": int(pid),
                "request_id": str(request_id or ""),
                "instance_id": str(instance_id or ""),
                "started_at": started_at,
                "last_heartbeat_at": now,
            }

            if len(state["monitors"]) >= self.active_limit:
                state["circuit_open_until"] = now + self.circuit_seconds
                state["circuit_alert_sent_at"] = now
                return self._decision(
                    state,
                    now,
                    accepted=False,
                    alert_required=True,
                )
            return self._decision(state, now, accepted=True)

    def heartbeat(self, retry_key: str, *, pid: int) -> dict[str, Any]:
        now = float(self.clock())
        with self._locked_state() as state:
            self._cleanup_stale(state, now)
            self._refresh_expired_circuit(state, now)
            monitor = state["monitors"].get(retry_key)
            if isinstance(monitor, dict) and int(monitor.get("pid") or 0) == int(pid):
                monitor["last_heartbeat_at"] = now
            return self._decision(
                state,
                now,
                accepted=not self._is_open(state, now),
            )

    def unregister(self, retry_key: str, *, pid: int) -> dict[str, Any]:
        now = float(self.clock())
        with self._locked_state() as state:
            self._cleanup_stale(state, now)
            monitor = state["monitors"].get(retry_key)
            if not isinstance(monitor, dict) or int(monitor.get("pid") or 0) == int(pid):
                state["monitors"].pop(retry_key, None)
            self._refresh_expired_circuit(state, now)
            return self._decision(
                state,
                now,
                accepted=not self._is_open(state, now),
            )

    def snapshot(self) -> dict[str, Any]:
        now = float(self.clock())
        with self._locked_state() as state:
            self._cleanup_stale(state, now)
            self._refresh_expired_circuit(state, now)
            decision = self._decision(
                state,
                now,
                accepted=not self._is_open(state, now),
            )
            return {
                **decision,
                "monitors": json.loads(json.dumps(state["monitors"])),
            }
