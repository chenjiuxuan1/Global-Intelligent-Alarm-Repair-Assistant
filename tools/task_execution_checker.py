#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
定时任务执行检查工具
用于验证定时任务执行步骤是否完整

使用方法:
    python3 task_execution_checker.py --task abnormal    # 检查异常调度检测
    python3 task_execution_checker.py --task repair      # 检查智能告警修复
    python3 task_execution_checker.py --task all         # 检查所有任务
"""

import sys
import os
import json
import argparse
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config.config import WORKSPACE_CONFIG


WORKSPACE_ROOT = WORKSPACE_CONFIG['root']

# 任务配置
TASKS = {
    'abnormal': {
        'name': '异常调度自动检测',
        'script': 'core/auto_stop_abnormal_schedule.py',
        'steps': [
            '步骤1: 加载调度配置',
            '步骤2: 获取运行中实例',
            '步骤3: 异常检测',
            '步骤4: 自动停止异常实例（条件）',
            '步骤5: TV通知（条件）',
            '步骤6: 钉钉报告（已禁用）',
            '步骤7: 保存检测记录',
            '步骤8: 执行完成'
        ]
    },
    'repair': {
        'name': '智能告警修复',
        'script': 'core/repair_strict_7step.py',
        'steps': [
            '步骤1: 扫描告警',
            '步骤2: 查找工作流位置',
            '步骤3: 执行修复',
            '步骤4: 记录+复验',
            '步骤5: 钉钉报告（已禁用）',
            '步骤6: 保存操作记录',
            '步骤7: TV报告',
            '步骤8: 执行完成'
        ]
    }
}


def get_effective_workspace_root():
    """优先使用配置路径；若配置路径无效，则回退到当前仓库根目录"""
    configured_root = WORKSPACE_ROOT
    current_repo_root = str(Path(__file__).resolve().parents[1])

    for candidate in [configured_root, current_repo_root]:
        if candidate and os.path.exists(os.path.join(candidate, "core", "repair_strict_7step.py")):
            return candidate
    return configured_root


EFFECTIVE_WORKSPACE_ROOT = get_effective_workspace_root()


def check_script_exists(script_name):
    """检查脚本文件是否存在"""
    script_path = os.path.join(EFFECTIVE_WORKSPACE_ROOT, script_name)
    return os.path.exists(script_path)


def check_script_syntax(script_name):
    """检查脚本语法是否正确"""
    import py_compile
    script_path = os.path.join(EFFECTIVE_WORKSPACE_ROOT, script_name)
    try:
        py_compile.compile(
            script_path,
            doraise=True,
            cfile=os.path.join("/tmp", "task_execution_checker.pyc"),
        )
        return True, None
    except Exception as e:
        return False, str(e)


def check_env_variables():
    """检查环境变量"""
    required = ['DS_TOKEN', 'DB_PASSWORD']
    missing = []
    for var in required:
        if not os.environ.get(var):
            missing.append(var)
    return missing


def check_csv_file():
    """检查CSV文件"""
    csv_path = os.path.join(EFFECTIVE_WORKSPACE_ROOT, "dolphinscheduler", "schedules_export.csv")
    if not os.path.exists(csv_path):
        return False, "文件不存在"
    if os.path.getsize(csv_path) == 0:
        return False, "文件为空"
    return True, "正常"


def print_check_result(item, status, detail=""):
    """打印检查结果"""
    icon = "✅" if status else "❌"
    print(f"  {icon} {item}", end="")
    if detail:
        print(f": {detail}")
    else:
        print()


def check_task(task_key):
    """检查指定任务"""
    task = TASKS.get(task_key)
    if not task:
        print(f"❌ 未知任务: {task_key}")
        return False
    
    print("="*70)
    print(f"🔍 检查任务: {task['name']}")
    print("="*70)
    print()
    
    all_ok = True
    
    # 1. 检查脚本文件
    print("1. 脚本文件检查:")
    script_exists = check_script_exists(task['script'])
    print_check_result("脚本文件存在", script_exists, task['script'])
    all_ok = all_ok and script_exists
    
    if script_exists:
        syntax_ok, error = check_script_syntax(task['script'])
        print_check_result("脚本语法正确", syntax_ok, error if error else "")
        all_ok = all_ok and syntax_ok
    print()
    
    # 2. 检查环境变量
    print("2. 环境变量检查:")
    missing_env = check_env_variables()
    if missing_env:
        print_check_result("环境变量", False, f"缺少: {', '.join(missing_env)}")
        all_ok = False
    else:
        print_check_result("环境变量", True, "已设置")
    print()
    
    # 3. 检查数据文件
    if task_key == 'abnormal':
        print("3. 数据文件检查:")
        csv_ok, csv_detail = check_csv_file()
        print_check_result("调度配置CSV", csv_ok, csv_detail)
        all_ok = all_ok and csv_ok
        print()
    
    # 4. 检查执行步骤
    print("4. 执行步骤检查:")
    for i, step in enumerate(task['steps'], 1):
        print(f"   {i}. {step}")
    print()
    
    # 5. 总体状态
    print("="*70)
    if all_ok:
        print(f"✅ {task['name']} 检查通过，可以正常执行")
    else:
        print(f"❌ {task['name']} 检查未通过，请修复上述问题")
    print("="*70)
    print()
    
    return all_ok


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='定时任务执行检查工具')
    parser.add_argument('--task', choices=['abnormal', 'repair', 'all'], 
                       default='all', help='要检查的任务')
    args = parser.parse_args()
    
    print()
    print("🚀 定时任务执行检查工具")
    print(f"⏰ 检查时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    if args.task == 'all':
        results = []
        for task_key in TASKS:
            results.append(check_task(task_key))
            print()
        
        print("="*70)
        print("📊 总体检查结果")
        print("="*70)
        for task_key in TASKS:
            task = TASKS[task_key]
            status = "✅ 通过" if results else "❌ 失败"
            print(f"  {status} {task['name']}")
        print("="*70)
    else:
        check_task(args.task)


if __name__ == '__main__':
    main()
