# tools/ 目录

**用途**: 工具脚本

## 文件说明

| 文件 | 用途 |
|------|------|
| `extract_ds_sql.py` | 提取 DolphinScheduler 项目中的内嵌 SQL |
| `extract_ds_sh_usage.py` | 提取 DS 项目里 `.sh` 资源/脚本使用清单 |
| `fill_ds_workflow_resources.py` | 给指定工作流任务补 `resourceList` |
| `update_ds_dwd_shell_script.py` | 批量更新 DWD 任务脚本和环境 |
| `task_execution_checker.py` | 检查定时任务执行环境 |

## 使用方法

### 提取 SQL
```bash
# 提取指定项目的 SQL
python3 tools/extract_ds_sql.py --project-name <project_name> --output ./sql_export/<project_name>

# 示例
python3 tools/extract_ds_sql.py --project-name DW_DM --output ./sql_export/DW_DM
```

### 提取 .sh 使用清单
```bash
python3 tools/extract_ds_sh_usage.py DW_DM DW_DWD DW_RPT --output ./sql_export/all_projects_sh_usage.csv
```

### 回填任务资源文件
```bash
# 预览
python3 tools/fill_ds_workflow_resources.py --project-name '巴基斯坦-数仓工作流_new' --workflow-name 'DWD'

# 提交
python3 tools/fill_ds_workflow_resources.py --project-name '巴基斯坦-数仓工作流_new' --workflow-name 'DWD' --apply

# 覆盖已有 resourceList（适合 DWD_SEC / DWD_SEC（1D） 这类需要统一回刷资源路径的工作流）
python3 tools/fill_ds_workflow_resources.py \
  --project-name '巴基斯坦-数仓工作流_new' \
  --workflow-name 'DWD_SEC' \
  --resource-root 'deploy/resources/starrocks_workflow/dwd_sec' \
  --overwrite-existing --apply

# 保留原有相对路径，只把 resourceList 规范化成 DS 后端真正使用的 fullName
# 适合 pak_sr 这类 bash pak_sr/... 的工作流
python3 tools/fill_ds_workflow_resources.py \
  --project-name '巴基斯坦-贷后数仓_new' \
  --workflow-name 'DWD明细层构建(1)_import_20260402150146514' \
  --overwrite-existing \
  --reuse-existing-relative-paths \
  --resource-prefix 'dolphinscheduler/resource/dolphinscheduler/resources' \
  --apply
```

### 批量更新 DWD 任务脚本和环境
```bash
# 预览
python3 tools/update_ds_dwd_shell_script.py --project-name '巴基斯坦-数仓工作流_new' --workflow-name 'DWD'

# 提交
python3 tools/update_ds_dwd_shell_script.py --project-name '巴基斯坦-数仓工作流_new' --workflow-name 'DWD' --apply

# 忽略旧脚本文本是否完全一致，强制统一替换所有 SHELL 任务
python3 tools/update_ds_dwd_shell_script.py \
  --project-name '巴基斯坦-数仓工作流_new' \
  --workflow-name 'DWD_SEC' \
  --replace-all-shell-scripts \
  --apply
```

### 检查任务环境
```bash
# 检查所有任务
python3 tools/task_execution_checker.py --task all

# 检查指定任务
python3 tools/task_execution_checker.py --task abnormal
python3 tools/task_execution_checker.py --task repair
```

## 依赖环境

```bash
export DS_BASE_URL='http://127.0.0.1:12345/dolphinscheduler'
export DS_TOKEN='your_token'
```

常用 SSH 隧道命令：

```bash
ssh -N -f -L 12345:10.20.84.176:12345 -i /Users/jiangchuanchen/Desktop/id_rsa_pak jiangchuan@8.222.174.163 -p 36000 -o ServerAliveInterval=60 -o TCPKeepAlive=yes
```

检查隧道：

```bash
lsof -iTCP:12345 -sTCP:LISTEN -n -P
curl -s 'http://127.0.0.1:12345/dolphinscheduler/projects?pageNo=1&pageSize=1' -H "token: $DS_TOKEN"
```

说明：
- 上面 4 个 DS API 脚本已经按当前本地隧道地址适配。
- 默认建议先 dry-run，再带 `--apply` 执行真实更新。
- `fill_ds_workflow_resources.py` 有两种模式：
  - 默认模式：按 `resource_root/任务名/任务名.sql` 直接重建 `resourceList`
  - `--reuse-existing-relative-paths`：保留任务里已有的相对路径，只补成完整 DS fullName
  - `--resource-name-override`：所有命中的任务统一使用同一个完整资源文件
- `pak_sr` 这类任务有一个常见陷阱：
  - 前端搜索框里看到的是展示路径，例如 `dolphinscheduler/resources/pak_sr/...`
  - Worker 真正下载 OSS 时用的是资源中心 `fullName`
  - 实际需要写入的通常是 `dolphinscheduler/resource/...`
- 如果某个工作流已经被错误写成双前缀，例如
  `dolphinscheduler/resource/dolphinscheduler/resources/dolphinscheduler/resources/...`
  现在脚本会自动规范回单一正确前缀。

示例：`kbm_summary_reprint_12h` 全部任务共用同一个资源文件

```bash
python3 tools/fill_ds_workflow_resources.py \
  --project-name '巴基斯坦-数仓工作流_new' \
  --workflow-name 'kbm_summary_reprint_12h' \
  --resource-root 'deploy/resources/starrocks_workflow/kbm/kbm_summary' \
  --resource-name-override 'dolphinscheduler/resource/deploy/resources/starrocks_workflow/kbm/kbm_summary/kbm_summary.sql' \
  --overwrite-existing --apply
```
