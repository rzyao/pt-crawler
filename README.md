# PT Crawler (Python)

独立的 PT 站点爬虫脚本：抓取列表页，解析详情页，下载 `.torrent` 并提取基础元数据（`name`、`info_hash`、`size`、`files`、`imdb`）。与当前 PHP 项目无关，可单独运行。

使用步骤（Windows）：

1. 创建虚拟环境并安装依赖：
   - `python -m venv scripts\pt-crawler\.venv`
   - `scripts\pt-crawler\.venv\Scripts\python.exe -m pip install -r scripts\pt-crawler\requirements.txt`
2. 配置与运行：
   - 可选：复制示例配置 `scripts\pt-crawler\settings.example.json` 为 `scripts\pt-crawler\settings.json` 并按需修改
   - **默认配置加载**：若未通过 `--config` 指定配置文件，脚本将自动尝试加载与 `pt_crawler.py` 同目录下的 `settings.json`。
   - 使用配置运行：
     - `scripts\pt-crawler\.venv\Scripts\python.exe scripts\pt-crawler\pt_crawler.py --config scripts\pt-crawler\settings.json`
   - 无参数自动加载默认配置运行：
     - `scripts\pt-crawler\.venv\Scripts\python.exe scripts\pt-crawler\pt_crawler.py`
   - 命令行覆盖配置：
     - `scripts\pt-crawler\.venv\Scripts\python.exe scripts\pt-crawler\pt_crawler.py --config scripts\pt-crawler\settings.json --pages 1 --delay 0.2`

主要参数：

- `--config` 配置文件路径（JSON），若提供则从配置加载默认值；若未提供，将尝试加载脚本同目录下的 `settings.json`。
- `--base-url` 站点基础 URL（可在配置或命令行提供，必需其一）
- `--list-path` 列表页路径（默认配置 `/torrents.php`）
- `--pages` 抓取页数（默认配置 1）
- `--cookie` 认证 Cookie（可选）
- `--user-agent` UA 字符串（可选）
- `--out-dir` 输出目录（默认 `scripts/pt-crawler/output`）
- `--delay` 请求间延迟秒数（默认 0.5）
- `--allow-v2` 允许保存 v2/hybrid 种子（命令行提供则优先）

输出内容：

- `output/torrents/*.torrent` 下载的种子文件
- `output/metadata.jsonl` 每行一个 JSON 记录，包含详情 URL、下载 URL、`info_hash`、`name`、`size`、`files`、`imdb` 等

注意事项：

- 站点结构可能不同，脚本使用通用选择器（`details.php?id=`、`download.php?id=`、`.torrent`）。如需适配特定站，建议修改选择器逻辑。
- 合理设置延迟，避免频繁请求对方站点；遵守站点规则与法律法规。
 - 配置与命令行优先级：命令行参数优先于配置文件；未在命令行提供的参数将从配置文件填充。