# Global Intelligent Alarm Repair Assistant

一套代码运行 CN、TH、INE、PK、MX、PH 六个国家的智能告警修复、复验、异常调度检测和 TV 报告能力。

旧的 6 个国家仓库先保留为回滚基线；本仓库从主路径开始平台化，后续再逐步收敛辅助 DS 工具脚本。

## 快速开始

```bash
cp config/country_profiles/ph.env.example .env.local
# 编辑 .env.local，填入 DS_TOKEN、DB_PASSWORD、workflow code、TV bot 等真实值

APP_COUNTRY=ph python3 core/repair_strict_7step.py
APP_COUNTRY=ph python3 core/send_tv_report.py --test
APP_COUNTRY=ph python3 core/auto_stop_abnormal_schedule.py
```

也可以不复制 profile，直接通过环境变量选择国家：

```bash
APP_COUNTRY=th python3 core/repair_strict_7step.py
COUNTRY=ine python3 core/send_tv_report.py --test
```

配置优先级：

1. 进程环境变量
2. `.env.local` 或 `APP_ENV_FILE` 指向的文件
3. `config/country_profiles/<country>.env.example`
4. `config/config.py` 中的安全默认值

## 国家 Profile

已内置 6 个 profile 示例：

```text
config/country_profiles/cn.env.example
config/country_profiles/th.env.example
config/country_profiles/ine.env.example
config/country_profiles/pk.env.example
config/country_profiles/mx.env.example
config/country_profiles/ph.env.example
```

profile 只保存非敏感默认值和占位符。真实的 token、密码、机器人 ID、workflow code 建议放在 `.env.local` 或发布环境变量中。

## 核心目录

```text
config/             运行时配置、国家 profile
core/               智能修复、异常调度检测、TV 报告
alert/              告警查询、告警桥接、发送逻辑
dolphinscheduler/   DS API 和复验工作流工具
tools/              DS SQL/资源/脚本维护工具
tests/              配置和主路径单元测试
docs/               迁移、执行、API 文档
```

## 主要命令

```bash
# 配置检查
python3 tests/country_config_checks.py

# profile 加载检查
python3 -m unittest tests.country_profile_loader_checks -v

# 智能告警修复
APP_COUNTRY=ph python3 core/repair_strict_7step.py

# TV 报告测试
APP_COUNTRY=ph python3 core/send_tv_report.py --test

# 异常调度检测
APP_COUNTRY=ph python3 core/auto_stop_abnormal_schedule.py
```

## 迁移策略

第一阶段目标是“不影响当前功能”：复制现有主路径实现，增加国家 profile 层，确保每个国家可以通过环境变量选择同一份代码运行。

第二阶段再处理辅助脚本中仍可能存在的国内 DS 默认值，例如 `dolphinscheduler/check_running.py`、`dolphinscheduler/search_table.py`、`dolphinscheduler/check_orphan_schedule.py`、`dolphinscheduler/analyze_startup.py`。

详细说明见 [docs/platform-migration.md](docs/platform-migration.md)。
