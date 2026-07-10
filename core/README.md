# core/ 目录

**用途**: 核心定时任务脚本

## 文件说明

| 文件 | 用途 | 执行频率 |
|------|------|----------|
| `auto_stop_abnormal_schedule.py` | 异常调度检测与停止 | 每半小时（00,30分） |
| `repair_strict_7step.py` | 智能告警修复（8步流程） | 每日 06:40 |
| `send_tv_report.py` | TV报告发送辅助模块 | 被调用 |

## 使用方法

```bash
# 手动执行异常调度检测
python3 core/auto_stop_abnormal_schedule.py

# 手动执行智能告警修复
python3 core/repair_strict_7step.py
```

## 执行流程

### auto_stop_abnormal_schedule.py（8步）
1. 加载调度配置
2. 获取运行中实例
3. 异常检测
4. 自动停止异常实例
5. TV通知（有条件）
6. 钉钉报告（已禁用）
7. 保存检测记录
8. 执行完成

### repair_strict_7step.py（8步）
1. 扫描告警
2. 查找工作流位置
3. 执行修复
4. 记录+复验
5. 钉钉报告（已禁用）
6. 保存操作记录
7. TV报告
8. 执行完成
