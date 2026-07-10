#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import auto_load_env
from config.config import DB_CONFIG, OPENCLAW_CONFIG, TABLE_CONFIG


# -*- coding: utf-8 -*-
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
"""
OpenClaw 告警搬运工脚本
监控数据库中的告警并转发给 OpenClaw 处理

作者：陈江川
日期：2026-03-18
"""

import pymysql
import requests
import time
import json

# ================= 1. 配置区 =================
DB_HOST = DB_CONFIG['host']
DB_PORT = DB_CONFIG['port']
DB_USER = DB_CONFIG['user']
DB_PASS = DB_CONFIG['password']
DB_NAME = DB_CONFIG['database']
OPENCLAW_WEBHOOK = OPENCLAW_CONFIG['webhook']
OPENCLAW_HOOK_TOKEN = OPENCLAW_CONFIG['token']
QUALITY_ALERT_TABLE = TABLE_CONFIG['quality_alert_table']
# ==========================================


def check_config():
    """检查配置是否完整"""
    if not DB_PASS:
        raise ValueError(
            "DB_PASSWORD环境变量未设置！\n"
            "请执行: export DB_PASSWORD='your_db_password'\n"
            "或在 ~/.bashrc 中添加: export DB_PASSWORD='your_db_password'"
        )


# 启动时检查配置
check_config()


def fetch_and_forward_alerts():
    """抓取未处理告警并转发给 OpenClaw"""
    try:
        # 连接本地隧道映射的数据库
        conn = pymysql.connect(
            host=DB_HOST, 
            port=DB_PORT, 
            user=DB_USER, 
            password=DB_PASS, 
            database=DB_NAME,
            charset='utf8mb4'
        )
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        
        # 抓取所有 status = 0 (未处理) 的告警
        cursor.execute(f"""
            SELECT id, content, created_at 
            FROM {QUALITY_ALERT_TABLE}
            WHERE status = 0 
            ORDER BY created_at ASC
            limit 2
        """)
        new_alerts = cursor.fetchall()
        
        if not new_alerts:
            # print(f"[{time.strftime('%H:%M:%S')}] 暂无新告警...")
            conn.close()
            return

        print(f"\n[{time.strftime('%H:%M:%S')}] 🚨 发现 {len(new_alerts)} 条新告警，准备投递给 AI 大脑...")

        processed_ids = []
        for alert in new_alerts:
            # 格式化告警消息
            alert_type = alert.get('type', 1)
            alert_level = "P" + str(alert_type) if alert_type else "P1"  # type 转告警级别
            
            # 从 content 中提取信息（如果有【执行语句】则分割）
            content = alert['content']
            sql_content = ""
            main_content = content
            if "【执行语句】" in content:
                parts = content.split("【执行语句】", 1)
                main_content = parts[0].strip()
                sql_content = parts[1].strip() if len(parts) > 1 else ""
            
            # 组装格式化消息
            formatted_msg = f"""【任务名称】数据质量校验任务_{alert['id']}
【告警时间】{alert['created_at'].strftime('%Y-%m-%d %H:%M:%S') if alert.get('created_at') else 'N/A'}
【告警级别】{alert_level}
【告警内容】{main_content}
【执行语句】{sql_content}"""
            
            # 组装发给 OpenClaw 的 JSON 数据（使用 /hooks/wattrel/wake 格式）
            payload = {
                "text": formatted_msg,
                "mode": "now"
            }
            
            # POST 给 OpenClaw Webhook（使用 Authorization Header 认证）
            response = requests.post(
                OPENCLAW_WEBHOOK, 
                json=payload, 
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {OPENCLAW_HOOK_TOKEN}"
                },
                timeout=30
            )
            
            # 如果 OpenClaw 成功接收 (200 或 202)
            if response.status_code in (200, 202):
                processed_ids.append(str(alert['id']))
                print(f" ✅ 告警 [ID: {alert['id']}] 投递成功！")
            else:
                print(f" ❌ 告警 [ID: {alert['id']}] 投递失败，状态码：{response.status_code}")
                print(f"    响应内容：{response.text[:200]}")
        
        # 更新数据库状态，防止重复报警
        if processed_ids:
            ids_str = ",".join(processed_ids)
            cursor.execute(f"UPDATE {QUALITY_ALERT_TABLE} SET status = 1 WHERE id IN ({ids_str})")
            conn.commit()
            print(f"[{time.strftime('%H:%M:%S')}] 数据库回写完毕，已标记为处理完成 (status=1)。")
        
        conn.close()

    except pymysql.Error as e:
        print(f"[{time.strftime('%H:%M:%S')}] ❌ 数据库连接异常：{e}")
    except requests.RequestException as e:
        print(f"[{time.strftime('%H:%M:%S')}] ❌ Webhook 请求异常：{e}")
    except Exception as e:
        print(f"[{time.strftime('%H:%M:%S')}] ❌ 脚本运行异常：{e}")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='OpenClaw 告警搬运工脚本')
    parser.add_argument('--once', action='store_true', help='只运行一次扫描，然后退出（手动触发模式）')
    parser.add_argument('--interval', type=int, default=30, help='轮询间隔（分钟），默认 30 分钟')
    
    args = parser.parse_args()
    
    interval_seconds = args.interval * 60
    
    print("=" * 60)
    if args.once:
        print("🚀 OpenClaw 告警雷达 - 手动触发模式")
        print("=" * 60)
        print(f"📡 Webhook 地址：{OPENCLAW_WEBHOOK}")
        print(f"💾 数据库：{DB_HOST}:{DB_PORT}/{DB_NAME}")
        print("-" * 60)
        print()
        
        # 只运行一次
        fetch_and_forward_alerts()
        print("\n✅ 扫描完成，程序退出。")
    else:
        print("🚀 OpenClaw 告警雷达已启动，正在监听数据库...")
        print("=" * 60)
        print(f"📡 Webhook 地址：{OPENCLAW_WEBHOOK}")
        print(f"💾 数据库：{DB_HOST}:{DB_PORT}/{DB_NAME}")
        print(f"⏱️  轮询间隔：{args.interval} 分钟")
        print("-" * 60)
        print()
        
        while True:
            fetch_and_forward_alerts()
            time.sleep(interval_seconds)
