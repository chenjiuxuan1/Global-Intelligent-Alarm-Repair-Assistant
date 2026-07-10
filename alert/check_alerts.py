#!/usr/bin/env python3
import os
import pymysql

# 从环境变量读取配置
DB_HOST = os.environ.get('DB_HOST', '172.20.0.235')
DB_PORT = int(os.environ.get('DB_PORT', '13306'))
DB_USER = os.environ.get('DB_USER', 'e_ds')
DB_PASSWORD = os.environ.get('DB_PASSWORD', '')
DB_NAME = os.environ.get('DB_NAME', 'wattrel')

if not DB_PASSWORD:
    print("错误: DB_PASSWORD环境变量未设置")
    print("请执行: export DB_PASSWORD='your_db_password'")
    exit(1)

conn = pymysql.connect(
    host=DB_HOST, 
    port=DB_PORT, 
    user=DB_USER, 
    password=DB_PASSWORD, 
    database=DB_NAME,
    charset='utf8mb4'
)
cursor = conn.cursor(pymysql.cursors.DictCursor)
cursor.execute('SELECT id, type, content, created_at FROM wattrel_quality_alert LIMIT 5')
rows = cursor.fetchall()

for r in rows:
    print(f"ID: {r['id']}, Type: {r['type']}, Created: {r['created_at']}")
    print(f"Content: {r['content'][:300]}...")
    print('-' * 80)

conn.close()
