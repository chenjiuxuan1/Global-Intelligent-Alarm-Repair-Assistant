"""Optional non-CN audit copy of current quality-result anomalies to SR testdb.

This module intentionally does not influence master repair, DS scheduling, or
recheck behavior. It only writes a durable audit row after the normal scan.
"""
import hashlib
import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime, timedelta

from config.config import TABLE_CONFIG, TESTDB_ALERT_CONFIG
from core import repair_strict_7step as repair

COUNTRY = (os.getenv("APP_COUNTRY") or os.getenv("COUNTRY") or "").strip().lower()


def enabled():
    return TESTDB_ALERT_CONFIG["enabled"] and COUNTRY and COUNTRY != "cn"


def _identifier(value):
    parts = [part.strip().strip("`") for part in str(value or "").split(".")]
    if not parts or any(not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", part) for part in parts):
        raise ValueError("invalid SQL identifier")
    return ".".join("`" + part + "`" for part in parts)


def _connection():
    import pymysql
    from pymysql.cursors import DictCursor
    missing = [key for key in ("host", "user", "password") if not TESTDB_ALERT_CONFIG[key]]
    if missing:
        raise ValueError("missing SR testdb configuration: " + ", ".join(missing))
    return pymysql.connect(host=TESTDB_ALERT_CONFIG["host"], port=TESTDB_ALERT_CONFIG["port"],
        user=TESTDB_ALERT_CONFIG["user"], password=TESTDB_ALERT_CONFIG["password"],
        database=TESTDB_ALERT_CONFIG["database"], charset="utf8mb4", cursorclass=DictCursor)


def ensure_table(conn):
    table = _identifier(TESTDB_ALERT_CONFIG["table"])
    sql = f'''CREATE TABLE IF NOT EXISTS {table} (
      audit_key VARCHAR(128) NOT NULL, alert_id BIGINT,
      source_database VARCHAR(512), comparison_database VARCHAR(512),
      source_table VARCHAR(512), comparison_table VARCHAR(512),
      metric_name VARCHAR(512), metric_description VARCHAR(2048),
      source_sql VARCHAR(65533), comparison_sql VARCHAR(65533),
      source_value VARCHAR(65533), comparison_value VARCHAR(65533),
      data_date DATETIME, entered_testdb_at DATETIME,
      data_diff DECIMAL(38,6), alert_class VARCHAR(16), diff_label TINYINT,
      status VARCHAR(32), ai_analysis VARCHAR(8192), ai_status VARCHAR(32),
      ai_error VARCHAR(1024), updated_at DATETIME
    ) ENGINE=OLAP PRIMARY KEY(audit_key)
    DISTRIBUTED BY HASH(audit_key) BUCKETS 1 PROPERTIES ("replication_num"="1")'''
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()


def _value(row, *keys):
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return None


def _json_safe(value):
    """Preserve scalar values and grouped-query lists in a text column."""
    if value is None or isinstance(value, str):
        return value
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, default=str)
    return str(value)


def data_date(row, now):
    """Use the checked business-window start, never alert updated_at."""
    begin_time = repair.normalize_to_datetime(row.get("begin"))
    if begin_time:
        return begin_time
    end_time = repair.normalize_to_datetime(row.get("end"))
    if end_time:
        return end_time
    return repair.normalize_to_datetime(row.get("created_at")) or now


def alert_class(row, now):
    age = max((now.date() - data_date(row, now).date()).days, 0)
    if age <= 7:
        return "7d"
    if age <= 90:
        return "90d"
    if age <= 365:
        return "1y"
    return "expired"


def diff_label(row):
    try:
        return 2 if float(row.get("diff")) < 0 else 1  # 1=missing, 2=extra
    except (TypeError, ValueError):
        return 1


def audit_key(row, now):
    value = "|".join(str(item or "") for item in (
        _value(row, "id"), _value(row, "src_tbl"), _value(row, "dest_tbl"),
        data_date(row, now).isoformat()))
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def analyze_long_anomaly(row, now, observations):
    """Ask n8n/AI for an advisory date range; it cannot run SQL or DS tasks."""
    if alert_class(row, now) not in {"90d", "1y"} or not TESTDB_ALERT_CONFIG["ai_webhook_url"]:
        return "disabled", "", ""
    payload = {
        "country": COUNTRY,
        "source_database": _value(row, "src_db"),
        "comparison_database": _value(row, "dest_db"),
        "source_table": _value(row, "src_tbl"),
        "comparison_table": _value(row, "dest_tbl"),
        "metric_name": row.get("name"),
        "metric_description": row.get("desc"),
        "source_sql": row.get("src_sql"),
        "comparison_sql": row.get("dest_sql"),
        "source_value": _json_safe(_value(row, "src_value", "src_count")),
        "comparison_value": _json_safe(_value(row, "dest_value", "dest_count")),
        "diff": row.get("diff"),
        "data_date": data_date(row, now).strftime("%Y-%m-%d"),
        "alert_class": alert_class(row, now),
        "observations": observations,
        "instruction": "Locate the most likely anomaly start/end date from the supplied metadata. Return JSON only; do not execute SQL or start jobs.",
    }
    headers = {"Content-Type": "application/json"}
    if TESTDB_ALERT_CONFIG["ai_webhook_token"]:
        headers["Authorization"] = "Bearer " + TESTDB_ALERT_CONFIG["ai_webhook_token"]
    try:
        request = urllib.request.Request(TESTDB_ALERT_CONFIG["ai_webhook_url"], data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
        with urllib.request.urlopen(request, timeout=TESTDB_ALERT_CONFIG["ai_timeout_seconds"]) as response:
            return "complete", response.read().decode("utf-8", errors="replace")[:8192], ""
    except (urllib.error.URLError, TimeoutError, ValueError) as error:
        return "error", "", str(error)[:1024]


def source_rows():
    from alert.db_config import get_db_connection
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT * FROM {_identifier(TABLE_CONFIG['quality_result_table'])} WHERE result=1 AND is_repaired=0")
            return cur.fetchall()
    finally:
        conn.close()


def persist_current_alerts():
    """Create the audit table if needed and append each current result=1 alert once."""
    now = datetime.now()
    conn = _connection()
    try:
        ensure_table(conn)
        table = _identifier(TESTDB_ALERT_CONFIG["table"])
        sql = f"""INSERT INTO {table} (audit_key,alert_id,source_database,comparison_database,source_table,comparison_table,metric_name,metric_description,source_sql,comparison_sql,source_value,comparison_value,data_date,entered_testdb_at,data_diff,alert_class,diff_label,status,ai_analysis,ai_status,ai_error,updated_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"""
        with conn.cursor() as cur:
            for row in source_rows():
                key = audit_key(row, now)
                cur.execute(f"SELECT audit_key FROM {table} WHERE audit_key=%s", (key,))
                if cur.fetchone():
                    continue
                cur.execute(
                    f"SELECT data_date,data_diff,source_value,comparison_value FROM {table} "
                    "WHERE source_table=%s AND comparison_table=%s ORDER BY data_date ASC",
                    (_value(row, "src_tbl"), _value(row, "dest_tbl")),
                )
                observations = [
                    {
                        **item,
                        "data_date": item.get("data_date").strftime("%Y-%m-%d")
                        if getattr(item.get("data_date"), "strftime", None) else item.get("data_date"),
                    }
                    for item in cur.fetchall()
                ]
                observations.append({
                    "data_date": data_date(row, now).strftime("%Y-%m-%d"),
                    "data_diff": row.get("diff"),
                    "source_value": _json_safe(_value(row, "src_value", "src_count")),
                    "comparison_value": _json_safe(_value(row, "dest_value", "dest_count")),
                })
                ai_status, ai_analysis, ai_error = analyze_long_anomaly(row, now, observations)
                cur.execute(sql, (key, _value(row, "id"), _value(row, "src_db"), _value(row, "dest_db"), _value(row, "src_tbl"), _value(row, "dest_tbl"),
                    row.get("name"), row.get("desc"), row.get("src_sql"), row.get("dest_sql"),
                    _json_safe(_value(row, "src_value", "src_count")), _json_safe(_value(row, "dest_value", "dest_count")),
                    data_date(row, now), now, row.get("diff"), alert_class(row, now), diff_label(row), "recorded",
                    ai_analysis, ai_status, ai_error, now))
        conn.commit()
    finally:
        conn.close()
