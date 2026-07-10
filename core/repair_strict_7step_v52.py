#!/usr/bin/env python3
"""
智能告警修复 - v5.2 最终修复版
修复问题:
1. 步骤2执行完成的准确判断
2. 步骤4状态检查不显示详细状态的问题
3. API查询失败时的错误处理

作者: OpenClaw
日期: 2026-03-27
"""

import sys
sys.path.insert(0, '/home/node/.openclaw/workspace')
from config import auto_load_env

import json
import os
import urllib.request
import time
from datetime import datetime
from urllib.parse import urlencode

# 配置
WORKSPACE = '/home/node/.openclaw/workspace'
DS_BASE = 'http://172.20.0.235:12345/dolphinscheduler'
PROJECT_CODE = '158514956085248'
FUYAN_PROJECT_CODE = '158515019231232'
DS_TOKEN = '72b6ff29a6484039a1ddd3f303973505'

# 复验工作流
FUYAN_WORKFLOWS = [
    {'name': '每日复验全级别数据(W-1)', 'code': '158515019703296', 'level': 'all'},
    {'name': '两小时复验3级表数据(D-1)', 'code': '158515019667456', 'level': '3'},
]

# 维护任务关键词（排除）
MAINTENANCE_KEYWORDS = ['补充', '删除', '清理', '修复', '历史', '冗余', '临时', 'test', 'copy', '手插入']


def log(msg):
    ts = datetime.now().strftime('%H:%M:%S')
    print(f"[{ts}] {msg}", flush=True)


def ds_api_get(endpoint):
    """DS API GET请求"""
    url = f"{DS_BASE}{endpoint}"
    req = urllib.request.Request(url)
    req.add_header('token', DS_TOKEN)
    req.add_header('Accept', 'application/json, text/plain, */*')
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            result = json.loads(response.read().decode('utf-8'))
            return result.get('code') == 0, result.get('data', {}), result.get('msg', '')
    except Exception as e:
        return False, {}, str(e)


def ds_api_post(endpoint, data):
    """DS API POST请求"""
    url = f"{DS_BASE}{endpoint}"
    encoded_data = urlencode(data).encode('utf-8')
    req = urllib.request.Request(
        url, data=encoded_data,
        headers={'Content-Type': 'application/x-www-form-urlencoded'},
        method='POST'
    )
    req.add_header('token', DS_TOKEN)
    req.add_header('Accept', 'application/json, text/plain, */*')
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            result = json.loads(response.read().decode('utf-8'))
            return result.get('code') == 0, result, result.get('msg', '')
    except Exception as e:
        return False, {}, str(e)


def step1_scan_alerts():
    """步骤1: 扫描告警"""
    log("="*70)
    log("【步骤1】扫描告警")
    log("="*70)
    
    alerts = []
    try:
        from alert.db_config import get_db_connection
        conn = get_db_connection()
        with conn.cursor() as cursor:
            sql = """
                SELECT id, name, src_db, src_tbl, dest_db, dest_tbl, `begin`, diff
                FROM wattrel_quality_result
                WHERE result = 1 AND is_repaired = 0
                  AND created_at >= DATE_SUB(NOW(), INTERVAL 3 DAY)
                ORDER BY created_at DESC
            """
            cursor.execute(sql)
            rows = cursor.fetchall()
            
            for row in rows:
                dest_db = row.get('dest_db') or ''
                dest_tbl = row.get('dest_tbl') or ''
                
                if dest_db.lower() in ['dwd', 'dwb', 'ads'] and dest_tbl:
                    table_name = dest_tbl
                else:
                    table_name = row.get('src_tbl') or ''
                
                begin_time = row.get('begin')
                if begin_time:
                    dt = begin_time.strftime('%Y-%m-%d') if hasattr(begin_time, 'strftime') else str(begin_time).split()[0]
                else:
                    dt = datetime.now().strftime('%Y-%m-%d')
                
                alerts.append({
                    'id': row['id'],
                    'table': table_name,
                    'dt': dt,
                    'name': row.get('name', ''),
                    'diff': row.get('diff', '')
                })
        
        conn.close()
        log(f"✅ 查询到 {len(alerts)} 条异常记录")
        
    except Exception as e:
        log(f"❌ 查询数据库失败: {e}")
        return []
    
    # 去重
    table_alerts = {}
    for alert in alerts:
        table = alert['table']
        if table and table not in table_alerts:
            table_alerts[table] = alert
    
    unique_alerts = list(table_alerts.values())
    log(f"📊 去重后: {len(unique_alerts)} 个")
    for alert in unique_alerts[:5]:  # 只显示前5个
        log(f"  ✅ {alert['table']} (dt={alert['dt']})")
    if len(unique_alerts) > 5:
        log(f"  ... 还有 {len(unique_alerts)-5} 个")
    
    return unique_alerts


def step2_search_in_workflow(workflow_code, table_name):
    """在指定工作流中搜索表"""
    success, detail, msg = ds_api_get(f"/projects/{PROJECT_CODE}/workflow-definition/{workflow_code}")
    if not success:
        return None
    
    search_term = table_name.lower().replace('dwd_', '').replace('dwb_', '').replace('ods_', '')
    tasks = detail.get('taskDefinitionList', [])
    
    for task in tasks:
        task_name = task.get('name', '')
        task_name_lower = task_name.lower()
        
        # 排除维护任务
        is_maintenance = any(kw in task_name_lower for kw in MAINTENANCE_KEYWORDS)
        if is_maintenance:
            continue
        
        # 匹配任务名
        if search_term in task_name_lower:
            return {
                'workflow_code': workflow_code,
                'workflow_name': detail.get('processDefinition', {}).get('name', ''),
                'task_code': task.get('code'),
                'task_name': task_name
            }
        
        # 匹配SQL
        task_params = task.get('taskParams', '{}')
        if isinstance(task_params, str):
            try:
                task_params = json.loads(task_params)
            except:
                task_params = {}
        
        sql = task_params.get('sql', '').lower()
        if search_term in sql:
            return {
                'workflow_code': workflow_code,
                'workflow_name': detail.get('processDefinition', {}).get('name', ''),
                'task_code': task.get('code'),
                'task_name': task_name
            }
    
    return None


def step2_find_locations(alerts):
    """步骤2: 查找工作流位置 - 只搜索关键工作流"""
    log("\n" + "="*70)
    log("【步骤2】查找工作流位置")
    log("="*70)
    
    # 优先搜索这些工作流（提高效率）
    priority_workflows = [
        ('158514956979200', 'DWD'),
        ('158514957656064', 'DWD(D-1)'),
        ('158514958374912', '国内-数仓工作流(H-1)'),
        ('158514957337600', '国内-数仓工作流(D-1)'),
        ('158514957297664', 'DWB'),
        ('158514957701120', 'DWB(D-1)'),
        ('158514957779968', 'DWS'),
        ('158514958004224', 'DWS(D-1)'),
    ]
    
    tasks = []
    found_count = 0
    
    for alert in alerts:
        table = alert['table']
        log(f"🔍 {table}")
        
        location = None
        # 先在优先工作流中搜索
        for wf_code, wf_name in priority_workflows:
            result = step2_search_in_workflow(wf_code, table)
            if result:
                location = result
                break
        
        # 如果没找到，再搜索所有工作流
        if not location:
            success, data, msg = ds_api_get(f"/projects/{PROJECT_CODE}/workflow-definition?pageNo=1&pageSize=100")
            if success:
                for wf in data.get('totalList', []):
                    if (wf.get('code'), wf.get('name')) not in priority_workflows:
                        result = step2_search_in_workflow(wf.get('code'), table)
                        if result:
                            location = result
                            break
        
        if location:
            task = {
                'alert_id': alert['id'],
                'table': table,
                'dt': alert['dt'],
                'workflow_code': location['workflow_code'],
                'workflow_name': location['workflow_name'],
                'task_code': location['task_code'],
                'task_name': location['task_name']
            }
            log(f"  ✅ {location['workflow_name']} -> {location['task_name']}")
            found_count += 1
        else:
            task = {
                'alert_id': alert['id'],
                'table': table,
                'dt': alert['dt'],
                'workflow_code': '',
                'workflow_name': '未找到',
                'task_code': '',
                'task_name': ''
            }
            log(f"  ❌ 未找到")
        
        tasks.append(task)
    
    log(f"\n📊 找到 {found_count}/{len(alerts)} 个工作流")
    return tasks


def step3_start_repair(tasks):
    """步骤3: 启动修复任务"""
    log("\n" + "="*70)
    log("【步骤3】启动修复任务")
    log("="*70)
    
    results = []
    running_instances = []
    
    for i, task in enumerate(tasks, 1):
        table = task['table']
        dt = task['dt']
        workflow_code = task.get('workflow_code')
        task_code = task.get('task_code')
        
        if not workflow_code or not task_code:
            log(f"[{i}/{len(tasks)}] ⏭️ {table} - 未找到工作流")
            task['status'] = 'skipped_no_workflow'
            results.append(task)
            continue
        
        log(f"\n[{i}/{len(tasks)}] {table}")
        log(f"  工作流: {task['workflow_name']}")
        log(f"  任务: {task['task_name']}")
        
        # 启动修复
        schedule_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        data = {
            'workflowDefinitionCode': workflow_code,
            'startNodeList': task_code,
            'taskDependType': 'TASK_ONLY',
            'failureStrategy': 'CONTINUE',
            'warningType': 'NONE',
            'warningGroupId': 0,
            'execType': 'START_PROCESS',
            'startParams': f'[{{"prop":"dt","value":"{dt}"}}]',
            'environmentCode': 154818922491872,
            'tenantCode': 'dolphinscheduler',
            'dryRun': 0,
            'scheduleTime': schedule_time
        }
        
        success, result, msg = ds_api_post(f"/projects/{PROJECT_CODE}/executors/start-workflow-instance", data)
        
        if success:
            instance_data = result.get('data')
            # DS 3.3.0 返回的是数组格式 [id]，需要取第一个元素
            if isinstance(instance_data, list) and len(instance_data) > 0:
                instance_id = instance_data[0]
            else:
                instance_id = instance_data
            log(f"  ✅ 启动成功，实例ID: {instance_id}")
            task['status'] = 'success'
            task['instance_id'] = instance_id
            running_instances.append({
                'table': table,
                'instance_id': instance_id,
                'task': task
            })
        else:
            error_msg = result.get('msg', '未知错误')
            log(f"  ❌ 启动失败: {error_msg}")
            task['status'] = 'failed'
            task['error'] = error_msg
        
        results.append(task)
        time.sleep(1)
    
    log(f"\n📊 启动结果: {len(running_instances)} 个成功, {len(tasks) - len(running_instances)} 个跳过/失败")
    return results, running_instances


def step4_wait_and_check(running_instances, poll_interval=30, max_wait=1800):
    """步骤4: 动态监控任务状态（每30秒检查一次）- 修复版"""
    if not running_instances:
        log("\n  没有需要等待的任务")
        return [], []
    
    log("\n" + "="*70)
    log("【步骤4】动态监控任务状态")
    log("="*70)
    log(f"  共 {len(running_instances)} 个任务")
    log(f"  轮询间隔: {poll_interval}秒")
    log(f"  最大等待: {max_wait}秒 (30分钟)")
    
    start_time = time.time()
    completed_tasks = []
    failed_tasks = []
    pending = running_instances.copy()
    
    check_count = 0
    
    while pending and (time.time() - start_time) < max_wait:
        elapsed = int(time.time() - start_time)
        check_count += 1
        log(f"\n⏱️  第{check_count}次检查 (已等待 {elapsed}秒)")
        log("-" * 70)
        
        still_pending = []
        status_changed = False
        current_status = []
        
        for item in pending:
            table = item['table']
            instance_id = item['instance_id']
            
            # 查询实例状态
            success, data, msg = ds_api_get(f"/projects/{PROJECT_CODE}/workflow-instances/{instance_id}")
            
            if success and data:
                state = data.get('state', 'UNKNOWN')
                current_status.append((table, state))
                
                if state in ['SUCCESS', 'FINISHED']:
                    log(f"  ✅ {table}: 完成 ({state})")
                    item['task']['final_status'] = 'success'
                    item['task']['end_time'] = data.get('endTime')
                    completed_tasks.append(item['task'])
                    status_changed = True
                elif state in ['FAILED', 'KILL', 'STOP']:
                    log(f"  ❌ {table}: 失败 ({state})")
                    item['task']['final_status'] = 'failed'
                    item['task']['error'] = f"状态: {state}"
                    failed_tasks.append(item['task'])
                    status_changed = True
                else:
                    # 仍在运行中
                    log(f"  ⏳ {table}: {state}")
                    still_pending.append(item)
            else:
                # 查询失败
                log(f"  ⚠️  {table}: 查询失败 ({msg})")
                current_status.append((table, f"查询失败: {msg}"))
                still_pending.append(item)
        
        pending = still_pending
        
        # 显示汇总
        log("-" * 70)
        log(f"📊 当前状态: 成功={len(completed_tasks)}, 失败={len(failed_tasks)}, 运行中={len(pending)}")
        
        # 如果都完成了，立即退出
        if not pending:
            log(f"\n🎉 所有任务已完成！")
            break
        
        # 等待下一轮
        log(f"  还有 {len(pending)} 个任务运行中，{poll_interval}秒后再次检查...")
        time.sleep(poll_interval)
    
    # 处理超时任务
    if pending:
        log(f"\n⚠️  等待超时，以下任务未完成:")
        for item in pending:
            log(f"    - {item['table']}: {item['instance_id']}")
            item['task']['final_status'] = 'timeout'
            failed_tasks.append(item['task'])
    
    log(f"\n📊 最终结果:")
    log(f"  ✅ 成功: {len(completed_tasks)} 个")
    log(f"  ❌ 失败/超时: {len(failed_tasks)} 个")
    
    return completed_tasks, failed_tasks


def step5_execute_fuyan(completed_tasks, failed_tasks, alerts):
    """步骤5: 执行复验"""
    log("\n" + "="*70)
    log("【步骤5】执行复验")
    log("="*70)
    
    # 记录重跑次数
    log("\n5.1 记录重跑次数...")
    record_file = f"{WORKSPACE}/auto_repair_records/repair_counts.json"
    counts = {}
    if os.path.exists(record_file):
        with open(record_file, 'r') as f:
            counts = json.load(f)
    
    today = datetime.now().strftime('%Y-%m-%d')
    for task in completed_tasks:
        table = task['table']
        if table not in counts:
            counts[table] = {}
        counts[table][today] = counts[table].get(today, 0) + 1
        log(f"  📝 {table}: 今日第{counts[table][today]}次")
    
    with open(record_file, 'w') as f:
        json.dump(counts, f, indent=2)
    
    # 执行复验
    log(f"\n5.2 执行复验工作流...")
    fuyan_results = []
    
    for i, fuyan in enumerate(FUYAN_WORKFLOWS, 1):
        log(f"  [{i}] {fuyan['name']}")
        
        schedule_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        data = {
            'workflowDefinitionCode': fuyan['code'],
            'failureStrategy': 'CONTINUE',
            'warningType': 'NONE',
            'warningGroupId': 0,
            'execType': 'START_PROCESS',
            'environmentCode': 154818922491872,
            'tenantCode': 'dolphinscheduler',
            'dryRun': 0,
            'scheduleTime': schedule_time
        }
        
        success, result, msg = ds_api_post(f"/projects/{FUYAN_PROJECT_CODE}/executors/start-workflow-instance", data)
        if success:
            instance_id = result.get('data')
            if isinstance(instance_id, list) and len(instance_id) > 0:
                instance_id = instance_id[0]
            log(f"    ✅ 启动成功: {instance_id}")
            fuyan_results.append({'name': fuyan['name'], 'id': instance_id, 'status': 'success'})
        else:
            error_msg = result.get('msg', '未知错误')
            log(f"    ❌ 启动失败: {error_msg}")
            fuyan_results.append({'name': fuyan['name'], 'status': 'failed', 'error': error_msg})
    
    return fuyan_results


def step6_save_report(results, completed_tasks, failed_tasks, fuyan_results):
    """步骤6: 保存记录"""
    log("\n" + "="*70)
    log("【步骤6】保存记录")
    log("="*70)
    
    record_dir = f"{WORKSPACE}/auto_repair_records/{datetime.now().strftime('%Y-%m-%d')}"
    os.makedirs(record_dir, exist_ok=True)
    
    detail_file = f"{record_dir}/detail_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(detail_file, 'w') as f:
        json.dump({
            'timestamp': datetime.now().isoformat(),
            'results': results,
            'completed_tasks': completed_tasks,
            'failed_tasks': failed_tasks,
            'fuyan_results': fuyan_results,
        }, f, indent=2, ensure_ascii=False)
    
    log(f"  ✅ 记录已保存: {detail_file}")
    
    # TV报告
    log("\n" + "="*70)
    log("📺 TV告警修复报告")
    log("="*70)
    log(f"\n执行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log(f"修复成功: {len(completed_tasks)} 个")
    log(f"修复失败: {len(failed_tasks)} 个")
    
    if completed_tasks:
        log(f"\n✅ 成功任务:")
        for task in completed_tasks:
            log(f"  - {task['table']}")
    
    if failed_tasks:
        log(f"\n⚠️ 失败/超时任务:")
        for task in failed_tasks:
            log(f"  - {task['table']}: {task.get('error', '未知错误')}")
    
    log(f"\n🔄 复验工作流: {len(fuyan_results)} 个")
    for fuyan in fuyan_results:
        status = "✅" if fuyan.get('status') == 'success' else "❌"
        log(f"  {status} {fuyan['name']}")
    
    log("\n" + "="*70)


def main():
    """主函数"""
    log("="*70)
    log("🚀 智能告警修复流程（v5.2 最终修复版）")
    log("="*70)
    log(f"⏰ 执行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log("")
    
    # 步骤1: 扫描告警
    alerts = step1_scan_alerts()
    if not alerts:
        log("\n✅ 没有需要处理的告警，流程结束")
        return
    
    # 步骤2: 查找工作流
    tasks = step2_find_locations(alerts)
    
    # 步骤3: 启动修复
    results, running_instances = step3_start_repair(tasks)
    
    # 步骤4: 动态监控（每30秒检查一次）
    completed_tasks, failed_tasks = step4_wait_and_check(running_instances)
    
    # 步骤5: 执行复验
    fuyan_results = step5_execute_fuyan(completed_tasks, failed_tasks, alerts)
    
    # 步骤6: 保存记录
    step6_save_report(results, completed_tasks, failed_tasks, fuyan_results)
    
    log("\n" + "="*70)
    log("✅ 流程完成")
    log("="*70)


if __name__ == '__main__':
    main()
