# 印尼 DS 失败自动重跑

导入 `印尼-DS失败自动重跑.json` 后，DolphinScheduler 的 Http 告警实例调用：

```text
POST <你的 n8n 地址>/webhook/ine-ds-failed-auto-rerun
Content-Type: application/json
```

请求体建议至少包含 DS 失败实例信息：

```json
{
  "country": "ine",
  "project_code": "项目编码",
  "instance_id": "失败实例ID",
  "workflow_name": "工作流名称",
  "task_name": "失败任务名称"
}
```

如果告警实例能配置 token，可以额外传：

```json
{
  "ds_token": "DolphinScheduler token"
}
```

如果不传 `ds_token`，印尼机器会从 `/root/Global-Intelligent-Alarm-Repair-Assistant/.env.local` 读取 `DS_TOKEN`。

## 执行规则

- 只处理印尼，SSH 到 `root@192.168.21.236 -p 36000`。
- n8n 收到告警后后台启动脚本并立即返回，避免 DolphinScheduler Http 告警超时。
- 后台脚本调用 `/root/ds-scheduler-gateway/scripts/ds_scheduler_entry.py --country ine --action retry_instance`。
- `retry_instance` 在 DS 网关中对应 `START_FAILURE_TASK_PROCESS`，即从失败节点开始执行。
- 最多重跑 3 次。
- 每次重跑后等待 3 分钟，再用 `get_instance` 检查状态。
- 状态为 `SUCCESS` 时清理重跑计数。
- 状态仍为 `FAILURE`/`FAILED`/`STOP`/`KILL`/`KILLING` 时继续下一次。
- 3 次后仍未恢复，发送失败告警到截图中的 `tv-monitor`：
  `https://tv-service-alert.kuainiu.chat/alert`。

## 运行记录

重跑次数记录在：

```text
/root/Global-Intelligent-Alarm-Repair-Assistant/auto_repair_records/ine_ds_failed_retry_counts.json
```

单次后台执行日志在：

```text
/tmp/ine_ds_failed_auto_retry_<request_id>.log
```
