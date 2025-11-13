import pymysql
import pymysql.cursors
import time

def init_db(db_config: dict):
    conn = pymysql.connect(
        host=db_config['host'],
        port=db_config['port'],
        user=db_config['user'],
        password=db_config['password'],
        database=db_config['database'],
        cursorclass=pymysql.cursors.DictCursor
    )
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS torrents (
            id INT AUTO_INCREMENT PRIMARY KEY,
            info_hash VARCHAR(64) UNIQUE,
            name TEXT,
            title TEXT,
            introduction TEXT,
            description LONGTEXT,
            category TEXT,
            medium TEXT,
            video_codec TEXT,
            audiocodec TEXT,
            standard TEXT,
            production_team TEXT,
            size BIGINT,
            is_single_file TINYINT(1),
            is_upload TINYINT(1) DEFAULT 0,
            multi_file_list LONGTEXT,
            crawl_site TEXT,
            crawl_link TEXT,
            saved_path TEXT,
            meta_version VARCHAR(10),
            crawledAt DATETIME DEFAULT CURRENT_TIMESTAMP,
            tags TEXT
        )''')
    conn.commit()
    conn.close()

def ensure_torrents_is_upload(db_config: dict):
    conn = pymysql.connect(
        host=db_config['host'],
        port=db_config['port'],
        user=db_config['user'],
        password=db_config['password'],
        database=db_config['database'],
        cursorclass=pymysql.cursors.DictCursor
    )
    cursor = conn.cursor()
    cursor.execute("SHOW COLUMNS FROM torrents LIKE 'is_upload'")
    row = cursor.fetchone()
    if not row:
        cursor.execute("ALTER TABLE torrents ADD COLUMN is_upload TINYINT(1) DEFAULT 0")
        conn.commit()
    conn.close()

def ensure_torrents_crawled_at(db_config: dict):
    conn = pymysql.connect(
        host=db_config['host'],
        port=db_config['port'],
        user=db_config['user'],
        password=db_config['password'],
        database=db_config['database'],
        cursorclass=pymysql.cursors.DictCursor
    )
    cursor = conn.cursor()
    cursor.execute("SHOW COLUMNS FROM torrents LIKE 'crawledAt'")
    row = cursor.fetchone()
    if not row:
        cursor.execute("ALTER TABLE torrents ADD COLUMN crawledAt DATETIME DEFAULT CURRENT_TIMESTAMP")
        conn.commit()
    else:
        cursor.execute("ALTER TABLE torrents MODIFY crawledAt DATETIME DEFAULT CURRENT_TIMESTAMP")
        conn.commit()
    conn.close()

def init_site_task_tables(db_config: dict):
    conn = pymysql.connect(
        host=db_config['host'],
        port=db_config['port'],
        user=db_config['user'],
        password=db_config['password'],
        database=db_config['database'],
        cursorclass=pymysql.cursors.DictCursor
    )
    cursor = conn.cursor()
    
    # 创建 sites 表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sites (
            id INT AUTO_INCREMENT PRIMARY KEY,
            base_url TEXT,
            list_path TEXT,
            cookie TEXT,
            user_agent TEXT,
            out_dir TEXT,
            torrent_download_dir TEXT
        )''')
    
    # 检查并添加 name 字段
    cursor.execute("SHOW COLUMNS FROM sites LIKE 'name'")
    if not cursor.fetchone():
        cursor.execute("ALTER TABLE sites ADD COLUMN name TEXT")
    
    # 创建 tasks 表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tasks (
            id INT AUTO_INCREMENT PRIMARY KEY,
            site_id INT,
            name TEXT,
            schedule_type VARCHAR(20),
            schedule_value TEXT,
            status VARCHAR(20) DEFAULT 'inactive',
            last_run DATETIME
        )''')
    
    # 创建 settings 表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            id INT AUTO_INCREMENT PRIMARY KEY,
            key_name VARCHAR(100) UNIQUE,
            value TEXT,
            description TEXT
        )''')
    
    conn.commit()
    conn.close()

def add_site(db_conn: pymysql.connections.Connection, site: dict) -> int:
    cursor = db_conn.cursor()
    cols = ['name','base_url','list_path','cookie']
    vals = [site.get('name'), site.get('base_url'), site.get('list_path'), site.get('cookie')]
    
    # 如果提供了user_agent，则添加到插入语句中
    if site.get('user_agent') is not None:
        cols.append('user_agent')
        vals.append(site.get('user_agent'))
    
    sql = f"INSERT INTO sites ({', '.join(cols)}) VALUES ({', '.join(['%s']*len(cols))})"
    cursor.execute(sql, vals)
    db_conn.commit()
    return cursor.lastrowid

def list_sites(db_conn: pymysql.connections.Connection):
    cursor = db_conn.cursor()
    cursor.execute("SELECT * FROM sites ORDER BY id DESC")
    return cursor.fetchall()

def get_site(db_conn: pymysql.connections.Connection, site_id: int):
    cursor = db_conn.cursor()
    cursor.execute("SELECT * FROM sites WHERE id = %s", (site_id,))
    return cursor.fetchone()

def add_task(db_conn: pymysql.connections.Connection, task: dict) -> int:
    cursor = db_conn.cursor()
    cols = ['site_id','name','schedule_type','schedule_value','status']
    sql = f"INSERT INTO tasks ({', '.join(cols)}) VALUES ({', '.join(['%s']*len(cols))})"
    vals = [task.get('site_id'), task.get('name'), task.get('schedule_type'), task.get('schedule_value'), task.get('status','inactive')]
    cursor.execute(sql, vals)
    db_conn.commit()
    return cursor.lastrowid

def list_tasks(db_conn: pymysql.connections.Connection):
    cursor = db_conn.cursor()
    cursor.execute("SELECT * FROM tasks ORDER BY id DESC")
    return cursor.fetchall()

def update_task(db_conn: pymysql.connections.Connection, task_id: int, task_data: dict) -> bool:
    cursor = db_conn.cursor()
    fields = []
    values = []
    for key, value in task_data.items():
        if key != 'id':  # 不允许更新ID
            fields.append(f"{key} = %s")
            values.append(value)
    values.append(task_id)
    
    if fields:
        sql = f"UPDATE tasks SET {', '.join(fields)} WHERE id = %s"
        cursor.execute(sql, values)
        db_conn.commit()
        return cursor.rowcount > 0
    return False

def delete_task(db_conn: pymysql.connections.Connection, task_id: int) -> bool:
    cursor = db_conn.cursor()
    cursor.execute("DELETE FROM tasks WHERE id = %s", (task_id,))
    db_conn.commit()
    return cursor.rowcount > 0

def update_site(db_conn: pymysql.connections.Connection, site_id: int, site_data: dict) -> bool:
    cursor = db_conn.cursor()
    fields = []
    values = []
    for key, value in site_data.items():
        if key != 'id':  # 不允许更新ID
            # 如果user_agent为None，跳过更新这个字段
            if key == 'user_agent' and value is None:
                continue
            fields.append(f"{key} = %s")
            values.append(value)
    values.append(site_id)
    
    if fields:
        sql = f"UPDATE sites SET {', '.join(fields)} WHERE id = %s"
        cursor.execute(sql, values)
        db_conn.commit()
        return cursor.rowcount > 0
    return False

def delete_site(db_conn: pymysql.connections.Connection, site_id: int) -> bool:
    cursor = db_conn.cursor()
    cursor.execute("DELETE FROM sites WHERE id = %s", (site_id,))
    db_conn.commit()
    return cursor.rowcount > 0

def update_torrent(db_conn: pymysql.connections.Connection, torrent_id: int, torrent_data: dict) -> bool:
    cursor = db_conn.cursor()
    fields = []
    values = []
    for key, value in torrent_data.items():
        if key != 'id':  # 不允许更新ID
            fields.append(f"{key} = %s")
            values.append(value)
    values.append(torrent_id)
    
    if fields:
        sql = f"UPDATE torrents SET {', '.join(fields)} WHERE id = %s"
        cursor.execute(sql, values)
        db_conn.commit()
        return cursor.rowcount > 0
    return False

def delete_torrent(db_conn: pymysql.connections.Connection, torrent_id: int) -> bool:
    cursor = db_conn.cursor()
    cursor.execute("DELETE FROM torrents WHERE id = %s", (torrent_id,))
    db_conn.commit()
    return cursor.rowcount > 0

def get_setting(db_conn: pymysql.connections.Connection, key: str):
    cursor = db_conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key_name = %s", (key,))
    row = cursor.fetchone()
    return row['value'] if row else None

def set_setting(db_conn: pymysql.connections.Connection, key: str, value: str, description: str = None):
    cursor = db_conn.cursor()
    cursor.execute("""
        INSERT INTO settings (key_name, value, description) 
        VALUES (%s, %s, %s) 
        ON DUPLICATE KEY UPDATE value = VALUES(value), description = VALUES(description)
    """, (key, value, description))
    db_conn.commit()

def get_torrent_data(db_conn: pymysql.connections.Connection, info_hash: str):
    cursor = db_conn.cursor()
    cursor.execute("""
        SELECT tags, standard FROM torrents WHERE info_hash = %s
    """, (info_hash,))
    return cursor.fetchone()

def torrent_exists(db_conn: pymysql.connections.Connection, info_hash: str) -> bool:
    cursor = db_conn.cursor()
    cursor.execute("""
        SELECT 1 FROM torrents WHERE info_hash = %s LIMIT 1
    """, (info_hash,))
    return cursor.fetchone() is not None

def crawl_link_exists(db_conn: pymysql.connections.Connection, crawl_link: str) -> bool:
    cursor = db_conn.cursor()
    cursor.execute("""
        SELECT 1 FROM torrents WHERE crawl_link = %s LIMIT 1
    """, (crawl_link,))
    return cursor.fetchone() is not None

def save_torrent_to_db(db_conn: pymysql.connections.Connection, record: dict):
    cursor = db_conn.cursor()
    try:
        base_cols = ['info_hash','name','title','introduction','description','category','medium','video_codec','audiocodec','standard','production_team','size','is_single_file','is_upload','multi_file_list','crawl_site','crawl_link','saved_path','meta_version','tags']
        use_crawled = bool(record.get('crawledAt'))
        cols = base_cols[:]
        values = [record.get('info_hash'), record.get('name'), record.get('title', ''), record.get('introduction', ''), record.get('description', ''), record.get('category', ''), record.get('medium', ''), record.get('video_codec', ''), record.get('audiocodec', ''), record.get('standard', ''), record.get('production_team', ''), record.get('size'), record.get('is_single_file', 0), record.get('is_upload', 0), record.get('multi_file_list', ''), record.get('crawl_site', ''), record.get('crawl_link', ''), record.get('saved_path'), record.get('meta_version'), record.get('tags', '')]
        if use_crawled:
            cols.insert(-1, 'crawledAt')
            values.insert(-1, record.get('crawledAt'))
        placeholders = ', '.join(['%s'] * len(cols))
        sql = f"INSERT INTO torrents ({', '.join(cols)}) VALUES ({placeholders})"
        cursor.execute(sql, values)
        db_conn.commit()
        print(f"  [DB] Saved {record.get('name')} to database.")
    except pymysql.err.IntegrityError:
        print(f"  [DB] Torrent with info_hash {record.get('info_hash')} already exists, skipping.")
    except Exception as e:
        print(f"  [DB] Error saving {record.get('name')} to database: {e}")
