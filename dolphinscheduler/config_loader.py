"""
配置加载器 - 安全读取DS Token
"""
import os

DS_CONFIG = {
    'base_url': 'http://172.20.0.235:12345/dolphinscheduler',
    'token': os.environ.get('DS_TOKEN', ''),
    'project_code': '158514956085248'
}

if not DS_CONFIG['token']:
    print("⚠️ 警告: DS_TOKEN环境变量未设置")
    print("请执行: export DS_TOKEN='your_token'")
