#!/usr/bin/env python3
"""
Compatibility entry for Indonesia DS failed-instance auto retry.

The implementation lives in tools/ds_failed_auto_retry.py. Keep this file so
older n8n workflows that still call tools/ine_ds_failed_auto_retry.py continue
to use the shared retry and TV alert logic.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Callable

from tools import ds_failed_auto_retry as shared


ROOT = shared.ROOT
DEFAULT_STATE_FILE = shared.default_state_file("ine")
DEFAULT_GATEWAY_ENTRY = shared.DEFAULT_GATEWAY_ENTRY
DEFAULT_TV_URL = shared.DEFAULT_TV_URL
DEFAULT_TV_BOT_ID = shared.DEFAULT_TV_BOT_ID
DEFAULT_TV_APP_ID = shared.DEFAULT_TV_APP_ID
SUCCESS_STATES = shared.SUCCESS_STATES
TERMINAL_FAILURE_STATES = shared.TERMINAL_FAILURE_STATES

_load_dotenv = shared._load_dotenv
_decode_payload = shared._decode_payload
_walk_values = shared._walk_values
_first_nested = shared._first_nested
_string_blob = shared._string_blob
_regex_first = shared._regex_first
_read_json = shared._read_json
_write_json = shared._write_json
record_attempt = shared.record_attempt
clear_attempts = shared.clear_attempts
current_attempts = shared.current_attempts
_payload_b64 = shared._payload_b64
extract_instance_state = shared.extract_instance_state
extract_failure_reason = shared.extract_failure_reason
send_tv_alert = shared.send_tv_alert
build_retry_progress_message = shared.build_retry_progress_message
build_failure_message = shared.build_failure_message


def normalize_alert_payload(raw: Any) -> dict[str, Any]:
    return shared.normalize_alert_payload(raw, country="ine")


def run_gateway_action(
    action: str,
    ds_token: str,
    payload: dict[str, Any],
    request_id: str,
    gateway_entry: Path = DEFAULT_GATEWAY_ENTRY,
) -> dict[str, Any]:
    return shared.run_gateway_action(
        action,
        ds_token,
        payload,
        request_id,
        country="ine",
        gateway_entry=gateway_entry,
    )


def auto_retry(
    alert: dict[str, Any],
    ds_token: str,
    max_attempts: int,
    retry_delay_seconds: int,
    state_file: Path,
    sleep: Callable[[int], None] = shared.time.sleep,
    gateway_runner: Callable[[str, str, dict[str, Any], str], dict[str, Any]] | None = None,
    tv_sender: Callable[[str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    alert = {**alert, "country": "ine"}
    return shared.auto_retry(
        alert=alert,
        ds_token=ds_token,
        max_attempts=max_attempts,
        retry_delay_seconds=retry_delay_seconds,
        state_file=state_file,
        sleep=sleep,
        gateway_runner=gateway_runner,
        tv_sender=tv_sender,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--payload-b64", required=True)
    parser.add_argument("--ds-token", default="")
    parser.add_argument("--request-id", default="")
    parser.add_argument("--max-attempts", type=int, default=int(os.getenv("DS_FAILED_MAX_RETRIES", "3")))
    parser.add_argument("--retry-delay-seconds", type=int, default=int(os.getenv("DS_FAILED_RETRY_DELAY_SECONDS", "180")))
    parser.add_argument("--state-file", default=str(DEFAULT_STATE_FILE))
    args = parser.parse_args(argv)

    _load_dotenv(ROOT / ".env.local")
    raw = _decode_payload(args.payload_b64)
    alert = normalize_alert_payload(raw)
    ds_token = args.ds_token.strip() or alert.get("ds_token") or os.getenv("DS_TOKEN", "")

    result = auto_retry(
        alert=alert,
        ds_token=ds_token,
        max_attempts=args.max_attempts,
        retry_delay_seconds=args.retry_delay_seconds,
        state_file=Path(args.state_file),
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
