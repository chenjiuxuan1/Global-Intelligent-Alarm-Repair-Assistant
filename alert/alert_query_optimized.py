#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys
sys.path.insert(0, "/home/node/.openclaw/workspace")
import auto_load_env


# -*- coding: utf-8 -*-
"""
优化的告警查询脚本
- 时间：昨天到今天
- 过滤：status=0 + 未恢复的所有告警（不区分层级）
- 格式：保持原有告警格式

作者：OpenClaw
日期：2026-03-23
"""

import json
import urllib.request
import subprocess
import os
from datetime import datetime, timedelta

# ================= 配置区 =================
# 从环境变量读取数据库配置
DB_CONFIG = {
    'host': os.environ.get('DB_HOST', '172.20.0.235'),
    'port': int(os.environ.get('DB_PORT', '13306')),
    'user': os.environ.get('DB_USER', 'e_ds'),
    'password': os.environ.get('DB_PASSWORD', ''),
    'database': os.environ.get('DB_NAME', 'wattrel')
}

OPENCLAW_WEBHOOK = os.environ.get('OPENCLAW_WEBHOOK', 'http://127.0.0.1:18789/hooks/wattrel/wake')
OPENCLAW_HOOK_TOKEN = os.environ.get('OPENCLAW_HOOK_TOKEN', 'wattrel-webhook-secret-token-2026')
# ==========================================


def check_config():
    """检查配置是否完整"""
    if not DB_CONFIG['password']:
        raise ValueError(
            "DB_PASSWORD环境变量未设置！\n"
            "请执行: export DB_PASSWORD='your_db_password'\n"
            "或在 ~/.bashrc 中添加: export DB_PASSWORD='your_db_password'"
        )


# 启动时检查配置
check_config()


def get_yesterday_today():
    """获取昨天到今天的日期范围"""
    today = datetime.now()
    yesterday = today - timedelta(days=1)
    return yesterday.strftime('%Y-%m-%d'), today.strftime('%Y-%m-%d')


def query_alerts():
    """
    查询告警
    - 时间：昨天到今天
    - 状态：未处理(status=0)
    - 过滤：排除已恢复的告警
    - 范围：所有告警（不区分层级）
    """
    yesterday, today = get_yesterday_today()
    yesterday_start = f"{yesterday} 00:00:00"
    today_end = f"{today} 23:59:59"
    
    js_code = f"""
const mysql = require('/tmp/node_modules/mysql2/promise');

async function query() {{
    const conn = await mysql.createConnection({{
        host: '{DB_CONFIG['host']}',
        port: {DB_CONFIG['port']},
        user: '{DB_CONFIG['user']}',
        password: '{DB_CONFIG['password']}',
        database: '{DB_CONFIG['database']}',
        charset: 'utf8mb4'
    }});
    
    const [rows] = await conn.execute(`
        SELECT id, content, type, status, created_at
        FROM wattrel_quality_alert
        WHERE created_at >= ?
          AND created_at <= ?
          AND status = 0
          AND content NOT LIKE '%已恢复%'
        ORDER BY created_at DESC
    `, ['{yesterday_start}', '{today_end}']);
    
    await conn.end();
    console.log(JSON.stringify(rows));
}}

query().catch(e => {{ console.error(e); process.exit(1); }});
"""
    
    try:
        result = subprocess.run(
            ['node', '-e', js_code],
            capture_output=True,
            text=True,
            timeout=15
        )
        
        if result.returncode == 0:
            return json.loads(result.stdout)
        else:
            print(f"查询失败: {result.stderr}")
            return []
    except Exception as e:
        print(f"执行失败: {e}")
        return []


def send_webhook(message):
    """发送消息到Webhook"""
    try:
        req = urllib.request.Request(
            OPENCLAW_WEBHOOK,
            data=json.dumps({'text': message, 'mode': 'now'}).encode('utf-8'),
            headers={
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {OPENCLAW_HOOK_TOKEN}'
            },
            method='POST'
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except Exception as e:
        print(f"发送失败: {e}")
        return False


def format_alert(alert):
    """格式化告警 - 保持原有格式"""
    alert_id = alert.get('id')
    content = alert.get('content', '')
    alert_type = alert.get('type', '1')
    created_at = alert.get('created_at')
    
    # 解析内容，分离主要内容和SQL
    main_content = content
    sql_content = ''
    
    if '【执行语句】' in content:
        parts = content.split('【执行语句】', 1)
        main_content = parts[0].strip()
        sql_content = parts[1].strip()
    
    # 格式化时间
    try:
        if isinstance(created_at, str):
            dt = datetime.strptime(created_at, '%Y-%m-%dT%H:%M:%S.%fZ')
        else:
            dt = created_at
        time_str = dt.strftime('%Y-%m-%d %H:%M:%S')
    except:
        time_str = str(created_at)
    
    # 构建消息 - 保持原有格式
    lines = [
        f"【任务名称】数据质量校验任务_{alert_id}",
        f"【告警时间】{time_str}",
        f"【告警级别】P{alert_type}",
        f"【告警内容】{main_content}",
    ]
    
    if sql_content:
        lines.append(f"【执行语句】{sql_content}")
    
    return '\n'.join(lines)


def update_alert_status(alert_ids):
    """更新告警状态为已处理"""
    if not alert_ids:
        return
    
    ids_str = ",".join([str(id) for id in alert_ids])
    
    js_update = f"""
const mysql = require('/tmp/node_modules/mysql2/promise');
async function update() {{
    const conn = await mysql.createConnection({{
        host: '{DB_CONFIG['host']}',
        port: {DB_CONFIG['port']}',
        user: '{DB_CONFIG['user']}',
        password: '{DB_CONFIG['password']}',
        database: '{DB_CONFIG['database']}',
        charset: 'utf8mb4'
    }});
    await conn.execute(
        "UPDATE wattrel_quality_alert SET status = 1 WHERE id IN ({ids_str})"
    );
    await conn.end();
    console.log('更新完成');
}}
update().catch(e => console.error(e));
"""
    
    try:
        subprocess.run(['node', '-e', js_update], capture_output=True, timeout=10)
    except Exception as e:
        print(f"更新状态失败: {e}")


def main():
    """主函数"""
    yesterday, today = get_yesterday_today()
    
    print("=" * 70)
    print("🚀 数据质量告警查询")
    print("=" * 70)
    print(f"\n[*] 查询时间范围: {yesterday} 00:00:00 至 {today} 23:59:59")
    print("[*] 过滤条件: 未处理(status=0) + 未恢复")
    print("[*] 查询范围: 所有告警（不区分层级）")
    print()
    
    # 查询告警
    alerts = query_alerts()
    
    print(f"[!] 发现 {len(alerts)} 条未处理告警")
    print()
    
    if not alerts:
        message = "🎉 数据质量告警查询\n\n昨天到今天没有新的异常告警，数据质量正常！"
        print("[+] 没有异常告警，数据质量正常！🎉")
        send_webhook(message)
        return
    
    # 逐条推送告警
    processed_ids = []
    
    for i, alert in enumerate(alerts, 1):
        formatted_msg = format_alert(alert)
        
        print(f"[{i}/{len(alerts)}] 推送告警 ID:{alert['id']}...")
        
        if send_webhook(formatted_msg):
            processed_ids.append(alert['id'])
            print(f"   ✅ 推送成功")
        else:
            print(f"   ❌ 推送失败")
        print()
    
    # 更新数据库状态
    if processed_ids:
        update_alert_status(processed_ids)
        print(f"[+] 已更新 {len(processed_ids)} 条告警为已处理状态")
    
    print("=" * 70)
    print("✅ 任务完成")
    print("=" * 70)


if __name__ == "__main__":
    main()
