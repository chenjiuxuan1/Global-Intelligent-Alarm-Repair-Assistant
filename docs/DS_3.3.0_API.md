# DolphinScheduler 3.3.0 API 文档

**版本**: 3.3.0  
**更新日期**: 2026-03-26  
**适用项目**: 国内数仓-工作流 (158514956085248)

---

## 🔑 认证方式

### Token认证

所有API请求需要在Header中携带Token：

```http
token: 72b6ff29a6484039a1ddd3f303973505
Accept: application/json, text/plain, */*
```

**注意**: DS 3.3.0 必须添加 `Accept` header 才能返回JSON格式。

---

## 📋 API路径变更说明

### 主要变更

| 功能 | 旧路径 (3.2.x) | 新路径 (3.3.0) |
|------|---------------|---------------|
| 工作流列表 | `process-definition` | `workflow-definition` ✅ |
| 工作流详情 | `process-definition/{code}` | `workflow-definition/{code}` ✅ |
| 实例列表 | `process-instances` | `workflow-instances` ✅ |
| 实例详情 | `process-instances/{id}` | `workflow-instances/{id}` ✅ |
| 启动工作流 | `executors/start-process-instance` | 保持不变 ✅ |
| 任务统计 | `analysis/task-state-count` | 保持不变 ✅ |

---

## 🚀 常用API详解

### 1. 工作流管理

#### 获取工作流列表
```http
GET /projects/{projectCode}/workflow-definition?pageNo=1&pageSize=100
```

**请求示例**:
```bash
curl -X GET "http://172.20.0.235:12345/dolphinscheduler/projects/158514956085248/workflow-definition?pageNo=1&pageSize=100" \
  -H "token: 72b6ff29a6484039a1ddd3f303973505" \
  -H "Accept: application/json, text/plain, */*"
```

**响应示例**:
```json
{
  "code": 0,
  "msg": "success",
  "data": {
    "total": 148,
    "totalList": [
      {
        "id": 14203,
        "code": 169063834846994,
        "name": "国内-数仓工作流(H-1)",
        "releaseState": "ONLINE"
      }
    ]
  }
}
```

#### 获取工作流详情
```http
GET /projects/{projectCode}/workflow-definition/{workflowCode}
```

**请求示例**:
```bash
curl -X GET "http://172.20.0.235:12345/dolphinscheduler/projects/158514956085248/workflow-definition/158514956979200" \
  -H "token: 72b6ff29a6484039a1ddd3f303973505" \
  -H "Accept: application/json, text/plain, */*"
```

**响应示例**:
```json
{
  "code": 0,
  "msg": "success",
  "data": {
    "processDefinition": {
      "code": 158514956979200,
      "name": "DWD",
      "releaseState": "ONLINE"
    },
    "taskDefinitionList": [
      {
        "code": 158514956981265,
        "name": "dwd_asset_account_repay",
        "taskType": "SQL"
      }
    ]
  }
}
```

---

### 2. 工作流实例管理

#### 获取实例列表
```http
GET /projects/{projectCode}/workflow-instances?pageNo=1&pageSize=100&stateType={state}
```

**状态类型**:
- `RUNNING_EXECUTION` - 运行中
- `SUCCESS` - 成功
- `FAILURE` - 失败
- `KILL` - 已终止

**请求示例**:
```bash
curl -X GET "http://172.20.0.235:12345/dolphinscheduler/projects/158514956085248/workflow-instances?stateType=RUNNING_EXECUTION&pageNo=1&pageSize=100" \
  -H "token: 72b6ff29a6484039a1ddd3f303973505" \
  -H "Accept: application/json, text/plain, */*"
```

#### 获取实例详情
```http
GET /projects/{projectCode}/workflow-instances/{instanceId}
```

**请求示例**:
```bash
curl -X GET "http://172.20.0.235:12345/dolphinscheduler/projects/158514956085248/workflow-instances/169054061052608" \
  -H "token: 72b6ff29a6484039a1ddd3f303973505" \
  -H "Accept: application/json, text/plain, */*"
```

**响应示例**:
```json
{
  "code": 0,
  "msg": "success",
  "data": {
    "id": 169054061052608,
    "state": "SUCCESS",
    "startTime": "2026-03-26T18:28:36",
    "endTime": "2026-03-26T18:30:15"
  }
}
```

---

### 3. 执行工作流

#### 启动工作流实例
```http
POST /projects/{projectCode}/executors/start-process-instance
Content-Type: application/x-www-form-urlencoded
```

**请求参数**:
| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| processDefinitionCode | long | 是 | 工作流Code |
| startNodeList | string | 否 | 启动节点Code（TASK_ONLY模式） |
| taskDependType | string | 否 | 任务依赖类型: TASK_ONLY/FRONTEND/END |
| failureStrategy | string | 否 | 失败策略: CONTINUE/END |
| warningType | string | 否 | 告警类型 |
| warningGroupId | int | 否 | 告警组ID |
| execType | string | 否 | 执行类型: START_PROCESS/COMPLEMENT_DATA |
| startParams | string | 否 | 启动参数（JSON格式） |
| environmentCode | long | 否 | 环境Code |
| tenantCode | string | 否 | 租户Code |
| dryRun | int | 否 | 是否试运行: 0/1 |

**请求示例**:
```bash
curl -X POST "http://172.20.0.235:12345/dolphinscheduler/projects/158514956085248/executors/start-process-instance" \
  -H "token: 72b6ff29a6484039a1ddd3f303973505" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "processDefinitionCode=158514956979200" \
  -d "startNodeList=158514956981265" \
  -d "taskDependType=TASK_ONLY" \
  -d "failureStrategy=CONTINUE" \
  -d "startParams={\"global\":[{\"prop\":\"dt\",\"value\":\"2026-03-25\"}]}" \
  -d "environmentCode=154818922491872" \
  -d "tenantCode=dolphinscheduler"
```

**响应示例**:
```json
{
  "code": 0,
  "msg": "success",
  "data": 169054061052608
}
```

---

### 4. 任务统计

#### 获取任务状态统计
```http
GET /projects/analysis/task-state-count?startDate={start}&endDate={end}
```

**请求示例**:
```bash
curl -X GET "http://172.20.0.235:12345/dolphinscheduler/projects/analysis/task-state-count?startDate=2026-03-26+00:00:00&endDate=2026-03-26+23:59:59" \
  -H "token: 72b6ff29a6484039a1ddd3f303973505" \
  -H "Accept: application/json, text/plain, */*"
```

**响应示例**:
```json
{
  "code": 0,
  "msg": "success",
  "data": {
    "totalCount": 31659,
    "taskInstanceStatusCounts": [
      {"state": "RUNNING_EXECUTION", "count": 6},
      {"state": "SUCCESS", "count": 30868},
      {"state": "FAILURE", "count": 774}
    ]
  }
}
```

---

### 5. 项目管理

#### 获取项目列表
```http
GET /projects?pageNo=1&pageSize=100
```

**请求示例**:
```bash
curl -X GET "http://172.20.0.235:12345/dolphinscheduler/projects?pageNo=1&pageSize=100" \
  -H "token: 72b6ff29a6484039a1ddd3f303973505" \
  -H "Accept: application/json, text/plain, */*"
```

#### 获取项目详情
```http
GET /projects/{projectCode}
```

---

## 📊 状态码说明

### 实例状态
| 状态 | 说明 |
|------|------|
| SUBMITTED_SUCCESS | 提交成功 |
| RUNNING_EXECUTION | 运行中 |
| SUCCESS | 成功完成 |
| FAILURE | 执行失败 |
| KILL | 已终止 |
| PAUSE | 已暂停 |
| NEED_FAULT_TOLERANCE | 需要容错处理 |
| DELAY_EXECUTION | 延迟执行 |
| FORCED_SUCCESS | 强制成功 |
| DISPATCH | 调度中 |

### API返回码
| Code | 说明 |
|------|------|
| 0 | 成功 |
| 10001 | 参数错误 |
| 10002 | 认证失败 |
| 10003 | 无权限 |
| 10004 | 资源不存在 |
| 10005 | 服务端错误 |

---

## 🔧 Python调用示例

```python
import urllib.request
import json
from urllib.parse import urlencode

DS_BASE = "http://172.20.0.235:12345/dolphinscheduler"
DS_TOKEN = "72b6ff29a6484039a1ddd3f303973505"
PROJECT_CODE = "158514956085248"

def ds_api_get(endpoint):
    """DS 3.3.0 GET请求"""
    url = f"{DS_BASE}{endpoint}"
    req = urllib.request.Request(url)
    req.add_header('token', DS_TOKEN)
    req.add_header('Accept', 'application/json, text/plain, */*')
    
    with urllib.request.urlopen(req, timeout=15) as response:
        return json.loads(response.read().decode('utf-8'))

def ds_api_post(endpoint, data):
    """DS 3.3.0 POST请求"""
    url = f"{DS_BASE}{endpoint}"
    encoded_data = urlencode(data).encode('utf-8')
    
    req = urllib.request.Request(
        url, data=encoded_data,
        headers={'Content-Type': 'application/x-www-form-urlencoded'},
        method='POST'
    )
    req.add_header('token', DS_TOKEN)
    req.add_header('Accept', 'application/json, text/plain, */*')
    
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode('utf-8'))

# 获取工作流列表
result = ds_api_get(f"/projects/{PROJECT_CODE}/workflow-definition?pageNo=1&pageSize=10")
print(f"工作流数: {result['data']['total']}")
```

---

## 📁 相关文件

| 文件 | 说明 |
|------|------|
| `core/repair_strict_7step.py` | 智能告警修复主脚本 |
| `core/auto_stop_abnormal_schedule.py` | 异常调度检测 |
| `dolphinscheduler/search_table.py` | 工作流搜索 |
| `backup/2026-03-26-ds-api-fix/` | 原始文件备份 |

---

## 📝 更新日志

### 2026-03-26
- 适配DolphinScheduler 3.3.0 API路径变更
- process-definition → workflow-definition
- process-instances → workflow-instances
- 添加必需的Accept header

---

**维护人员**: 数据平台团队  
**最后更新**: 2026-03-26
