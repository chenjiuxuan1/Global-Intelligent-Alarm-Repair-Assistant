# n8n Workflow Templates

This directory contains sanitized n8n workflow templates generated from the six current country workflow exports.

Generated templates:

- `templates/智能告警修复-中国-统一平台模板.json`
- `templates/智能告警修复-泰国-统一平台模板.json`
- `templates/智能告警修复-印尼-统一平台模板.json`
- `templates/智能告警修复-巴基斯坦-统一平台模板.json`
- `templates/智能告警修复-墨西哥-统一平台模板.json`
- `templates/智能告警修复-菲律宾-统一平台模板.json`

The templates intentionally preserve:

- Existing webhook paths and webhook node topology.
- Existing manual trigger flow.
- Existing SSH credential references.
- Existing country-specific remote hosts.
- Existing check-before-repair behavior.
- China's extra PL/financial alert webhook nodes.

The templates intentionally change:

- Old country repository paths such as `/root/PH-Intelligent-Alarm-Repair-Assistant` to `/root/Global-Intelligent-Alarm-Repair-Assistant`.
- Runtime execution to include `APP_COUNTRY=<country>` and `APP_WORKSPACE=/root/Global-Intelligent-Alarm-Repair-Assistant`.
- Inline DS/DB/SR secrets to environment placeholders.

Before importing a template into n8n, deploy the platform repository on the remote host and prepare `.env.local` there with the real values for:

- `DS_TOKEN`
- `DB_PASSWORD`
- `OPENCLAW_HOOK_TOKEN`, if used
- `TV_BOT_ID`, when not already in the country profile
- `FUYAN_WORKFLOWS_JSON`
- country-specific workflow/project codes
- for China's PL alert nodes: `SR_PASSWORD` and `SR_BACKUP_PASSWORD`

Regenerate templates after editing the source exports:

```bash
python3 tools/build_platform_n8n_workflows.py
```
