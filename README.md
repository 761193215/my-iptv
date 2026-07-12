# 自用 IPTV 订阅生成器

自动从多个公开仓库抓取直播源，按 **内地央视 / 港澳台 / 韩国** 分类合并，剔除失效占位符（如 `{BEIJINGTV}`）、海外新闻台和购物台，生成一个可在手机订阅的 `iptv.m3u`。

当前产出：**288 个频道**（内地央视 242 / 港澳台 26 / 韩国 20），均不低于 1080P（含未标注保留项）。

## 文件说明

| 文件 | 作用 |
|------|------|
| `build_iptv.py` | 主脚本，零依赖（仅 Python 标准库） |
| `iptv.m3u` | 生成的订阅文件 |
| `.github/workflows/update.yml` | GitHub Actions，每天自动重跑脚本并提交 |
| `README.md` | 本说明 |

## 快速开始

```bash
python build_iptv.py                 # 抓取并合并（默认带国内代理前缀）
python build_iptv.py --no-proxy      # 直连 GitHub（网络好时用）
python build_iptv.py --check         # 额外校验链接可达性，剔除死链（慢，几分钟）
```

跑完生成 `iptv.m3u`。

## 在手机上播放

**方式一：直接传文件**（最快）
把 `iptv.m3u` 发到手机（微信/网盘/邮件均可），用 **影视仓** 或 **VLC** 打开该文件即可。缺点：换源后要重新传。

**方式二：URL 订阅**（推荐，自动更新）
见下方「托管到 GitHub」。手机里填一个 raw 链接，以后脚本更新了，手机刷新就同步。

## 托管到 GitHub（推荐：一次配置，每天自动更新）

1. 在 GitHub **新建一个公开仓库**（例如 `my-iptv`）
2. 把 `build_iptv.py`、`.github/workflows/update.yml`、`README.md` 推上去
3. 首次去仓库的 **Actions** 页 → 选「更新 IPTV 订阅」→ **Run workflow** 手动跑一次
   （之后每天凌晨自动跑）
4. 跑完后仓库里会生成 `iptv.m3u`，点开它 → 右上角 **Raw** 按钮 → 复制地址，形如：
   ```
   https://raw.githubusercontent.com/你的用户名/my-iptv/main/iptv.m3u
   ```
5. 手机 **影视仓**：「添加订阅」→ 粘贴上面这个 raw 链接 → 保存。完成。

之后你什么都不用管，GitHub 每天自动抓最新源、剔除死链、更新文件，手机刷新订阅即同步。

## 配置调整（改 `build_iptv.py` 顶部）

| 配置项 | 说明 |
|--------|------|
| `SOURCES` | 源列表，可增删；每个源指定 `category`（内地央视/港澳台/韩国） |
| `PROXY_PREFIX` | 国内代理前缀；能直连就改成 `""` |
| `EXCLUDE_KEYWORDS` | 海外台黑名单（VOA/BBC/CNN 等） |
| `SHOPPING_KEYWORDS` | 购物台关键词，不想剔除就清空列表 |
| `NAME_MAP` | 英文台名 → 中文名映射 |
| `MAX_SOURCES_PER_CHANNEL` | 每个频道保留几个备用源（按清晰度排序） |
| `MIN_RESOLUTION` | 最低清晰度，低于此值的源丢弃（默认 `1080`，即只要 1080P 及以上） |
| `KEEP_UNLABELED` | 名称未标注分辨率的源是否保留（`True`=保留未标注的；`False`=只留明确≥`MIN_RESOLUTION` 的） |
| `EPG_URL` | 节目单地址，拉不到也不影响播放 |

**想加地区**：在 `SOURCES` 里加一条 iptv-org 对应国家的文件即可，例如：
```python
{"name": "日本", "url": "https://raw.githubusercontent.com/iptv-org/iptv/master/streams/jp.m3u", "category": "日本"},
```
（记得在分类统计、`cat_order` 里加上新分类）

## 常见问题

- **某台黑屏/转圈**：该源失效了，换列表里的备用源；或重跑脚本（上游仓库会更新源）
- **全部抓取失败**：网络问题，确认能否访问 `raw.githubusercontent.com`，必要时保留默认代理前缀
- **`--check` 很慢**：逐条探测链接，几百条要几分钟，平时不用，偶尔清理死链时跑一次
- **想保留购物台**：把 `SHOPPING_KEYWORDS = []` 改成空列表
- **代理前缀失效**：换一个，如 `https://ghfast.top/` 或 `https://mirror.ghproxy.com/`

## 频道来源

- [iptv-org/iptv](https://github.com/iptv-org/iptv)（全球最大，按国家分文件）
- [mytv-android/China-TV-Live-M3U8](https://github.com/mytv-android/China-TV-Live-M3U8)（内地，带中文台标）
- [Free-TV/IPTV](https://github.com/Free-TV/IPTV)（香港）

均为公开仓库，版权归原作者所有。请仅观看你有权访问的内容。
