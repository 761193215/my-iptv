#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_iptv.py — 自动抓取多个公开 IPTV 源，按地区分类合并成你自己的订阅列表。

功能：
  1. 从配置的多个 GitHub 仓库抓取 M3U 源（支持国内代理前缀）
  2. 按「内地央视 / 港澳台 / 韩国」分类
  3. 剔除占位符链接（如 {BEIJINGTV}）、海外新闻台、购物台
  4. 同名频道去重，优先保留高清源
  5. 输出带 EPG 节目单 + 台标的 iptv.m3u
  6. 可选：--check 开启链接可达性校验，剔除死链（多线程，较慢）

零依赖，仅用 Python 标准库。
用法：
  python build_iptv.py              # 抓取并合并，输出 iptv.m3u
  python build_iptv.py --check      # 同上，并校验链接可达性（慢）
  python build_iptv.py --no-proxy   # 不使用代理前缀，直连 GitHub
"""

import argparse
import re
import ssl
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse

# ============================================================
# 配置区：在这里增删源、调整分类
# ============================================================

# 国内访问 raw.githubusercontent.com 可能慢/被墙，默认套一层代理前缀。
# 若你网络可直连，用 --no-proxy 关掉，或把这里改成 ""。
PROXY_PREFIX = "https://gh-proxy.com/"

# 源列表：每个源给一个默认分类。脚本会再按关键词二次校正/剔除。
# name       : 备注名
# url        : raw 地址（无需手动加代理，脚本会自动套 PROXY_PREFIX）
# category   : 默认分类 内地央视 / 港澳台 / 韩国
SOURCES = [
    {
        "name": "iptv-org 中国大陆",
        "url": "https://raw.githubusercontent.com/iptv-org/iptv/master/streams/cn.m3u",
        "category": "内地央视",
    },
    {
        "name": "iptv-org 中国香港",
        "url": "https://raw.githubusercontent.com/iptv-org/iptv/master/streams/hk.m3u",
        "category": "港澳台",
    },
    {
        "name": "iptv-org 中国台湾",
        "url": "https://raw.githubusercontent.com/iptv-org/iptv/master/streams/tw.m3u",
        "category": "港澳台",
    },
    {
        "name": "iptv-org 韩国",
        "url": "https://raw.githubusercontent.com/iptv-org/iptv/master/streams/kr.m3u",
        "category": "韩国",
    },
    {
        "name": "mytv-android 内地(中文台标)",
        "url": "https://raw.githubusercontent.com/mytv-android/China-TV-Live-M3U8/main/iptv.m3u",
        "category": "内地央视",
    },
    {
        "name": "Free-TV 香港",
        "url": "https://raw.githubusercontent.com/Free-TV/IPTV/master/playlists/playlist_hong_kong.m3u8",
        "category": "港澳台",
    },
]

# 输出文件
OUTPUT_FILE = "iptv.m3u"

# EPG 节目单地址（播放器会自动拉取，拉不到也不影响播放）
EPG_URL = "https://e.erw.cc/all.xml.gz"

# 同名频道最多保留几个备用源（去重用，按清晰度排序）
MAX_SOURCES_PER_CHANNEL = 3

# 清晰度过滤：低于此值的源丢弃（1080 = 只要 1080P 及以上）
MIN_RESOLUTION = 1080
# 名称未标注分辨率的源是否保留（True=保留未标注的；False=只留明确标注≥MIN_RESOLUTION 的）
KEEP_UNLABELED = True

# 剔除关键词：命中则丢弃（用户只要内地/港澳台/韩国，海外新闻台不要）
EXCLUDE_KEYWORDS = [
    "VOA", "美国之音", "Deutsche Welle", "France 24", "NHK World",
    "RT News", "RT America", "BBC", "Al Jazeera", "Sky News",
    "Fox News", "CNN", "CNBC", "Bloomberg", "ABC News", "CBS News",
    "CNA", "Euronews", "TRT World", "CGTN America",
]

# 购物台剔除（韩国购物台特别多，默认剔除；想保留把列表清空）
SHOPPING_KEYWORDS = ["Shopping", "Shop", "购物", "홈쇼핑", "쇼핑", "HomeShopping", "MyShop"]

# 常见台英文名 -> 中文名映射（让内地/常见台显示中文名，更友好）
NAME_MAP = {
    "CCTV-1": "CCTV-1 综合", "CCTV-2": "CCTV-2 财经", "CCTV-3": "CCTV-3 综艺",
    "CCTV-4": "CCTV-4 中文国际", "CCTV-5": "CCTV-5 体育", "CCTV-5+": "CCTV-5+ 体育赛事",
    "CCTV-6": "CCTV-6 电影", "CCTV-7": "CCTV-7 国防军事", "CCTV-8": "CCTV-8 电视剧",
    "CCTV-9": "CCTV-9 纪录", "CCTV-10": "CCTV-10 科教", "CCTV-11": "CCTV-11 戏曲",
    "CCTV-12": "CCTV-12 社会与法", "CCTV-13": "CCTV-13 新闻", "CCTV-14": "CCTV-14 少儿",
    "CCTV-15": "CCTV-15 音乐", "CCTV-16": "CCTV-16 奥林匹克", "CCTV-17": "CCTV-17 农业农村",
    "CGTN": "CGTN 英语", "CGTN Documentary": "CGTN 纪录",
    "RTHK TV 31": "港台电视31", "RTHK TV 32": "港台电视32", "RTHK TV 33": "港台电视33",
    "HOY TV": "HOY TV", "HOY Infotainment": "HOY 资讯",
    "Phoenix Chinese Channel": "凤凰中文", "Phoenix InfoNews Channel": "凤凰资讯",
    "KBS World": "KBS World", "Arirang TV": "Arirang TV", "YTN": "YTN",
    "TV Chosun": "TV朝鲜", "Channel A": "Channel A",
}


# ============================================================
# 抓取
# ============================================================

def build_url(raw_url, use_proxy):
    """给 github raw 地址套代理前缀（仅对 raw.githubusercontent.com）。"""
    if use_proxy and PROXY_PREFIX and "raw.githubusercontent.com" in raw_url:
        return PROXY_PREFIX + raw_url
    return raw_url


def fetch_text(url, timeout=30):
    """下载文本，返回 (文本, 错误信息)。"""
    ctx = ssl.create_default_context()
    # 部分自签名 CDN 证书不全，这里放宽校验以保证抓取成功率
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 build_iptv"})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            data = resp.read()
            # iptv-org / github 都是 utf-8；个别源可能 gbk，容错
            try:
                return data.decode("utf-8"), None
            except UnicodeDecodeError:
                return data.decode("utf-8", errors="ignore"), None
    except Exception as e:
        return "", f"{e}"


# ============================================================
# 解析 M3U
# ============================================================

# 提取 tvg-xxx 等属性
ATTR_RE = re.compile(r'([a-zA-Z0-9_-]+)="([^"]*)"')


def parse_attrs(extinf_line):
    """从 #EXTINF 行提取属性字典和频道名。"""
    # #EXTINF:-1 tvg-name="X" tvg-logo="Y" group-title="Z",频道名
    attrs = {}
    m = ATTR_RE.findall(extinf_line)
    for k, v in m:
        attrs[k.lower()] = v
    # 频道名：最后一个逗号之后
    comma = extinf_line.rfind(",")
    name = extinf_line[comma + 1:].strip() if comma != -1 else ""
    return attrs, name


def parse_m3u(text):
    """解析 M3U 文本，返回 (头属性行, [channel,...])。channel 为 dict。"""
    header = "#EXTM3U"
    channels = []
    current = None
    for line in text.splitlines():
        line = line.rstrip("\n").rstrip("\r")
        if not line.strip():
            continue
        if line.startswith("#EXTM3U"):
            header = line
            continue
        if line.startswith("#EXTINF"):
            attrs, name = parse_attrs(line)
            current = {
                "attrs": attrs,
                "name": name,
                "url": "",
                "vlcopts": [],  # 如 http-referrer
            }
            continue
        if line.startswith("#EXTVLCOPT"):
            if current is not None:
                current["vlcopts"].append(line)
            continue
        if line.startswith("#"):
            # 其他注释行忽略
            continue
        # 非 # 开头 → 视为 URL
        if current is not None:
            current["url"] = line.strip()
            channels.append(current)
            current = None
    return header, channels


# ============================================================
# 分类 / 过滤
# ============================================================

def normalize_name(name):
    """归一化频道名用于去重：去分辨率/标记后缀、统一大小写。"""
    # 去 (1080p) [Geo-blocked] [Not 24/7] 等尾巴
    n = re.sub(r"\s*[\(\[].*?[\)\]]\s*", "", name)
    return n.strip().lower()


def extract_resolution(name):
    """从名称提取分辨率用于排序，越大越优先。"""
    m = re.search(r"(\d{3,4})p", name)
    if m:
        return int(m.group(1))
    if "4K" in name or "4k" in name:
        return 2160
    if "8K" in name:
        return 4320
    return 0


def is_placeholder_url(url):
    """是否为占位符（非 http 开头，如 {BEIJINGTV}）。"""
    if not url:
        return True
    return not (url.startswith("http://") or url.startswith("https://"))


def hit_any(text, keywords):
    low = text.lower()
    return any(k.lower() in low for k in keywords)


def localize_name(name):
    """英文常见台名 -> 中文名（精确匹配基础名，避免 CCTV-1 误伤 CCTV-10）。"""
    # 剥离尾部 (1080p) [Geo-blocked] 等后缀，得到基础名再查表
    base = re.sub(r"\s*[\(\[].*?[\)\]]\s*", "", name).strip()
    if base in NAME_MAP:
        suffix = name[len(base):] if name.startswith(base) else ""
        return NAME_MAP[base] + suffix
    return name


def filter_channel(ch, default_category):
    """
    返回该频道应归入的分类，None 表示剔除。
    """
    name = ch["name"]
    url = ch["url"]

    # 1. 占位符 / 无效链接
    if is_placeholder_url(url):
        return None

    # 2. 海外新闻台黑名单
    if hit_any(name, EXCLUDE_KEYWORDS):
        return None

    # 3. 购物台
    if hit_any(name, SHOPPING_KEYWORDS):
        return None

    # 4. 清晰度过滤：明确低于阈值的丢弃；未标注的按 KEEP_UNLABELED 处理
    res = extract_resolution(name)
    if res > 0:
        if res < MIN_RESOLUTION:
            return None
    else:
        if not KEEP_UNLABELED:
            return None

    # 5. 用源默认分类（已足够，iptv-org 按国家分文件）
    return default_category


# ============================================================
# 校验（可选，--check）
# ============================================================

def check_url_reachable(url, vlcopts, timeout=8):
    """短超时探测链接是否可达。返回 True/False。"""
    headers = {"User-Agent": "Mozilla/5.0 build_iptv"}
    # 支持 #EXTVLCOPT:http-referrer=...
    for opt in vlcopts:
        if "http-referrer=" in opt:
            ref = opt.split("=", 1)[1]
            headers["Referer"] = ref
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            # 读一小段就关，m3u8 是文本，读前 512 字节确认是 playlist
            chunk = resp.read(512)
            return True
    except Exception:
        return False


# ============================================================
# 输出
# ============================================================

def write_m3u(channels, path, header_attrs):
    """写出最终 m3u。channels 已分类去重排序。"""
    # 重写头：注入 EPG
    header = '#EXTM3U x-tvg-url="' + EPG_URL + '"'
    lines = [header]
    # 按分类排序输出
    cat_order = {"内地央视": 0, "港澳台": 1, "韩国": 2}
    channels_sorted = sorted(channels, key=lambda c: (cat_order.get(c["category"], 9), c["name"]))

    for ch in channels_sorted:
        attrs = dict(ch["attrs"])
        name = ch["display_name"]
        attrs["group-title"] = ch["category"]
        if "tvg-name" not in attrs or not attrs["tvg-name"]:
            attrs["tvg-name"] = name
        attr_str = " ".join(f'{k}="{v}"' for k, v in attrs.items() if v)
        lines.append(f"#EXTINF:-1 {attr_str},{name}")
        for opt in ch["vlcopts"]:
            lines.append(opt)
        lines.append(ch["url"])
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


# ============================================================
# 主流程
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="自动抓取并合并 IPTV 订阅列表")
    parser.add_argument("--check", action="store_true", help="校验链接可达性（慢，多线程）")
    parser.add_argument("--no-proxy", action="store_true", help="不使用代理前缀，直连 GitHub")
    parser.add_argument("--check-workers", type=int, default=20, help="校验线程数")
    args = parser.parse_args()

    use_proxy = not args.no_proxy

    print("=" * 60)
    print("IPTV 订阅列表生成器")
    print(f"代理前缀: {PROXY_PREFIX if use_proxy else '(直连)'}")
    print(f"链接校验: {'开启' if args.check else '关闭'}")
    print("=" * 60)

    all_channels = []
    stats = {"fetched": 0, "failed": 0}

    # 1. 抓取 + 解析
    for src in SOURCES:
        full_url = build_url(src["url"], use_proxy)
        print(f"\n[抓取] {src['name']}")
        print(f"        {full_url}")
        text, err = fetch_text(full_url)
        if err:
            print(f"        ✗ 失败: {err}")
            stats["failed"] += 1
            continue
        _, channels = parse_m3u(text)
        print(f"        ✓ 解析到 {len(channels)} 条")
        for ch in channels:
            ch["category"] = filter_channel(ch, src["category"])
        all_channels.extend(channels)
        stats["fetched"] += 1

    print(f"\n源抓取完成: 成功 {stats['fetched']}/{len(SOURCES)}，失败 {stats['failed']}")

    # 2. 过滤
    kept = [c for c in all_channels if c["category"] is not None]
    dropped = len(all_channels) - len(kept)
    print(f"过滤: 共 {len(all_channels)} 条，保留 {len(kept)}，剔除 {dropped}（占位符/海外/购物台/低清）")
    labeled_hd = sum(1 for c in kept if extract_resolution(c["name"]) >= MIN_RESOLUTION)
    unlabeled = sum(1 for c in kept if extract_resolution(c["name"]) == 0)
    print(f"  其中明确≥{MIN_RESOLUTION}P: {labeled_hd} 条，未标注分辨率(保留): {unlabeled} 条")

    # 3. 中文化名称
    for ch in kept:
        ch["display_name"] = localize_name(ch["name"])

    # 4. 去重：同名按分辨率排序保留前 N
    groups = {}
    for ch in kept:
        key = normalize_name(ch["display_name"])
        groups.setdefault(key, []).append(ch)
    deduped = []
    for key, items in groups.items():
        items.sort(key=lambda c: extract_resolution(c["name"]), reverse=True)
        deduped.extend(items[:MAX_SOURCES_PER_CHANNEL])
    print(f"去重: {len(kept)} -> {len(deduped)}（每频道最多 {MAX_SOURCES_PER_CHANNEL} 源）")

    # 5. 可选校验
    if args.check:
        print(f"\n[校验] 开始探测 {len(deduped)} 条链接（{args.check_workers} 线程，每条 8s 超时）...")
        results = {}
        with ThreadPoolExecutor(max_workers=args.check_workers) as ex:
            future_map = {
                ex.submit(check_url_reachable, c["url"], c["vlcopts"]): c for c in deduped
            }
            done = 0
            for fut in as_completed(future_map):
                c = future_map[fut]
                try:
                    results[id(c)] = fut.result()
                except Exception:
                    results[id(c)] = False
                done += 1
                if done % 20 == 0:
                    print(f"        已校验 {done}/{len(deduped)}")
        alive = [c for c in deduped if results.get(id(c))]
        dead = len(deduped) - len(alive)
        print(f"校验完成: 可达 {len(alive)}，不可达 {dead}")
        deduped = alive

    # 6. 输出
    write_m3u(deduped, OUTPUT_FILE, None)

    # 分类统计
    cat_count = {}
    for c in deduped:
        cat_count[c["category"]] = cat_count.get(c["category"], 0) + 1

    print("\n" + "=" * 60)
    print(f"✓ 已生成: {OUTPUT_FILE}")
    print(f"  共 {len(deduped)} 个频道（含备用源）")
    for cat in ["内地央视", "港澳台", "韩国"]:
        print(f"    {cat}: {cat_count.get(cat, 0)}")
    print(f"  EPG 节目单: {EPG_URL}")
    print("=" * 60)
    print("\n下一步：把这个文件传到手机用，或推到 GitHub 用 raw 链接订阅。")
    print("详见 README 说明。")


if __name__ == "__main__":
    main()
