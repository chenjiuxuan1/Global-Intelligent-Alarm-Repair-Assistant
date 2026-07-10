# data/ 目录

**用途**: 数据文件

## 子目录

| 目录 | 用途 |
|------|------|
| `cron_jobs/` | 定时任务导出记录 |
| `auto_repair_records/` | 自动修复操作记录 |

## 文件说明

| 文件 | 用途 |
|------|------|
| `schedules_export.csv` | DolphinScheduler 调度配置导出（28个调度） |

## 说明

- 此目录下的文件为运行时数据
- `auto_repair_records/` 包含 `.log`, `.json`, `.sh` 等执行记录
- 不会被 Git 追踪（已在 .gitignore 中配置）
