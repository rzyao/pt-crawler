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
    """
    根据提供的 cookie 和 user_agent 构造 HTTP 请求头字典。

    参数:
        cookie (str | None): 可选的 Cookie 字符串。
        user_agent (str | None): 可选的 User-Agent 字符串。

    返回:
        dict: 包含 User-Agent 和（如有）Cookie 的请求头字典。
    """
    headers = {
        'User-Agent': user_agent or 'PTCrawler/1.0 (+https://example.org)'
    }
    if cookie:
        headers['Cookie'] = cookie
    return headers

def find_detail_links(soup: BeautifulSoup, base_url: str) -> list[str]:
    """
    从 BeautifulSoup 对象中提取所有详情页链接。

    遍历所有带 href 的 <a> 标签，若链接中包含 'details.php?id='、'/details/' 或 'view.php?id=' 等关键字，
    则将其转换为绝对 URL 并去重后返回。

    参数:
        soup (BeautifulSoup): 待解析的 HTML 文档对象。
        base_url (str): 用于构造绝对 URL 的基础地址。

    返回:
        list[str]: 去重后的详情页绝对链接列表。
    """
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
    """
    从 BeautifulSoup 对象中提取描述 HTML 内容。

    优先查找 #kdescr、#descr、.descr、.description、#description 等元素，
    若找到则返回该节点的 HTML 字符串；否则返回整个 <body> 的 HTML 字符串；
    若连 <body> 都不存在，则返回空字符串。
    """
    selectors = ['#kdescr', '#descr', '.descr', '.description', '#description']
    for sel in selectors:
        node = soup.select_one(sel)
        if node:
            return str(node)
    body = soup.find('body')
    return str(body) if body else ''

def extract_mediainfo(soup: BeautifulSoup) -> str | None:
    """
    从 BeautifulSoup 对象中提取 MediaInfo 文本。

    查找第一个 <pre> 标签，若存在则返回其完整文本内容（保留换行），否则返回 None。
    """
    pre = soup.find('pre')
    if not pre:
        return None
    return pre.get_text('\n', strip=False) or None

def extract_description(soup: BeautifulSoup) -> str | None:
    """
    从 BeautifulSoup 对象中提取描述内容。

    优先查找 #kdescr、#descr、.descr 元素，移除其中不包含“官组作品”或“原作者”文本的 <fieldset> 标签，
    返回处理后的 HTML 字符串；若未找到目标节点或结果为空，则返回 None。
    """
    node = soup.select_one('#kdescr') or soup.select_one('#descr') or soup.select_one('.descr')
    if not node:
        return None
    def _keep_fieldset(fs: Tag) -> bool:
        txt = fs.get_text(strip=True)
        if txt is None:
            txt = ''
        keys = ['官组作品', '原作者']
        return any(k in txt for k in keys)
    for fs in list(node.find_all('fieldset')):
        if not _keep_fieldset(fs):
            fs.decompose()
    return node.decode_contents() or None

def extract_imdb(text: str) -> str | None:
    """
    从给定文本中提取第一个 IMDb 链接。

    参数:
        text (str): 待搜索的文本。

    返回:
        str | None: 匹配到的完整 IMDb URL；若未找到则返回 None。
    """
    m = re.search(r'https?://www\.imdb\.com/title/tt\d+', text, re.I)
    return m.group(0) if m else None

def decode_str(b: bytes) -> str:
    """
    尝试以多种编码（utf-8、utf-8-sig、latin-1）解码字节串，若均失败则以 utf-8 忽略错误方式解码。
    """
    for enc in ('utf-8', 'utf-8-sig', 'latin-1'):
        try:
            return b.decode(enc)
        except Exception:
            pass
    return b.decode('utf-8', errors='ignore')

def compute_info_hash(info_dict: dict) -> tuple[str, str]:
    """
    根据 info 字典计算种子文件的 info_hash。

    参数:
        info_dict (dict): 种子 info 字典，可能包含 meta version 字段。

    返回:
        tuple[str, str]: (版本, 十六进制哈希)。版本为 'v1' 时使用 SHA1，'v2' 时使用 SHA256。
    """
    # Returns (version, hexdigest). v1 uses SHA1; v2 uses SHA256
    meta_version = info_dict.get(b'meta version')
    encoded = bencodepy.encode(info_dict)
    if meta_version == 2:
        digest = hashlib.sha256(encoded).hexdigest()
        return ('v2', digest)
    digest = hashlib.sha1(encoded).hexdigest()
    return ('v1', digest)

def parse_torrent(torrent_bytes: bytes) -> dict:
    """
    解析种子文件字节流，提取元信息并返回结构化字典。

    参数:
        torrent_bytes (bytes): 种子文件原始字节内容。

    返回:
        dict: 包含以下字段的字典：
            - meta_version: 种子版本（'v1' 或 'v2'）
            - info_hash: 十六进制 info 哈希值
            - name: 种子名称
            - files: 文件列表，每个元素为 {'path': 文件路径, 'length': 文件大小}
            - size: 总大小（字节）

    异常:
        ValueError: 若种子文件无效或缺失 info 字典。
    """
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
    """
    从 BeautifulSoup 对象中查找第一个文本内容与给定正则匹配的 <td> 标签，
    并返回其下一个兄弟 <td> 标签中的纯文本内容（去除首尾空白）。
    
    参数:
        soup (BeautifulSoup): 待解析的 HTML 文档对象。
        text (str): 用于匹配目标 <td> 文本的正则表达式字符串。
    
    返回:
        str | None: 匹配到的兄弟 <td> 中的纯文本内容；若未找到则返回 None。
    """
    td_tag = soup.find('td', string=re.compile(text))
    if td_tag:
        sibling = td_tag.find_next_sibling('td')
        if sibling:
            return sibling.get_text(strip=True)
    return None

def extract_title(soup: BeautifulSoup) -> str | None:
    """
    从 BeautifulSoup 对象中提取标题文本。

    优先查找 id 为 'top' 的 <h1> 标签，获取其纯文本内容后，
    移除其中的“免费/免費”标记和“剩余时间/剩餘時間”信息，
    并将多余空白压缩为单个空格，最终返回处理后的标题字符串；
    若未找到对应 <h1> 或处理结果为空，则返回 None。
    """
    h = soup.find('h1', id='top')
    if not h:
        return None
    t = h.get_text(' ', strip=True)
    t = re.sub(r'\[\s*(免费|免費)\s*\]', '', t)
    t = re.sub(r'(剩余时间|剩餘時間)：.*', '', t)
    t = re.sub(r'\s+', ' ', t).strip()
    return t or None

def extract_subtitle(soup: BeautifulSoup) -> str | None:
    """
    从 BeautifulSoup 对象中提取副标题文本。

    优先查找包含“副标题”或“副標題”关键字的 <tr> 行，
    返回对应 <td class="rowfollow"> 中的纯文本内容；
    若未找到，则尝试在 <tbody> 的第二行最后一个 <td> 中提取文本。
    若均无果，返回 None。
    """
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
    """
    从 BeautifulSoup 对象中提取种子基本信息（如大小、类型、编码等）。

    优先查找包含“基本信息”或“基本資訊”的 <tr> 行，提取对应 <td class="rowfollow"> 中的内容；
    若未找到，则尝试在 <tbody> 的第四行中提取。
    将 <b> 标签作为字段名，后续文本作为字段值，最终返回字段名到字段值的映射字典。
    若解析到“大小”字段，会自动补充对应的字节数到 'size_bytes' 键。
    """
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
    """
    从 BeautifulSoup 对象中提取标签（tags）文本。

    优先查找包含“标签”、“標籤”或“標簽”关键字的 <tr> 行，
    提取对应 <td class="rowfollow"> 中所有 <span> 的文本并以逗号连接；
    若无 <span> 则直接返回该 <td> 的纯文本。
    若未找到对应行，则尝试在 <tbody> 的第三行第二个 <td> 中提取。
    若均无果，返回 None。
    """
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
