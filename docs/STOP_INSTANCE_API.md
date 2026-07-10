# 停止 DolphinScheduler 工作流实例 API 命令

## 🔴 停止实例 API

### HTTP 请求

```bash
curl -X POST "http://172.20.0.235:12345/dolphinscheduler/projects/{projectCode}/executors/execute" \
  -H "Content-Type: application/json" \
  -H "token: {your_token}" \
  -d '{
    "processInstanceId": {instanceId},
    "executeType": "STOP"
  }'
```

### 参数说明

| 参数 | 值 | 说明 |
|------|-----|------|
| `projectCode` | `158514956085248` | 国内数仓-工作流项目Code |
| `token` | `097ef3039a5d7af826c1cab60dedf96a` | DS Token |
| `processInstanceId` | 如 `540592` | 要停止的实例ID |
| `executeType` | `STOP` | 执行类型：停止 |

### 实际执行示例

```bash
# 停止实例 540592
curl -X POST "http://172.20.0.235:12345/dolphinscheduler/projects/158514956085248/executors/execute" \
  -H "Content-Type: application/json" \
  -H "token: 097ef3039a5d7af826c1cab60dedf96a" \
  -d '{
    "processInstanceId": 540592,
    "executeType": "STOP"
  }'
```

### 响应示例

**成功:**
```json
{
  "code": 0,
  "msg": "success",
  "data": null
}
```

**失败:**
```json
{
  "code": 50014,
  "msg": "execute process instance error",
  "data": null
}
```

---

## 🔍 查询运行中实例 API

### 获取实例列表

```bash
curl -s "http://172.20.0.235:12345/dolphinscheduler/projects/158514956085248/process-instances?stateType=RUNNING_EXECUTION&pageNo=1&pageSize=100" \
  -H "token: 097ef3039a5d7af826c1cab60dedf96a"
```

### 获取实例详情（查看启动类型）

```bash
curl -s "http://172.20.0.235:12345/dolphinscheduler/projects/158514956085248/process-instances/{instanceId}" \
  -H "token: 097ef3039a5d7af826c1cab60dedf96a"
```

**关键字段:** `commandType`
- `SCHEDULER` - 定时调度启动
- `MANUAL` - 手动启动
- `START_PROCESS` - API启动
- `COMPLEMENT_DATA` - 补数据启动

---

## 📝 脚本中使用的停止逻辑

```python
def stop_instance(instance_id):
    """停止工作流实例"""
    url = f"http://172.20.0.235:12345/dolphinscheduler/projects/158514956085248/executors/execute"
    
    data = {
        'processInstanceId': instance_id,
        'executeType': 'STOP'
    }
    
    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode('utf-8'),
        headers={'Content-Type': 'application/json'},
        method='POST'
    )
    req.add_header('token', os.environ.get('DS_TOKEN'))
    
    with urllib.request.urlopen(req, timeout=10) as response:
        result = json.loads(response.read().decode('utf-8'))
        return result.get('code') == 0
```

---

## ⚠️ 常见问题

### 停止失败原因

| 错误信息 | 可能原因 |
|---------|----------|
| `execute process instance error` | 实例已完成/状态不可停止/API权限不足 |
| `process instance not found` | 实例ID错误或实例已删除 |
| `unauthorized` | Token无效或权限不足 |

### 解决建议

1. **确认实例状态** - 先查询实例详情确认是否还在运行
2. **检查Token** - 确保使用有效的DS Token
3. **手动停止** - 如果API停止失败，登录DS控制台手动停止

---

**文档日期**: 2026-03-26
