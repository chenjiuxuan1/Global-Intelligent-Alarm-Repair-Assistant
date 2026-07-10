#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DolphinScheduler API 启动脚本
支持：基础启动、自定义参数、单任务执行等场景

作者：陈江川
日期：2026-03-17
版本：v1.0
"""

import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import os  # 新增：支持环境变量配置
import urllib.request
import urllib.parse
import json
from datetime import datetime
from typing import Optional, Dict, Any


class DolphinSchedulerClient:
    """DolphinScheduler API 客户端"""
    
    def __init__(self, base_url: str = None, token: str = None):
        """
        初始化客户端
        
        Args:
            base_url: DolphinScheduler API 地址
                      直连: http://127.0.0.1:12345/dolphinscheduler
                      SSH隧道: http://127.0.0.1:18789/dolphinscheduler (本地端口映射)
            token: API Token，默认使用配置文件中的 token
        """
        # 默认配置：DS 内网映射地址（172.20.0.235:12345）
        self.base_url = (base_url or os.environ.get('DS_BASE_URL', 'http://172.20.0.235:12345/dolphinscheduler')).rstrip('/')
        self.token = token or os.environ.get('DS_TOKEN', os.environ.get('DS_TOKEN', ''))
        self.headers = {
            'token': self.token,
            'Content-Type': 'application/x-www-form-urlencoded'
        }
        
        # 默认配置
        self.default_config = {
            'environment_code': '154818922491872',  # prod 环境
            'tenant_code': 'dolphinscheduler',
            'worker_group': 'default',
            'failure_strategy': 'CONTINUE',
            'warning_type': 'NONE',
            'priority': 'MEDIUM',
            'run_mode': 'RUN_MODE_SERIAL',
            'exec_type': 'START_PROCESS',
            'dry_run': '0',
            'task_depend_type': 'TASK_POST'  # 默认执行整个工作流
        }
    
    def start_workflow(
        self,
        project_code: str,
        process_code: str,
        custom_params: Optional[Dict[str, Any]] = None,
        task_code: Optional[str] = None,
        task_depend_type: str = 'TASK_POST',
        environment_code: Optional[str] = None,
        tenant_code: Optional[str] = None,
        schedule_time: str = ''
    ) -> Dict[str, Any]:
        """
        启动工作流
        
        Args:
            project_code: 项目 Code
            process_code: 工作流 Code
            custom_params: 自定义参数字典，如 {"dt": "2026-03-17"}
            task_code: 任务 Code（指定单个任务时使用）
            task_depend_type: 任务依赖类型
                - TASK_ONLY: 只执行指定任务
                - TASK_POST: 执行指定任务 + 所有下游任务（默认）
                - TASK_PRE: 执行指定任务 + 所有上游任务
            environment_code: 环境 Code（可选，默认使用 prod）
            tenant_code: 租户 Code（可选，默认 dolphinscheduler）
            schedule_time: 调度时间（必须传，即使是空字符串）
        
        Returns:
            响应字典，成功时包含 instance_id，失败时包含 error_message
        
        Example:
            # 基础启动
            client.start_workflow("159737550740160", "168243093291713")
            
            # 带自定义参数
            client.start_workflow("159737550740160", "168243093291713", 
                                  custom_params={"dt": "2026-03-17"})
            
            # 只执行单个任务
            client.start_workflow("159737550740160", "168243093291713",
                                  task_code="168251685969600",
                                  task_depend_type="TASK_ONLY")
        """
        # 构建请求体
        body = {
            'processDefinitionCode': process_code,
            'failureStrategy': self.default_config['failure_strategy'],
            'warningType': self.default_config['warning_type'],
            'warningGroupId': '0',
            'processInstancePriority': self.default_config['priority'],
            'workerGroup': self.default_config['worker_group'],
            'environmentCode': environment_code or self.default_config['environment_code'],
            'tenantCode': tenant_code or self.default_config['tenant_code'],
            'taskDependType': task_depend_type,
            'runMode': self.default_config['run_mode'],
            'execType': self.default_config['exec_type'],
            'dryRun': self.default_config['dry_run'],
            'scheduleTime': schedule_time,  # ⚠️ 必须传，即使是空字符串
        }
        
        # 添加自定义参数（转换为 JSON 字符串）
        if custom_params:
            body['startParams'] = json.dumps(custom_params)
        
        # 添加任务 Code（指定单个任务时）
        if task_code:
            body['startNodeList'] = task_code
        
        # 发送请求
        url = f"{self.base_url}/projects/{project_code}/executors/start-process-instance"
        
        try:
            response = requests.post(url, headers=self.headers, data=body, timeout=30)
            response.raise_for_status()
            
            result = response.json()
            
            if result.get('code') == 0:
                return {
                    'success': True,
                    'instance_id': result.get('data'),
                    'message': 'success',
                    'project_code': project_code,
                    'process_code': process_code,
                    'task_code': task_code,
                    'custom_params': custom_params
                }
            else:
                return {
                    'success': False,
                    'error_code': result.get('code'),
                    'error_message': result.get('msg'),
                    'project_code': project_code,
                    'process_code': process_code
                }
                
        except requests.exceptions.RequestException as e:
            return {
                'success': False,
                'error_code': 'NETWORK_ERROR',
                'error_message': str(e),
                'project_code': project_code,
                'process_code': process_code
            }
    
    def get_workflow_info(self, project_code: str, process_code: str) -> Dict[str, Any]:
        """
        查询工作流详情
        
        Args:
            project_code: 项目 Code
            process_code: 工作流 Code
        
        Returns:
            工作流信息字典
        """
        url = f"{self.base_url}/projects/{project_code}/process-definition/{process_code}"
        
        try:
            response = requests.get(url, headers=self.headers, timeout=30)
            response.raise_for_status()
            
            result = response.json()
            
            if result.get('code') == 0:
                return {
                    'success': True,
                    'data': result.get('data', {})
                }
            else:
                return {
                    'success': False,
                    'error_code': result.get('code'),
                    'error_message': result.get('msg')
                }
        except requests.exceptions.RequestException as e:
            return {
                'success': False,
                'error_code': 'NETWORK_ERROR',
                'error_message': str(e)
            }
    
    def get_workflows_list(self, project_code: str) -> Dict[str, Any]:
        """
        查询项目下所有工作流列表
        
        Args:
            project_code: 项目 Code
        
        Returns:
            工作流列表字典
        """
        url = f"{self.base_url}/projects/{project_code}/process-definition/query-process-definition-list"
        
        try:
            response = requests.get(url, headers=self.headers, timeout=30)
            response.raise_for_status()
            
            result = response.json()
            
            if result.get('code') == 0:
                return {
                    'success': True,
                    'data': result.get('data', [])
                }
            else:
                return {
                    'success': False,
                    'error_code': result.get('code'),
                    'error_message': result.get('msg')
                }
        except requests.exceptions.RequestException as e:
            return {
                'success': False,
                'error_code': 'NETWORK_ERROR',
                'error_message': str(e)
            }
    
    def get_environments(self) -> Dict[str, Any]:
        """
        查询可用环境列表
        
        Returns:
            环境列表字典
        """
        url = f"{self.base_url}/environment/list-paging?pageNo=1&pageSize=10"
        
        try:
            response = requests.get(url, headers=self.headers, timeout=30)
            response.raise_for_status()
            
            result = response.json()
            
            if result.get('code') == 0:
                return {
                    'success': True,
                    'data': result.get('data', {}).get('totalList', [])
                }
            else:
                return {
                    'success': False,
                    'error_code': result.get('code'),
                    'error_message': result.get('msg')
                }
        except requests.exceptions.RequestException as e:
            return {
                'success': False,
                'error_code': 'NETWORK_ERROR',
                'error_message': str(e)
            }
    
    def get_user_info(self) -> Dict[str, Any]:
        """
        查询当前用户信息
        
        Returns:
            用户信息字典
        """
        url = f"{self.base_url}/users/get-user-info"
        
        try:
            response = requests.get(url, headers=self.headers, timeout=30)
            response.raise_for_status()
            
            result = response.json()
            
            if result.get('code') == 0:
                return {
                    'success': True,
                    'data': result.get('data', {})
                }
            else:
                return {
                    'success': False,
                    'error_code': result.get('code'),
                    'error_message': result.get('msg')
                }
        except requests.exceptions.RequestException as e:
            return {
                'success': False,
                'error_code': 'NETWORK_ERROR',
                'error_message': str(e)
            }


# ==================== 便捷函数 ====================

def start_workflow_simple(
    project_code: str,
    process_code: str,
    dt: Optional[str] = None
) -> Dict[str, Any]:
    """
    简化版启动函数 - 最常用的场景
    
    Args:
        project_code: 项目 Code
        process_code: 工作流 Code
        dt: 业务日期（可选），如 "2026-03-17"
    
    Returns:
        启动结果
    
    Example:
        # 基础启动
        start_workflow_simple("159737550740160", "168243093291713")
        
        # 带业务日期
        start_workflow_simple("159737550740160", "168243093291713", dt="2026-03-17")
    """
    client = DolphinSchedulerClient(
        base_url="http://127.0.0.1:12345/dolphinscheduler",
        token=os.environ.get('DS_TOKEN', '')
    )
    
    custom_params = {}
    if dt:
        custom_params['dt'] = dt
    
    return client.start_workflow(
        project_code=project_code,
        process_code=process_code,
        custom_params=custom_params if custom_params else None
    )


def start_single_task(
    project_code: str,
    process_code: str,
    task_code: str,
    dt: Optional[str] = None
) -> Dict[str, Any]:
    """
    启动单个任务 - 只执行指定的任务
    
    Args:
        project_code: 项目 Code
        process_code: 工作流 Code
        task_code: 任务 Code
        dt: 业务日期（可选）
    
    Returns:
        启动结果
    
    Example:
        start_single_task("159737550740160", "168243093291713", "168251685969600", dt="2026-03-17")
    """
    client = DolphinSchedulerClient(
        base_url="http://127.0.0.1:12345/dolphinscheduler",
        token=os.environ.get('DS_TOKEN', '')
    )
    
    custom_params = {}
    if dt:
        custom_params['dt'] = dt
    
    return client.start_workflow(
        project_code=project_code,
        process_code=process_code,
        custom_params=custom_params if custom_params else None,
        task_code=task_code,
        task_depend_type='TASK_ONLY'
    )


# ==================== 命令行入口 ====================

if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='DolphinScheduler API 启动脚本')
    parser.add_argument('--project', required=True, help='项目 Code')
    parser.add_argument('--process', required=True, help='工作流 Code')
    parser.add_argument('--task', help='任务 Code（可选，指定单个任务时使用）')
    parser.add_argument('--dt', help='业务日期（可选），如 2026-03-17')
    parser.add_argument('--mode', choices=['full', 'single', 'post', 'pre'], 
                       default='full', help='执行模式：full=整个工作流，single=单个任务，post=当前 + 下游，pre=当前 + 上游')
    
    args = parser.parse_args()
    
    # 映射执行模式
    mode_map = {
        'full': 'TASK_POST',
        'single': 'TASK_ONLY',
        'post': 'TASK_POST',
        'pre': 'TASK_PRE'
    }
    
    # 创建客户端
    client = DolphinSchedulerClient(
        base_url="http://127.0.0.1:12345/dolphinscheduler",
        token=os.environ.get('DS_TOKEN', '')
    )
    
    # 构建自定义参数
    custom_params = {}
    if args.dt:
        custom_params['dt'] = args.dt
    
    # 启动工作流
    print(f"🚀 正在启动工作流...")
    print(f"   项目 Code: {args.project}")
    print(f"   工作流 Code: {args.process}")
    if args.task:
        print(f"   任务 Code: {args.task}")
    if args.dt:
        print(f"   业务日期：{args.dt}")
    print(f"   执行模式：{args.mode}")
    print()
    
    result = client.start_workflow(
        project_code=args.project,
        process_code=args.process,
        custom_params=custom_params if custom_params else None,
        task_code=args.task,
        task_depend_type=mode_map[args.mode]
    )
    
    # 输出结果
    if result['success']:
        print(f"✅ 启动成功！")
        print(f"   实例 ID: {result['instance_id']}")
    else:
        print(f"❌ 启动失败！")
        print(f"   错误码：{result['error_code']}")
        print(f"   错误信息：{result['error_message']}")
