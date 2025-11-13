import os
import yaml
import json
import pymysql
from typing import Optional, Dict, Any
from datetime import datetime

def load_config(path: Optional[str]) -> dict:
    """
    读取 YAML 配置文件。
    - path 为 None 或空时返回空字典
    - 正常返回解析后的 dict（若文件为空对象则返回 {}）
    - 异常交由调用方处理
    """
    if not path:
        return {}
    with open(path, 'r', encoding='utf-8') as f:
        obj = yaml.safe_load(f)
        return obj or {}


def save_config(path: str, config: dict):
    """
    保存配置到 YAML 文件。
    """
    with open(path, 'w', encoding='utf-8') as f:
        yaml.dump(config, f, allow_unicode=True)

def get_db_connection():
    """
    获取数据库连接，只使用配置文件中的数据库配置
    """
    try:
        config = load_config('/config/config.yaml')
        return pymysql.connect(
            host=config.get('db_host', 'localhost'),
            port=config.get('db_port', 3306),
            user=config.get('db_user', 'root'),
            password=config.get('db_password', ''),
            database=config.get('db_name', 'pt_crawler'),
            charset='utf8mb4',
            cursorclass=pymysql.cursors.DictCursor
        )
    except Exception as e:
        print(f"从配置文件获取数据库配置失败: {e}")
        raise

def get_system_setting(key: str, default: Any = None) -> Any:
    """
    从系统设置中获取单个配置值（不包括数据库配置）
    """
    # 排除数据库配置，这些只从config.yaml读取
    if key.startswith('db_'):
        config = load_config('/config/config.yaml')
        return config.get(key, default)
    
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT setting_value, setting_type FROM system_settings WHERE setting_key = %s",
                    (key,)
                )
                result = cursor.fetchone()
                if result:
                    return parse_setting_value(result['setting_value'], result['setting_type'])
                return default
    except Exception as e:
        print(f"获取系统设置 {key} 失败: {e}")
        return default

def set_system_setting(key: str, value: Any, setting_type: str = 'string', description: str = None):
    """
    设置系统配置值（不包括数据库配置）
    """
    # 不允许通过系统设置修改数据库配置
    if key.startswith('db_'):
        print(f"不允许通过系统设置修改数据库配置: {key}")
        return False
    
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                # 转换值为字符串存储
                str_value = convert_setting_value(value, setting_type)
                
                cursor.execute(
                    """INSERT INTO system_settings (setting_key, setting_value, setting_type, description)
                       VALUES (%s, %s, %s, %s)
                       ON DUPLICATE KEY UPDATE 
                       setting_value = VALUES(setting_value),
                       setting_type = VALUES(setting_type),
                       description = VALUES(description)""",
                    (key, str_value, setting_type, description)
                )
                conn.commit()
                return True
    except Exception as e:
        print(f"设置系统设置 {key} 失败: {e}")
        return False

def get_system_settings_by_prefix(prefix: str) -> Dict[str, Any]:
    """
    获取指定前缀的所有系统设置（不包括数据库配置）
    """
    # 不允许查询数据库配置
    if prefix.startswith('db_'):
        return {}
    
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT setting_key, setting_value, setting_type FROM system_settings WHERE setting_key LIKE %s",
                    (f"{prefix}%",)
                )
                results = cursor.fetchall()
                settings = {}
                for row in results:
                    key = row['setting_key']
                    value = parse_setting_value(row['setting_value'], row['setting_type'])
                    settings[key] = value
                return settings
    except Exception as e:
        print(f"获取系统设置前缀 {prefix} 失败: {e}")
        return {}

def get_all_system_settings() -> Dict[str, Dict[str, Any]]:
    """
    获取所有系统设置（不包括数据库配置），按分类分组
    """
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT setting_key, setting_value, setting_type, description FROM system_settings ORDER BY setting_key"
                )
                results = cursor.fetchall()
                
                settings = {
                    'crawler': {},
                    'sites': {},
                    'other': {}
                }
                
                for row in results:
                    key = row['setting_key']
                    value = parse_setting_value(row['setting_value'], row['setting_type'])
                    setting_info = {
                        'value': value,
                        'type': row['setting_type'],
                        'description': row['description']
                    }
                    
                    # 分类设置（排除数据库配置）
                    if key in ['out_dir', 'torrent_download_dir', 'delay', 'test_mode', 'test_limit', 'allow_v2']:
                        settings['crawler'][key] = setting_info
                    elif key == 'sites':
                        settings['sites'][key] = setting_info
                    else:
                        settings['other'][key] = setting_info
                
                return settings
    except Exception as e:
        print(f"获取所有系统设置失败: {e}")
        return {}

def get_database_config() -> Dict[str, Any]:
    """
    从配置文件获取数据库配置
    """
    config = load_config('/config/config.yaml')
    return {
        'host': config.get('db_host', 'localhost'),
        'port': config.get('db_port', 3306),
        'user': config.get('db_user', 'root'),
        'password': config.get('db_password', ''),
        'database': config.get('db_name', 'pt_crawler'),
    }

def parse_setting_value(value: str, setting_type: str) -> Any:
    """
    根据设置类型解析字符串值为对应类型
    """
    if value is None:
        return None
    
    try:
        if setting_type == 'integer':
            return int(value)
        elif setting_type == 'float':
            return float(value)
        elif setting_type == 'boolean':
            return value.lower() == 'true'
        elif setting_type == 'json':
            return json.loads(value) if value else {}
        elif setting_type == 'string':
            return value
        else:
            return value
    except (ValueError, json.JSONDecodeError):
        return value

def convert_setting_value(value: Any, setting_type: str) -> str:
    """
    将值转换为字符串存储
    """
    if value is None:
        return ''
    
    if setting_type == 'json':
        return json.dumps(value, ensure_ascii=False)
    elif setting_type == 'boolean':
        return 'true' if value else 'false'
    else:
        return str(value)
