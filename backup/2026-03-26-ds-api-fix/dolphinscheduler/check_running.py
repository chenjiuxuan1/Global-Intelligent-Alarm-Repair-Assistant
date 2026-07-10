#!/usr/bin/env python3

# 自动加载环境变量
import sys
sys.path.insert(0, "/home/node/.openclaw/workspace")
import auto_load_env

# -*- coding: utf-8 -*-
"""
检测国内数仓-工作流正在运行的工作流实例
支持筛选和详细信息展示

作者：OpenClaw
日期：2026-03-23
"""

import urllib.request
import urllib.error
import json
import sys
import argparse
import os
from datetime import datetime

# DolphinScheduler 配置
DS_CONFIG = {
    'base_url': 'http://172.20.0.235:12345/dolphinscheduler',
    'token': os.environ.get('DS_TOKEN', ''),
    'project_code': '158514956085248',
    'project_name': '国内数仓-工作流'
}


def fetch_running_workflows(filter_name=None, limit=20):
    """
    获取正在运行的工作流实例列表
    
    Args:
        filter_name: 按工作流名称筛选（支持模糊匹配）
        limit: 返回的最大实例数
        
    Returns:
        tuple: (success: bool, workflows: list, total: int)
    """
    url = f"{DS_CONFIG['base_url']}/projects/{DS_CONFIG['project_code']}/process-instances"
    params = f"?stateType=RUNNING_EXECUTION&pageNo=1&pageSize={limit}"
    
    full_url = url + params
    
    req = urllib.request.Request(full_url)
    req.add_header('token', DS_CONFIG['token'])
    
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            result = json.loads(response.read().decode('utf-8'))
            
            if result.get('code') == 0:
                total = result.get('data', {}).get('total', 0)
                workflows = result.get('data', {}).get('totalList', [])
                
                # 按名称筛选
                if filter_name:
                    workflows = [w for w in workflows if filter_name.lower() in w.get('name', '').lower()]
                
                return True, workflows, total
            else:
                print(f"❌ API 错误: {result.get('msg', 'Unknown')}")
                return False, [], 0
                
    except urllib.error.URLError as e:
        print(f"❌ 连接失败: {e}")
        return False, [], 0
    except json.JSONDecodeError:
        print("❌ JSON 解析错误")
        return False, [], 0
    except Exception as e:
        print(f"❌ 异常: {e}")
        return False, [], 0


def format_duration(seconds):
    """格式化运行时长"""
    if not seconds:
        return "未知"
    
    # 确保是整数
    try:
        seconds = int(seconds)
    except (ValueError, TypeError):
        return "未知"
    
    minutes = seconds // 60
    hours = minutes // 60
    
    if hours > 0:
        return f"{hours}小时{minutes % 60}分钟"
    elif minutes > 0:
        return f"{minutes}分钟"
    else:
        return f"{seconds}秒"


def display_workflows(workflows, total, filter_name=None):
    """格式化显示工作流列表"""
    
    print("=" * 70)
    print(f"📊 项目: {DS_CONFIG['project_name']}")
    print(f"🔍 筛选条件: {filter_name if filter_name else '无（全部）'}")
    print("=" * 70)
    
    if not workflows:
        if total == 0:
            print("\n⚪ 当前没有正在运行的工作流实例")
            print(f"   总计: {total} 个实例\n")
        else:
            print(f"\n⚪ 筛选后无匹配的工作流")
            print(f"   总计运行中: {total} 个实例")
            print(f"   筛选条件 '{filter_name}' 无匹配\n")
        return
    
    # 显示统计信息
    print(f"\n🟢 正在运行的实例: {len(workflows)} 个（显示/总计: {len(workflows)}/{total}）\n")
    
    # 显示每个工作流的详细信息
    for i, wf in enumerate(workflows, 1):
        name = wf.get('name', 'N/A')
        instance_id = wf.get('id', 'N/A')
        state = wf.get('state', 'N/A')
        start_time = wf.get('startTime', 'N/A')
        duration = wf.get('duration', 0)
        
        print(f"[{i}] 📋 {name}")
        print(f"    实例ID: {instance_id}")
        print(f"    状态: {state}")
        print(f"    开始时间: {start_time}")
        print(f"    已运行: {format_duration(duration)}")
        
        # 显示工作流定义Code（用于后续操作）
        process_code = wf.get('processDefinitionCode', 'N/A')
        print(f"    工作流Code: {process_code}")
        print()
    
    print("=" * 70)


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description='检测国内数仓-工作流正在运行的工作流实例',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  %(prog)s                           # 显示所有运行中的实例
  %(prog)s -f "同步"                 # 筛选名称包含"同步"的实例
  %(prog)s -f "H-1" -l 10          # 筛选并最多显示10个
  %(prog)s --check-only            # 只检查是否有运行中，不显示详情
        """
    )
    
    parser.add_argument(
        '-f', '--filter',
        help='按工作流名称筛选（支持模糊匹配）'
    )
    parser.add_argument(
        '-l', '--limit',
        type=int,
        default=20,
        help='最多显示的实例数（默认: 20）'
    )
    parser.add_argument(
        '--check-only',
        action='store_true',
        help='只检查是否有运行中的实例，不显示详细信息'
    )
    
    args = parser.parse_args()
    
    # 获取数据
    success, workflows, total = fetch_running_workflows(
        filter_name=args.filter,
        limit=args.limit
    )
    
    if not success:
        print("⚠️ 查询失败")
        sys.exit(2)
    
    # 仅检查模式
    if args.check_only:
        if total > 0:
            print(f"🟢 有 {total} 个工作流正在运行")
            sys.exit(1)  # 返回1表示有运行中
        else:
            print("⚪ 没有工作流在运行（空闲）")
            sys.exit(0)  # 返回0表示空闲
    
    # 详细显示模式
    display_workflows(workflows, total, args.filter)
    
    # 返回退出码
    if total > 0:
        sys.exit(1)  # 有运行中
    else:
        sys.exit(0)  # 空闲


if __name__ == '__main__':
    main()
