# 系统记忆摘要 - 智能告警修复系统

**创建时间**: 2026-03-26  
**版本**: v2.11  
**用途**: 关键信息速查，便于快速恢复上下文

---

## 🎯 系统核心

### 两大定时任务

| 任务 | 频率 | 脚本 | 核心功能 |
|------|------|------|----------|
| **异常调度检测** | 每半小时 (00,30分) | `auto_stop_abnormal_schedule.py` | 检测并停止异常调度实例 |
| **智能告警修复** | 每日 06:40 | `repair_strict_7step.py` | 修复数据质量告警 |

---

## 🔧 关键配置

### 环境变量（必须）
```bash
export DS_TOKEN='097ef3039a5d7af826c1cab60dedf96a'
export DB_PASSWORD='hAN0Hax1lop'
export DB_HOST='172.20.0.235'
export DB_PORT='13306'
export DB_USER='e_ds'
export DB_NAME='wattrel'
```

### 重要文件路径
```
# 配置
~/.bashrc                              # 环境变量
/workspace/config.py                   # 配置管理
/workspace/auto_load_env.py            # 自动加载

# 数据
/workspace/dolphinscheduler/schedules_export.csv  # 28个调度配置

# 记录
/workspace/auto_repair_records/        # 操作记录
/workspace/memory/                     # 每日记忆
```

---

## 📊 项目信息

### DolphinScheduler 项目
| 项目名称 | Code |
|---------|------|
| 国内数仓-工作流 | 158514956085248 |
| 国内数仓-质量校验 | 158515019231232 |
| okr_ads | 159737550740160 |

### 复验工作流（6个）
```python
# 每日必跑
158515019703296  # 每日复验全级别数据(W-1)

# 智能选择
158515019593728  # 每小时复验1级表数据(D-1) - dwb_表
158515019667456  # 两小时复验3级表数据(D-1) - 其他表
```

---

## 🚨 关键规则

### 异常调度检测
- **检测对象**: 无定时配置但被调度启动、调度已下线但仍被启动
- **通知策略**: 只有异常时才TV通知，正常静默
- **执行边界**: 每次执行独立，无历史记录

### 智能告警修复
- **复验选择**: dwb_→1级复验，其他→3级复验
- **每日限制**: 单表最多修复3次（代码中已限制）
- **通知策略**: TV始终发送，钉钉已禁用

---

## 💡 常用命令

```bash
# 手动执行
python3 auto_stop_abnormal_schedule.py
python3 repair_strict_7step.py

# 检查配置
python3 task_execution_checker.py --task all

# 提取 SQL
python3 extract_ds_sql.py 159737550740160 --name okr_ads

# 查看定时任务状态
openclaw cron list
```

---

## 🔑 关键决策记录

### 2026-03-26 重要变更
1. **定时任务投递**: 钉钉已禁用，仅TV通知
2. **执行边界**: 每次执行独立，不跨周期记录
3. **异常处理**: 早上出现→修复→中午再出现→再次修复
4. **模板文件**: 新增6个模板文件方便复现

### 技术选型
- **SQL提取**: 通过DS API直接拉取，不通过UI
- **复验策略**: 智能选择（dwb→1级，其他→3级）
- **记录保存**: 本地JSON/LOG/SH三种格式

---

## 📞 联系信息

- **GitHub**: https://github.com/jiangchuan788-debug/openclaw-dw-assistant
- **用户**: 江川
- **用途**: 数据仓库监控和告警自动修复

---

**此文件为关键记忆摘要，应随系统更新而更新。**
