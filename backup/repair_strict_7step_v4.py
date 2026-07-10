#!/usr/bin/env python3
"""
智能告警修复 - 生产环境版本 (v4.3)
真实调用API，等待修复任务完成后执行复验
失败任务也会执行复验，并在TV报告中汇总提示人工处理

作者: OpenClaw
日期: 2026-03-26
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
DS_TOKEN = os.environ.get('DS_TOKEN', '72b6ff29a6484039a1ddd3f303973505')

# 复验工作流
FUYAN_WORKFLOWS = [
    {'name': '每日复验全级别数据(W-1)', 'code': '158515019703296', 'level': 'all'},
    {'name': '每小时复验1级表数据(D-1)', 'code': '158515019593728', 'level': '1'},
    {'name': '两小时复验3级表数据(D-1)', 'code': '158515019667456', 'level': '3'},
]


def log(msg):
    ts = datetime.now().strftime('%H:%M:%S')
    print(f"[{ts}] {msg}")


def ds_api_get(endpoint):
    """DS API GET 请求 (DS 3.3.0)"""
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
    """DS API POST 请求 - form-data格式 (DS 3.3.0)"""
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
    """步骤1: 扫描告警 - 从 wattrel_quality_result 表"""
    log("="*70)
    log("【步骤1】扫描告警 - 从 wattrel_quality_result 表")
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
                # 优先选择DWD/DWB层的目标表
                dest_db = row.get('dest_db') or ''
                dest_tbl = row.get('dest_tbl') or ''
                src_db = row.get('src_db') or ''
                src_tbl = row.get('src_tbl') or ''

                if dest_db.lower() in ['dwd', 'dwb', 'ads'] and dest_tbl:
                    table_name = dest_tbl
                elif src_db.lower() in ['dwd', 'dwb', 'ads'] and src_tbl:
                    table_name = src_tbl
                else:
                    table_name = dest_tbl or src_tbl

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
        log(f"✅ 从 wattrel_quality_result 表查询到 {len(alerts)} 条异常记录")

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
    log(f"\n📊 扫描结果: {len(unique_alerts)} 个（去重后）")
    for alert in unique_alerts:
        log(f"  ✅ {alert['table']} (dt={alert['dt']})")

    return unique_alerts


def search_table_in_workflows(table_name):
    """在所有工作流中搜索表名 (DS 3.3.0: workflow-definition)
    
    修复: 排除维护类任务（补充、删除、清理等）
    """
    success, data, msg = ds_api_get(f"/projects/{PROJECT_CODE}/workflow-definition?pageNo=1&pageSize=100")
    if not success:
        return None

    workflows = data.get('totalList', [])
    
    # 维护任务关键词（需要排除）
    maintenance_keywords = ['补充', '删除', '清理', '修复', '历史', '冗余', '临时', 'test', 'copy']

    for wf in workflows:
        process_code = wf.get('code')
        process_name = wf.get('name', '')

        # 获取工作流详情 (DS 3.3.0: workflow-definition)
        s, detail, m = ds_api_get(f"/projects/{PROJECT_CODE}/workflow-definition/{process_code}")
        if not s:
            continue

        tasks = detail.get('taskDefinitionList', [])
        for task in tasks:
            task_name = task.get('name', '')
            
            # 排除维护类任务
            is_maintenance = any(kw in task_name.lower() for kw in maintenance_keywords)
            if is_maintenance:
                continue
            
            # 优先匹配任务名（去掉dwd_前缀）
            table_short = table_name.lower().replace('dwd_', '').replace('dwb_', '').replace('ods_', '')
            if table_short in task_name.lower():
                return {
                    'workflow_code': process_code,
                    'workflow_name': process_name,
                    'task_code': task.get('code'),
                    'task_name': task.get('name')
                }
            
            # 其次匹配SQL内容
            task_params = task.get('taskParams', {})
            if isinstance(task_params, str):
                try:
                    task_params = json.loads(task_params)
                except:
                    task_params = {}

            sql = task_params.get('sql', '')
            if sql and table_name.lower() in sql.lower():
                return {
                    'workflow_code': process_code,
                    'workflow_name': process_name,
                    'task_code': task.get('code'),
                    'task_name': task.get('name')
                }

    return None


def step2_find_locations(alerts):
    """步骤2: 查找工作流位置"""
    log("\n" + "="*70)
    log("【步骤2】查找工作流位置")
    log("="*70)

    tasks = []
    for alert in alerts:
        table = alert['table']
        log(f"  🔍 查找: {table}")

        location = search_table_in_workflows(table)
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
            log(f"    ✅ 找到: {location['workflow_name']} -> {location['task_name']}")
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
            log(f"    ❌ 未找到")

        tasks.append(task)

    return tasks


def start_task_only(workflow_code, task_code, dt):
    """启动特定任务（TASK_ONLY模式） (DS 3.3.0)"""
    import time
    schedule_time = time.strftime('%Y-%m-%d %H:%M:%S')

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
    return success, result


def get_instance_status(instance_id):
    """查询工作流实例状态 (DS 3.3.0: workflow-instances)"""
    endpoint = f"/projects/{PROJECT_CODE}/workflow-instances/{instance_id}"
    success, data, msg = ds_api_get(endpoint)
    if success and data:
        state = data.get('state', 'UNKNOWN')
        return state, data
    return 'UNKNOWN', {}


def wait_for_instances_complete(results, timeout=1800, poll_interval=10):
    """等待所有修复实例完成

    Args:
        results: 修复任务结果列表
        timeout: 最大等待时间（秒），默认30分钟
        poll_interval: 轮询间隔（秒），默认10秒

    Returns:
        success_tasks: 成功的任务列表
        failed_tasks: 失败的任务列表
    """
    log("\n" + "="*70)
    log("【步骤3.5】等待修复任务完成")
    log("="*70)

    # 筛选出需要等待的任务（有instance_id的）
    pending_tasks = [r for r in results if r.get('instance_id') and r.get('status') == 'success']

    if not pending_tasks:
        log("  没有需要等待的任务")
        return [], []

    log(f"  共 {len(pending_tasks)} 个任务需要等待完成")
    log(f"  超时设置: {timeout}秒, 轮询间隔: {poll_interval}秒")

    start_time = time.time()
    completed_tasks = []
    failed_tasks = []

    while pending_tasks and (time.time() - start_time) < timeout:
        still_pending = []

        for task in pending_tasks:
            table = task['table']
            instance_id = task['instance_id']

            state, data = get_instance_status(instance_id)

            if state in ['SUCCESS', 'FINISHED']:
                log(f"  ✅ {table}: 完成 (状态: {state})")
                task['final_status'] = 'success'
                task['end_time'] = data.get('endTime')
                completed_tasks.append(task)
            elif state in ['FAILED', 'KILL', 'STOP']:
                log(f"  ❌ {table}: 失败 (状态: {state})")
                task['final_status'] = 'failed'
                task['error'] = f"实例状态: {state}"
                failed_tasks.append(task)
            else:
                # 仍在运行中
                log(f"  ⏳ {table}: 运行中 (状态: {state})")
                still_pending.append(task)

        pending_tasks = still_pending

        if pending_tasks:
            elapsed = int(time.time() - start_time)
            remaining = timeout - elapsed
            log(f"  ⏱️  已等待 {elapsed}秒, 还剩 {len(pending_tasks)} 个任务, 剩余时间 {remaining}秒")
            time.sleep(poll_interval)

    # 检查是否超时
    if pending_tasks:
        log(f"\n  ⚠️  等待超时！以下任务未完成:")
        for task in pending_tasks:
            log(f"    - {task['table']}: {task['instance_id']}")
            task['final_status'] = 'timeout'
            failed_tasks.append(task)

    log(f"\n  📊 等待结果统计:")
    log(f"    ✅ 成功: {len(completed_tasks)} 个")
    log(f"    ❌ 失败/超时: {len(failed_tasks)} 个")

    return completed_tasks, failed_tasks


def step3_execute_with_limits(tasks):
    """步骤3: 执行修复"""
    log("\n" + "="*70)
    log("【步骤3】执行修复")
    log("="*70)

    results = []
    processed_tables = set()

    for i, task in enumerate(tasks, 1):
        table = task['table']
        dt = task['dt']
        workflow_code = task.get('workflow_code')
        task_code = task.get('task_code')

        if not workflow_code or not task_code:
            log(f"[{i}/{len(tasks)}] ⏭️ {table} - 未找到工作流，跳过")
            task['status'] = 'skipped_no_workflow'
            results.append(task)
            continue

        if table in processed_tables:
            log(f"[{i}/{len(tasks)}] ⏭️ {table} - 已修复，跳过")
            task['status'] = 'skipped_duplicate'
            results.append(task)
            continue

        log(f"\n[{i}/{len(tasks)}] {table}")
        log(f"  dt: {dt}")
        log(f"  工作流: {task.get('workflow_name')}")

        # dt范围检查
        try:
            dt_date = datetime.strptime(dt, '%Y-%m-%d')
            if abs((dt_date - datetime.now()).days) > 10:
                log(f"  ❌ dt超出范围，跳过")
                task['status'] = 'skipped_dt_range'
                results.append(task)
                continue
        except:
            pass

        # 启动修复
        log(f"  🔄 启动修复任务...")
        success, result = start_task_only(workflow_code, task_code, dt)

        if success:
            instance_id = result.get('data', 'unknown')
            log(f"  ✅ 启动成功，实例ID: {instance_id}")
            task['status'] = 'success'
            task['instance_id'] = instance_id
            processed_tables.add(table)
        else:
            error_msg = result.get('msg', '未知错误')
            log(f"  ❌ 启动失败: {error_msg}")
            task['status'] = 'failed'
            task['error'] = error_msg

        results.append(task)
        time.sleep(2)

    return results


def start_fuyan_workflow(workflow_code):
    """启动复验工作流 (DS 3.3.0)"""
    import time
    schedule_time = time.strftime('%Y-%m-%d %H:%M:%S')
    
    data = {
        'workflowDefinitionCode': workflow_code,
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
    return success, result


def step4_record_and_fuyan(success_tasks, failed_tasks, alerts=None):
    """步骤4: 记录重跑次数 + 执行复验（无论修复是否成功都执行复验）"""
    log("\n" + "="*70)
    log("【步骤4】记录重跑次数 + 执行复验")
    log("="*70)

    # 4.1 记录重跑次数（只记录成功的）
    log("\n4.1 记录重跑次数...")
    record_file = f"{WORKSPACE}/auto_repair_records/repair_counts.json"
    counts = {}
    if os.path.exists(record_file):
        with open(record_file, 'r') as f:
            counts = json.load(f)

    today = datetime.now().strftime('%Y-%m-%d')
    for task in success_tasks:
        table = task['table']
        if table not in counts:
            counts[table] = {}
        counts[table][today] = counts[table].get(today, 0) + 1
        log(f"  📝 {table}: 今日第{counts[table][today]}次")

    with open(record_file, 'w') as f:
        json.dump(counts, f, indent=2)

    # 4.2 显示修复结果摘要
    log(f"\n4.2 修复结果摘要:")
    log(f"    ✅ 成功: {len(success_tasks)} 个")
    if failed_tasks:
        log(f"    ⚠️  失败/超时: {len(failed_tasks)} 个（需要人工处理）")
        for task in failed_tasks:
            log(f"      - {task['table']}: {task.get('error', task.get('final_status', '失败'))}")

    # 4.3 执行复验（无论修复是否成功都执行，以便验证当前数据状态）
    log(f"\n4.3 执行复验工作流...")
    log(f"    说明: 即使修复有失败，仍执行复验以验证当前数据状态")

    # 智能选择复验工作流
    selected_codes = {'158515019703296'}  # 每日全级别必跑
    for alert in alerts or []:
        table = alert.get('table', '')
        if table.startswith('dwb_'):
            selected_codes.add('158515019593728')  # 1级表
        else:
            selected_codes.add('158515019667456')  # 3级表

    fuyan_workflows = [wf for wf in FUYAN_WORKFLOWS if wf['code'] in selected_codes]
    fuyan_results = []

    log(f"\n4.4 启动复验工作流 (共{len(fuyan_workflows)}个)...")
    for i, fuyan in enumerate(fuyan_workflows, 1):
        log(f"  [{i}] {fuyan['name']}")
        success, result = start_fuyan_workflow(fuyan['code'])
        if success:
            instance_id = result.get('data', 'unknown')
            log(f"    ✅ 启动成功，实例ID: {instance_id}")
            fuyan_results.append({'name': fuyan['name'], 'id': instance_id, 'status': 'success'})
        else:
            error_msg = result.get('msg', '未知错误')
            log(f"    ❌ 启动失败: {error_msg}")
            fuyan_results.append({'name': fuyan['name'], 'status': 'failed', 'error': error_msg})

    return fuyan_results


def step5_save_report(results, success_tasks, failed_tasks, fuyan_results):
    """步骤5: 保存记录并生成TV报告"""
    log("\n" + "="*70)
    log("【步骤5】保存记录 + 生成TV报告")
    log("="*70)

    # 统计
    launched = [r for r in results if r.get('status') == 'success']
    skipped = [r for r in results if r.get('status') != 'success']

    log(f"  修复启动: {len(launched)} 个")
    log(f"  修复成功: {len(success_tasks)} 个")
    log(f"  修复失败: {len(failed_tasks)} 个")
    log(f"  跳过/未找到: {len(skipped)} 个")

    # 保存记录
    record_dir = f"{WORKSPACE}/auto_repair_records/{datetime.now().strftime('%Y-%m-%d')}"
    os.makedirs(record_dir, exist_ok=True)

    detail_file = f"{record_dir}/detail_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(detail_file, 'w') as f:
        json.dump({
            'timestamp': datetime.now().isoformat(),
            'results': results,
            'success_tasks': success_tasks,
            'failed_tasks': failed_tasks,
            'fuyan_results': fuyan_results,
            'fixed_count': len(success_tasks),
            'failed_count': len(failed_tasks)
        }, f, indent=2, ensure_ascii=False)

    log(f"  ✅ 记录已保存: {detail_file}")

    # 生成TV报告
    tv_report = generate_tv_report(success_tasks, failed_tasks, fuyan_results)

    return launched, success_tasks, failed_tasks, tv_report


def generate_tv_report(success_tasks, failed_tasks, fuyan_results):
    """生成TV格式的报告"""
    report_lines = []
    report_lines.append("\n" + "="*70)
    report_lines.append("📺 TV告警修复报告")
    report_lines.append("="*70)

    # 1. 执行摘要
    report_lines.append(f"\n【执行摘要】")
    report_lines.append(f"  执行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report_lines.append(f"  修复成功: {len(success_tasks)} 个")
    report_lines.append(f"  修复失败: {len(failed_tasks)} 个")
    report_lines.append(f"  复验工作流: {len(fuyan_results)} 个")

    # 2. 成功任务
    if success_tasks:
        report_lines.append(f"\n【✅ 修复成功任务】({len(success_tasks)}个)")
        for i, task in enumerate(success_tasks, 1):
            report_lines.append(f"  {i}. {task['table']}")
            report_lines.append(f"     实例ID: {task.get('instance_id', 'N/A')}")
            report_lines.append(f"     完成时间: {task.get('end_time', 'N/A')}")

    # 3. 失败任务（重点提示）
    if failed_tasks:
        report_lines.append(f"\n" + "⚠️"*20)
        report_lines.append(f"【❌ 修复失败任务 - 需要人工处理】({len(failed_tasks)}个)")
        report_lines.append("⚠️"*20)

        for i, task in enumerate(failed_tasks, 1):
            report_lines.append(f"\n  {i}. 📋 {task['table']}")
            report_lines.append(f"     🔴 状态: {task.get('final_status', 'FAILED')}")
            report_lines.append(f"     📅 日期: {task.get('dt', 'N/A')}")
            report_lines.append(f"     💬 错误: {task.get('error', '未知错误')}")
            if task.get('instance_id'):
                report_lines.append(f"     🔗 实例ID: {task['instance_id']}")
            report_lines.append(f"     👤 建议: 请登录DolphinScheduler检查任务详情并手动处理")

        report_lines.append(f"\n" + "⚠️"*20)
        report_lines.append("【处理建议】")
        report_lines.append("  1. 登录 DolphinScheduler 控制台")
        report_lines.append("  2. 查看上述失败任务的实例日志")
        report_lines.append("  3. 根据错误信息修复问题")
        report_lines.append("  4. 如需重新修复，可手动启动对应工作流")
        report_lines.append("  5. 或等待下次定时任务自动重试")
        report_lines.append("⚠️"*20)
    else:
        report_lines.append(f"\n【✅ 所有任务修复成功】")
        report_lines.append("  无需要人工处理的任务")

    # 4. 复验信息
    if fuyan_results:
        report_lines.append(f"\n【🔄 复验工作流】({len(fuyan_results)}个)")
        for fuyan in fuyan_results:
            status_icon = "✅" if fuyan.get('status') == 'success' else "❌"
            report_lines.append(f"  {status_icon} {fuyan['name']}")
            if fuyan.get('id'):
                report_lines.append(f"     实例ID: {fuyan['id']}")

    # 5. 结尾
    report_lines.append(f"\n" + "="*70)
    report_lines.append("报告生成完成")
    report_lines.append("="*70)

    # 输出到日志
    for line in report_lines:
        log(line)

    # 同时保存到文件
    report_file = f"{WORKSPACE}/auto_repair_records/{datetime.now().strftime('%Y-%m-%d')}/tv_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    with open(report_file, 'w', encoding='utf-8') as f:
        f.write('\n'.join(report_lines))
    log(f"\n📄 TV报告已保存: {report_file}")

    return '\n'.join(report_lines)


def main():
    """主函数"""
    log("="*70)
    log("🚀 智能告警修复流程（生产环境版本 v4.3）")
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

    # 步骤3: 执行修复（启动任务）
    results = step3_execute_with_limits(tasks)

    # 步骤3.5: 等待所有修复任务完成 (超时改为600秒=10分钟)
    success_tasks, failed_tasks = wait_for_instances_complete(results, timeout=600)

    # 步骤4: 记录+复验（无论修复是否成功都执行复验）
    fuyan_results = step4_record_and_fuyan(success_tasks, failed_tasks, alerts)

    # 步骤5: 保存记录 + 生成TV报告
    launched, success, failed, tv_report = step5_save_report(results, success_tasks, failed_tasks, fuyan_results)

    log("\n" + "="*70)
    log("✅ 流程完成")
    log("="*70)
    log(f"\n📊 最终统计:")
    log(f"  扫描告警: {len(alerts)} 个")
    log(f"  修复启动: {len(launched)} 个")
    log(f"  修复成功: {len(success)} 个")
    log(f"  修复失败: {len(failed)} 个")
    log(f"  执行复验: {len(fuyan_results)} 个")

    # 如果有失败任务，返回非零退出码（可选，用于外部监控）
    if failed_tasks:
        log(f"\n⚠️  存在 {len(failed_tasks)} 个失败任务，请查看TV报告进行人工处理")
        return 1
    return 0


if __name__ == '__main__':
    main()
