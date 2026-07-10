#!/usr/bin/env python3

# 自动加载环境变量
import sys
sys.path.insert(0, "/home/node/.openclaw/workspace")
import auto_load_env

# -*- coding: utf-8 -*-
"""
搜索特定表名在哪些工作流中使用
通过查询工作流的任务定义来匹配表名

作者：OpenClaw
日期：2026-03-23
"""

import os
import urllib.request
import urllib.error
import json
import sys
import argparse
import re

# DolphinScheduler 配置
DS_CONFIG = {
    'base_url': 'http://172.20.0.235:12345/dolphinscheduler',
    'token': os.environ.get('DS_TOKEN', ''),
    'project_code': '158514956085248',
    'project_name': '国内数仓-工作流'
}


def fetch_all_workflows():
    """获取所有工作流列表"""
    all_workflows = []
    page_no = 1
    page_size = 50
    
    while True:
        url = f"{DS_CONFIG['base_url']}/projects/{DS_CONFIG['project_code']}/process-definition"
        params = f"?pageNo={page_no}&pageSize={page_size}"
        
        req = urllib.request.Request(url + params)
        req.add_header('token', DS_CONFIG['token'])
        
        try:
            with urllib.request.urlopen(req, timeout=15) as response:
                result = json.loads(response.read().decode('utf-8'))
                
                if result.get('code') == 0:
                    workflows = result.get('data', {}).get('totalList', [])
                    total = result.get('data', {}).get('total', 0)
                    
                    if not workflows:
                        break
                    
                    all_workflows.extend(workflows)
                    
                    if len(all_workflows) >= total:
                        break
                    
                    page_no += 1
                else:
                    break
        except:
            break
    
    return all_workflows


def get_workflow_detail(process_code):
    """
    获取工作流详情，包含任务定义
    
    Returns:
        dict: 工作流详情，包含 taskDefinitionList
    """
    url = f"{DS_CONFIG['base_url']}/projects/{DS_CONFIG['project_code']}/process-definition/{process_code}"
    
    req = urllib.request.Request(url)
    req.add_header('token', DS_CONFIG['token'])
    
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            result = json.loads(response.read().decode('utf-8'))
            if result.get('code') == 0:
                return result.get('data', {})
    except Exception as e:
        print(f"    ⚠️ 获取详情失败: {e}")
    
    return {}


def search_in_task(task, search_term):
    """
    在任务中搜索关键词
    
    Args:
        task: 任务定义
        search_term: 搜索关键词
        
    Returns:
        list: 匹配到的字段和上下文
    """
    matches = []
    search_lower = search_term.lower()
    
    # 搜索任务名称
    task_name = task.get('name', '')
    if search_lower in task_name.lower():
        matches.append({'field': '任务名称', 'content': task_name})
    
    # 搜索任务描述
    description = task.get('description', '')
    if search_lower in description.lower():
        matches.append({'field': '描述', 'content': description[:100]})
    
    # 搜索任务参数（SQL等）
    task_params = task.get('taskParams', '{}')
    if isinstance(task_params, str):
        try:
            task_params = json.loads(task_params)
        except:
            task_params = {}
    
    # SQL 语句
    raw_script = task_params.get('rawScript', '')
    if raw_script and search_lower in raw_script.lower():
        # 找到匹配的行
        lines = raw_script.split('\n')
        for i, line in enumerate(lines, 1):
            if search_lower in line.lower():
                matches.append({'field': f'SQL第{i}行', 'content': line.strip()[:150]})
                if len(matches) >= 3:  # 最多显示3行
                    break
    
    # 资源列表
    resource_list = task_params.get('resourceList', [])
    for res in resource_list:
        res_name = res.get('fullName', '')
        if search_lower in res_name.lower():
            matches.append({'field': '资源文件', 'content': res_name})
    
    # 其他可能的字段
    for key, value in task_params.items():
        if isinstance(value, str) and search_lower in value.lower():
            matches.append({'field': f'参数.{key}', 'content': value[:100]})
    
    return matches


def search_table_in_workflows(search_term):
    """
    在所有工作流中搜索表名
    
    Args:
        search_term: 要搜索的表名或关键词
    """
    print("=" * 100)
    print(f"🔍 在 [{DS_CONFIG['project_name']}] 中搜索: '{search_term}'")
    print("=" * 100)
    print()
    
    # 获取所有工作流
    print("📋 获取工作流列表...")
    workflows = fetch_all_workflows()
    
    if not workflows:
        print("❌ 未获取到工作流数据")
        return
    
    print(f"✅ 共 {len(workflows)} 个工作流，开始搜索...\n")
    
    results = []
    checked = 0
    
    for i, wf in enumerate(workflows, 1):
        process_code = wf.get('code')
        process_name = wf.get('name', 'N/A')
        
        print(f"  [{i}/{len(workflows)}] 检查: {process_name[:50]}", end='')
        
        # 获取工作流详情
        detail = get_workflow_detail(process_code)
        tasks = detail.get('taskDefinitionList', [])
        
        workflow_matches = []
        
        # 检查每个任务
        for task in tasks:
            matches = search_in_task(task, search_term)
            if matches:
                workflow_matches.append({
                    'task_name': task.get('name', 'N/A'),
                    'task_code': task.get('code', 'N/A'),
                    'task_type': task.get('taskType', 'N/A'),
                    'matches': matches
                })
        
        if workflow_matches:
            print(f"  🎯 找到 {len(workflow_matches)} 个匹配任务!")
            results.append({
                'workflow_name': process_name,
                'workflow_code': process_code,
                'workflow_status': wf.get('releaseState', 'N/A'),
                'tasks': workflow_matches
            })
        else:
            print()
        
        checked += 1
    
    # 输出结果
    print("\n" + "=" * 100)
    print(f"📊 搜索结果")
    print("=" * 100)
    print(f"   检查工作流: {checked}")
    print(f"   匹配工作流: {len(results)}")
    
    if not results:
        print(f"\n❌ 未找到包含 '{search_term}' 的工作流")
        return
    
    print(f"\n✅ 找到 {len(results)} 个工作流包含 '{search_term}':\n")
    
    for i, result in enumerate(results, 1):
        print(f"[{i}] 📋 工作流: {result['workflow_name']}")
        print(f"    工作流Code: {result['workflow_code']}")
        print(f"    状态: {result['workflow_status']}")
        print(f"    包含任务数: {len(result['tasks'])}")
        print()
        
        for j, task in enumerate(result['tasks'], 1):
            print(f"    [{j}] 任务: {task['task_name']}")
            print(f"        任务类型: {task['task_type']}")
            print(f"        任务Code: {task['task_code']}")
            print(f"        匹配详情:")
            
            for match in task['matches'][:5]:  # 最多显示5个匹配
                print(f"          - {match['field']}: {match['content']}")
            
            if len(task['matches']) > 5:
                print(f"          ... 还有 {len(task['matches']) - 5} 处匹配")
            print()
        
        print("-" * 100)
    
    print("\n💡 使用工作流Code启动工作流:")
    print(f"   python dolphinscheduler_api.py --project {DS_CONFIG['project_code']} --process <工作流Code>")


def main():
    parser = argparse.ArgumentParser(
        description='在DolphinScheduler工作流中搜索表名或关键词',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  %(prog)s ods_app_strawberry_middle_trade    # 搜索特定表名
  %(prog)s dwd_asset                          # 搜索前缀匹配
  %(prog)s "repay"                            # 搜索包含关键词
        """
    )
    
    parser.add_argument(
        'search_term',
        help='要搜索的表名或关键词'
    )
    
    args = parser.parse_args()
    
    search_table_in_workflows(args.search_term)


if __name__ == '__main__':
    main()
