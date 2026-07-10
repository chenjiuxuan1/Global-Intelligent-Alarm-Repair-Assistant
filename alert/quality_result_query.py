#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys
sys.path.insert(0, "/home/node/.openclaw/workspace")
import auto_load_env


# -*- coding: utf-8 -*-
"""
指标预警校验结果查询脚本 - 查询 wattrel_quality_result 表
- 只查询 result=1（异常）的数据
- 创建时间：最近3天
- 发送方式：openclaw message send

作者：OpenClaw
日期：2026-03-24
"""

import json
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

# 钉钉群配置
DINGTALK_CONVERSATION_ID = 'cidune9y06rl1j0uelxqielqw=='
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


def get_date_range():
    """获取最近3天的日期范围"""
    today = datetime.now()
    three_days_ago = today - timedelta(days=3)
    return three_days_ago.strftime('%Y-%m-%d %H:%M:%S'), today.strftime('%Y-%m-%d %H:%M:%S')


def query_quality_results():
    """
    查询指标预警校验结果
    - 条件：result=1（异常），最近3天
    - 表：wattrel_quality_result
    """
    start_time, end_time = get_date_range()
    
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
        SELECT 
            id, quality_id, name, type, \`desc\`,
            src_db, src_tbl, dest_db, dest_tbl,
            src_value, dest_value, diff,
            \`begin\`, \`end\`, result, status,
            src_error, dest_error, is_repaired,
            created_at, updated_at
        FROM wattrel_quality_result
        WHERE result = 1
          AND created_at >= ?
          AND created_at <= ?
        ORDER BY created_at DESC
    `, ['{start_time}', '{end_time}']);
    
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


def send_to_dingtalk(message):
    """发送消息到钉钉群"""
    try:
        result = subprocess.run(
            [
                'openclaw', 'message', 'send',
                '--channel', 'dingtalk-connector',
                '--target', f'group:{DINGTALK_CONVERSATION_ID}',
                '--message', message
            ],
            capture_output=True,
            text=True,
            timeout=15
        )
        
        return 'Sent via DingTalk' in result.stdout or result.returncode == 0
    except Exception as e:
        print(f"发送异常: {e}")
        return False


def format_quality_result(result):
    """格式化校验结果"""
    result_id = result.get('id')
    name = result.get('name', 'N/A')
    desc = result.get('desc', '')
    src_db = result.get('src_db', '')
    src_tbl = result.get('src_tbl', '')
    dest_db = result.get('dest_db', '')
    dest_tbl = result.get('dest_tbl', '')
    src_value = result.get('src_value', '')
    dest_value = result.get('dest_value', '')
    diff = result.get('diff', 0)
    begin = result.get('begin', '')
    end = result.get('end', '')
    created_at = result.get('created_at', '')
    
    # 格式化时间
    try:
        if isinstance(created_at, str):
            dt = datetime.strptime(created_at, '%Y-%m-%dT%H:%M:%S.%fZ')
            time_str = dt.strftime('%Y-%m-%d %H:%M:%S')
        else:
            time_str = str(created_at)
    except:
        time_str = str(created_at)
    
    # 格式化日期范围
    date_range = ''
    if begin and end:
        try:
            b = datetime.strptime(str(begin), '%Y-%m-%dT%H:%M:%S.%fZ')
            e = datetime.strptime(str(end), '%Y-%m-%dT%H:%M:%S.%fZ')
            date_range = f"{b.strftime('%Y-%m-%d')} 至 {e.strftime('%Y-%m-%d')}"
        except:
            date_range = f"{begin} 至 {end}"
    
    # 构建消息
    lines = [
        f"【任务名称】指标校验_{result_id}_{name}",
        f"【告警时间】{time_str}",
        f"【校验类型】{desc}",
    ]
    
    if date_range:
        lines.append(f"【日期范围】{date_range}")
    
    lines.append(f"【原库表】{src_db}.{src_tbl}")
    lines.append(f"【目的库表】{dest_db}.{dest_tbl}")
    lines.append(f"【原值】{src_value}")
    lines.append(f"【目的值】{dest_value}")
    lines.append(f"【差异数】{diff}")
    
    return '\n'.join(lines)


def main():
    """主函数"""
    start_time, end_time = get_date_range()
    
    print("=" * 80)
    print("🚀 指标预警校验结果查询")
    print("=" * 80)
    print(f"\n[*] 查询表: wattrel_quality_result")
    print(f"[*] 查询条件: result=1（异常）")
    print(f"[*] 时间范围: {start_time} 至 {end_time}")
    print(f"[*] 发送方式: openclaw message send")
    print()
    
    # 查询数据
    results = query_quality_results()
    
    print(f"[!] 发现 {len(results)} 条异常校验结果")
    print()
    
    if not results:
        message = "🎉 指标预警校验\n\n最近3天没有异常校验结果，数据质量正常！"
        print("[+] 没有异常数据，数据质量正常！🎉")
        send_to_dingtalk(message)
        return
    
    # 逐条推送
    success_count = 0
    
    for i, result in enumerate(results, 1):
        formatted_msg = format_quality_result(result)
        
        print(f"[{i}/{len(results)}] 发送校验结果 ID:{result['id']}...")
        
        if send_to_dingtalk(formatted_msg):
            success_count += 1
            print(f"   ✅ 已发送")
        else:
            print(f"   ❌ 发送失败")
        print()
    
    # 发送总结
    summary = f"📊 校验结果发送完成\n共计 {len(results)} 条异常，成功发送 {success_count} 条"
    send_to_dingtalk(summary)
    
    print("=" * 80)
    print(f"✅ 任务完成（成功: {success_count}/{len(results)}）")
    print("=" * 80)


if __name__ == "__main__":
    main()
