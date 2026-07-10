# 智能告警修复系统 - 维护文档

**版本**: v4.1  
**更新日期**: 2026-03-26  
**维护人员**: 数据平台团队

---

## 📋 系统概述

本系统用于自动检测和修复 DolphinScheduler 数据仓库中的数据质量告警。

### 核心功能
1. **扫描数据质量告警** - 从 `wattrel_quality_result` 表查询异常数据
2. **自动定位工作流** - 在 DS 中搜索告警表对应的工作流和任务
3. **执行修复** - 启动特定任务的修复实例（TASK_ONLY 模式）
4. **执行复验** - 启动复验工作流验证修复结果

---

## 🏗️ 系统架构

### 目录结构

```
/workspace/
├── core/
│   └── repair_strict_7step.py      # 生产环境主脚本 ⭐
├── tests/
│   └── test_repair.py              # 测试版本
├── config/
│   ├── config.py                   # 配置管理
│   └── auto_load_env.py            # 环境变量加载
├── alert/
│   └── db_config.py                # 数据库配置
├── modules/
│   └── dolphinscheduler/           # DS 操作模块
├── docs/
│   └── ...                         # 其他文档
└── auto_repair_records/            # 执行记录
```

### 核心文件说明

| 文件 | 用途 | 修改频率 |
|------|------|----------|
| `core/repair_strict_7step.py` | 主修复脚本 | 低 |
| `tests/test_repair.py` | 测试脚本 | 中 |
| `config/config.py` | 配置管理 | 低 |
| `alert/db_config.py` | 数据库连接 | 低 |

---

## 🔄 执行流程详解

### 完整流程图

```
┌─────────────────────────────────────────────────────────────┐
│                    智能告警修复流程                           │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ 【步骤1】扫描告警                                              │
├─────────────────────────────────────────────────────────────┤
│ 数据源: wattrel_quality_result 表                            │
│ 查询条件:                                                    │
│   - result = 1        (异常数据)                             │
│   - is_repaired = 0   (未修复)                               │
│   - created_at >= NOW() - 3天                               │
│                                                              │
│ 表名识别逻辑:                                                │
│   优先选择 DWD/DWB/ADS 层的目标表:                           │
│   if dest_db in ['dwd', 'dwb', 'ads'] and dest_tbl:         │
│       table_name = dest_tbl                                 │
│   elif src_db in ['dwd', 'dwb', 'ads'] and src_tbl:         │
│       table_name = src_tbl                                  │
│   else:                                                     │
│       table_name = dest_tbl or src_tbl                      │
│                                                              │
│ 输出: 告警列表 [{id, table, dt, name, diff}]                 │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ 【步骤2】查找工作流位置                                        │
├─────────────────────────────────────────────────────────────┤
│ API: GET /projects/{code}/process-definition                │
│ 遍历所有工作流 → 获取任务详情 → 在 SQL 中搜索表名             │
│                                                              │
│ 匹配逻辑:                                                    │
│   task_params.sql 包含 table_name                           │
│                                                              │
│ 输出: 任务列表 [{                                            │
│   table, dt,                                                │
│   workflow_code, workflow_name,                             │
│   task_code, task_name                                      │
│ }]                                                          │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ 【步骤3】执行修复                                              │
├─────────────────────────────────────────────────────────────┤
│ 限制检查:                                                    │
│   1. dt 范围: 当前日期 ±10 天                               │
│   2. 同一表不重复修复（单次执行内）                          │
│   3. 必须找到对应工作流                                       │
│                                                              │
│ API: POST /projects/{code}/executors/start-process-instance │
│ 参数:                                                        │
│   - processDefinitionCode: 工作流 code                       │
│   - startNodeList: 任务 code                                │
│   - taskDependType: TASK_ONLY                               │
│   - startParams: {"global": [{"prop": "dt", "value": dt}]}   │
│   - environmentCode: 154818922491872                        │
│   - tenantCode: dolphinscheduler                            │
│                                                              │
│ 执行方式: 异步（启动后不等待完成）                            │
│ 输出: 修复结果 [{status, instance_id}]                       │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ 【步骤4】记录重跑次数 + 执行复验                               │
├─────────────────────────────────────────────────────────────┤
│ 4.1 记录重跑次数                                            │
│   文件: auto_repair_records/repair_counts.json               │
│   记录每个表每日修复次数                                      │
│                                                              │
│ 4.2 智能选择复验工作流                                       │
│   默认: 每日复验全级别数据(W-1)                             │
│   条件:                                                      │
│     - dwb_ 开头表 → +1级表复验(D-1)                         │
│     - 其他表 → +3级表复验(D-1)                              │
│                                                              │
│ API: POST /projects/158515019231232/executors/...           │
│ 复验工作流:                                                 │
│   - 每日复验全级别数据(W-1): 158515019703296               │
│   - 每小时复验1级表数据(D-1): 158515019593728              │
│   - 两小时复验3级表数据(D-1): 158515019667456              │
│                                                              │
│ 执行方式: 异步（启动后不等待完成）                            │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ 【步骤5】保存记录                                              │
├─────────────────────────────────────────────────────────────┤
│ 文件: auto_repair_records/YYYY-MM-DD/                       │
│   detail_YYYYMMDD_HHMMSS.json                               │
│                                                              │
│ 内容:                                                        │
│   - timestamp: 执行时间                                     │
│   - results: 修复结果列表                                   │
│   - fuyan_results: 复验结果列表                             │
│   - fixed_count: 成功数量                                   │
│   - failed_count: 失败数量                                  │
└─────────────────────────────────────────────────────────────┘
```

---

## ⚙️ 定时任务配置

### 任务列表

| 任务名称 | 执行频率 | 脚本路径 | 超时时间 |
|---------|---------|---------|---------|
| 智能告警修复 | 每日 06:40 | `core/repair_strict_7step.py` | 1800秒 (30分钟) |
| 异常调度检测 | 每半小时 | `core/auto_stop_abnormal_schedule.py` | 300秒 (5分钟) |

### 配置方法

```bash
# 使用 openclaw cron 命令配置

# 1. 添加智能告警修复任务
openclaw cron add \
  --name "智能告警修复-每日早上6:40" \
  --schedule "40 6 * * *" \
  --tz "Asia/Shanghai" \
  --command "python3 /home/node/.openclaw/workspace/core/repair_strict_7step.py" \
  --timeout 1800

# 2. 添加异常调度检测任务
openclaw cron add \
  --name "异常调度检测-每半小时" \
  --schedule "0,30 * * * *" \
  --tz "Asia/Shanghai" \
  --command "python3 /home/node/.openclaw/workspace/core/auto_stop_abnormal_schedule.py" \
  --timeout 300
```

### 当前任务ID

- 智能告警修复: `eb6275ba-12de-405a-982f-9065817816c9`
- 异常调度检测: `1d37efe1-d348-476c-bf41-1c6b6a78d549`

---

## 🔧 关键配置

### 环境变量

```bash
# DolphinScheduler
export DS_TOKEN='097ef3039a5d7af826c1cab60dedf96a'

# 数据库
export DB_PASSWORD='hAN0Hax1lop'
export DB_HOST='172.20.0.235'
export DB_PORT='13306'
export DB_USER='e_ds'
export DB_NAME='wattrel'
```

配置位置: `~/.bashrc`

### 项目代码

| 项目名称 | Code | 用途 |
|---------|------|------|
| 国内数仓-工作流 | 158514956085248 | 修复任务所在项目 |
| 国内数仓-质量校验 | 158515019231232 | 复验工作流所在项目 |

### 复验工作流

| 工作流名称 | Code | 级别 | 执行条件 |
|-----------|------|------|---------|
| 每日复验全级别数据(W-1) | 158515019703296 | all | 必跑 |
| 每小时复验1级表数据(D-1) | 158515019593728 | 1 | dwb_表 |
| 两小时复验3级表数据(D-1) | 158515019667456 | 3 | 其他表 |

---

## 📝 维护操作

### 日常检查

```bash
# 1. 检查定时任务状态
openclaw cron list

# 2. 查看最近执行记录
ls -lt auto_repair_records/$(date +%Y-%m-%d)/

# 3. 检查修复次数统计
cat auto_repair_records/repair_counts.json
```

### 手动执行

```bash
# 生产版本（真实执行）
cd /home/node/.openclaw/workspace
python3 core/repair_strict_7step.py

# 测试版本（快速验证）
python3 tests/test_repair.py
```

### 排查问题

```bash
# 1. 检查环境变量
echo $DS_TOKEN
echo $DB_PASSWORD

# 2. 测试数据库连接
python3 -c "from alert.db_config import get_db_connection; print('OK')"

# 3. 测试DS API
python3 -c "from core.repair_strict_7step import ds_api_get; print(ds_api_get('/projects'))"
```

---

## 🚨 常见问题

### Q1: 扫描不到告警
**检查**: 
- `wattrel_quality_result` 表是否有 `result=1` 的记录
- `is_repaired` 是否为 0
- `created_at` 是否在3天内

### Q2: 找不到工作流
**检查**:
- 表名是否正确（DWD/DWB层）
- SQL中是否包含该表名
- 工作流是否在项目 `158514956085248` 中

### Q3: 修复启动失败
**检查**:
- DS_TOKEN 是否有效
- 工作流是否处于上线状态
- 环境变量 `environmentCode` 是否正确

### Q4: 复验启动失败
**检查**:
- 复验项目 `158515019231232` 是否存在
- 复验工作流 code 是否正确

---

## 📊 监控指标

| 指标 | 正常范围 | 检查方式 |
|------|---------|---------|
| 每日告警数量 | 0-10个 | 查看执行日志 |
| 修复成功率 | >80% | 查看记录文件 |
| 执行时长 | <30分钟 | 查看定时任务状态 |
| 复验启动率 | 100% | 查看执行日志 |

---

## 🔄 版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| v4.1 | 2026-03-26 | 分离生产和测试版本，优化表名识别 |
| v4.0 | 2026-03-26 | 真正实现API调用（非模拟） |
| v3.0 | 2026-03-26 | 重构目录结构 |
| v2.8 | 2026-03-25 | 最终稳定版本（异步执行） |

---

## 📞 联系方式

- **GitHub**: https://github.com/jiangchuan788-debug/openclaw-dw-assistant
- **维护人员**: 数据平台团队
- **最后更新**: 2026-03-26

---

**本文档为系统维护的唯一参考，修改前请仔细阅读。**
