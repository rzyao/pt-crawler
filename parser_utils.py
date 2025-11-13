import hashlib
import re
from urllib.parse import urljoin

import bencodepy
from bs4 import BeautifulSoup
from bs4.element import Tag

def absolute_url(base_url: str, href: str) -> str:
    href = href.strip()
    if href.startswith('http://') or href.startswith('https://'):
        return href
    return urljoin(base_url.rstrip('/') + '/', href)

def get_headers(cookie: str | None, user_agent: str | None) -> dict:
    headers = {
        'User-Agent': user_agent or 'PTCrawler/1.0 (+https://example.org)'
    }
    if cookie:
        headers['Cookie'] = cookie
    return headers

def find_detail_links(soup: BeautifulSoup, base_url: str) -> list[str]:
    links = set()
    for a in soup.find_all('a', href=True):
        href = a['href']
        if any(x in href for x in ['details.php?id=', '/details/', 'view.php?id=']):
            links.add(absolute_url(base_url, href))
    return list(links)

def find_torrent_link(soup: BeautifulSoup, base_url: str) -> str | None:
    # Common patterns: download.php?id=, direct .torrent
    for a in soup.find_all('a', href=True):
        href = a['href']
        if 'download.php?id=' in href or href.endswith('.torrent'):
            return absolute_url(base_url, href)
    return None

import os
def ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)

def extract_descr_html(soup: BeautifulSoup) -> str:
    selectors = ['#kdescr', '#descr', '.descr', '.description', '#description']
    for sel in selectors:
        node = soup.select_one(sel)
        if node:
            return str(node)
    body = soup.find('body')
    return str(body) if body else ''

def extract_description(soup: BeautifulSoup) -> str | None:
    node = soup.select_one('#kdescr') or soup.select_one('#descr') or soup.select_one('.descr')
    if not node:
        return None
    for fs in node.find_all('fieldset'):
        fs.unwrap()
    return node.decode_contents() or None

def extract_imdb(text: str) -> str | None:
    m = re.search(r'https?://www\.imdb\.com/title/tt\d+', text, re.I)
    return m.group(0) if m else None

def decode_str(b: bytes) -> str:
    for enc in ('utf-8', 'utf-8-sig', 'latin-1'):
        try:
            return b.decode(enc)
        except Exception:
            continue
    return b.decode('utf-8', errors='ignore')

def compute_info_hash(info_dict: dict) -> tuple[str, str]:
    # Returns (version, hexdigest). v1 uses SHA1; v2 uses SHA256
    meta_version = info_dict.get(b'meta version')
    encoded = bencodepy.encode(info_dict)
    if meta_version == 2:
        digest = hashlib.sha256(encoded).hexdigest()
        return ('v2', digest)
    digest = hashlib.sha1(encoded).hexdigest()
    return ('v1', digest)

def parse_torrent(torrent_bytes: bytes) -> dict:
    d = bencodepy.decode(torrent_bytes)
    if not isinstance(d, dict) or b'info' not in d:
        raise ValueError('Invalid torrent: missing info dict')
    info = d[b'info']
    version, infohash = compute_info_hash(info)

    name = decode_str(info.get(b'name', b'')).strip() or 'unnamed'
    files = []
    total_size = 0
    if b'files' in info and isinstance(info[b'files'], list):
        for f in info[b'files']:
            length = int(f.get(b'length', 0))
            path = '/'.join(decode_str(p) for p in f.get(b'path', []))
            files.append({'path': path, 'length': length})
            total_size += length
    else:
        length = int(info.get(b'length', 0))
        files.append({'path': name, 'length': length})
        total_size = length

    return {
        'meta_version': version,
        'info_hash': infohash,
        'name': name,
        'files': files,
        'size': total_size,
    }

def extract_text_from_td_sibling(soup: BeautifulSoup, text: str) -> str | None:
    td_tag = soup.find('td', string=re.compile(text))
    if td_tag:
        sibling = td_tag.find_next_sibling('td')
        if sibling:
            return sibling.get_text(strip=True)
    return None

def extract_title(soup: BeautifulSoup) -> str | None:
    h = soup.find('h1', id='top')
    if not h:
        return None
    t = h.get_text(' ', strip=True)
    t = re.sub(r'\[\s*(免费|免費)\s*\]', '', t)
    t = re.sub(r'(剩余时间|剩餘時間)：.*', '', t)
    t = re.sub(r'\s+', ' ', t).strip()
    return t or None

def extract_subtitle(soup: BeautifulSoup) -> str | None:
    for tr in soup.find_all('tr'):
        th = tr.find('td', class_='rowhead')
        if th and ('副标题' in th.get_text(strip=True) or '副標題' in th.get_text(strip=True)):
            td = tr.find('td', class_='rowfollow')
            if td:
                return td.get_text(strip=True)
    tbody = soup.find('tbody')
    if tbody:
        trs = tbody.find_all('tr')
        if len(trs) >= 2:
            tds = trs[1].find_all('td')
            if tds:
                return tds[-1].get_text(strip=True)
    return None

def _normalize_label(label: str | None) -> str | None:
    if not label:
        return None
    label = label.strip().replace(':', '').replace('：', '')
    if '大小' in label:
        return 'size'
    if '类型' in label or '類型' in label or '类别' in label or '類別' in label:
        return 'category'
    if '媒介' in label or '音频类' in label or '音頻類' in label or '音訊類' in label:
        return 'medium'
    if '音频编码' in label or '音頻編碼' in label or '音訊編碼' in label:
        return 'audiocodec'
    if '视频编码' in label or '視頻編碼' in label or '視訊編碼' in label or label == '编码' or label == '編碼':
        return 'video_codec'
    if '分辨率' in label or '标准' in label or '解析度' in label or '標準' in label:
        return 'standard'
    if '制作组' in label or '製作組' in label:
        return 'production_team'
    return None

def _parse_size_text(s: str) -> int | None:
    m = re.search(r'([\d.]+)\s*([KMGT]?B)', s, re.IGNORECASE)
    if not m:
        return None
    v, u = m.groups()
    v = float(v)
    u = u.upper()
    if u == 'KB':
        return int(v * 1024)
    if u == 'MB':
        return int(v * 1024**2)
    if u == 'GB':
        return int(v * 1024**3)
    if u == 'TB':
        return int(v * 1024**4)
    return None

def extract_basic_info(soup: BeautifulSoup) -> dict:
    result: dict[str, str] = {}
    target_td: Tag | None = None
    for tr in soup.find_all('tr'):
        th = tr.find('td', class_='rowhead')
        if th and ('基本信息' in th.get_text(strip=True) or '基本資訊' in th.get_text(strip=True)):
            target_td = tr.find('td', class_='rowfollow')
            break
    if not target_td:
        tbody = soup.find('tbody')
        if tbody:
            trs = tbody.find_all('tr')
            if len(trs) >= 4:
                target_td = trs[3].find('td')
                if not target_td:
                    return result
            else:
                return result
    current_key: str | None = None
    for node in target_td.children:
        if isinstance(node, Tag) and node.name == 'b':
            label = node.get('title') or node.get_text(strip=True)
            key = _normalize_label(label)
            current_key = key
            if current_key and current_key not in result:
                result[current_key] = ''
            continue
        text = ''
        if isinstance(node, Tag):
            text = node.get_text(strip=True)
        else:
            text = str(node).strip()
        text = text.replace('\xa0', ' ').strip()
        if current_key and text:
            if result[current_key]:
                result[current_key] += ' '
            result[current_key] += text
    for k in list(result.keys()):
        result[k] = result[k].strip()
    if 'size' in result:
        size_bytes = _parse_size_text(result['size'])
        if size_bytes is not None:
            result['size_bytes'] = size_bytes
    return result

def extract_tags(soup: BeautifulSoup) -> str | None:
    for tr in soup.find_all('tr'):
        th = tr.find('td', class_='rowhead')
        if th and ('标签' in th.get_text(strip=True) or '標籤' in th.get_text(strip=True) or '標簽' in th.get_text(strip=True)):
            td = tr.find('td', class_='rowfollow')
            if not td:
                return None
            spans = td.find_all('span')
            texts = [s.get_text(strip=True) for s in spans if s.get_text(strip=True)]
            if texts:
                return ','.join(texts)
            return td.get_text(strip=True) or None
    tbody = soup.find('tbody')
    if tbody:
        trs = tbody.find_all('tr')
        for tr in trs:
            tds = tr.find_all('td')
            if not tds:
                continue
            head_text = tds[0].get_text(strip=True)
            if any(lbl in head_text for lbl in ['标签','標籤','標簽']):
                td = tds[-1]
                spans = td.find_all('span')
                texts = [s.get_text(strip=True) for s in spans if s.get_text(strip=True)]
                if texts:
                    return ','.join(texts)
                return td.get_text(strip=True) or None
        if len(trs) >= 3:
            tds = trs[2].find_all('td')
            if len(tds) >= 2:
                td = tds[1]
                spans = td.find_all('span')
                texts = [s.get_text(strip=True) for s in spans if s.get_text(strip=True)]
                if texts:
                    return ','.join(texts)
                return td.get_text(strip=True) or None
    return None
