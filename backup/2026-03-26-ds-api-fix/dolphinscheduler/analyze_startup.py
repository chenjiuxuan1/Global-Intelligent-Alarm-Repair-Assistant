#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
分析工作流实例的启动来源（历史数据分析）
用于排查"未上定时却被启动"的问题根源

作者：OpenClaw
日期：2026-03-23
"""

import os
import urllib.request
import json
import sys
from collections import Counter
from datetime import datetime, timedelta

# DolphinScheduler 配置
DS_CONFIG = {
    'base_url': 'http://172.20.0.235:12345/dolphinscheduler',
    'token': os.environ.get('DS_TOKEN', ''),
    'project_code': '158514956085248',
    'project_name': '国内数仓-工作流'
}

# 启动类型说明
COMMAND_TYPE_DESC = {
    'SCHEDULER': '定时调度',
    'MANUAL': '手动触发',
    'COMPLEMENT_DATA': '补数据',
    'START_PROCESS': 'API调用',
    'RETRY': '故障重试',
    'UNKNOWN': '未知'
}


def fetch_recent_instances(days=7, limit=100):
    """
    获取最近的工作流实例
    
    Args:
        days: 查询最近几天的数据
        limit: 最大数量
        
    Returns:
        list: 实例列表
    """
    # 查询成功的实例（最近完成的）
    url = f"{DS_CONFIG['base_url']}/projects/{DS_CONFIG['project_code']}/process-instances"
    params = f"?stateType=SUCCESS&pageNo=1&pageSize={limit}"
    
    full_url = url + params
    req = urllib.request.Request(full_url)
    req.add_header('token', DS_CONFIG['token'])
    
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            result = json.loads(response.read().decode('utf-8'))
            if result.get('code') == 0:
                return result.get('data', {}).get('totalList', [])
    except Exception as e:
        print(f"❌ 查询失败: {e}")
    
    return []


def get_instance_detail(instance_id):
    """获取实例详情"""
    url = f"{DS_CONFIG['base_url']}/projects/{DS_CONFIG['project_code']}/process-instances/{instance_id}"
    
    req = urllib.request.Request(url)
    req.add_header('token', DS_CONFIG['token'])
    
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            result = json.loads(response.read().decode('utf-8'))
            if result.get('code') == 0:
                return result.get('data', {})
    except:
        pass
    
    return {}


def analyze_startup_patterns():
    """分析启动模式"""
    print("=" * 80)
    print(f"📊 {DS_CONFIG['project_name']} - 工作流启动来源分析")
    print("=" * 80)
    print("\n🔍 查询最近完成的实例...")
    
    instances = fetch_recent_instances(days=7, limit=50)
    
    if not instances:
        print("❌ 未获取到实例数据")
        return
    
    print(f"✅ 获取到 {len(instances)} 个实例\n")
    
    # 分析每个实例的启动类型
    type_counter = Counter()
    user_counter = Counter()
    workflow_startup = {}  # 记录每个工作流的启动类型分布
    
    print("📋 分析实例启动来源...")
    for i, inst in enumerate(instances, 1):
        instance_id = inst.get('id')
        name = inst.get('name', 'N/A')
        
        # 获取详情
        detail = get_instance_detail(instance_id)
        command_type = detail.get('commandType', 'UNKNOWN')
        start_user = detail.get('startUser', detail.get('userName', 'system'))
        
        # 统计
        type_counter[command_type] += 1
        user_counter[start_user] += 1
        
        # 记录工作流启动类型
        if name not in workflow_startup:
            workflow_startup[name] = Counter()
        workflow_startup[name][command_type] += 1
        
        if i <= 10:  # 显示前10个详情
            icon = {
                'SCHEDULER': '⏰',
                'MANUAL': '👤',
                'COMPLEMENT_DATA': '📅',
                'START_PROCESS': '🔌',
                'RETRY': '🔁'
            }.get(command_type, '❓')
            print(f"  [{i}] {icon} {name[:40]:<40} | {COMMAND_TYPE_DESC.get(command_type, command_type):<10} | {start_user}")
    
    # 统计报告
    print("\n" + "=" * 80)
    print("📊 启动类型统计（最近50个实例）")
    print("=" * 80)
    
    for cmd_type, count in type_counter.most_common():
        desc = COMMAND_TYPE_DESC.get(cmd_type, cmd_type)
        percentage = (count / len(instances)) * 100
        bar = '█' * int(percentage / 5)
        print(f"  {desc:<12} {count:>3}个 ({percentage:>5.1f}%) {bar}")
    
    # 用户统计
    print("\n" + "=" * 80)
    print("👤 启动用户统计")
    print("=" * 80)
    
    for user, count in user_counter.most_common(10):
        print(f"  {user:<20} {count:>3}次")
    
    # 疑似异常的工作流（非定时调度占比高）
    print("\n" + "=" * 80)
    print("⚠️ 疑似异常的工作流（非定时调度启动比例高）")
    print("=" * 80)
    
    abnormal_workflows = []
    for workflow, counter in workflow_startup.items():
        total = sum(counter.values())
        scheduler_count = counter.get('SCHEDULER', 0)
        non_scheduler = total - scheduler_count
        
        if total >= 3 and non_scheduler > scheduler_count:
            # 非定时启动占比超过50%
            abnormal_workflows.append({
                'name': workflow,
                'total': total,
                'scheduler': scheduler_count,
                'non_scheduler': non_scheduler,
                'non_scheduler_pct': (non_scheduler / total) * 100
            })
    
    if abnormal_workflows:
        # 按非定时启动比例排序
        abnormal_workflows.sort(key=lambda x: x['non_scheduler_pct'], reverse=True)
        
        for wf in abnormal_workflows[:10]:
            print(f"\n  📋 {wf['name']}")
            print(f"      总计: {wf['total']}次")
            print(f"      ⏰ 定时调度: {wf['scheduler']}次")
            print(f"      ⚠️  非定时: {wf['non_scheduler']}次 ({wf['non_scheduler_pct']:.1f}%)")
            
            # 显示该工作流的具体启动类型分布
            types = workflow_startup[wf['name']]
            for t, c in types.most_common():
                if t != 'SCHEDULER':
                    print(f"         - {COMMAND_TYPE_DESC.get(t, t)}: {c}次")
    else:
        print("  ✅ 没有发现异常工作流（所有工作流都以定时调度为主）")
    
    # 建议
    print("\n" + "=" * 80)
    print("💡 诊断建议")
    print("=" * 80)
    
    if type_counter.get('MANUAL', 0) > 5:
        print("  ⚠️  手动触发较多，建议检查是否有用户频繁手动启动")
    
    if type_counter.get('START_PROCESS', 0) > 5:
        print("  ⚠️  API调用较多，建议检查外部系统调用情况")
    
    if type_counter.get('COMPLEMENT_DATA', 0) > 3:
        print("  📅 补数据任务较多，可能是正常的数据回填操作")
    
    if type_counter.get('RETRY', 0) > 5:
        print("  🔁 故障重试较多，建议检查工作流稳定性")
    
    print("\n  🔍 如需停止非正常启动的实例，请运行:")
    print("     python check_abnormal_startup.py --show-all")
    print("\n  🛑 如需立即停止所有非定时启动的实例:")
    print("     python check_abnormal_startup.py --stop")
    
    print("=" * 80)


if __name__ == '__main__':
    analyze_startup_patterns()
