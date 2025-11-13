#!/usr/bin/env python3
import argparse
import os
import sys
from urllib.parse import urljoin, urlparse
import asyncio
import types

import yaml

from config_manager import load_config, get_system_settings_by_prefix, get_system_setting, get_database_config, get_db_connection
from db_manager import init_db, save_torrent_to_db
from parser_utils import absolute_url, get_headers, find_detail_links, find_torrent_link, extract_descr_html, extract_imdb, decode_str, compute_info_hash, parse_torrent, extract_text_from_td_sibling, ensure_dir
from crawler import crawl

def main(argv=None) -> int:
    p = argparse.ArgumentParser(description='Standalone PT crawler: fetch .torrent files and basic metadata')
    p.add_argument('--config', help='JSON 配置文件路径（可选）。若未提供，将尝试加载脚本同目录下的 settings.json')
    

    args = p.parse_args(argv)

    config_path_to_load = args.config
    if not config_path_to_load:
        default_config_path = os.path.join('config', 'config.yaml')
        if os.path.exists(default_config_path):
            config_path_to_load = default_config_path
            print(f"[config] 未指定配置文件，自动加载默认配置文件: {os.path.abspath(config_path_to_load)}")
        else:
            print("[config] 未指定配置文件，且脚本同目录下未找到 settings.yaml")

    cfg = {}
    if config_path_to_load:
        try:
            cfg = load_config(config_path_to_load)
            print(f"[config] 使用配置文件: {os.path.abspath(config_path_to_load)}")
        except FileNotFoundError:
            print(f'[config] 错误: 配置文件未找到: {os.path.abspath(config_path_to_load)}')
            return 1
        except yaml.YAMLError as e:
            print(f'[config] 错误: 配置文件解析失败 ({os.path.abspath(config_path_to_load)}): {e}')
            return 1
        except Exception as e:
            print(f'[config] 读取配置文件时发生未知错误 ({os.path.abspath(config_path_to_load)}): {e}')
            return 1
    else:
        print("[config] 未加载任何配置文件。")
    
    # 尝试从数据库加载系统设置
    try:
        db_settings = get_system_settings_by_prefix('')
        if db_settings:
            print(f"[config] 从数据库加载了 {len(db_settings)} 个系统设置")
            cfg.update(db_settings)
        else:
            print("[config] 数据库中没有系统设置，使用配置文件")
    except Exception as e:
        print(f"[config] 从数据库加载设置失败: {e}")
        print("[config] 回退到配置文件")

    def pick(key, default=None):
        return cfg.get(key, default)

    base_url = pick('base_url')
    list_path = pick('list_path', '/torrents.php')
    pages = int(pick('pages', 1))
    cookie = pick('cookie')
    user_agent = pick('user_agent')
    out_dir = pick('out_dir', 'scripts/pt-crawler/output')
    torrent_download_dir = pick('torrent_download_dir', 'scripts/pt-crawler/output/torrents')
    delay = float(pick('delay', 0.5))
    allow_v2 = bool(cfg.get('allow_v2', False))
    test_mode = bool(cfg.get('test_mode', False))
    test_limit = int(cfg.get('test_limit', 5))

    if not base_url:
        try:
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT * FROM sites ORDER BY id DESC LIMIT 1")
                    site = cursor.fetchone()
                    if site:
                        base_url = site.get('base_url') or base_url
                        list_path = site.get('list_path') or list_path
                        cookie = site.get('cookie') or cookie
                        user_agent = site.get('user_agent') or user_agent
                        out_dir = site.get('out_dir') or out_dir
                        torrent_download_dir = site.get('torrent_download_dir') or torrent_download_dir
        except Exception as e:
            pass
    if not base_url:
        print('缺少 base_url，请在数据库站点配置或系统设置中提供')
        return 1

    # 从配置文件获取数据库配置
    db_config = get_database_config()
    db_host = db_config['host']
    db_port = db_config['port']
    db_user = db_config['user']
    db_password = db_config['password']
    db_name = db_config['database']

    opts = types.SimpleNamespace(
        base_url=base_url,
        list_path=list_path,
        pages=pages,
        cookie=cookie,
        user_agent=user_agent,
        out_dir=out_dir,
        torrent_download_dir=torrent_download_dir,
        delay=delay,
        allow_v2=allow_v2,
        test_mode=test_mode,
        test_limit=test_limit,
        db_host=db_host,
        db_port=db_port,
        db_user=db_user,
        db_password=db_password,
        db_name=db_name,
    )

    # Call the crawl function
    # crawl(opts)
    asyncio.run(crawl(opts))
    # return crawl(opts)
    return 0


if __name__ == '__main__':
    sys.exit(main())
