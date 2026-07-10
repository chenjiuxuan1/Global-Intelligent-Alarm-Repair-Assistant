#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import auto_load_env
from config.config import DB_CONFIG, OPENCLAW_CONFIG, TABLE_CONFIG


# -*- coding: utf-8 -*-
"""
告警格式化发送脚本
按照标准格式发送告警到钉钉群

用法：
    python send_alert.py --task-name "任务名称" --alert-time "2026-03-19 11:30:00" --level "3" --check-time "03 月 18 日 00 时 至 03 月 19 日 00 时" --content "告警内容" --sql "SELECT ..."
    
    或者从数据库读取最新告警：
    python send_alert.py --from-db
"""

import sys
import io
import argparse
import json
import requests
from datetime import datetime

# 确保 UTF-8 输出
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# ================= 配置区 =================
OPENCLAW_WEBHOOK = OPENCLAW_CONFIG['webhook']
OPENCLAW_HOOK_TOKEN = OPENCLAW_CONFIG['token']
DB_HOST = DB_CONFIG['host']
DB_PORT = DB_CONFIG['port']
DB_USER = DB_CONFIG['user']
DB_PASS = DB_CONFIG['password']
DB_NAME = DB_CONFIG['database']
QUALITY_ALERT_TABLE = TABLE_CONFIG['quality_alert_table']
# ==========================================


def check_db_config():
    """检查数据库配置"""
    if not DB_PASS:
        print("⚠️ 警告: DB_PASSWORD环境变量未设置")
        print("请执行: export DB_PASSWORD='your_db_password'")
        return False
    return True


def format_alert_message(task_name, alert_time, level, check_time, content, sql=""):
    """
    按照标准格式组装告警消息
    
    标准格式：
    【任务名称】每天校验 3 级表数据 (D-1)_copy_20260318165711389 
    【告警时间】2026-03-18 17:50:42 
    【告警级别】3 
    【校验时间】03 月 17 日 00 时 至 03 月 18 日 00 时 
    【告警内容】指标校验异常 ods_qsq_erp_atransaction 数量不一致 期望值 202776 实际值 202778 差值为 -2 
    【执行语句】SELECT COUNT(*) as cnt FROM ...
    """
    message = f"""【任务名称】{task_name}
【告警时间】{alert_time}
【告警级别】{level}
【校验时间】{check_time}
【告警内容】{content}"""
    
    if sql:
        message += f"\n【执行语句】{sql}"
    
    return message


def send_to_openclaw(message):
    """
    发送告警消息到 OpenClaw Webhook
    """
    payload = {
        "text": message,
        "mode": "now"
    }
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {OPENCLAW_HOOK_TOKEN}"
    }
    
    try:
        response = requests.post(
            OPENCLAW_WEBHOOK,
            json=payload,
            headers=headers,
            timeout=30
        )
        
        if response.status_code in (200, 202):
            print(f"✅ 告警发送成功！状态码：{response.status_code}")
            return True
        else:
            print(f"❌ 告警发送失败！状态码：{response.status_code}")
            print(f"   响应内容：{response.text[:200]}")
            return False
            
    except requests.RequestException as e:
        print(f"❌ 网络请求异常：{e}")
        return False


def fetch_latest_alert_from_db():
    """
    从数据库读取最新的一条未处理告警
    """
    try:
        import pymysql
        
        conn = pymysql.connect(
            host=DB_HOST,
            port=DB_PORT,
            user=DB_USER,
            password=DB_PASS,
            database=DB_NAME,
            charset='utf8mb4'
        )
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        
        # 获取最新的一条未处理告警
        cursor.execute(f"""
            SELECT id, content, type, created_at 
            FROM {QUALITY_ALERT_TABLE}
            WHERE status = 0 
            ORDER BY created_at DESC 
            LIMIT 1
        """)
        
        alert = cursor.fetchone()
        conn.close()
        
        if not alert:
            print("⚠️ 暂无未处理告警")
            return None
        
        return alert
        
    except Exception as e:
        print(f"❌ 数据库查询异常：{e}")
        return None


def parse_content(content):
    """
    从 content 字段中提取各部分信息
    
    示例输入：
    指标校验异常 ods_qsq_erp_atransaction 数量不一致 期望值 202776 实际值 202778 差值为 -2 
    【执行语句】SELECT COUNT(*) as cnt FROM ...
    
    返回：(告警内容，执行语句)
    """
    if "【执行语句】" in content:
        parts = content.split("【执行语句】", 1)
        main_content = parts[0].strip()
        sql_content = parts[1].strip() if len(parts) > 1 else ""
    else:
        main_content = content.strip()
        sql_content = ""
    
    return main_content, sql_content


def send_from_db():
    """
    从数据库读取告警并发送
    """
    alert = fetch_latest_alert_from_db()
    
    if not alert:
        return False
    
    # 解析告警内容
    main_content, sql_content = parse_content(alert['content'])
    
    # 提取任务名称（从 content 中提取表名作为任务名）
    task_name = f"数据质量校验任务_{alert['id']}"
    
    # 格式化时间
    alert_time = alert['created_at'].strftime('%Y-%m-%d %H:%M:%S') if alert.get('created_at') else 'N/A'
    
    # 告警级别
    level = "P" + str(alert.get('type', 1)) if alert.get('type') else "P1"
    
    # 校验时间（需要智能提取，这里先用默认值）
    check_time = "03 月 18 日 00 时 至 03 月 19 日 00 时"
    
    # 尝试从 content 中提取校验时间
    import re
    date_pattern = r"(\d{4}-\d{2}-\d{2})"
    dates = re.findall(date_pattern, main_content)
    if len(dates) >= 2:
        try:
            start_date = datetime.strptime(dates[0], '%Y-%m-%d')
            end_date = datetime.strptime(dates[1], '%Y-%m-%d')
            check_time = start_date.strftime('%m 月 %d 日 00 时') + ' 至 ' + end_date.strftime('%m 月 %d 日 00 时')
        except:
            pass
    
    # 组装消息
    message = format_alert_message(
        task_name=task_name,
        alert_time=alert_time,
        level=level,
        check_time=check_time,
        content=main_content,
        sql=sql_content
    )
    
    print(f"📋 准备发送告警 [ID: {alert['id']}]")
    print("-" * 60)
    print(message)
    print("-" * 60)
    
    # 发送
    success = send_to_openclaw(message)
    
    # 如果发送成功，更新数据库状态
    if success:
        try:
            import pymysql
            conn = pymysql.connect(
                host=DB_HOST,
                port=DB_PORT,
                user=DB_USER,
                password=DB_PASS,
                database=DB_NAME,
                charset='utf8mb4'
            )
            cursor = conn.cursor()
            cursor.execute(f"UPDATE {QUALITY_ALERT_TABLE} SET status = 1 WHERE id = {alert['id']}")
            conn.commit()
            conn.close()
            print(f"✅ 数据库状态已更新 (status=1)")
        except Exception as e:
            print(f"⚠️ 数据库更新失败：{e}")
    
    return success


def main():
    parser = argparse.ArgumentParser(
        description='告警格式化发送脚本',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例用法:
  # 从数据库读取最新告警并发送
  python send_alert.py --from-db
  
  # 手动指定告警内容发送
  python send_alert.py --task-name "每天校验 3 级表数据" --alert-time "2026-03-19 11:30:00" --level "3" --check-time "03 月 18 日 00 时 至 03 月 19 日 00 时" --content "指标校验异常" --sql "SELECT ..."
        """
    )
    
    parser.add_argument('--from-db', action='store_true', 
                        help='从数据库读取最新告警并发送')
    
    # 手动指定参数
    parser.add_argument('--task-name', type=str, help='任务名称')
    parser.add_argument('--alert-time', type=str, help='告警时间 (YYYY-MM-DD HH:MM:SS)')
    parser.add_argument('--level', type=str, help='告警级别 (1/2/3 或 P1/P2/P3)')
    parser.add_argument('--check-time', type=str, help='校验时间范围')
    parser.add_argument('--content', type=str, help='告警内容')
    parser.add_argument('--sql', type=str, default='', help='执行语句 (可选)')
    
    args = parser.parse_args()
    
    print("=" * 60)
    print("🚀 告警格式化发送工具")
    print("=" * 60)
    print(f"📡 Webhook: {OPENCLAW_WEBHOOK}")
    print("-" * 60)
    
    if args.from_db:
        # 从数据库模式
        success = send_from_db()
    elif args.task_name and args.content:
        # 手动指定模式
        message = format_alert_message(
            task_name=args.task_name,
            alert_time=args.alert_time or datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            level=args.level or "3",
            check_time=args.check_time or "03 月 18 日 00 时 至 03 月 19 日 00 时",
            content=args.content,
            sql=args.sql
        )
        
        print(f"📋 准备发送告警")
        print("-" * 60)
        print(message)
        print("-" * 60)
        
        success = send_to_openclaw(message)
    else:
        print("❌ 错误：请指定 --from-db 或提供 --task-name 和 --content 参数")
        print("\n使用 --help 查看帮助")
        success = False
    
    print("=" * 60)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
