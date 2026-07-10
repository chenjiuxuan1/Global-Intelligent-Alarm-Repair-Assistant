"""
数据库配置模块 - 统一从共享配置读取数据库连接信息
"""

from config.config import DB_CONFIG, OPENCLAW_CONFIG, get_db_config as get_shared_db_config


def check_db_config():
    """检查数据库配置是否完整"""
    get_shared_db_config()
    return True


def get_db_config():
    """获取数据库配置（检查是否设置）"""
    return get_shared_db_config()


def get_db_connection():
    """获取数据库连接"""
    import pymysql
    from pymysql.cursors import DictCursor
    check_db_config()
    return pymysql.connect(cursorclass=DictCursor, **DB_CONFIG)
