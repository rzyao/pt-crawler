"""PT crawler runtime for NexusPHP-based sites."""
import asyncio
import os
import time
import json
import argparse
import requests
import pymysql
import pymysql.cursors
from bs4 import BeautifulSoup

from config_manager import load_config, get_database_config, get_system_setting
from db_manager import init_db, save_torrent_to_db, get_torrent_data, torrent_exists, crawl_link_exists
from parser_utils import (
    absolute_url,
    get_headers,
    find_detail_links,
    find_torrent_link,
    extract_descr_html,
    parse_torrent,
    extract_text_from_td_sibling,
    ensure_dir,
    extract_title,
    extract_subtitle,
    extract_basic_info,
    extract_tags,
    extract_description,
)

async def run_crawler_for_site(site: dict, task: dict) -> dict:
    """
    为单个站点执行任务爬虫
    用于手动执行功能
    """
    print(f"开始为站点 {site['name']} 执行任务 {task['name']}")
    
    try:
        db_config = get_database_config()
        config = {}
        crawler_keys = ['out_dir', 'torrent_download_dir', 'delay', 'test_mode', 'test_limit', 'allow_v2']
        for key in crawler_keys:
            value = get_system_setting(key)
            if value is not None:
                config[key] = value
        
        db_host = db_config.get('host', 'localhost')
        db_port = db_config.get('port', 3306)
        db_user = db_config.get('user', 'root')
        db_password = db_config.get('password', '')
        db_name = db_config.get('database', 'pt_crawler')

        class MockArgs:
            def __init__(self):
                self.base_url = site['base_url']
                self.list_path = site.get('list_path', '/torrents.php')
                self.cookie = site.get('cookie', '')
                self.user_agent = site.get('user_agent', '')
                self.out_dir = config.get('out_dir', './output')
                self.torrent_download_dir = config.get('torrent_download_dir', './torrents')
                self.db_host = db_host
                self.db_port = db_port
                self.db_user = db_user
                self.db_password = db_password
                self.db_name = db_name
                self.delay = config.get('delay', 0.5)
                self.test_mode = config.get('test_mode', False)
                self.test_limit = config.get('test_limit', 5)
                self.allow_v2 = config.get('allow_v2', False)
        
        opts = MockArgs()
        
        # 调用现有的爬虫函数
        result = await crawl(opts)
        
        return {
            "success": True,
            "message": f"任务执行完成，处理了 {result} 个种子",
            "task_id": task['id'],
            "site_name": site['name']
        }
        
    except (requests.exceptions.RequestException, ValueError, OSError, pymysql.err.Error) as e:
        error_msg = f"任务执行失败: {str(e)}"
        print(error_msg)
        return {
            "success": False,
            "message": error_msg,
            "task_id": task['id'],
            "site_name": site['name'],
            "error": str(e)
        }




async def crawl(opts: argparse.Namespace) -> int:
    session = requests.Session()
    headers = get_headers(opts.cookie, opts.user_agent)
    out_dir = opts.out_dir
    ensure_dir(out_dir)
    tdir = os.path.join(out_dir, 'torrents')
    ensure_dir(tdir)
    ensure_dir(opts.torrent_download_dir)
    meta_path = os.path.join(out_dir, 'metadata.jsonl')

    db_config = {
        'host': opts.db_host,
        'port': opts.db_port,
        'user': opts.db_user,
        'password': opts.db_password,
        'database': opts.db_name,
    }
    init_db(db_config)
    db_conn = pymysql.connect(**db_config, cursorclass=pymysql.cursors.DictCursor)

    created = 0
    skipped = 0
    seen_link_streak = 0
    stop_due_to_seen = False

    page = 1
    while True:
        list_url = absolute_url(opts.base_url, opts.list_path)
        if '?' in list_url:
            list_url += f'&page={page}'
        else:
            list_url += f'?page={page}'
        print(f'[list] {list_url}')
        try:
            r = session.get(list_url, headers=headers, timeout=30)
            print(f'  [DEBUG] List page status code: {r.status_code}')
            if r.status_code != 200:
                print(f'  ! HTTP {r.status_code} for {list_url}')
                print(f'  [DEBUG] List page response: {r.text[:500]}')
                skipped += 1
                break
        except requests.exceptions.RequestException as e:
            print(f'  ! Request failed for {list_url}: {e}')
            skipped += 1
            break
        soup = BeautifulSoup(r.text, 'html.parser')
        detail_links = find_detail_links(soup, opts.base_url)
        print(f'  [DEBUG] Found {len(detail_links)} detail links.')
        if not detail_links:
            print('  ! no detail links found')
            skipped += 1
            break

        limit = len(detail_links)
        if getattr(opts, 'test_mode', False):
            limit = min(getattr(opts, 'test_limit', 5) or 5, len(detail_links))
        for durl in detail_links[:limit]:
            print(f'  [DEBUG] Processing detail link: {durl}')
            try:
                dr = session.get(durl, headers=headers, timeout=30)
                detail_page_path = os.path.join(out_dir, 'first_torrent_detail_page.html')
                if not os.path.exists(detail_page_path):
                    try:
                        with open(detail_page_path, 'w', encoding='utf-8') as f:
                            f.write(dr.text)
                            f.flush()
                        print(f"Successfully saved first torrent detail page to {detail_page_path}")
                    except OSError as e:
                        print(f"Error saving first torrent detail page to {detail_page_path}: {e}")

                print(f'  [DEBUG] Detail page status code for {durl}: {dr.status_code}')
                if dr.status_code != 200:
                    print(f'  ! detail HTTP {dr.status_code} {durl}')
                    print(f'  [DEBUG] Detail page response for {durl}: {dr.text}')
                    skipped += 1
                    continue
                dsoup = BeautifulSoup(dr.text, 'html.parser')
                turl = find_torrent_link(dsoup, opts.base_url)
                if not turl:
                    print('  ! no torrent link')
                    skipped += 1
                    continue
                if crawl_link_exists(db_conn, turl):
                    seen_link_streak += 1
                else:
                    seen_link_streak = 0
                if seen_link_streak >= 10:
                    stop_due_to_seen = True
                    print('  [STOP] 连续10个种子链接已存在，停止抓取')
                    break

                tr = session.get(turl, headers=headers, timeout=30)
                if tr.status_code != 200:
                    print(f'  ! torrent HTTP {tr.status_code} {turl}')
                    skipped += 1
                    continue
                tbytes = tr.content

                try:
                    info = parse_torrent(tbytes)
                except ValueError as e:
                    print(f'  ! parse error: {e}')
                    skipped += 1
                    continue

                if info['meta_version'] == 'v2' and not opts.allow_v2:
                    print('  ! skip v2/hybrid torrent')
                    skipped += 1
                    continue

                # filename from content-disposition or infohash
                filename = f"{info['info_hash']}.torrent"
                out_file = os.path.join(opts.torrent_download_dir, filename)
                with open(out_file, 'wb') as f:
                    f.write(tbytes)

                descr_html = extract_descr_html(dsoup)
                description = extract_description(dsoup)
                print(f"  [DEBUG] descr_html length: {len(descr_html) if descr_html else 0}")
                # imdb_url removed per new schema

                basic = extract_basic_info(dsoup)
                category = basic.get('category') or extract_text_from_td_sibling(dsoup, r'(类型|類型|类别|類別)[：:]?')
                medium = basic.get('medium') or extract_text_from_td_sibling(dsoup, r'(媒介|音频类|音頻類|音訊類)[：:]?')
                video_codec = basic.get('video_codec') or extract_text_from_td_sibling(dsoup, r'(编码|編碼|视频编码|視頻編碼|視訊編碼)[：:]?')
                audiocodec = basic.get('audiocodec') or extract_text_from_td_sibling(dsoup, r'(音频编码|音頻編碼|音訊編碼)[：:]?')
                standard = basic.get('standard') or extract_text_from_td_sibling(dsoup, r'(分辨率|解析度|标准|標準)[：:]?')
                production_team = basic.get('production_team') or extract_text_from_td_sibling(dsoup, r'(制作组|製作組)[：:]?')
                title = extract_title(dsoup)
                tags = extract_tags(dsoup)
                # times_completed is already extracted as 'completed'
                # nfo and technical_info might require more specific selectors or patterns
                # For now, let's assume they are not directly available as simple td siblings.

                subtitle = extract_subtitle(dsoup)
                if basic.get('size_bytes'):
                    info['size'] = basic['size_bytes']

                # seeders/leechers/completed removed per new schema

                is_single_file = 1 if len(info['files']) == 1 else 0
                record = {
                    'name': info['name'],
                    'info_hash': info['info_hash'],
                    'meta_version': info['meta_version'],
                    'size': info['size'],
                    'saved_path': out_file,
                    'category': category,
                    'title': title,
                    'introduction': subtitle,
                    'description': description or '',
                    'crawl_site': opts.base_url,
                    'medium': medium,
                    'video_codec': video_codec,
                    'standard': standard,
                    'production_team': production_team,
                    'audiocodec': audiocodec,
                    'is_single_file': is_single_file,
                    'multi_file_list': json.dumps(info['files'], ensure_ascii=False),
                    'crawl_link': turl,
                    'tags': tags,
                }
                if torrent_exists(db_conn, info['info_hash']):
                    print(f"  [DB] Torrent with info_hash {info['info_hash']} already exists, skipping insert.")
                else:
                    save_torrent_to_db(db_conn, record)

                # Verify data
                retrieved_data = get_torrent_data(db_conn, info['info_hash'])
                if retrieved_data:
                    print(f"  [VERIFY] Tags: {retrieved_data['tags']}, Standard: {retrieved_data['standard']}")
                else:
                    print(f"  [VERIFY] Could not retrieve data for info_hash: {info['info_hash']}")
                with open(meta_path, 'a', encoding='utf-8') as mf:
                    mf.write(json.dumps(record, ensure_ascii=False) + '\n')

                created += 1
                print(f"  + saved {filename} | {info['name']}")
                if opts.delay > 0:
                    time.sleep(opts.delay)
            except (requests.exceptions.RequestException, ValueError, OSError) as e:
                print(f'  ! error: {e}')
                skipped += 1
        if stop_due_to_seen:
            break
        page += 1
    db_conn.close()
    print(f'done. created={created} skipped={skipped}')
    return 0

async def run_crawler(site_config: dict):
    opts = argparse.Namespace()
    for key, value in site_config.items():
        setattr(opts, key, value)
    required_opts = ['base_url', 'list_path', 'cookie', 'user_agent', 'out_dir', 'torrent_download_dir']
    for opt in required_opts:
        if not hasattr(opts, opt) or getattr(opts, opt) is None:
            raise ValueError(f"Missing required configuration option: {opt}")
    if not hasattr(opts, 'delay'):
        opts.delay = 0.5
    if not hasattr(opts, 'allow_v2'):
        opts.allow_v2 = False
    mysql_required_opts = ['db_host', 'db_port', 'db_user', 'db_password', 'db_name']
    for opt in mysql_required_opts:
        if not hasattr(opts, opt) or getattr(opts, opt) is None:
            raise ValueError(f"Missing required MySQL configuration option: {opt}")
    await crawl(opts)

def main():
    parser = argparse.ArgumentParser(description='PT-Crawler for NexusPHP based sites.')
    parser.add_argument('--conf', type=str, default='config/config.yaml', help='Path to the configuration file.')
    opts = parser.parse_args()

    config = load_config(opts.conf)
    
    # Override opts with config values
    for key, value in config.items():
        if not key.startswith('_comment_'): # Ignore comment keys
            setattr(opts, key, value)

    # Ensure required options are set
    required_opts = ['base_url', 'list_path', 'cookie', 'user_agent', 'out_dir', 'torrent_download_dir']
    for opt in required_opts:
        if not hasattr(opts, opt) or getattr(opts, opt) is None:
            raise ValueError(f"Missing required configuration option: {opt}")

    # Set default values for optional options if not provided
    if not hasattr(opts, 'pages'):
        opts.pages = 1
    if not hasattr(opts, 'delay'):
        opts.delay = 0.5
    if not hasattr(opts, 'allow_v2'):
        opts.allow_v2 = False

    mysql_required_opts = ['db_host', 'db_port', 'db_user', 'db_password', 'db_name']
    for opt in mysql_required_opts:
        if not hasattr(opts, opt) or getattr(opts, opt) is None:
            raise ValueError(f"Missing required MySQL configuration option: {opt}")

    asyncio.run(crawl(opts))

if __name__ == '__main__':
    main()
