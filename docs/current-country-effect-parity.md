# Current Country Effect Parity

This file records how the unified platform preserves the current six-country n8n behavior.

## Shared Repair Flow

For TH, INE, PK, MX, and PH, the current n8n shape is:

```text
Webhook -> 执行环境检测 -> 智能修复
手动触发 -> 拉取最新代码 -> 环境检测 -> 智能修复1
```

The platform templates keep that shape. Only the remote repository path and runtime country selector change.

## Country Runtime Mapping

| Country | Current remote | Platform country | Current behavior kept |
| --- | --- | --- | --- |
| CN | `root@10.20.47.14:36000` | `APP_COUNTRY=cn` | DS URL, DB host/port/user/name, TV mentions, webhook `ds-quality-alert1`, manual pull path, extra PL alert nodes |
| TH | `root@192.168.20.236:36000` | `APP_COUNTRY=th` | webhook UUID, DB host/port/user, timeout/retry/progress overrides on manual repair |
| INE | `root@192.168.21.236:36000` | `APP_COUNTRY=ine` | webhook `ds-quality-alert`, TV mentions, fetch/reset pull style |
| PK | `root@10.20.84.176` | `APP_COUNTRY=pk` | webhook UUID, master checkout/pull style |
| MX | `root@172.20.220.165:36000` | `APP_COUNTRY=mx` | webhook UUID, DS environment code, tenant code, TV bot, TV mentions |
| PH | `root@10.20.10.12` | `APP_COUNTRY=ph` | webhook UUID, TV API URL, TV mentions, process-v2 DS start mode |

## Secrets Policy

The source n8n exports contain inline secrets. The platform repository does not commit those values. The generated n8n templates expect secrets to be available from the remote host's `.env.local` or deployment environment.

This keeps runtime behavior the same after deployment while preventing secrets from being baked into git history.

## Verification

Run these checks after changing workflow templates or profiles:

```bash
python3 tools/build_platform_n8n_workflows.py
python3 -m unittest tests.n8n_workflow_template_checks -v
python3 -m unittest discover -s tests -p '*_checks.py' -v
```
