import argparse
import base64
import json
import re
import requests
from urllib.parse import urlparse
from bs4 import BeautifulSoup
import pymysql
from config_manager import get_database_config
from urllib.parse import urlparse

def fetch_pending(conn, limit):
    cur = conn.cursor()
    cur.execute("SELECT id, info_hash, name, title, introduction, description, mediainfo, category, medium, video_codec, audiocodec, standard, production_team, crawl_site, saved_path, tags FROM torrents WHERE is_upload = 0 ORDER BY id DESC LIMIT %s", (limit,))
    return cur.fetchall()

def mark_uploaded(conn, tid):
    cur = conn.cursor()
    cur.execute("UPDATE torrents SET is_upload = 1 WHERE id = %s", (tid,))
    conn.commit()

def make_payload(row, overrides):
    path = row['saved_path']
    with open(path, 'rb') as f:
        b64 = base64.b64encode(f.read()).decode('ascii')
    intro = row.get('introduction') or ""
    desc = row.get('description') or ""
    desc = re.sub(r"\bby\s*csauto\b", "", desc, flags=re.IGNORECASE).strip()
    mi_text = row.get('mediainfo') or ""
    vcodec, acodec, standard = parse_mediainfo(mi_text)
    imdb_auto, douban_auto = extract_links(desc or intro)
    payload = {
        "name": row['name'] or "",
        "category": row.get('category') or "",
        "title": row.get('title') or "",
        "introduction": row.get('introduction') or "",
        "standard": (standard or row.get('standard') or ""),
        "videoCodec": (vcodec or row.get('video_codec') or ""),
        "audioCodec": (acodec or row.get('audiocodec') or ""),
        "productionTeam": row.get('production_team') or "",
        "region": overrides.get('region', ""),
        "language": overrides.get('language', ""),
        "subtitleType": overrides.get('subtitleType', ""),
        "imdbUrl": (imdb_auto or overrides.get('imdbUrl', "")),
        "doubanUrl": (douban_auto or overrides.get('doubanUrl', "")),
        "description": desc,
        "mediaInfo": mi_text,
        "isAnonymous": str(overrides.get('isAnonymous', False)).lower(),
        "fileBase64": b64,
        "originalName": row['name'] or ""
    }
    def _is_url(u: str) -> bool:
        if not u:
            return False
        p = urlparse(u)
        return p.scheme in ("http", "https") and bool(p.netloc)
    if not _is_url(payload.get("imdbUrl", "")):
        payload.pop("imdbUrl", None)
    if not _is_url(payload.get("doubanUrl", "")):
        payload.pop("doubanUrl", None)
    return payload

def extract_links(text: str):
    imdb = None
    douban = None
    if not text:
        return imdb, douban
    s = text
    try:
        soup = BeautifulSoup(text, 'html.parser')
        for a in soup.find_all('a', href=True):
            href = (a.get('href') or '').strip().strip('`"\'')
            if not href:
                continue
            if re.search(r"https?://(?:www\.)?imdb\.com/title/tt\d+/?", href, re.IGNORECASE):
                imdb = imdb or href
            if re.search(r"https?://(?:movie\.)?douban\.com/subject/\d+/?", href, re.IGNORECASE):
                douban = douban or href
        if imdb or douban:
            return imdb, douban
    except Exception:
        pass
    m = re.search(r"https?://(?:www\.)?imdb\.com/title/tt\d+/?", s, re.IGNORECASE)
    if m:
        imdb = m.group(0)
    m = re.search(r"https?://(?:movie\.)?douban\.com/subject/\d+/?", s, re.IGNORECASE)
    if m:
        douban = m.group(0)
    return imdb, douban

def parse_mediainfo(text: str):
    video = None
    audio = None
    height = None
    width = None
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        m = re.search(r"^Video_Format_List\s*:\s*(.+)$", s, re.IGNORECASE)
        if m and not video:
            video = m.group(1).strip()
            continue
        m = re.search(r"^Audio_Format_List\s*:\s*(.+)$", s, re.IGNORECASE)
        if m and not audio:
            audio = m.group(1).strip()
            continue
        m = re.search(r"^Audio codecs\s*:\s*(.+)$", s, re.IGNORECASE)
        if m and not audio:
            audio = m.group(1).strip()
            continue
        m = re.search(r"^Codecs Video\s*:\s*(.+)$", s, re.IGNORECASE)
        if m and not video:
            video = m.group(1).strip()
            continue
        m = re.search(r"^Format\s*:\s*(.+)$", s, re.IGNORECASE)
        if m and not video and 'Video' in text:
            cand = m.group(1).strip()
            if cand:
                video = cand
            continue
        m = re.search(r"^Format\s*:\s*(.+)$", s, re.IGNORECASE)
        if m and not audio and 'Audio' in text:
            cand = m.group(1).strip()
            if cand:
                audio = cand
            continue
        m = re.search(r"^Width\s*:\s*(\d+)", s, re.IGNORECASE)
        if m and not width:
            width = int(m.group(1))
            continue
        m = re.search(r"^Height\s*:\s*(\d+)", s, re.IGNORECASE)
        if m and not height:
            height = int(m.group(1))
            continue
    std = None
    if height:
        if height >= 2160:
            std = '2160p'
        elif height >= 1440:
            std = '1440p'
        elif height >= 1080:
            std = '1080p'
        elif height >= 720:
            std = '720p'
    return video, audio, std

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--api-url', required=True)
    p.add_argument('--api-token')
    p.add_argument('--limit', type=int, default=10)
    p.add_argument('--region', default="")
    p.add_argument('--language', default="")
    p.add_argument('--subtitleType', default="")
    p.add_argument('--imdbUrl', default="")
    p.add_argument('--doubanUrl', default="")
    p.add_argument('--isAnonymous', action='store_true')
    p.add_argument('--dry-run', action='store_true')
    p.add_argument('--no-proxy', action='store_true')
    p.add_argument('--timeout', type=int, default=30)
    args = p.parse_args()

    db = get_database_config()
    conn = pymysql.connect(host=db['host'], port=db['port'], user=db['user'], password=db['password'], database=db['database'], cursorclass=pymysql.cursors.DictCursor)
    rows = fetch_pending(conn, args.limit)
    overrides = {
        "region": args.region,
        "language": args.language,
        "subtitleType": args.subtitleType,
        "imdbUrl": args.imdbUrl,
        "doubanUrl": args.doubanUrl,
        "isAnonymous": args.isAnonymous,
    }
    headers = {"Content-Type": "application/json"}
    if args.api_token:
        headers["Authorization"] = f"Bearer {args.api_token}"
    session = requests.Session()
    proxies = None
    host = urlparse(args.api_url).hostname or ""
    if args.no_proxy or host in ("127.0.0.1", "localhost"):
        session.trust_env = False
        proxies = {"http": None, "https": None}
    for r in rows:
        payload = make_payload(r, overrides)
        if args.dry_run:
            print(json.dumps(payload, ensure_ascii=False))
            continue
        try:
            resp = session.post(args.api_url, headers=headers, json=payload, timeout=args.timeout, proxies=proxies)
            if resp.ok:
                mark_uploaded(conn, r['id'])
                print(json.dumps({"id": r['id'], "status": "uploaded"}))
            else:
                print(json.dumps({"id": r['id'], "status": "failed", "code": resp.status_code, "text": resp.text[:200]}))
        except requests.exceptions.ProxyError as e:
            print(json.dumps({"id": r['id'], "status": "failed", "error": "proxy_error", "detail": str(e)[:200]}))
        except requests.exceptions.ConnectionError as e:
            print(json.dumps({"id": r['id'], "status": "failed", "error": "connection_error", "detail": str(e)[:200]}))
    conn.close()

if __name__ == '__main__':
    main()
