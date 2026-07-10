# config/ 目录

**用途**: 系统配置文件

## 文件说明

| 文件 | 用途 |
|------|------|
| `config.py` | 配置管理，安全读取Token等敏感信息 |
| `auto_load_env.py` | 自动从 ~/.bashrc 加载环境变量 |

## 环境变量要求

使用前确保已设置以下环境变量（在 ~/.bashrc 中）:

```bash
export DS_BASE_URL='http://your-ds-host:12345/dolphinscheduler'
export DS_TOKEN='your_ds_token'
export DS_PROJECT_CODE='your_main_project_code'
export DS_FUYAN_PROJECT_CODE='your_fuyan_project_code'
export DS_ENVIRONMENT_CODE='your_environment_code'
export DS_TENANT_CODE='your_tenant_code'
export DB_PASSWORD='your_db_password'
export DB_HOST='your_db_host'
export DB_PORT='13306'
export DB_USER='your_db_user'
export DB_NAME='your_db_name'
```

完整变量说明、复验工作流 JSON 格式和多国家迁移清单见 [docs/country-config-migration.md](/Users/jiangchuanchen/Desktop/PH-Intelligent-Alarm-Repair-Assistant/docs/country-config-migration.md)。
