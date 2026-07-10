# 智能告警修复流程 - 执行文档

## 📋 文档信息
- **版本**: v2.2
- **更新日期**: 2026-03-25
- **执行环境**: OpenClaw + DolphinScheduler
- **工作目录**: `/home/node/.openclaw/workspace`

---

## 🎯 执行前准备

### 1. 确认当前工作目录
```bash
cd /home/node/.openclaw/workspace
pwd  # 确认输出: /home/node/.openclaw/workspace
```

### 2. 设置环境变量（只需一次）
**🆕 自动加载**: 脚本会自动从 `~/.bashrc` 加载环境变量，无需手动 `source`

首次使用前，将以下配置写入 `~/.bashrc`:

```bash
# 编辑配置文件
nano ~/.bashrc

# 添加以下内容到文件末尾
# ========== 智能告警修复系统配置 ==========
# DolphinScheduler API Token
export DS_TOKEN='your_ds_token_here'

# 数据库连接配置
export DB_PASSWORD='your_db_password_here'
export DB_HOST='172.20.0.235'      # 可选，默认
export DB_PORT='13306'             # 可选，默认
export DB_USER='e_ds'              # 可选，默认
export DB_NAME='wattrel'           # 可选，默认
# ==========================================
```

**保存并退出**: `Ctrl+X` → `Y` → `Enter`

### 3. 验证环境变量已配置
```bash
# 查看 ~/.bashrc 中的配置
grep -A 10 "智能告警修复系统配置" ~/.bashrc
```

---

## 🚀 正式执行流程（8步）

### 🆕 执行方式（无需手动设置环境变量）

所有脚本已配置**自动加载环境变量**，直接执行即可：

```bash
cd /home/node/.openclaw/workspace
python3 repair_strict_7step.py
```

脚本会自动：
1. 检测环境变量是否已设置
2. 如未设置，自动从 `~/.bashrc` 加载
3. 显示加载成功的提示

---

### 【步骤1】扫描数据库告警

**操作命令**:
```bash
cd /home/node/.openclaw/workspace/alert
python3 alert_query_optimized.py
```

**自动加载提示**:
```
✅ 已从 /home/node/.bashrc 加载 6 个环境变量
```

**预期输出**:
```
======================================================================
🚀 数据质量告警查询
======================================================================
[*] 查询时间范围: 2026-03-23 00:00:00 至 2026-03-24 23:59:59
[!] 发现 X 条未处理告警
[1/X] 推送告警 ID:xxxx...
   ✅ 推送成功
...
```

**检查点**:
- [ ] 环境变量自动加载成功
- [ ] 告警已推送到钉钉群
- [ ] 记录告警ID列表

---

### 【步骤2】整理告警表，查找工作流位置

#### 2.1 解析告警内容，提取表名和dt

**告警内容解析规则**:
```
表名提取: 匹配 (dwd_\w+|dwb_\w+|ods_\w+|ads_\w+)
dt提取: 从执行语句中提取日期 'YYYY-MM-DD'
```

**示例**:
```
告警内容包含:
  "dwb_asset_period_info dwb_asset_period_info_penalty_amt(申请借款金额统计)不一致"
  "due_time >= '2026-03-22 00:00:00'"
  
提取结果:
  表名: dwb_asset_period_info
  dt: 2026-03-22
```

#### 2.2 对每个表调用search_table.py查找位置

**操作命令**（无需手动设置环境变量）:
```bash
cd /home/node/.openclaw/workspace/dolphinscheduler
python3 search_table.py dwb_asset_period_info
```

**预期输出**:
```
✅ 已从 /home/node/.bashrc 加载 6 个环境变量

====================================================================================================
🔍 在 [国内数仓-工作流] 中搜索: 'dwb_asset_period_info'
...
✅ 找到 X 个工作流包含 'dwb_asset_period_info':

[1] 📋 工作流: DWB
    工作流Code: 158514957297664
    状态: ONLINE
    ...
    [1] 任务: dwb_asset_period_info
        任务Code: 158514957297701
```

#### 2.3 记录表位置（每天一份，覆盖式写入）

**操作命令**:
```bash
cat > /home/node/.openclaw/workspace/auto_repair_records/$(date +%Y-%m-%d)_table_locations.json << 'EOF'
{
  "date": "$(date -Iseconds)",
  "tables": {
    "表名1": {
      "table": "表名1",
      "dt": "2026-03-22",
      "level": "P1",
      "workflow_name": "工作流名称",
      "workflow_code": "工作流Code",
      "task_name": "任务名称",
      "task_code": "任务Code"
    },
    "表名2": { ... }
  }
}
EOF
```

**检查点**:
- [ ] 环境变量自动加载成功
- [ ] 每个告警表都找到对应的工作流
- [ ] 工作流状态为ONLINE

---

### 【步骤3】指定dt重跑（带限制条件）

#### 3.1 制定执行计划

**输出执行计划表格**:
```
执行计划:
序号 | 表名 | dt | 工作流 | 任务Code | dt差值 | 状态
-----|------|----|--------|----------|--------|------
1    | xxx  | xxx| xxx    | xxx      | X天    | 待检查
2    | xxx  | xxx| xxx    | xxx      | X天    | 待检查
```

#### 3.2 限制条件检查

**检查1: dt范围验证（≤10天）**
```python
# 伪代码逻辑
dt_date = datetime.strptime(dt, '%Y-%m-%d')
today = datetime.now()
diff_days = (today - dt_date).days

if diff_days > 10:
    跳过该表，记录"dt超出范围"
elif diff_days < 0:
    跳过该表，记录"dt为未来日期"
else:
    继续执行
```

**检查2: 工作流空闲检查**（无需手动设置环境变量）
```bash
cd /home/node/.openclaw/workspace/dolphinscheduler
python3 check_running.py --check-only -f "工作流名称"
# 返回码: 0=空闲, 1=忙碌
```

**检查3: 同工作流串行控制**
```python
# 如果多个表属于同一个工作流，需要串行执行
# 使用锁或等待机制
```

**检查4: 全局并行限制（最多2个）**
```python
MAX_PARALLEL = 2
```

#### 3.3 执行重跑

**构建启动命令**（无需手动设置环境变量）:
```bash
cd /home/node/.openclaw/workspace
python3 repair_strict_7step.py

# 或在脚本内部自动执行curl:
# curl命令使用从~/.bashrc加载的DS_TOKEN
```

**检查点**:
- [ ] 环境变量自动加载成功
- [ ] 返回code=0，msg=success
- [ ] 记录instance_id

---

### 【步骤4】记录重跑次数 + 执行复验 + 再次检查告警

#### 4.1 记录重跑次数

**操作命令**:
```bash
cat >> /home/node/.openclaw/workspace/auto_repair_records/repair_counts.json << 'EOF'
{
  "表名": {
    "2026-03-24": 1  // 今日第1次
  }
}
EOF
```

#### 4.2 执行全部6个复验工作流

**复验工作流列表**:
| 序号 | 名称 | Code |
|-----|------|------|
| 1 | 每日复验全级别数据(W-1) | 158515019703296 |
| 2 | 每小时复验1级表数据(D-1) | 158515019593728 |
| 3 | 每小时复验2级表数据(D-1) | 158515019630592 |
| 4 | 两小时复验3级表数据(D-1) | 158515019667456 |
| 5 | 每周复验全级别数据(M-3) | 158515019741184 |
| 6 | 每月11日复验全级别数据(Y-2) | 158515019778048 |

**操作命令**（由脚本自动执行，无需手动设置）:
```bash
# 已在 repair_strict_7step.py 中自动执行
```

**等待复验完成**:
```bash
sleep 300  # 等待5分钟
```

#### 4.3 再次检查数据库告警

**操作命令**（无需手动设置环境变量）:
```bash
cd /home/node/.openclaw/workspace/alert
python3 alert_query_optimized.py
```

**对比修复前后**:
- 修复前的告警表是否还在列表中？
- 如果还在 → 标记为失败
- 如果不在 → 标记为成功

---

### 【步骤5】发送修复报告到钉钉

**报告模板**:
```
📊 智能告警修复报告

✅ 以下表通过按照指定dt重跑的方式修复成功:
  • 表名1 (dt=2026-03-22) - 实例ID: xxx
  • 表名2 (dt=2026-03-22) - 实例ID: xxx

❌ 以下表修复失败，需要人工处理:
  • 表名3 (dt=2026-03-22) - @陈江川
    
🔄 复验执行: 6/6 个工作流已启动
```

**发送方式**: 脚本自动发送

---

### 【步骤6】保存操作记录

**创建记录目录**:
```bash
mkdir -p /home/node/.openclaw/workspace/auto_repair_records/$(date +%Y-%m-%d)
```

**保存3类文件**:

1. **详细数据** (`detail_YYYYMMDD_HHMMSS.json`):
```json
{
  "timestamp": "2026-03-24T10:00:00",
  "tasks": [...],
  "fuyan_results": [...],
  "fixed": ["表名1", "表名2"],
  "failed": ["表名3"]
}
```

2. **执行命令** (`commands_YYYYMMDD_HHMMSS.sh`):
```bash
#!/bin/bash
# 执行的命令记录
...
```

3. **思考过程** (`thinking_YYYYMMDD_HHMMSS.md`):
```markdown
# 执行记录
## 时间: xxx
## 步骤1: ...
## 步骤2: ...
...
```

---

### 【步骤7】TV API报告发送 🆕

**操作命令**（脚本自动执行）:
```bash
# 使用脚本发送报告
python3 send_tv_report.py "报告内容"

# 或在Python中调用
python3 -c "
from send_tv_report import send_tv_report
report = '''📊 智能告警修复报告
...
'''
send_tv_report(report)
"
```

**TV API配置**:
- API地址: `https://tv-service-alert.kuainiu.chat/alert/v2/array`
- 机器人ID: `fbbcabb4-d187-4d9e-8e1e-ba7654a24d1c`
- HTTP方法: POST
- Content-Type: application/json

**请求体格式**:
```json
{
  "botId": "fbbcabb4-d187-4d9e-8e1e-ba7654a24d1c",
  "message": "报告内容",
  "mentions": []
}
```

**检查点**:
- [ ] HTTP返回202
- [ ] 钉钉群中收到TV消息

---

### 【步骤8】完成统计

**输出汇总信息**:
```
📊 执行完成统计
================
执行时间: 2026-03-25 10:00:00
修复任务: X成功, Y失败
复验工作流: 6/6 成功
记录文件: 3类已保存
TV报告: 已发送
================
```

---

## 📝 执行记录模板

每次执行后填写：

```
执行日期: 2026-03-25
执行人: OpenClaw
环境变量: 自动从~/.bashrc加载
告警数量: X条
修复成功: X个表
修复失败: X个表
复验状态: 6/6 成功
TV报告: 已发送
记录路径: auto_repair_records/2026-03-25/
```

---

## ⚠️ 常见问题处理

### 问题1: 环境变量未自动加载
**现象**: 脚本提示"已从~/.bashrc加载0个环境变量"
**解决**: 
```bash
# 检查~/.bashrc中是否有配置
grep "DS_TOKEN" ~/.bashrc

# 如果没有，重新添加
echo "export DS_TOKEN='your_token'" >> ~/.bashrc
```

### 问题2: 脚本无法读取环境变量
**现象**: "DS_TOKEN环境变量未设置"
**解决**:
```bash
# 检查~/.bashrc格式是否正确
cat ~/.bashrc | grep -A 5 "智能告警修复系统配置"

# 确保格式为: export VAR_NAME='value'
```

### 问题3: search_table.py找不到表
**解决**: 尝试使用表名关键字（如'account_repay'而非完整表名）

### 问题4: check_running.py返回忙碌
**解决**: 循环等待，最多等待5分钟

---

## 🔗 相关文件索引

| 文件 | 用途 |
|------|------|
| `auto_load_env.py` 🆕 | 自动加载环境变量模块 |
| `config.py` | 安全配置读取模块 |
| `alert/alert_query_optimized.py` | 告警扫描（自动加载）|
| `dolphinscheduler/search_table.py` | 表位置查找（自动加载）|
| `dolphinscheduler/check_running.py` | 工作流状态检查（自动加载）|
| `dolphinscheduler/run_fuyan_workflows.py` | 复验工作流（自动加载）|
| `send_tv_report.py` | TV API报告发送 |
| `repair_strict_7step.py` | 完整8步流程脚本（自动加载）|
| `EXECUTION_GUIDE.md` | 本文档 |
| `dolphinscheduler/workflows_export.csv` | 工作流列表参考 |

---

## ✅ 执行确认清单

执行完成后检查：
- [ ] 步骤1: 告警已推送钉钉
- [ ] 步骤2: 表位置已记录到JSON文件
- [ ] 步骤3: 重跑任务已启动（检查instance_id）
- [ ] 步骤4: 6个复验工作流已启动
- [ ] 步骤5: 报告已发送到钉钉群
- [ ] 步骤6: 3类记录文件已保存
- [ ] **步骤7**: **TV报告已发送** 🆕
- [ ] 步骤8: 完成统计输出

---

## 🔐 安全提示

1. **环境变量管理**: 
   - DS_TOKEN和DB_PASSWORD通过`~/.bashrc`设置
   - 脚本自动加载，代码中无硬编码
   - 建议设置文件权限: `chmod 600 ~/.bashrc`

2. **自动加载机制**:
   - 脚本启动时自动检测环境变量
   - 如未设置，自动从`~/.bashrc`读取
   - 已设置则跳过，避免重复加载

3. **日志检查**: 确保日志文件中不包含明文密码

---

## 📝 更新日志

### v2.2 (2026-03-25)
- 🆕 **新增**: 环境变量自动加载功能
- 新增 `auto_load_env.py` 模块
- 所有脚本自动从 `~/.bashrc` 加载环境变量
- 无需手动 `source ~/.bashrc`

### v2.1 (2026-03-25)
- 安全升级: 移除所有明文密码
- Token和密码改为环境变量读取

### v2.0 (2026-03-25)
- 新增步骤7: TV API报告发送
- 更新为完整8步流程

### v1.0 (2026-03-24)
- 初始版本，7步流程

---

**文档结束**
