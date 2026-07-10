# 智能告警修复系统 - 维护手册

**文档版本**: v1.0  
**系统版本**: v4.1  
**更新日期**: 2026-03-26  
**编写者**: OpenClaw  
**维护团队**: 数据平台团队

---

## 📌 文档说明

**本文档是系统维护的唯一参考，包含：**
- 完整的执行流程逻辑
- 定时任务配置详情
- 数据库查询规则
- API调用方式
- 常见问题排查

**维护人员只需阅读本文档即可理解和维护系统。**

---

## 🎯 系统概述

### 核心功能

本系统自动完成以下5个步骤：

```
【步骤1】扫描告警  →  查询 wattrel_quality_result 表
       ↓
【步骤2】查找位置  →  在DS中搜索表对应的工作流
       ↓
【步骤3】执行修复  →  启动特定任务修复实例
       ↓
【步骤4】记录复验  →  记录次数 + 启动复验工作流
       ↓
【步骤5】保存记录  →  保存执行详情到JSON
```

### 系统特点

| 特性 | 说明 |
|------|------|
| **数据源** | `wattrel_quality_result` 表（质量校验结果） |
| **执行方式** | 异步（启动后不等待任务完成） |
| **表名识别** | 优先选择 DWD/DWB/ADS 层（而非ODS层） |
| **修复模式** | TASK_ONLY（仅修复特定任务，不触发下游） |
| **复验策略** | 智能选择（dwb→1级复验，其他→3级复验） |

---

## 🔄 执行流程详解

### 【步骤1】扫描告警

**数据源**: `wattrel_quality_result` 表

**查询SQL**:
```sql
SELECT 
    id, quality_id, name, type,
    src_db, src_tbl, dest_db, dest_tbl,
    src_value, dest_value, diff,
    `begin`, `end`, result, status,
    src_error, dest_error, is_repaired,
    created_at, updated_at
FROM wattrel_quality_result
WHERE result = 1              -- 异常数据
  AND is_repaired = 0         -- 未修复
  AND created_at >= DATE_SUB(NOW(), INTERVAL 3 DAY)
ORDER BY created_at DESC
```

**表名识别逻辑**（关键！）:
```python
# 优先选择 DWD/DWB/ADS 层的目标表（正确的方式）
if dest_db.lower() in ['dwd', 'dwb', 'ads'] and dest_tbl:
    table_name = dest_tbl        # 选目标表（DWD/DWB层）
elif src_db.lower() in ['dwd', 'dwb', 'ads'] and src_tbl:
    table_name = src_tbl         # 选源表（如果是DWD/DWB层）
else:
    table_name = dest_tbl or src_tbl  # 默认选目标表
```

**常见错误**（已修复）:
```python
# ❌ 错误：总是选ODS层的源表
table_name = src_tbl  # ods_xxx

# ✅ 正确：优先选DWD/DWB层的目标表  
table_name = dest_tbl  # dwd_xxx / dwb_xxx
```

**示例**:
- 告警: `dwd_asset_clean_clearing_trans` 数量不一致
- 数据: `src_tbl=ods_capital_clean_clearing_trans`, `dest_tbl=dwd_asset_clean_clearing_trans`
- 选择: ✅ `dwd_asset_clean_clearing_trans` (DWD层)

---

### 【步骤2】查找工作流位置

**API调用**:
```
GET /projects/158514956085248/process-definition?pageNo=1&pageSize=100
```

**搜索逻辑**:
1. 获取所有工作流列表
2. 对每个工作流获取任务详情
3. 在 `taskParams.sql` 中搜索表名
4. 返回第一个匹配的工作流和任务

**返回结果**:
```python
{
    'workflow_code': '158514956979200',     # 工作流Code
    'workflow_name': 'DWD_资产表修复',       # 工作流名称
    'task_code': '158514956981265',         # 任务Code
    'task_name': 'dwd_asset_account_repay'  # 任务名称
}
```

**项目Code**:
- 修复项目: `158514956085248`（国内数仓-工作流）
- 复验项目: `158515019231232`（国内数仓-质量校验）

---

### 【步骤3】执行修复

**限制检查**:
1. **dt范围**: 当前日期 ±10 天
2. **重复修复**: 单次执行内同一表不重复修复
3. **工作流存在**: 必须找到对应工作流

**API调用**:
```
POST /projects/158514956085248/executors/start-process-instance
Content-Type: application/x-www-form-urlencoded
```

**请求参数**:
```python
{
    'processDefinitionCode': workflow_code,     # 工作流Code
    'startNodeList': task_code,                 # 任务Code
    'taskDependType': 'TASK_ONLY',              # 仅执行该任务
    'failureStrategy': 'CONTINUE',              # 失败继续
    'warningType': 'NONE',                      # 不发送告警
    'warningGroupId': 0,
    'execType': 'START_PROCESS',
    'startParams': '{"global": [{"prop": "dt", "value": "2026-03-26"}]}',  # dt参数
    'environmentCode': 154818922491872,         # 环境Code
    'tenantCode': 'dolphinscheduler',           # 租户
    'dryRun': 0,
    'scheduleTime': ''
}
```

**重要说明**:
- 使用 **TASK_ONLY** 模式，仅执行特定任务，不触发下游依赖
- 传递 **dt参数**，指定修复的日期分区
- **异步执行**，启动后立即返回，不等待任务完成

---

### 【步骤4】记录重跑次数 + 执行复验

#### 4.1 记录重跑次数

**文件**: `auto_repair_records/repair_counts.json`

**格式**:
```json
{
  "dwd_asset_account_repay": {
    "2026-03-26": 3,    # 今日修复3次
    "2026-03-25": 1
  },
  "dwb_asset_period_info": {
    "2026-03-26": 2
  }
}
```

**用途**: 统计每个表每日修复次数（仅统计，不影响执行）

#### 4.2 执行复验工作流

**复验工作流列表**:

| 工作流名称 | Code | 级别 | 执行条件 |
|-----------|------|------|---------|
| 每日复验全级别数据(W-1) | 158515019703296 | all | **必跑** |
| 每小时复验1级表数据(D-1) | 158515019593728 | 1 | 告警表以 `dwb_` 开头 |
| 两小时复验3级表数据(D-1) | 158515019667456 | 3 | 其他表 |

**智能选择逻辑**:
```python
selected_codes = {'158515019703296'}  # 每日全级别必跑

for alert in alerts:
    table = alert['table']
    if table.startswith('dwb_'):
        selected_codes.add('158515019593728')  # 1级表复验
    else:
        selected_codes.add('158515019667456')  # 3级表复验
```

**API调用**:
```
POST /projects/158515019231232/executors/start-process-instance
```

**参数**: 与修复类似，但不指定 `startNodeList`（启动整个工作流）

**注意**: 复验也是**异步执行**，启动后不等待完成

---

### 【步骤5】保存记录

**文件路径**: `auto_repair_records/YYYY-MM-DD/detail_YYYYMMDD_HHMMSS.json`

**内容**:
```json
{
  "timestamp": "2026-03-26T18:28:36",
  "results": [
    {
      "table": "dwd_asset_account_repay",
      "dt": "2026-03-26",
      "workflow_code": "158514956979200",
      "task_code": "158514956981265",
      "status": "success",
      "instance_id": "169054061052608"
    }
  ],
  "fuyan_results": [
    {"name": "每日复验全级别数据(W-1)", "id": "169054064355008", "status": "success"}
  ],
  "fixed_count": 2,
  "failed_count": 0
}
```

---

## ⚙️ 定时任务配置

### 当前配置的任务

| 任务名称 | 执行频率 | 脚本路径 | 超时时间 | 任务ID |
|---------|---------|---------|---------|--------|
| 智能告警修复 | 每日 06:40 | `core/repair_strict_7step.py` | 1800秒 (30分钟) | `eb6275ba-12de-405a-982f-9065817816c9` |
| 异常调度检测 | 每半小时 | `core/auto_stop_abnormal_schedule.py` | 300秒 (5分钟) | `1d37efe1-d348-476c-bf41-1c6b6a78d549` |

### 配置命令

```bash
# 查看当前任务
openclaw cron list

# 添加智能告警修复任务（如需要重新配置）
openclaw cron add \
  --name "智能告警修复-每日早上6:40" \
  --schedule "40 6 * * *" \
  --tz "Asia/Shanghai" \
  --command "python3 /home/node/.openclaw/workspace/core/repair_strict_7step.py" \
  --timeout 1800

# 添加异常调度检测任务
openclaw cron add \
  --name "异常调度检测-每半小时" \
  --schedule "0,30 * * * *" \
  --tz "Asia/Shanghai" \
  --command "python3 /home/node/.openclaw/workspace/core/auto_stop_abnormal_schedule.py" \
  --timeout 300
```

### 手动执行

```bash
# 生产版本（真实执行）
cd /home/node/.openclaw/workspace
python3 core/repair_strict_7step.py

# 测试版本（快速验证）
python3 tests/test_repair.py
```

---

## 🔧 关键配置

### 环境变量

**必须配置**（在 `~/.bashrc` 中）：

```bash
# DolphinScheduler Token
export DS_TOKEN='097ef3039a5d7af826c1cab60dedf96a'

# 数据库配置
export DB_PASSWORD='hAN0Hax1lop'
export DB_HOST='172.20.0.235'
export DB_PORT='13306'
export DB_USER='e_ds'
export DB_NAME='wattrel'
```

**使配置生效**:
```bash
source ~/.bashrc
```

### 项目代码对照表

| 项目名称 | Code | 用途 |
|---------|------|------|
| 国内数仓-工作流 | `158514956085248` | 修复任务所在项目 |
| 国内数仓-质量校验 | `158515019231232` | 复验工作流所在项目 |
| okr_ads | `159737550740160` | 其他项目（可选） |

### 环境Code

```python
environmentCode = 154818922491872  # 默认环境
tenantCode = 'dolphinscheduler'     # 默认租户
```

---

## 📝 日常维护操作

### 每日检查清单

```bash
# 1. 检查定时任务状态
openclaw cron list

# 2. 查看最新执行记录
ls -lt auto_repair_records/$(date +%Y-%m-%d)/ | head -5

# 3. 查看今日修复统计
cat auto_repair_records/repair_counts.json | grep $(date +%Y-%m-%d)

# 4. 检查是否有失败
cat auto_repair_records/$(date +%Y-%m-%d)/detail_*.json | grep -c '"status": "failed"'
```

### 问题排查步骤

**问题1: 扫描不到告警**
```bash
# 检查数据库
mysql -h 172.20.0.235 -P 13306 -u e_ds -p -e "
SELECT COUNT(*) FROM wattrel.wattrel_quality_result 
WHERE result=1 AND is_repaired=0 AND created_at >= DATE_SUB(NOW(), INTERVAL 3 DAY);
"
```

**问题2: 找不到工作流**
```bash
# 检查表名是否正确（应该是DWD/DWB层）
# 手动搜索
curl "http://172.20.0.235:12345/dolphinscheduler/projects/158514956085248/process-definition" \
  -H "token: $DS_TOKEN" | python3 -m json.tool | grep -i "表名"
```

**问题3: 修复启动失败**
```bash
# 检查DS Token是否有效
curl "http://172.20.0.235:12345/dolphinscheduler/projects" \
  -H "token: $DS_TOKEN"

# 检查工作流是否上线
# 登录DS控制台查看工作流状态
```

**问题4: 复验启动失败**
```bash
# 检查复验项目是否存在
curl "http://172.20.0.235:12345/dolphinscheduler/projects/158515019231232" \
  -H "token: $DS_TOKEN"
```

---

## 🚨 常见问题 (FAQ)

### Q1: 为什么扫描到的表是ODS层而不是DWD层？

**原因**: 表名识别逻辑错误，选择了 `src_tbl`（ODS层）而不是 `dest_tbl`（DWD层）。

**解决**: 已修复。现在逻辑优先选择 `dest_db` 为 dwd/dwb/ads 的 `dest_tbl`。

### Q2: 为什么修复任务启动了但是不等完成就开始复验了？

**原因**: 设计如此。系统采用**异步执行**模式：
1. 启动修复任务后立即返回
2. 不等待修复任务完成
3. 立即启动复验工作流
4. 整个脚本快速完成

**优点**: 快速完成，适合定时任务。  
**缺点**: 不知道任务最终是否真正成功。

### Q3: 如何确认修复任务真的成功了？

**方法1**: 登录 DolphinScheduler 控制台查看实例状态。  
**方法2**: 等待复验工作流完成后查看复验结果。  
**方法3**: 修改代码添加等待逻辑（但会增加执行时间）。

### Q4: 可以修改为等待任务完成后再继续吗？

**可以**，但需要修改代码：
```python
# 启动任务后添加等待逻辑
success, result = start_task_only(workflow_code, task_code, dt)
if success:
    instance_id = result.get('data')
    # 添加等待
    wait_for_instance_complete(instance_id, timeout=600)
```

**注意**: 这样会导致脚本执行时间很长（每个任务等待5-10分钟）。

### Q5: 复验工作流是做什么的？

**作用**: 验证修复后的数据质量。  
**包含**: 6个复验工作流（每日、每小时、每2小时、每周、每月）。  
**逻辑**: 根据告警表类型智能选择（dwb→1级，其他→3级，都+每日全级别）。

### Q6: 为什么同一个表会修复多次？

**原因**: 
1. 告警在 `wattrel_quality_result` 表中 `is_repaired` 仍为 0
2. 定时任务每次都会扫描到该告警
3. 每次都会启动修复

**解决**: 修复成功后应更新 `is_repaired=1`（当前未实现，需手动或复验后更新）。

---

## 📊 监控指标

| 指标 | 正常范围 | 告警阈值 | 检查方式 |
|------|---------|---------|---------|
| 每日告警数量 | 0-10个 | >20个 | 执行日志 |
| 修复成功率 | >80% | <50% | 记录文件 |
| 执行时长 | <30分钟 | >45分钟 | 定时任务状态 |
| 复验启动率 | 100% | <100% | 执行日志 |
| 任务失败次数 | 0-1次 | >3次 | 记录文件 |

---

## 🔄 版本历史

| 版本 | 日期 | 主要变更 |
|------|------|---------|
| v4.1 | 2026-03-26 | 分离生产和测试版本，修复表名识别逻辑 |
| v4.0 | 2026-03-26 | 真正实现API调用（非模拟） |
| v3.0 | 2026-03-26 | 重构目录结构（core/, config/, tests/） |
| v2.8 | 2026-03-25 | 最终稳定版本（异步执行，示例数据） |
| v2.0 | 2026-03-24 | 初始版本，基本实现 |

---

## 📞 联系信息

- **GitHub 仓库**: https://github.com/jiangchuan788-debug/openclaw-dw-assistant
- **维护团队**: 数据平台团队
- **最后更新**: 2026-03-26

---

## ✅ 维护 checklist

**每日**:
- [ ] 检查定时任务是否正常执行
- [ ] 查看执行日志是否有错误
- [ ] 确认修复成功数量

**每周**:
- [ ] 检查 `repair_counts.json` 统计
- [ ] 清理过期的执行记录文件
- [ ] 验证复验工作流是否正常

**每月**:
- [ ] 检查数据库连接性能
- [ ] 更新文档（如有变更）
- [ ] 备份重要配置文件

---

**本文档为系统维护的唯一参考，如有疑问请联系数据平台团队。**
