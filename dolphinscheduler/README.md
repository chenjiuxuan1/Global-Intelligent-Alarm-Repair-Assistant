# DolphinScheduler 操作模块 (dolphinscheduler/)

**功能**: DolphinScheduler API 操作、工作流管理、异常检测

说明：
- `tools/` 目录下已经沉淀了当前维护中的 DS API 主链路脚本，例如 SQL 提取、`.sh` 使用清单、资源文件回填、DWD 脚本环境更新。
- 本目录下更多是历史脚本、特定场景脚本和运行诊断脚本，部分仍使用旧接口路由或固定环境配置。
- 如果你的目标是当前巴基斯坦数仓这套 DS 环境，优先使用 `tools/` 下的 DS API 脚本。

---

## 📋 文件说明

| 文件 | 功能 | 使用场景 |
|------|------|----------|
| `check_running.py` | 检查工作流运行状态 | 修复前检查 |
| `search_table.py` | 查找表对应的工作流和任务 | 定位告警表 |
| `run_fuyan_workflows.py` | 执行复验工作流 | 修复后验证 |
| `check_orphan_schedule.py` | 检测异常调度实例 | 定时检测 |
| `dolphinscheduler_api.py` | API调用封装 | 通用API |
| `config_loader.py` | 配置加载 | 辅助 |
| `analyze_startup.py` | 启动分析 | 辅助 |
| `schedules_export.csv` | 定时调度配置 | 异常检测数据源 |
| `README.md` | 本文件 | - |

---

## 🔧 核心功能

### 1. 检查工作流状态 (check_running.py)

```bash
# 检查是否有工作流在运行
python3 dolphinscheduler/check_running.py --check-only

# 输出: 🟢 有 X 个工作流正在运行 / ✅ 所有工作流已空闲
```

### 2. 查找表位置 (search_table.py)

```bash
# 查找表对应的工作流
python3 dolphinscheduler/search_table.py dwd_asset_account_repay

# 返回: 工作流名称、Code、任务Code等
```

### 3. 执行复验工作流 (run_fuyan_workflows.py)

```python
# 复验工作流列表（6个）
FUYAN_WORKFLOWS = [
    {'name': '每日复验全级别数据(W-1)', 'code': '158515019703296'},
    {'name': '每小时复验1级表数据(D-1)', 'code': '158515019593728'},
    {'name': '每小时复验2级表数据(D-1)', 'code': '158515019630592'},
    {'name': '两小时复验3级表数据(D-1)', 'code': '158515019667456'},
    {'name': '每周复验全级别数据(M-3)', 'code': '158515019741184'},
    {'name': '每月11日复验全级别数据(Y-2)', 'code': '158515019778048'}
]
```

### 4. 异常调度检测 (check_orphan_schedule.py)

**检测逻辑：**
1. 加载CSV中的调度配置（28个）
2. 查询运行中的工作流实例
3. 检查是否为异常：
   - 无定时配置但被调度启动
   - 调度已下线但仍被启动
4. 自动停止异常实例

---

## 📊 定时调度配置 (schedules_export.csv)

**包含**: 国内数仓-工作流项目的28个定时调度

| 状态 | 数量 |
|------|------|
| ONLINE | 9个 |
| OFFLINE | 19个 |

**更新方式**: 每天晚上手动更新

---

## 🔌 API配置

```python
DS_CONFIG = {
    'base_url': 'http://172.20.0.235:12345/dolphinscheduler',
    'token': os.environ.get('DS_TOKEN', ''),
    'project_code': '158514956085248'  # 国内数仓-工作流
}
```

---

## 📝 常用API端点

| 功能 | 端点 |
|------|------|
| 查询运行中实例 | `/projects/{code}/process-instances?stateType=RUNNING_EXECUTION` |
| 启动工作流 | `/projects/{code}/executors/start-process-instance` |
| 停止实例 | `/projects/{code}/executors/execute` (STOP) |
| 查询调度配置 | `/projects/{code}/schedules` |

---

**作者**: OpenClaw  
**最后更新**: 2026-03-26
