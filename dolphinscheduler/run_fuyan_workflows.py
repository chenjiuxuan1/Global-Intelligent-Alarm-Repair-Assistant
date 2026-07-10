#!/usr/bin/env python3

# 自动加载环境变量
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import auto_load_env
from config.config import DS_CONFIG, FUYAN_WORKFLOWS

# -*- coding: utf-8 -*-
"""
依次启动所有"复验"工作流

基于CSV中的复验工作流信息，按顺序启动

作者：OpenClaw
日期：2026-03-23
"""

import urllib.request
import urllib.error
import json
import time
from datetime import datetime
from urllib.parse import urlencode

# DolphinScheduler 配置
DS_ENVIRONMENT_CODE = DS_CONFIG['environment_code']
DS_TENANT_CODE = DS_CONFIG['tenant_code']


def start_workflow(project_code, workflow_code, workflow_name, dt=None):
    """
    启动工作流
    
    Args:
        project_code: 项目Code
        workflow_code: 工作流Code
        workflow_name: 工作流名称（用于日志）
        dt: 业务日期（可选）
        
    Returns:
        tuple: (success: bool, instance_id: str, message: str)
    """
    url = f"{DS_CONFIG['base_url']}/projects/{project_code}/executors/start-process-instance"
    
    # 构建请求体（参考dolphinscheduler_api.py）
    body = {
        'processDefinitionCode': workflow_code,
        'failureStrategy': 'CONTINUE',
        'warningType': 'NONE',
        'warningGroupId': '0',
        'processInstancePriority': 'MEDIUM',
        'workerGroup': 'default',
        'environmentCode': DS_ENVIRONMENT_CODE,
        'tenantCode': DS_TENANT_CODE,
        'taskDependType': 'TASK_POST',
        'runMode': 'RUN_MODE_SERIAL',
        'execType': 'START_PROCESS',
        'dryRun': '0',
        'scheduleTime': '',  # 必须传空字符串
    }
    
    # 添加业务日期参数
    if dt:
        body['startParams'] = json.dumps({"dt": dt})
    
    headers = {
        'token': DS_CONFIG['token'],
        'Content-Type': 'application/x-www-form-urlencoded'
    }
    
    try:
        # 编码请求体
        encoded_body = urlencode(body).encode('utf-8')
        
        req = urllib.request.Request(url, data=encoded_body, headers=headers, method='POST')
        
        with urllib.request.urlopen(req, timeout=30) as response:
            result = json.loads(response.read().decode('utf-8'))
            
            if result.get('code') == 0:
                instance_id = result.get('data')
                return True, instance_id, "启动成功"
            else:
                return False, None, result.get('msg', 'Unknown error')
                
    except urllib.error.HTTPError as e:
        return False, None, f"HTTP {e.code}: {e.reason}"
    except Exception as e:
        return False, None, f"异常: {str(e)}"


def run_all_fuyan_workflows(dt=None, interval=5):
    """
    依次启动所有复验工作流
    
    Args:
        dt: 业务日期，格式：YYYY-MM-DD，默认为今天
        interval: 每个工作流启动间隔（秒）
    """
    # 默认使用今天
    if not dt:
        dt = datetime.now().strftime('%Y-%m-%d')
    
    print("=" * 100)
    print(f"🚀 依次启动所有复验工作流")
    print(f"   业务日期: {dt}")
    print(f"   工作流数量: {len(FUYAN_WORKFLOWS)}")
    print("=" * 100)
    print()
    
    results = []
    success_count = 0
    failed_count = 0
    
    for i, wf in enumerate(FUYAN_WORKFLOWS, 1):
        project_code = wf['project_code']
        workflow_code = wf['workflow_code']
        workflow_name = wf['workflow_name']
        schedule = wf['schedule']
        level = wf['level']
        
        print(f"[{i}/{len(FUYAN_WORKFLOWS)}] 🚀 启动: {workflow_name}")
        print(f"      项目: {wf['project_name']}")
        print(f"      调度: {schedule} | 级别: {level}")
        print(f"      Code: {workflow_code}")
        
        # 启动工作流
        success, instance_id, message = start_workflow(
            project_code, workflow_code, workflow_name, dt
        )
        
        if success:
            print(f"      ✅ 启动成功！实例ID: {instance_id}")
            success_count += 1
            results.append({
                'workflow_name': workflow_name,
                'status': '成功',
                'instance_id': instance_id,
                'message': message
            })
        else:
            print(f"      ❌ 启动失败: {message}")
            failed_count += 1
            results.append({
                'workflow_name': workflow_name,
                'status': '失败',
                'instance_id': None,
                'message': message
            })
        
        print()
        
        # 间隔等待（最后一个不等待）
        if i < len(FUYAN_WORKFLOWS):
            print(f"   ⏳ 等待 {interval} 秒后启动下一个...")
            time.sleep(interval)
            print()
    
    # 汇总报告
    print("=" * 100)
    print("📊 执行汇总")
    print("=" * 100)
    print(f"   总工作流数: {len(FUYAN_WORKFLOWS)}")
    print(f"   ✅ 成功: {success_count}")
    print(f"   ❌ 失败: {failed_count}")
    print()
    
    if success_count == len(FUYAN_WORKFLOWS):
        print("🎉 所有复验工作流启动成功！")
    elif success_count > 0:
        print(f"⚠️ 部分成功，有 {failed_count} 个工作流启动失败")
    else:
        print("❌ 所有工作流启动失败，请检查配置")
    
    print()
    print("📋 详细结果:")
    print("-" * 100)
    for r in results:
        status_icon = "✅" if r['status'] == '成功' else "❌"
        instance_info = f" (ID: {r['instance_id']})" if r['instance_id'] else ""
        print(f"   {status_icon} {r['workflow_name']}{instance_info}")
    
    print("=" * 100)


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='依次启动所有复验工作流',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  %(prog)s                    # 使用今天日期启动
  %(prog)s --dt 2026-03-23    # 指定业务日期
  %(prog)s --interval 10      # 设置10秒间隔
        """
    )
    
    parser.add_argument(
        '--dt',
        help='业务日期，格式: YYYY-MM-DD (默认: 今天)'
    )
    parser.add_argument(
        '--interval',
        type=int,
        default=5,
        help='工作流启动间隔（秒，默认: 5）'
    )
    
    args = parser.parse_args()
    
    # 确认提示
    print("⚠️  即将依次启动以下复验工作流:")
    print()
    for i, wf in enumerate(FUYAN_WORKFLOWS, 1):
        print(f"   {i}. {wf['workflow_name']} ({wf['schedule']}, {wf['level']})")
    print()
    
    confirm = input("确认启动? (yes/no): ")
    if confirm.lower() != 'yes':
        print("❌ 已取消")
        sys.exit(0)
    
    print()
    
    # 执行启动
    run_all_fuyan_workflows(dt=args.dt, interval=args.interval)


if __name__ == '__main__':
    # 导入urllib.parse
    import urllib.parse
    main()
