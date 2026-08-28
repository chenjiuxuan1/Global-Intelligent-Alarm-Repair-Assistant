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
| `pk_sadapay_dwd_push_monitor_alert.py` | 巴基斯坦 sadpay DWD 数据推送任务日志监控告警 | n8n 触发 |
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

```python
from alert.send_alert import send_alert

send_alert(
    task_name='数据校验任务',
    alert_time='2026-03-26 10:00:00',
    level='3',
    content='表数据不一致'
)
```

### 发送 sadpay 推送业务库监控告警（巴基斯坦）

```bash
# 干跑：只打印消息，不发送
python3 alert/pk_sadapay_dwd_push_monitor_alert.py --dry-run

# 正式发送（DS token 建议从环境变量 DS_API_TOKEN_PK / DS_TOKEN 提供）
# 默认发送到 PL 告警测试群（bot 4d0bcc9b-71bf-41c5-ba9f-89b7278f9214）
python3 alert/pk_sadapay_dwd_push_monitor_alert.py \
    --bot-id "4d0bcc9b-71bf-41c5-ba9f-89b7278f9214" \
    --mentions "gretchenhe@kn.group"
```

该告警扫描巴基斯坦 DolphinScheduler `sadapay_ftp数据接入` 项目下 `DWD` 工作流
最新一次调度实例中 `dwd_user_sadapay_user_info数据推送` 任务节点的运行日志，
解析 `读出记录总数 / 读写失败总数` 等 DataX 统计字段并按固定格式发送 TV 告警
（@何柳琴 = gretchenhe@kn.group）。DS 访问走 n8n ds-scheduler 网关 webhook
（`DS_SCHEDULER_WEBHOOK_URL`，country=pk）。默认发送到 PL 告警测试群
（bot `4d0bcc9b-71bf-41c5-ba9f-89b7278f9214`），可通过 `--bot-id` 覆盖。

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
