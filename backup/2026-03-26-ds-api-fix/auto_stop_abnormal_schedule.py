#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
异常调度检测与自动停止脚本
执行时间: 2026-03-26 17:00 CST
"""

import json
import csv
import urllib.request
import os
from datetime import datetime

# 配置
DS_BASE_URL = "http://172.20.0.235:12345/dolphinscheduler"
DS_TOKEN = "097ef3039a5d7af826c1cab60dedf96a"
PROJECT_CODE = "158514956085248"

# TV配置
TV_API_URL = "https://tv-service-alert.kuainiu.chat/alert/v2/array"
TV_BOT_ID = "fbbcabb4-d187-4d9e-8e1e-ba7654a24d1c"

def send_tv_notification(messages):
    """发送TV通知"""
    if not messages:
        return
    
    alert_data = {
        "appId": "alert",
        "botId": TV_BOT_ID,
        "messages": messages
    }
    
    try:
        req = urllib.request.Request(
            TV_API_URL,
            data=json.dumps(alert_data).encode('utf-8'),
            headers={'Content-Type': 'application/json'},
            method='POST'
        )
        with urllib.request.urlopen(req, timeout=15) as response:
            return json.loads(response.read().decode('utf-8'))
    except Exception as e:
        print(f"TV发送失败: {e}")
        return None

def send_dingtalk_report(report):
    """发送钉钉报告 - 简化为控制台输出"""
    print("\n" + "="*60)
    print("📊 异常调度检测报告")
    print("="*60)
    print(report)
    print("="*60)

def load_schedules_from_csv(csv_path):
    """从CSV加载调度配置"""
    schedules = {}
    try:
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                workflow_code = row.get('工作流Code', '').strip()
                if workflow_code:
                    schedules[workflow_code] = {
                        'name': row.get('工作流名称', ''),
                        'code': workflow_code,
                        'status': row.get('状态', ''),
                        'cron': row.get('Cron表达式', '')
                    }
    except Exception as e:
        print(f"CSV加载失败: {e}")
    return schedules

def get_running_instances():
    """获取运行中的工作流实例"""
    url = f"{DS_BASE_URL}/projects/{PROJECT_CODE}/process-instances?stateType=RUNNING_EXECUTION&pageNo=1&pageSize=100"
    try:
        req = urllib.request.Request(url, headers={'token': DS_TOKEN})
        with urllib.request.urlopen(req, timeout=15) as response:
            data = json.loads(response.read().decode('utf-8'))
            if data.get('code') == 0:
                return data.get('data', {}).get('totalList', [])
    except Exception as e:
        print(f"获取运行实例失败: {e}")
    return []

def get_instance_detail(instance_id):
    """获取实例详情"""
    url = f"{DS_BASE_URL}/projects/{PROJECT_CODE}/process-instances/{instance_id}"
    try:
        req = urllib.request.Request(url, headers={'token': DS_TOKEN})
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode('utf-8'))
            if data.get('code') == 0:
                return data.get('data', {})
    except Exception as e:
        print(f"获取实例详情失败: {e}")
    return {}

def stop_instance(instance_id):
    """停止工作流实例"""
    url = f"{DS_BASE_URL}/projects/{PROJECT_CODE}/executors/execute"
    data = {
        'processInstanceId': instance_id,
        'executeType': 'STOP'
    }
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(data).encode('utf-8'),
            headers={'Content-Type': 'application/json'},
            method='POST'
        )
        req.add_header('token', DS_TOKEN)
        with urllib.request.urlopen(req, timeout=10) as response:
            result = json.loads(response.read().decode('utf-8'))
            return result.get('code') == 0
    except Exception as e:
        print(f"停止实例失败: {e}")
        return False

def main():
    print("🔄 开始异常调度自动检测...")
    print(f"⏰ 执行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # 1. 加载调度配置
    csv_path = '/home/node/.openclaw/workspace/dolphinscheduler/schedules_export.csv'
    schedules = load_schedules_from_csv(csv_path)
    print(f"📋 已加载 {len(schedules)} 个调度配置")
    
    # 统计ONLINE/OFFLINE数量
    online_count = sum(1 for s in schedules.values() if s['status'] == 'ONLINE')
    offline_count = sum(1 for s in schedules.values() if s['status'] == 'OFFLINE')
    print(f"   ONLINE: {online_count}个, OFFLINE: {offline_count}个")
    
    # 2. 获取运行中的实例
    running_instances = get_running_instances()
    print(f"\n🔍 发现 {len(running_instances)} 个运行中实例")
    
    # 检测结果
    abnormal_instances = []
    normal_count = 0
    
    for instance in running_instances:
        instance_id = instance.get('id')
        workflow_code = str(instance.get('processDefinitionCode', ''))
        workflow_name = instance.get('name', '')
        
        # 获取实例详情查看启动类型
        detail = get_instance_detail(instance_id)
        command_type = detail.get('commandType', '')
        
        # 只检查SCHEDULER类型的实例
        if command_type != 'SCHEDULER':
            print(f"   ℹ️ 实例 {instance_id} ({workflow_name}) 启动类型: {command_type}，跳过检查")
            normal_count += 1
            continue
        
        # 检查是否为异常
        if workflow_code not in schedules:
            # 异常类型1: 无定时配置但被调度启动
            abnormal_instances.append({
                'id': instance_id,
                'name': workflow_name,
                'code': workflow_code,
                'type': '无定时配置但被调度启动',
                'state': instance.get('state')
            })
        elif schedules[workflow_code]['status'] == 'OFFLINE':
            # 异常类型2: 调度已下线但仍被启动
            abnormal_instances.append({
                'id': instance_id,
                'name': workflow_name,
                'code': workflow_code,
                'type': '调度已下线但仍被启动',
                'state': instance.get('state')
            })
        else:
            normal_count += 1
    
    # 3. 自动停止异常实例
    tv_messages = []
    stopped_count = 0
    failed_count = 0
    
    if abnormal_instances:
        print(f"\n⚠️ 发现 {len(abnormal_instances)} 个异常调度实例:")
        for inst in abnormal_instances:
            print(f"   - {inst['name']} (ID: {inst['id']}, 类型: {inst['type']})")
            
            # 自动停止
            print(f"   🛑 正在停止实例 {inst['id']}...")
            if stop_instance(inst['id']):
                print(f"   ✅ 已停止: {inst['name']}")
                inst['stopped'] = True
                stopped_count += 1
                tv_messages.append({
                    "title": "✅ 异常调度已自动停止",
                    "text": f"工作流: {inst['name']}\n实例ID: {inst['id']}\n异常类型: {inst['type']}"
                })
            else:
                print(f"   ❌ 停止失败: {inst['name']}")
                inst['stopped'] = False
                failed_count += 1
                tv_messages.append({
                    "title": "❌ 异常调度停止失败",
                    "text": f"工作流: {inst['name']}\n实例ID: {inst['id']}\n异常类型: {inst['type']}\n⚠️ 需人工处理"
                })
    
    # 4. 发送TV通知
    if tv_messages:
        print(f"\n📺 发送TV通知 ({len(tv_messages)} 条)...")
        send_tv_notification(tv_messages)
    
    # 5. 生成钉钉报告
    report_lines = []
    report_lines.append(f"⏰ 检测时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report_lines.append(f"📋 调度配置: {len(schedules)} 个 (ONLINE: {online_count}, OFFLINE: {offline_count})")
    report_lines.append(f"🔍 运行中实例: {len(running_instances)} 个")
    
    if not running_instances:
        report_lines.append("\n✅ 当前无运行中实例，系统正常")
    elif not abnormal_instances:
        report_lines.append(f"\n✅ 未发现异常调度任务")
        report_lines.append(f"   所有 {normal_count} 个调度任务运行正常")
    else:
        report_lines.append(f"\n⚠️ 异常检测统计:")
        report_lines.append(f"   异常实例: {len(abnormal_instances)} 个")
        report_lines.append(f"   正常实例: {normal_count} 个")
        report_lines.append(f"\n🛑 自动停止结果:")
        report_lines.append(f"   成功: {stopped_count} 个")
        report_lines.append(f"   失败: {failed_count} 个")
        
        if failed_count > 0:
            report_lines.append(f"\n⚠️ 以下实例需要人工处理:")
            for inst in abnormal_instances:
                if not inst.get('stopped'):
                    report_lines.append(f"   - {inst['name']} (ID: {inst['id']})")
    
    report = "\n".join(report_lines)
    send_dingtalk_report(report)
    
    # 6. 保存检测记录
    record_file = f"/home/node/.openclaw/workspace/schedule_check_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    record = {
        'check_time': datetime.now().isoformat(),
        'total_schedules': len(schedules),
        'online_schedules': online_count,
        'offline_schedules': offline_count,
        'running_instances': len(running_instances),
        'normal_instances': normal_count,
        'abnormal_instances': abnormal_instances,
        'stopped_count': stopped_count,
        'failed_count': failed_count
    }
    with open(record_file, 'w', encoding='utf-8') as f:
        json.dump(record, f, indent=2, ensure_ascii=False)
    print(f"\n💾 检测记录已保存: {record_file}")
    
    print("\n✅ 异常调度检测完成")
    return record

if __name__ == '__main__':
    result = main()
    print(json.dumps(result, indent=2, ensure_ascii=False))
