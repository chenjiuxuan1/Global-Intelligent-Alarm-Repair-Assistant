# 告警处理模块 (alert/)

**功能**: 数据质量告警的查询、格式化和发送

---

## 📋 文件说明

| 文件 | 功能 | 使用场景 |
|------|------|----------|
| `alert_query_optimized.py` | 查询未处理告警 | 主流程调用 |
| `send_alert.py` | 格式化并发送告警 | 钉钉通知 |
| `check_alerts.py` | 告警状态检查 | 辅助脚本 |
| `alert_bridge.py` | 告警桥接处理 | 旧版兼容 |
| `quality_result_query.py` | 质量结果查询 | 详细查询 |
| `db_config.py` | 数据库配置 | 公共配置 |
| `README.md` | 本文件 | - |

---

## 🔧 核心功能

### 1. 告警查询 (alert_query_optimized.py)

```python
# 查询昨天到今天未恢复的告警
# 过滤: status=0 (未处理)
# 返回: 表名、告警内容、级别等
```

**告警表结构** (`wattrel_quality_alert`):
| 字段 | 说明 |
|------|------|
| `id` | 告警ID |
| `content` | 告警内容（含表名） |
| `status` | 0=未恢复, 1=已恢复 |
| `type` | 告警类型 |
| `created_at` | 创建时间 |

### 2. 告警发送 (send_alert.py)

```bash
# 手动发送告警
python3 send_alert.py \
    --task-name "任务名称" \
    --alert-time "2026-03-26 10:00:00" \
    --level "3" \
    --content "告警内容"
```

---

## 📝 使用示例

### 查询最新告警

```python
from alert.alert_query_optimized import query_alerts

alerts = query_alerts(
    start_date='2026-03-25',
    end_date='2026-03-26',
    status=0  # 未处理
)
```

### 发送告警到钉钉

```python
from alert.send_alert import send_alert

send_alert(
    task_name='数据校验任务',
    alert_time='2026-03-26 10:00:00',
    level='3',
    content='表数据不一致'
)
```

---

## 🔌 数据库连接

配置读取环境变量：
- `DB_HOST`: 172.20.0.235
- `DB_PORT`: 13306
- `DB_USER`: e_ds
- `DB_PASSWORD`: 从环境变量读取
- `DB_NAME`: wattrel

---

**作者**: OpenClaw  
**最后更新**: 2026-03-26
