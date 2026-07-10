#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
检测并停止"无定时配置但被调度启动"的异常工作流实例

核心逻辑：
- 正常：有定时配置 + 调度启动 ✅
- 正常：人工启动 ✅  
- 正常：API调用 ✅
- 异常：无定时配置 + 但被调度启动 ❌（需要停止）

作者：OpenClaw
日期：2026-03-23
"""

import os
import urllib.request
import urllib.error
import json
import sys
import argparse

# DolphinScheduler 配置
DS_CONFIG = {
    'base_url': 'http://172.20.0.235:12345/dolphinscheduler',
    'token': os.environ.get('DS_TOKEN', ''),
    'project_code': '158514956085248',
    'project_name': '国内数仓-工作流'
}


def fetch_running_instances():
    """获取正在运行的工作流实例"""
    url = f"{DS_CONFIG['base_url']}/projects/{DS_CONFIG['project_code']}/process-instances"
    params = "?stateType=RUNNING_EXECUTION&pageNo=1&pageSize=100"
    
    req = urllib.request.Request(url + params)
    req.add_header('token', DS_CONFIG['token'])
    
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            result = json.loads(response.read().decode('utf-8'))
            if result.get('code') == 0:
                return True, result.get('data', {}).get('totalList', [])
    except Exception as e:
        print(f"❌ 查询实例失败: {e}")
    
    return False, []


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
    except Exception as e:
        print(f"  ⚠️ 获取实例详情失败: {e}")
    
    return {}


def check_workflow_schedule(process_code):
    """
    检查工作流是否有定时调度配置
    
    Returns:
        dict: {
            'has_schedule': bool,  # 是否有定时配置
            'schedule_status': str,  # ONLINE/OFFLINE/NONE
            'cron': str,  # Cron表达式
            'schedule_id': str  # 调度ID
        }
    """
    url = f"{DS_CONFIG['base_url']}/projects/{DS_CONFIG['project_code']}/schedules"
    
    req = urllib.request.Request(url)
    req.add_header('token', DS_CONFIG['token'])
    
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            result = json.loads(response.read().decode('utf-8'))
            if result.get('code') == 0:
                schedules = result.get('data', {}).get('totalList', [])
                
                # 查找该工作流的调度配置
                for sch in schedules:
                    if str(sch.get('processDefinitionCode')) == str(process_code):
                        return {
                            'has_schedule': True,
                            'schedule_status': sch.get('releaseState', 'UNKNOWN'),  # ONLINE/OFFLINE
                            'cron': sch.get('crontab', 'N/A'),
                            'schedule_id': sch.get('id', 'N/A'),
                            'schedule_name': sch.get('processDefinitionName', 'N/A')
                        }
    except Exception as e:
        print(f"  ⚠️ 查询调度配置失败: {e}")
    
    # 没有找到调度配置
    return {
        'has_schedule': False,
        'schedule_status': 'NONE',
        'cron': 'N/A',
        'schedule_id': 'N/A',
        'schedule_name': 'N/A'
    }


def stop_instance(instance_id):
    """停止工作流实例"""
    url = f"{DS_CONFIG['base_url']}/projects/{DS_CONFIG['project_code']}/executors/execute"
    
    data = {
        'processInstanceId': instance_id,
        'executeType': 'STOP'
    }
    
    req = urllib.request.Request(
        url, 
        data=json.dumps(data).encode('utf-8'),
        headers={'Content-Type': 'application/json'},
        method='POST'
    )
    req.add_header('token', DS_CONFIG['token'])
    
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            result = json.loads(response.read().decode('utf-8'))
            if result.get('code') == 0:
                return True
            else:
                print(f"  ❌ 停止失败: {result.get('msg')}")
                return False
    except Exception as e:
        print(f"  ❌ 停止异常: {e}")
        return False


def analyze_and_stop_abnormal(stop_mode=False, force=False):
    """
    分析并停止异常实例
    
    异常定义：
    - commandType = SCHEDULER（调度启动）
    - 但该工作流没有定时配置 或 调度已下线（OFFLINE）
    """
    print("=" * 100)
    print(f"📊 项目: {DS_CONFIG['project_name']}")
    print("🔍 检测'无定时配置但被调度启动'的异常实例...")
    print("=" * 100)
    
    # 获取运行中的实例
    success, instances = fetch_running_instances()
    if not success or not instances:
        print("✅ 当前没有运行中的工作流实例")
        return
    
    print(f"\n📋 发现 {len(instances)} 个运行中的实例\n")
    
    abnormal_instances = []
    normal_count = 0
    
    for i, inst in enumerate(instances, 1):
        instance_id = inst.get('id')
        name = inst.get('name', 'N/A')
        process_code = inst.get('processDefinitionCode')
        state = inst.get('state', 'N/A')
        start_time = inst.get('startTime', 'N/A')
        
        # 获取实例详情
        detail = get_instance_detail(instance_id)
        command_type = detail.get('commandType', 'UNKNOWN')
        
        print(f"[{i}] 检查: {name[:40]}")
        print(f"    实例ID: {instance_id}")
        print(f"    启动类型: {command_type}")
        
        # 只有 SCHEDULER 类型的才需要检查是否有定时配置
        if command_type == 'SCHEDULER':
            # 查询该工作流的定时配置
            schedule_info = check_workflow_schedule(process_code)
            
            has_schedule = schedule_info['has_schedule']
            schedule_status = schedule_info['schedule_status']
            cron = schedule_info['cron']
            
            print(f"    定时配置: {'有' if has_schedule else '无'}")
            if has_schedule:
                print(f"    调度状态: {schedule_status}")
                print(f"    Cron: {cron}")
            
            # 判断是否为异常：
            # 情况1：没有定时配置，但被调度启动
            # 情况2：有定时配置但调度已下线（OFFLINE），仍被调度启动
            is_abnormal = False
            abnormal_reason = ""
            
            if not has_schedule:
                is_abnormal = True
                abnormal_reason = "无定时配置但被调度启动"
            elif schedule_status == 'OFFLINE':
                is_abnormal = True
                abnormal_reason = "调度已下线但仍被启动"
            
            if is_abnormal:
                print(f"    ⚠️ 异常: {abnormal_reason}")
                abnormal_instances.append({
                    'id': instance_id,
                    'name': name,
                    'reason': abnormal_reason,
                    'schedule_info': schedule_info,
                    'start_time': start_time
                })
            else:
                print(f"    ✅ 正常: 有定时配置且状态为{schedule_status}")
                normal_count += 1
        
        elif command_type == 'MANUAL':
            print(f"    ✅ 正常: 人工手动启动")
            normal_count += 1
        
        elif command_type == 'START_PROCESS':
            print(f"    ✅ 正常: API调用启动")
            normal_count += 1
        
        elif command_type == 'COMPLEMENT_DATA':
            print(f"    ✅ 正常: 补数据启动")
            normal_count += 1
        
        else:
            print(f"    ℹ️ 其他: {command_type}")
            normal_count += 1
        
        print()
    
    # 统计报告
    print("=" * 100)
    print("📊 检测结果")
    print("=" * 100)
    print(f"   总实例数: {len(instances)}")
    print(f"   ✅ 正常实例: {normal_count}")
    print(f"   ⚠️ 异常实例: {len(abnormal_instances)}")
    
    if abnormal_instances:
        print(f"\n⚠️ 发现 {len(abnormal_instances)} 个异常实例（需要停止）:")
        for inst in abnormal_instances:
            print(f"\n   📋 {inst['name']}")
            print(f"      实例ID: {inst['id']}")
            print(f"      异常原因: {inst['reason']}")
            print(f"      启动时间: {inst['start_time']}")
            if inst['schedule_info'].get('cron') != 'N/A':
                print(f"      原Cron: {inst['schedule_info']['cron']}")
        
        # 停止异常实例
        if stop_mode:
            print(f"\n🛑 准备停止这些异常实例...")
            
            if not force:
                confirm = input("\n确认停止以上异常实例? (yes/no): ")
                if confirm.lower() != 'yes':
                    print("❌ 已取消")
                    return
            
            stopped_count = 0
            for inst in abnormal_instances:
                print(f"\n🛑 停止: {inst['name']}")
                if stop_instance(inst['id']):
                    print("   ✅ 停止成功")
                    stopped_count += 1
                else:
                    print("   ❌ 停止失败")
            
            print(f"\n✅ 已成功停止 {stopped_count}/{len(abnormal_instances)} 个异常实例")
        else:
            print(f"\n💡 使用 --stop 参数停止这些异常实例:")
            print(f"   python {sys.argv[0]} --stop")
    else:
        print("\n✅ 没有发现异常实例，所有调度启动的任务都有正常的定时配置！")
    
    print("=" * 100)


def main():
    parser = argparse.ArgumentParser(
        description='检测并停止"无定时配置但被调度启动"的异常工作流实例',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
判断逻辑:
  ✅ 正常: 有定时配置 + 调度启动
  ✅ 正常: 人工启动 / API调用 / 补数据
  ❌ 异常: 无定时配置 + 但被调度启动（需要停止）
  ❌ 异常: 调度已下线 + 但仍被启动（需要停止）

使用示例:
  %(prog)s              # 只检测，不停止
  %(prog)s --stop       # 检测并停止异常实例
  %(prog)s --stop --force  # 强制停止，不提示确认
        """
    )
    
    parser.add_argument('--stop', action='store_true', help='停止检测到的异常实例')
    parser.add_argument('--force', action='store_true', help='强制停止，不提示确认')
    
    args = parser.parse_args()
    
    analyze_and_stop_abnormal(stop_mode=args.stop, force=args.force)


if __name__ == '__main__':
    main()
