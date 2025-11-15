from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
try:
    from fastapi.templating import Jinja2Templates
    templates = Jinja2Templates(directory="templates")
except Exception:
    templates = None
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import pymysql
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker
from config_manager import load_config, get_system_settings_by_prefix, get_db_connection, get_database_config, get_all_system_settings, get_system_setting, set_system_setting
from db_manager import init_site_task_tables, add_site, add_task, list_sites, list_tasks, get_site, ensure_torrents_crawled_at, ensure_torrents_is_upload, get_setting, set_setting, update_task, delete_task, update_site, delete_site, update_torrent, delete_torrent
try:
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.triggers.interval import IntervalTrigger
    scheduler = BackgroundScheduler()
    scheduler.start()
except Exception:
    BackgroundScheduler = None
    CronTrigger = None
    IntervalTrigger = None
    scheduler = None
import asyncio
import os
import shutil
import logging
import sys
from crawler import run_crawler

app = FastAPI()

app.mount("/static", StaticFiles(directory="static", check_dir=False), name="static")

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    try:
        with open("templates/index.html", "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    except Exception:
        return HTMLResponse(content="<html><body>index.html missing</body></html>")

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 获取数据库配置 - 只从config.yaml读取
if not os.path.exists('/config/config.yaml'):
    os.makedirs('/config', exist_ok=True)
    copied = False
    for src in ['/app/config.yaml', 'config.yaml']:
        if os.path.exists(src):
            shutil.copy(src, '/config/config.yaml')
            copied = True
            break
    if not copied:
        raise FileNotFoundError('/config/config.yaml not found and no default config available')
CONFIG = load_config('/config/config.yaml')
try:
    DB_CONFIG = get_database_config()
    
    LOG_LEVEL = str(CONFIG.get('log_level', 'INFO')).upper()
    logging.basicConfig(
        level=getattr(logging, LOG_LEVEL, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    logger = logging.getLogger("pt-crawler")
    logger.info(f"使用配置文件中的数据库配置: {DB_CONFIG['host']}:{DB_CONFIG['port']}")
except Exception as e:
    logger = logging.getLogger("pt-crawler")
    logger.error(f"加载数据库配置失败: {e}")
    # 使用默认配置
    DB_CONFIG = {
        'host': 'localhost',
        'port': 3306,
        'user': 'root',
        'password': '',
        'database': 'pt_crawler',
    }

engine = None
Session = None

# 服务启动后自动恢复定时任务（只注册非手动任务）
def _register_existing_scheduled_tasks():
    if not scheduler or not (CronTrigger and IntervalTrigger):
        return
    try:
        conn = pymysql.connect(**DB_CONFIG, cursorclass=pymysql.cursors.DictCursor)
        tasks = list_tasks(conn)  # [{'id', 'site_id', 'name', 'schedule_type', 'schedule_value', 'status', 'last_run'}]
        for t in tasks:
            stype = (t.get('schedule_type') or '').lower()
            svalue = str(t.get('schedule_value') or '').strip()
            # 手动任务不加入调度器；如存在 status 字段且非 active，则也不加入
            if stype == 'manual':
                continue
            status = (t.get('status') or '').lower()
            if status and status != 'active':
                continue
            try:
                if stype == 'cron':
                    trigger = CronTrigger.from_crontab(svalue)
                else:
                    trigger = IntervalTrigger(seconds=int(svalue or '0') or 0)
                    if trigger.interval.total_seconds() <= 0:
                        continue
                # 合并站点基础配置
                site_row = get_site(conn, t['site_id'])
                base = dict(CONFIG)
                if site_row:
                    for k in ['base_url','list_path','cookie','user_agent']:
                        if site_row.get(k):
                            base[k] = site_row[k]
                base['start_page'] = int((t.get('start_page') or 1))
                # 避免重复注册：如已存在同 id 任务，替换之
                try:
                    scheduler.remove_job(str(t['id']))
                except Exception:
                    pass
                scheduler.add_job(lambda: asyncio.run(run_crawler(base)), trigger, id=str(t['id']))
            except Exception:
                # 单条任务注册失败时跳过，不影响其他任务
                continue
        conn.close()
    except Exception:
        pass

@app.on_event("startup")
async def _on_startup():
    global engine, Session
    try:
        engine = sa.create_engine(
            f"mysql+pymysql://{DB_CONFIG['user']}:{DB_CONFIG['password']}@{DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['database']}"
        )
        Session = sessionmaker(bind=engine)
        init_site_task_tables(DB_CONFIG)
        ensure_torrents_crawled_at(DB_CONFIG)
        ensure_torrents_is_upload(DB_CONFIG)
    except Exception:
        pass
    try:
        _register_existing_scheduled_tasks()
    except Exception:
        pass

def get_conn():
    try:
        return pymysql.connect(**DB_CONFIG, cursorclass=pymysql.cursors.DictCursor, connect_timeout=5)
    except Exception:
        raise HTTPException(status_code=503, detail="数据库连接失败")

# 调度器

class Site(BaseModel):
    name: str
    base_url: str
    list_path: str | None = None
    cookie: str | None = None
    user_agent: str | None = None

class Task(BaseModel):
    name: str
    site_id: int
    schedule_type: str  # 'cron' or 'interval'
    schedule_value: str  # cron字符串或间隔秒
    start_page: int | None = 1

# API 端点示例
@app.post("/sites/")
async def add_site_endpoint(site: Site):
    conn = pymysql.connect(**DB_CONFIG, cursorclass=pymysql.cursors.DictCursor)
    site_id = add_site(conn, site.dict())
    conn.close()
    return {"id": site_id}

@app.post("/tasks/")
async def add_task_endpoint(task: Task):
    conn = pymysql.connect(**DB_CONFIG, cursorclass=pymysql.cursors.DictCursor)
    payload = task.dict()
    if payload.get('start_page') is None:
        payload['start_page'] = 1
    task_id = add_task(conn, payload)
    site_row = get_site(conn, task.site_id)
    conn.close()

    # 添加到调度器（只有当调度器可用且非手动任务时才添加）
    if scheduler and CronTrigger and IntervalTrigger and task.schedule_type != 'manual':
        try:
            if task.schedule_type == 'cron':
                trigger = CronTrigger.from_crontab(task.schedule_value)
            else:
                trigger = IntervalTrigger(seconds=int(task.schedule_value))

            base = dict(CONFIG)
            if site_row:
                for k in ['base_url','list_path','cookie','user_agent']:
                    if site_row.get(k):
                        base[k] = site_row[k]
            base['start_page'] = int(payload.get('start_page') or 1)
            scheduler.add_job(lambda: asyncio.run(run_crawler(base)), trigger, id=str(task_id))
        except Exception as e:
            logger = logging.getLogger("pt-crawler")
            logger.warning(f"添加任务到调度器失败: {e}")
    else:
        logger = logging.getLogger("pt-crawler")
        logger.info("手动任务或调度器未初始化，任务将不会自动执行")
    
    return {"id": task_id}

@app.get("/sites")
async def list_sites_endpoint():
    conn = pymysql.connect(**DB_CONFIG, cursorclass=pymysql.cursors.DictCursor)
    rows = list_sites(conn)
    conn.close()
    return rows

@app.get("/tasks")
async def list_tasks_endpoint():
    conn = get_conn()
    rows = list_tasks(conn)
    conn.close()
    return rows

@app.get("/torrents")
async def list_torrents_endpoint(limit: int = 50):
    conn = pymysql.connect(**DB_CONFIG, cursorclass=pymysql.cursors.DictCursor)
    cur = conn.cursor()
    cur.execute("SHOW COLUMNS FROM torrents LIKE 'crawledAt'")
    has_crawled_at = cur.fetchone() is not None
    select_cols = "id, info_hash, name, title, size, standard, crawl_site" + (", crawledAt" if has_crawled_at else "")
    cur.execute(f"SELECT {select_cols} FROM torrents ORDER BY id DESC LIMIT %s", (limit,))
    rows = cur.fetchall()
    conn.close()
    return rows

@app.get("/settings/{key}")
async def get_setting_endpoint(key: str):
    conn = pymysql.connect(**DB_CONFIG, cursorclass=pymysql.cursors.DictCursor)
    value = get_setting(conn, key)
    conn.close()
    return {"key": key, "value": value}

@app.post("/settings/{key}")
async def set_setting_endpoint(key: str, payload: dict):
    conn = pymysql.connect(**DB_CONFIG, cursorclass=pymysql.cursors.DictCursor)
    set_setting(conn, key, payload.get("value"), payload.get("description"))
    conn.close()
    return {"key": key, "value": payload.get("value")}

@app.get("/settings")
async def get_all_settings_endpoint():
    """获取所有系统设置"""
    conn = pymysql.connect(**DB_CONFIG, cursorclass=pymysql.cursors.DictCursor)
    cursor = conn.cursor()
    cursor.execute("SELECT key_name, value, description FROM settings ORDER BY key_name")
    settings = cursor.fetchall()
    conn.close()
    return {item['key_name']: {'value': item['value'], 'description': item['description']} for item in settings}

@app.post("/settings")
async def set_all_settings_endpoint(payload: dict):
    """批量设置系统配置"""
    conn = pymysql.connect(**DB_CONFIG, cursorclass=pymysql.cursors.DictCursor)
    results = {}
    for key, data in payload.items():
        if isinstance(data, dict):
            value = data.get('value')
            description = data.get('description')
        else:
            value = data
            description = None
        set_setting(conn, key, value, description)
        results[key] = value
    conn.close()
    return {"updated": results}

@app.post("/test-db-connection")
async def test_db_connection_endpoint(payload: dict):
    """测试数据库连接"""
    try:
        # 从payload中获取数据库配置
        db_config = {
            'host': payload.get('db_host'),
            'port': int(payload.get('db_port', 3306)),
            'user': payload.get('db_user'),
            'password': payload.get('db_password'),
            'database': payload.get('db_name'),
            'cursorclass': pymysql.cursors.DictCursor,
            'connect_timeout': 5  # 5秒超时
        }
        
        # 测试连接
        conn = pymysql.connect(**db_config)
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        result = cursor.fetchone()
        conn.close()
        
        if result:
            return {"success": True, "message": "数据库连接成功"}
        else:
            return {"success": False, "message": "数据库连接测试失败"}
            
    except pymysql.Error as e:
        return {"success": False, "message": f"数据库连接失败: {str(e)}"}
    except Exception as e:
        return {"success": False, "message": f"连接错误: {str(e)}"}

# 新增：任务操作API
@app.post("/tasks/{task_id}")
async def update_task_endpoint(task_id: int, task: Task):
    """更新任务"""
    conn = pymysql.connect(**DB_CONFIG, cursorclass=pymysql.cursors.DictCursor)
    success = update_task(conn, task_id, task.dict())
    conn.close()
    if success:
        return {"message": "任务更新成功", "id": task_id}
    else:
        raise HTTPException(status_code=404, detail="任务未找到")

@app.post("/tasks/{task_id}/delete")
async def delete_task_endpoint(task_id: int):
    """删除任务"""
    conn = pymysql.connect(**DB_CONFIG, cursorclass=pymysql.cursors.DictCursor)
    success = delete_task(conn, task_id)
    conn.close()
    if success:
        return {"message": "任务删除成功", "id": task_id}
    else:
        raise HTTPException(status_code=404, detail="任务未找到")

@app.post("/tasks/{task_id}/execute")
async def execute_task_endpoint(task_id: int):
    """手动执行任务"""
    conn = pymysql.connect(**DB_CONFIG, cursorclass=pymysql.cursors.DictCursor)
    
    # 获取任务信息
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM tasks WHERE id = %s", (task_id,))
    task = cursor.fetchone()
    
    if not task:
        conn.close()
        raise HTTPException(status_code=404, detail="任务未找到")
    
    # 获取对应的站点信息
    cursor.execute("SELECT * FROM sites WHERE id = %s", (task['site_id'],))
    site = cursor.fetchone()
    
    if not site:
        conn.close()
        raise HTTPException(status_code=404, detail="关联站点未找到")
    
    conn.close()
    
    # 异步执行爬虫任务
    try:
        # 创建后台任务执行爬虫
        import asyncio
        asyncio.create_task(run_single_task(task_id, task, site))
        
        return {
            "message": "任务已开始执行", 
            "id": task_id,
            "task_name": task['name'],
            "site_name": site['name']
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"任务执行失败: {str(e)}")

async def run_single_task(task_id: int, task: dict, site: dict):
    """运行单个任务"""
    try:
        logger = logging.getLogger("pt-crawler")
        logger.info(f"开始执行任务 {task_id}: {task['name']} - 站点: {site['name']}")
        
        # 这里调用实际的爬虫逻辑
        # 可以复用现有的爬虫代码
        from crawler import run_crawler_for_site
        
        # 执行爬虫（这里简化处理，实际应该调用完整的爬虫逻辑）
        result = await run_crawler_for_site(site, task)
        
        logger.info(f"任务 {task_id} 执行完成")
        return result
        
    except Exception as e:
        logger = logging.getLogger("pt-crawler")
        logger.error(f"任务 {task_id} 执行失败: {str(e)}")
        raise e

# 新增：站点操作API
@app.post("/sites/{site_id}")
async def update_site_endpoint(site_id: int, site: Site):
    """更新站点"""
    conn = pymysql.connect(**DB_CONFIG, cursorclass=pymysql.cursors.DictCursor)
    success = update_site(conn, site_id, site.dict())
    conn.close()
    if success:
        return {"message": "站点更新成功", "id": site_id}
    else:
        raise HTTPException(status_code=404, detail="站点未找到")

@app.post("/sites/{site_id}/delete")
async def delete_site_endpoint(site_id: int):
    """删除站点"""
    conn = pymysql.connect(**DB_CONFIG, cursorclass=pymysql.cursors.DictCursor)
    success = delete_site(conn, site_id)
    conn.close()
    if success:
        return {"message": "站点删除成功", "id": site_id}
    else:
        raise HTTPException(status_code=404, detail="站点未找到")

# 新增：种子操作API
@app.post("/torrents/{torrent_id}")
async def update_torrent_endpoint(torrent_id: int, payload: dict):
    """更新种子信息"""
    conn = pymysql.connect(**DB_CONFIG, cursorclass=pymysql.cursors.DictCursor)
    success = update_torrent(conn, torrent_id, payload)
    conn.close()
    if success:
        return {"message": "种子更新成功", "id": torrent_id}
    else:
        raise HTTPException(status_code=404, detail="种子未找到")

@app.post("/torrents/{torrent_id}/delete")
async def delete_torrent_endpoint(torrent_id: int):
    conn = pymysql.connect(**DB_CONFIG, cursorclass=pymysql.cursors.DictCursor)
    success = delete_torrent(conn, torrent_id)
    conn.close()
    if success:
        return {"message": "种子删除成功", "id": torrent_id}
    else:
        raise HTTPException(status_code=404, detail="种子未找到")

@app.delete("/torrents/{torrent_id}")
async def delete_torrent_endpoint_delete(torrent_id: int):
    conn = pymysql.connect(**DB_CONFIG, cursorclass=pymysql.cursors.DictCursor)
    success = delete_torrent(conn, torrent_id)
    conn.close()
    if success:
        return {"message": "种子删除成功", "id": torrent_id}
    else:
        raise HTTPException(status_code=404, detail="种子未找到")

# 系统设置管理API
@app.get("/api/system-settings")
async def get_system_settings():
    """获取所有系统设置"""
    try:
        settings = get_all_system_settings()
        return {"success": True, "data": settings}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取系统设置失败: {str(e)}")

@app.get("/api/system-settings/{setting_key}")
async def get_system_setting_endpoint(setting_key: str):
    """获取单个系统设置"""
    try:
        value = get_system_setting(setting_key)
        if value is not None:
            return {"success": True, "key": setting_key, "value": value}
        else:
            raise HTTPException(status_code=404, detail="设置项未找到")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取设置失败: {str(e)}")

@app.post("/api/system-settings/{setting_key}")
async def set_system_setting_endpoint(setting_key: str, payload: dict):
    """设置单个系统设置"""
    try:
        value = payload.get("value")
        setting_type = payload.get("type", "string")
        description = payload.get("description", "")
        
        success = set_system_setting(setting_key, value, setting_type, description)
        if success:
            return {"success": True, "message": "设置保存成功"}
        else:
            raise HTTPException(status_code=500, detail="设置保存失败")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"设置失败: {str(e)}")

@app.post("/api/system-settings/batch")
async def set_system_settings_batch(payload: dict):
    """批量设置系统设置"""
    try:
        settings = payload.get("settings", {})
        results = {}
        
        for key, setting_data in settings.items():
            if isinstance(setting_data, dict):
                value = setting_data.get("value")
                setting_type = setting_data.get("type", "string")
                description = setting_data.get("description", "")
            else:
                value = setting_data
                setting_type = "string"
                description = None
            
            success = set_system_setting(key, value, setting_type, description)
            results[key] = "success" if success else "failed"
        
        return {"success": True, "results": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"批量设置失败: {str(e)}")

@app.get("/api/system-settings/categories/{category}")
async def get_system_settings_by_category(category: str):
    """按分类获取系统设置"""
    try:
        if category == "database":
            # 数据库配置只从config.yaml读取，不通过API暴露
            config = load_config('/config/config.yaml')
            settings = {
                'db_host': config.get('db_host', 'localhost'),
                'db_port': config.get('db_port', 3306),
                'db_user': config.get('db_user', 'root'),
                'db_name': config.get('db_name', 'pt_crawler')
            }
            # 不暴露密码
            settings['db_password'] = '******' if config.get('db_password') else ''
        elif category == "crawler":
            crawler_keys = ["out_dir", "torrent_download_dir", "delay", "test_mode", "test_limit", "allow_v2"]
            settings = {}
            for key in crawler_keys:
                value = get_system_setting(key)
                if value is not None:
                    settings[key] = value
        elif category == "sites":
            settings = get_system_settings_by_prefix("sites")
        else:
            settings = get_system_settings_by_prefix(category)
        
        return {"success": True, "category": category, "settings": settings}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取分类设置失败: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
