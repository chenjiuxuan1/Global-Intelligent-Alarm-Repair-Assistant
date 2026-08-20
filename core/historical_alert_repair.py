#!/usr/bin/env python3
"""Queue-based historical repair for non-CN StarRocks quality alerts.

The script snapshots every unresolved quality alert into the country's SR
``testdb`` queue.  Missing data is repaired only when its class is due; excess
data remains in the queue as ``manual_review`` and never starts DolphinScheduler.
"""

from __future__ import annotations

import hashlib
import os
import time
from datetime import datetime, timedelta

from config.config import HISTORICAL_REPAIR_CONFIG, TABLE_CONFIG
from core import repair_strict_7step as repair


COUNTRY = (os.getenv("APP_COUNTRY") or os.getenv("COUNTRY") or "").strip().lower()
QUEUE_TABLE = HISTORICAL_REPAIR_CONFIG["table"]
QUALITY_RESULT_TABLE = TABLE_CONFIG["quality_result_table"]


def log(message):
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] [历史修复] {message}", flush=True)


def quote_identifier(value):
    return "`" + str(value).replace("`", "``") + "`"


def queue_enabled():
    return COUNTRY and COUNTRY != "cn"


def get_queue_connection():
    import pymysql
    from pymysql.cursors import DictCursor

    required = ("host", "user", "password")
    missing = [key for key in required if not HISTORICAL_REPAIR_CONFIG.get(key)]
    if missing:
        raise ValueError(
            "历史修复队列未配置 StarRocks testdb 连接: " + ", ".join(f"SR_TESTDB_{key.upper()}" for key in missing)
        )
    return pymysql.connect(
        host=HISTORICAL_REPAIR_CONFIG["host"],
        port=HISTORICAL_REPAIR_CONFIG["port"],
        user=HISTORICAL_REPAIR_CONFIG["user"],
        password=HISTORICAL_REPAIR_CONFIG["password"],
        database=HISTORICAL_REPAIR_CONFIG["database"],
        charset="utf8mb4",
        cursorclass=DictCursor,
    )


def ensure_queue_table(connection):
    """Create a StarRocks primary-key queue.  Re-inserts update the same alert."""
    table = quote_identifier(QUEUE_TABLE)
    sql = f"""
        CREATE TABLE IF NOT EXISTS {table} (
            queue_key VARCHAR(128) NOT NULL,
            alert_id BIGINT,
            source_table VARCHAR(512),
            comparison_table VARCHAR(512),
            source_column_name VARCHAR(512),
            source_column_count BIGINT,
            comparison_column_name VARCHAR(512),
            comparison_column_count BIGINT,
            data_updated_at DATETIME,
            queued_at DATETIME,
            diff DECIMAL(38, 6),
            alert_class VARCHAR(32),
            repair_action VARCHAR(32),
            status VARCHAR(32),
            workflow_code VARCHAR(128),
            task_code VARCHAR(128),
            last_error VARCHAR(2048),
            updated_at DATETIME
        ) ENGINE=OLAP
        PRIMARY KEY(queue_key)
        DISTRIBUTED BY HASH(queue_key) BUCKETS 1
        PROPERTIES ("replication_num" = "1")
    """
    with connection.cursor() as cursor:
        cursor.execute(sql)
    connection.commit()


def value_from(row, *names):
    for name in names:
        value = row.get(name)
        if value not in (None, ""):
            return value
    return None


def normalize_datetime(value):
    return repair.normalize_to_datetime(value)


def alert_updated_at(row, now=None):
    now = now or datetime.now()
    explicit = value_from(row, "data_updated_at", "updated_at", "data_time", "dt", "end")
    parsed = normalize_datetime(explicit)
    if parsed and value_from(row, "end") is not None and explicit == row.get("end"):
        return parsed - timedelta(days=1)
    return parsed or now


def classify_alert(row, now=None):
    now = now or datetime.now()
    age_days = max((now.date() - alert_updated_at(row, now).date()).days, 0)
    if age_days <= 7:
        return "seven_days"
    if age_days <= 90:
        return "ninety_days"
    if age_days <= 365:
        return "one_year"
    return "out_of_scope"


def diff_is_excess(value):
    try:
        return float(value) < 0
    except (TypeError, ValueError):
        return False


def queue_key(row, alert_class):
    raw = "|".join(str(value_from(row, "id") or "") for _ in [0])
    raw += "|" + str(repair.resolve_repair_table(row) or "") + "|" + alert_class
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def load_unresolved_alert_rows():
    from alert.db_config import get_db_connection

    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT * FROM {quote_identifier(QUALITY_RESULT_TABLE)} "
                "WHERE result = 1 AND is_repaired = 0 ORDER BY created_at DESC"
            )
            return cursor.fetchall()
    finally:
        connection.close()


def queue_alerts(connection, rows, now=None):
    now = now or datetime.now()
    table = quote_identifier(QUEUE_TABLE)
    sql = f"""INSERT INTO {table} (
        queue_key, alert_id, source_table, comparison_table,
        source_column_name, source_column_count,
        comparison_column_name, comparison_column_count,
        data_updated_at, queued_at, diff, alert_class, repair_action,
        status, updated_at
    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"""
    inserted = 0
    with connection.cursor() as cursor:
        for row in rows:
            alert_class = classify_alert(row, now)
            action = "manual_review" if (diff_is_excess(row.get("diff")) or alert_class == "out_of_scope") else "rerun"
            status = "manual_review" if action == "manual_review" else "pending"
            payload = (
                queue_key(row, alert_class), value_from(row, "id"),
                value_from(row, "src_tbl", "source_table"), value_from(row, "dest_tbl", "comparison_table"),
                value_from(row, "src_col", "src_column", "source_column", "src_field"),
                value_from(row, "src_count", "source_count", "src_column_count"),
                value_from(row, "dest_col", "dest_column", "comparison_column", "dest_field"),
                value_from(row, "dest_count", "comparison_count", "dest_column_count"),
                alert_updated_at(row, now), now, row.get("diff"), alert_class, action, status, now,
            )
            cursor.execute(sql, payload)
            inserted += 1
    connection.commit()
    return inserted


def class_is_due(alert_class, now=None):
    now = now or datetime.now()
    if alert_class == "seven_days":
        return True
    if alert_class == "ninety_days":
        return now.weekday() >= 5
    if alert_class == "one_year":
        return now.day == 1
    return False


def wait_for_ds_idle():
    poll = HISTORICAL_REPAIR_CONFIG["idle_poll_seconds"]
    max_wait = HISTORICAL_REPAIR_CONFIG["idle_max_wait_seconds"]
    started = time.monotonic()
    while True:
        running = repair.get_all_instances_from_lists(repair.PROJECT_CODE, state_type="RUNNING_EXECUTION")
        if not running:
            return True
        if max_wait and time.monotonic() - started >= max_wait:
            log(f"DS 仍有 {len(running)} 个运行实例，达到等待上限，本轮保留队列")
            return False
        log(f"DS 有 {len(running)} 个运行实例，{poll} 秒后再次检查")
        time.sleep(poll)


def due_queue_alerts(connection, now=None):
    now = now or datetime.now()
    due_classes = [item for item in ("seven_days", "ninety_days", "one_year") if class_is_due(item, now)]
    if not due_classes:
        return []
    placeholders = ", ".join(["%s"] * len(due_classes))
    sql = (
        f"SELECT * FROM {quote_identifier(QUEUE_TABLE)} "
        f"WHERE repair_action = 'rerun' AND status = 'pending' AND alert_class IN ({placeholders}) "
        "ORDER BY data_updated_at DESC LIMIT %s"
    )
    with connection.cursor() as cursor:
        cursor.execute(sql, [*due_classes, HISTORICAL_REPAIR_CONFIG["batch_size"]])
        return cursor.fetchall()


def queue_item_to_alert(item):
    return {
        "id": item.get("alert_id"),
        "table": item.get("comparison_table") or item.get("source_table"),
        "src_tbl": item.get("source_table") or "",
        "dest_tbl": item.get("comparison_table") or "",
        "search_tables": [item.get("comparison_table") or item.get("source_table")],
        "dt": item.get("data_updated_at").strftime("%Y-%m-%d") if item.get("data_updated_at") else "",
        "diff": item.get("diff"),
        "queue_key": item["queue_key"],
    }


def update_queue_status(connection, queue_key, status, error="", task=None):
    task = task or {}
    sql = (
        f"UPDATE {quote_identifier(QUEUE_TABLE)} SET status=%s, workflow_code=%s, task_code=%s, "
        "last_error=%s, updated_at=%s WHERE queue_key=%s"
    )
    with connection.cursor() as cursor:
        cursor.execute(sql, (status, task.get("workflow_code", ""), task.get("task_code", ""), error, datetime.now(), queue_key))
    connection.commit()


def source_alert_cleared(alert_id):
    if alert_id in (None, ""):
        return False
    from alert.db_config import get_db_connection

    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT 1 FROM {quote_identifier(QUALITY_RESULT_TABLE)} "
                "WHERE id=%s AND result=1 AND is_repaired=0 LIMIT 1",
                (alert_id,),
            )
            return cursor.fetchone() is None
    finally:
        connection.close()


def delete_queue_item(connection, queue_key):
    with connection.cursor() as cursor:
        cursor.execute(f"DELETE FROM {quote_identifier(QUEUE_TABLE)} WHERE queue_key=%s", (queue_key,))
    connection.commit()


def process_due_queue(connection, now=None):
    if not wait_for_ds_idle():
        return
    queued = due_queue_alerts(connection, now)
    if not queued:
        log("没有到期的缺失数据修复任务")
        return
    alerts = [queue_item_to_alert(item) for item in queued]
    tasks = repair.step2_find_locations(alerts)
    queue_keys_by_alert = {str(item.get("alert_id")): item["queue_key"] for item in queued}
    for task in tasks:
        task["queue_key"] = queue_keys_by_alert.get(str(task.get("alert_id")), "")
    runnable, manual = repair.apply_repair_strategy(tasks, {})
    for task in manual:
        update_queue_status(connection, task.get("queue_key", ""), "manual_review", task.get("error", ""), task)
    results, completed, failed = repair.execute_repairs_in_batches(runnable, max_parallel=1)
    for task in failed:
        update_queue_status(connection, task.get("queue_key", ""), "pending", task.get("error", ""), task)
    if completed:
        fuyan = repair.step5_execute_fuyan(completed, failed, alerts)
        repair.wait_for_fuyan_results(fuyan)
    for item in queued:
        if source_alert_cleared(item.get("alert_id")):
            delete_queue_item(connection, item["queue_key"])
            log(f"复验后差异已消失，已删除队列记录: {item['queue_key']}")
        else:
            update_queue_status(connection, item["queue_key"], "pending")


def main():
    if not queue_enabled():
        log("中国环境保持原有修复流程")
        return repair.main()
    connection = get_queue_connection()
    try:
        ensure_queue_table(connection)
        rows = load_unresolved_alert_rows()
        log(f"发现 {len(rows)} 条未恢复质量告警")
        queue_alerts(connection, rows)
        process_due_queue(connection)
    finally:
        connection.close()


if __name__ == "__main__":
    main()
