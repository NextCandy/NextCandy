#!/usr/bin/env python3
"""Regenerate the live dashboard SVGs for the NextCandy profile README.

Fetches public (non-fork) repositories from the GitHub API concurrently,
computes profile statistics, and renders assets/dashboard-light.svg +
assets/dashboard-dark.svg in a unified Bento Grid design.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

API = "https://api.github.com"
HEADERS = {
    "Accept": "application/vnd.github+json",
    "User-Agent": "nextcandy-profile-dashboard",
}
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
if GITHUB_TOKEN:
    HEADERS["Authorization"] = f"Bearer {GITHUB_TOKEN}"

# Include all public non-fork source repositories (excluding the profile repo itself).
DASHBOARD_EXCLUDED_REPOS = set()

# Fallback descriptions for repos without a GitHub description set
REPO_FALLBACK_DESC = {
    "domainhunter": "RDAP-first 域名监控与安全可注册性检测系统",
    "onekey": "Surge / Shadowrocket 一键部署：Hysteria2 端口跳跃 + Snell v5 + BBR 加固",
    "timeamber": "面向 NAS 的自托管博客、网页归档与内容管理平台 (TanStack Start + Supabase)",
    "content-animator": "交互式内容动效与现代化前端视觉呈现工具",
    "unusedomain": "UnUseDomain.com · 闲置精品域名资产展示米表",
    "dshunter": "自动化域名发现、嗅探与状态追踪工具",
    "dh": "轻量化域名查询与工具链实验原型",
    "dog.do": "🐶 Dog.Do · 极简品牌域名落地页与展示站点",
    "homepage": "极简个人主页与自托管服务导航门户",
}

REPO_SHORT_LABEL = {
    "domainhunter": "Hunter",
    "onekey": "onekey",
    "timeamber": "Amber",
    "content-animator": "Animator",
    "unusedomain": "UnUse",
    "dshunter": "dshunt",
    "dh": "dh",
    "dog.do": "dog.do",
    "homepage": "Home",
}

try:
    BEIJING_TZ = ZoneInfo("Asia/Shanghai")
except ZoneInfoNotFoundError:
    BEIJING_TZ = timezone(timedelta(hours=8), name="Asia/Shanghai")


def fetch_public_repos(username):
    """Return the user's public repos, forks excluded, most recently pushed first."""
    repos, page = [], 1
    while True:
        url = f"{API}/users/{username}/repos?per_page=100&page={page}&sort=pushed&direction=desc"
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=30) as resp:
            batch = json.load(resp)
        if not batch:
            break
        repos.extend(batch)
        if len(batch) < 100:
            break
        page += 1

    projects = [
        r for r in repos
        if (
            not r.get("fork")
            and r.get("name", "").casefold() != username.casefold()
            and r.get("name", "").casefold() not in DASHBOARD_EXCLUDED_REPOS
        )
    ]
    projects.sort(key=lambda r: r.get("pushed_at") or "", reverse=True)
    return projects


def _parse_datetime(value):
    """Parse a GitHub ISO-8601 timestamp and render it in Beijing time."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(BEIJING_TZ)
    except (TypeError, ValueError):
        return None


def _pushed(repo):
    """Parse GitHub's UTC timestamp and render it in Beijing time."""
    parsed = _parse_datetime(repo.get("pushed_at"))
    if parsed is None:
        raise ValueError(f"repository has no valid pushed_at timestamp: {repo.get('name')}")
    return parsed


def fetch_repo_commits_summary(username, repo_name):
    """Return latest commit details + exact total commit count via Link header."""
    import re
    url = f"{API}/repos/{username}/{repo_name}/commits?per_page=1"
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            link_header = resp.headers.get("Link", "")
            commits = json.load(resp)
        if not isinstance(commits, list) or not commits:
            return {"sha": "—", "message": "latest public push", "dt": None, "commit_count": 1}
        m = re.search(r'[?&]page=(\d+)>;\s*rel="last"', link_header)
        total_commits = int(m.group(1)) if m else len(commits)
        commit = commits[0]
        commit_data = commit.get("commit", {})
        lines = [line.strip() for line in (commit_data.get("message") or "").splitlines() if line.strip()]
        subject = lines[0] if lines else "latest public push"
        commit_dt = _parse_datetime(
            commit_data.get("committer", {}).get("date")
            or commit_data.get("author", {}).get("date")
        )
        return {
            "sha": (commit.get("sha") or "")[:7] or "—",
            "message": subject,
            "dt": commit_dt,
            "commit_count": total_commits,
        }
    except (HTTPError, URLError, TimeoutError, IndexError, KeyError, TypeError, json.JSONDecodeError):
        return {"sha": "—", "message": "latest public push", "dt": None, "commit_count": 1}


def profile_stats(username, projects):
    if not projects:
        raise SystemExit("no public source repositories found")
    total = len(projects)

    counts, order = {}, []
    for p in projects:
        lang = p.get("language") or "TXT"
        if lang not in counts:
            order.append(lang)
            counts[lang] = 0
        counts[lang] += 1
    languages = sorted(order, key=lambda l: -counts[l])
    lang_rows = [(l, counts[l]) for l in languages[:5]]

    # Fetch commit summaries concurrently for low latency
    with ThreadPoolExecutor(max_workers=min(8, max(1, len(projects)))) as pool:
        summaries = list(pool.map(lambda p: fetch_repo_commits_summary(username, p["name"]), projects))

    events = []
    for p, commit in zip(projects, summaries):
        name_lower = p["name"].casefold()
        raw_desc = (p.get("description") or "").strip()
        desc = raw_desc or REPO_FALLBACK_DESC.get(name_lower, "NextCandy open-source module")
        events.append({
            "name": p["name"],
            "short": REPO_SHORT_LABEL.get(name_lower, p["name"][:7]),
            "lang": (p.get("language") or "TXT").upper(),
            "dt": commit["dt"] or _pushed(p),
            "branch": p.get("default_branch") or "main",
            "sha": commit["sha"],
            "message": commit["message"],
            "description": desc,
            "homepage": (p.get("homepage") or "").strip(),
            "commit_count": commit.get("commit_count", 1),
        })
    events.sort(key=lambda item: item["dt"], reverse=True)
    recent = events[:6]
    latest = events[0]
    latest_dt = latest["dt"]
    generated_dt = datetime.now(BEIJING_TZ)
    year = generated_dt.year
    active_year = sum(1 for event in events if event["dt"].year == year)
    total_commits = sum(event["commit_count"] for event in events)

    return {
        "total": total,
        "total_commits": total_commits,
        "lang_count": len(counts),
        "langs": lang_rows,
        "active_year": active_year,
        "year": year,
        "latest": latest,
        "latest_dt": latest_dt,
        "generated_dt": generated_dt,
        "recent": recent,
        "events": events,
    }


def assert_readme_source_only(readme_path):
    """Sanity check: the README must reference the dashboard assets we generate."""
    text = Path(readme_path).read_text(encoding="utf-8")
    for needle in ("assets/dashboard-dark.svg", "assets/dashboard-light.svg"):
        if needle not in text:
            raise SystemExit(f"README does not reference {needle}; aborting")


THEMES = {
    "dark": {
        "bg0": "#070B14",
        "bg1": "#0B1120",
        "bg2": "#0F172A",
        "card0": "#111C2D",
        "card1": "#0D1524",
        "inner": "#090F1C",
        "border": "#1E293B",
        "line": "#334155",
        "text": "#F8FAFC",
        "sub": "#CBD5E1",
        "muted": "#64748B",
        "cyan": "#38BDF8",
        "cyan_bg": "#0C2D48",
        "pink": "#F472B6",
        "pink_bg": "#3B0D2C",
        "indigo": "#818CF8",
        "indigo_bg": "#1E1B4B",
        "emerald": "#34D399",
        "emerald_bg": "#062E26",
        "amber": "#FBBF24",
        "amber_bg": "#3B2506",
    },
    "light": {
        "bg0": "#FFFFFF",
        "bg1": "#F8FAFC",
        "bg2": "#F1F5F9",
        "card0": "#FFFFFF",
        "card1": "#F8FAFC",
        "inner": "#F1F5F9",
        "border": "#CBD5E1",
        "line": "#E2E8F0",
        "text": "#0F172A",
        "sub": "#334155",
        "muted": "#64748B",
        "cyan": "#0284C7",
        "cyan_bg": "#E0F2FE",
        "pink": "#DB2777",
        "pink_bg": "#FCE7F3",
        "indigo": "#4F46E5",
        "indigo_bg": "#E0E7FF",
        "emerald": "#059669",
        "emerald_bg": "#D1FAE5",
        "amber": "#D97706",
        "amber_bg": "#FEF3C7",
    },
}


def esc(s):
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def visual_width(s):
    """Estimate visual width in proportional sans units (CJK chars ~1.65x ASCII)."""
    w = 0.0
    for ch in str(s):
        w += 1.0 if ord(ch) < 128 else 1.65
    return w


def visual_truncate(s, max_units):
    """Truncate string cleanly by visual width so CJK text never overflows."""
    text = " ".join(str(s).split()).strip()
    if visual_width(text) <= max_units:
        return text
    out = []
    acc = 0.0
    for ch in text:
        cw = 1.0 if ord(ch) < 128 else 1.65
        if acc + cw > max_units - 1.2:
            break
        out.append(ch)
        acc += cw
    return "".join(out).rstrip() + "…"


def lang_color_pair(lang, t):
    l = lang.upper()
    if l in ("TYPESCRIPT", "TS"):
        return t["cyan"], t["cyan_bg"]
    if l == "GO":
        return t["emerald"], t["emerald_bg"]
    if l in ("SHELL", "SH", "BASH"):
        return t["indigo"], t["indigo_bg"]
    if l == "CSS":
        return t["pink"], t["pink_bg"]
    return t["amber"], t["amber_bg"]


def lang_short(lang):
    l = lang.upper()
    mapping = {
        "TYPESCRIPT": "TS",
        "JAVASCRIPT": "JS",
        "SHELL": "SH",
        "PYTHON": "PY",
    }
    return mapping.get(l, l[:4])


def render_dashboard(username, stats, mode):
    t = THEMES[mode]
    generated_dt = stats["generated_dt"]
    latest = stats["latest"]
    latest_dt = stats["latest_dt"]

    # Top rail metrics
    rail_specs = [
        ("REPOS", f"{stats['total']:02d}", t["cyan"]),
        ("COMMITS", f"{stats['total_commits']}", t["indigo"]),
        ("ACTIVE", f"{stats['active_year']:02d}/{stats['total']:02d}", t["emerald"]),
        ("SYNC DATE", generated_dt.strftime("%m.%d"), t["pink"]),
    ]
    rail_items = []
    for i, (label, val, col) in enumerate(rail_specs):
        rx = 430 + i * 142
        rail_items.append(f"""<g transform="translate({rx} 12)">
      <rect width="130" height="26" rx="8" fill="{t['inner']}" stroke="{t['line']}"/>
      <text x="12" y="17" class="mono top-label" fill="{t['muted']}">{esc(label)}</text>
      <text x="118" y="17.5" text-anchor="end" class="mono top-value" fill="{col}">{esc(val)}</text>
    </g>""")

    # Language telemetry bar & legend (filter out 0 count)
    palette = [t["cyan"], t["emerald"], t["indigo"], t["pink"], t["amber"]]
    lang_segments_data = [(name, count) for name, count in stats["langs"] if count > 0]
    shown_total = sum(count for _, count in lang_segments_data)
    rem = max(0, stats["total"] - shown_total)
    if rem > 0:
        lang_segments_data.append(("Other", rem))

    bar_x = 42.0
    bar_total_w = 302.0
    gap = 3.0
    avail_w = bar_total_w - gap * max(0, len(lang_segments_data) - 1)
    lang_rects = []
    lang_legends = []
    for i, (name, count) in enumerate(lang_segments_data):
        w = round(avail_w * count / stats["total"], 1)
        col = palette[i % len(palette)]
        lang_rects.append(
            f'<rect x="{bar_x:.1f}" y="388" width="{max(4.0, w):.1f}" height="10" rx="3" fill="{col}"/>'
        )
        bar_x += w + gap

        pct = round(100 * count / stats["total"], 1)
        col_idx = i % 3
        row_idx = i // 3
        lx = 42 + col_idx * 104
        ly = 418 + row_idx * 24
        lang_legends.append(f"""<g transform="translate({lx} {ly})">
      <circle cx="4" cy="-3.5" r="3.5" fill="{col}"/>
      <text x="13" y="0" class="mono lang-name" fill="{t['text']}">{esc(name)}</text>
      <text x="13" y="11" class="mono lang-pct" fill="{t['muted']}">{pct}% ({count})</text>
    </g>""")

    # Middle-bottom card: Repository Commit Pulse (all source repos, up to 9)
    pulse_repos = stats["events"][:9]
    max_commits = max((r["commit_count"] for r in pulse_repos), default=1)
    pulse_bars = []
    slot_w = 33.5
    start_x = 392.0
    for i, r in enumerate(pulse_repos):
        cnt = r["commit_count"]
        col, _ = lang_color_pair(r["lang"], t)
        bh = round(8.0 + 38.0 * (cnt / max_commits), 1)
        bx = start_x + i * slot_w
        by = 438.0 - bh
        pulse_bars.append(f"""<g transform="translate({bx:.1f} 0)">
      <rect x="4" y="392" width="16" height="46" rx="4" fill="{t['inner']}"/>
      <rect x="4" y="{by:.1f}" width="16" height="{bh:.1f}" rx="4" fill="{col}"/>
      <text x="12" y="{by - 4:.1f}" text-anchor="middle" class="mono chart-val" fill="{t['sub']}">{cnt}</text>
      <text x="12" y="452" text-anchor="middle" class="mono chart-lbl" fill="{t['muted']}">{esc(r['short'][:6])}</text>
    </g>""")

    # Right card: Recent Transmissions (6 items, cleanly formatted, zero overlap)
    rec_cards = []
    for i, item in enumerate(stats["recent"][:6]):
        ry = 112 + i * 56
        col, bg_col = lang_color_pair(item["lang"], t)
        is_top = i == 0
        card_fill = t["inner"] if is_top else t["card1"]
        card_stroke = col if is_top else t["line"]
        msg_truncated = visual_truncate(item["message"], 48)
        l_short = lang_short(item["lang"])
        date_str = item["dt"].strftime("%Y-%m-%d")
        time_str = item["dt"].strftime("%H:%M")

        rec_cards.append(f"""<g transform="translate(740 {ry})">
      <rect width="420" height="48" rx="8" fill="{card_fill}" stroke="{card_stroke}" stroke-width="{1.2 if is_top else 0.8}"/>
      <rect x="8" y="8" width="24" height="32" rx="6" fill="{bg_col}"/>
      <text x="20" y="28" text-anchor="middle" class="mono number" fill="{col}">{i + 1:02d}</text>
      <text x="42" y="20" class="mono ledger-repo" fill="{t['text']}">{esc(item['name'])}</text>
      <rect x="{48 + len(item['name']) * 7.4:.1f}" y="8" width="32" height="15" rx="4" fill="{bg_col}"/>
      <text x="{64 + len(item['name']) * 7.4:.1f}" y="18.5" text-anchor="middle" class="mono" font-size="8.5" font-weight="800" fill="{col}">{esc(l_short)}</text>
      <text x="408" y="19" text-anchor="end" class="mono ledger-date" fill="{col if is_top else t['sub']}">{date_str} · {time_str}</text>
      <text x="42" y="38" class="sans ledger-msg" clip-path="url(#msg-clip)" fill="{t['muted']}">{esc(msg_truncated)}</text>
    </g>""")

    # Latest highlight details
    latest_col, latest_bg = lang_color_pair(latest["lang"], t)
    latest_msg_line = visual_truncate(latest["message"], 58)
    latest_desc_line = visual_truncate(latest["description"], 64)
    latest_date_str = latest_dt.strftime("%Y-%m-%d")
    latest_time_str = latest_dt.strftime("%H:%M BJT")

    rail_s = "\n    ".join(rail_items)
    lang_rects_s = "\n    ".join(lang_rects)
    lang_legends_s = "\n    ".join(lang_legends)
    pulse_bars_s = "\n    ".join(pulse_bars)
    rec_cards_s = "\n    ".join(rec_cards)

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="486" viewBox="0 0 1200 486" role="img" aria-label="{esc(username)} live GitHub source repository telemetry" data-mode="{mode}">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="{t['bg0']}"/>
      <stop offset="55%" stop-color="{t['bg1']}"/>
      <stop offset="100%" stop-color="{t['bg2']}"/>
    </linearGradient>
    <linearGradient id="card" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="{t['card0']}"/>
      <stop offset="100%" stop-color="{t['card1']}"/>
    </linearGradient>
    <linearGradient id="accent" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0%" stop-color="{t['cyan']}"/>
      <stop offset="50%" stop-color="{t['indigo']}"/>
      <stop offset="100%" stop-color="{t['pink']}"/>
    </linearGradient>
    <pattern id="grid" width="32" height="32" patternUnits="userSpaceOnUse">
      <path d="M32 0H0V32" fill="none" stroke="{t['line']}" stroke-width="0.7" stroke-opacity="0.6"/>
    </pattern>
    <clipPath id="frame">
      <rect x="1" y="1" width="1198" height="484" rx="16"/>
    </clipPath>
    <clipPath id="msg-clip">
      <rect x="42" y="24" width="366" height="22"/>
    </clipPath>
  </defs>
  <style>
    .sans {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", Inter, Helvetica, Arial, sans-serif; }}
    .mono {{ font-family: "JetBrains Mono", "SFMono-Regular", "SF Mono", Menlo, Monaco, Consolas, "Liberation Mono", monospace; }}
    .title {{ font-size: 13px; font-weight: 800; letter-spacing: 2px; }}
    .top-label {{ font-size: 9px; font-weight: 700; letter-spacing: 1px; }}
    .top-value {{ font-size: 13px; font-weight: 800; }}
    .brand {{ font-size: 20px; font-weight: 900; letter-spacing: -0.8px; }}
    .section {{ font-size: 10.5px; font-weight: 800; letter-spacing: 1.6px; }}
    .hero-repo {{ font-size: 28px; font-weight: 900; letter-spacing: -0.6px; }}
    .hero-date {{ font-size: 38px; font-weight: 900; letter-spacing: -1px; }}
    .meta {{ font-size: 11px; font-weight: 700; }}
    .body-copy {{ font-size: 12.5px; font-weight: 500; }}
    .tiny {{ font-size: 9px; font-weight: 700; letter-spacing: 1px; }}
    .ledger-repo {{ font-size: 12px; font-weight: 800; }}
    .ledger-msg {{ font-size: 11px; font-weight: 500; }}
    .ledger-date {{ font-size: 9.5px; font-weight: 700; }}
    .number {{ font-size: 10px; font-weight: 800; }}
    .lang-name {{ font-size: 9.5px; font-weight: 700; }}
    .lang-pct {{ font-size: 8.5px; font-weight: 600; }}
    .chart-val {{ font-size: 8.5px; font-weight: 700; }}
    .chart-lbl {{ font-size: 8px; font-weight: 700; }}
    .pulse {{ transform-box: fill-box; transform-origin: center; animation: pulse 2.2s ease-in-out infinite; }}
    .spin {{ transform-box: fill-box; transform-origin: center; animation: spin 24s linear infinite; }}
    @keyframes pulse {{ 50% {{ opacity: 0.35; transform: scale(0.7); }} }}
    @keyframes spin {{ to {{ transform: rotate(360deg); }} }}
    @media (prefers-reduced-motion: reduce) {{ .pulse, .spin {{ animation: none; }} }}
  </style>

  <g clip-path="url(#frame)">
    <rect width="1200" height="486" fill="url(#bg)"/>
    <rect width="1200" height="486" fill="url(#grid)"/>

    <!-- Header Bar -->
    <rect x="0" y="0" width="1200" height="50" fill="{t['bg0']}" fill-opacity="0.8"/>
    <path d="M0 50H1200" stroke="{t['line']}" stroke-width="1"/>
    <circle class="pulse" cx="30" cy="25" r="5" fill="{t['pink']}"/>
    <text x="46" y="29.5" class="mono title" fill="{t['text']}">LIVE SIGNALS // SOURCE CONTROL</text>
    {rail_s}
    <text x="1146" y="31" text-anchor="end" class="sans brand" fill="{t['text']}">{esc(username)}</text>
    <path d="M1156 18L1172 10L1169 18L1153 26ZM1160 27L1176 19L1173 27L1157 35Z" fill="{t['pink']}"/>

    <!-- Top-Left Bento Card: Latest Commit Focus -->
    <rect x="24" y="64" width="684" height="252" rx="12" fill="url(#card)" stroke="{t['border']}"/>
    <rect x="24" y="80" width="4" height="220" rx="2" fill="url(#accent)"/>

    <g transform="translate(46 86)">
      <rect x="0" y="0" width="172" height="22" rx="11" fill="{t['pink_bg']}"/>
      <circle class="pulse" cx="13" cy="11" r="3.5" fill="{t['pink']}"/>
      <text x="24" y="14.5" class="mono tiny" fill="{t['pink']}">LATEST COMMIT PULSE</text>

      <rect x="182" y="0" width="88" height="22" rx="6" fill="{t['inner']}" stroke="{t['line']}"/>
      <text x="226" y="14.5" text-anchor="middle" class="mono tiny" fill="{t['sub']}">⎇ {esc(latest['branch'])}</text>

      <rect x="278" y="0" width="86" height="22" rx="6" fill="{t['cyan_bg']}"/>
      <text x="321" y="14.5" text-anchor="middle" class="mono tiny" fill="{t['cyan']}">#{esc(latest['sha'])}</text>

      <rect x="372" y="0" width="110" height="22" rx="6" fill="{latest_bg}"/>
      <text x="427" y="14.5" text-anchor="middle" class="mono tiny" fill="{latest_col}">{esc(latest['lang'])} MODULE</text>
    </g>

    <!-- Latest Repo Name & Date -->
    <text x="46" y="148" class="mono hero-repo" fill="{t['text']}">{esc(username)} / {esc(latest['name'])}</text>
    <text x="46" y="188" class="mono hero-date" fill="{t['cyan']}">{latest_date_str}</text>
    <rect x="288" y="163" width="96" height="24" rx="6" fill="{t['inner']}" stroke="{t['line']}"/>
    <text x="336" y="179" text-anchor="middle" class="mono meta" fill="{t['sub']}">{latest_time_str}</text>

    <!-- Commit Message Box -->
    <g transform="translate(46 206)">
      <rect width="466" height="54" rx="8" fill="{t['inner']}" stroke="{t['line']}"/>
      <rect x="0" y="8" width="3.5" height="38" rx="1.7" fill="{t['cyan']}"/>
      <text x="16" y="22" class="sans body-copy" font-weight="700" fill="{t['text']}">{esc(latest_msg_line)}</text>
      <text x="16" y="42" class="sans" font-size="11.5" fill="{t['muted']}">{esc(latest_desc_line)}</text>
    </g>

    <text x="46" y="286" class="mono tiny" fill="{t['muted']}">ACTIVE REPOSITORY STREAM · VERIFIED VIA GITHUB REST API</text>
    <text x="46" y="302" class="mono tiny" fill="{t['emerald']}">● TELEMETRY STATUS: SYNCHRONIZED (BEIJING TIME UTC+8)</text>

    <!-- Radar Gauge inside Top-Left Card -->
    <g transform="translate(608 178)">
      <circle r="68" fill="{t['inner']}" stroke="{t['line']}" stroke-width="1"/>
      <circle class="spin" r="56" fill="none" stroke="{t['cyan']}" stroke-width="1.2" stroke-dasharray="6 8" stroke-opacity="0.7"/>
      <circle r="38" fill="none" stroke="{t['muted']}" stroke-dasharray="2 5" stroke-opacity="0.6"/>
      <circle r="20" fill="none" stroke="{t['pink']}" stroke-opacity="0.8"/>
      <path d="M-64 0H64M0 -64V64" stroke="{t['line']}" stroke-width="0.8"/>
      <circle class="pulse" r="6" fill="{t['pink']}"/>
      <text x="0" y="88" text-anchor="middle" class="mono tiny" fill="{t['muted']}">SIGNAL INTEGRITY</text>
      <text x="-18" y="106" text-anchor="middle" class="mono section" fill="{t['emerald']}">100%</text>
      <rect x="14" y="96" width="4" height="11" rx="1" fill="{t['emerald']}"/>
      <rect x="21" y="96" width="4" height="11" rx="1" fill="{t['emerald']}"/>
      <rect x="28" y="96" width="4" height="11" rx="1" fill="{t['emerald']}"/>
      <rect x="35" y="96" width="4" height="11" rx="1" fill="{t['emerald']}"/>
    </g>

    <!-- Bottom-Left Card: Language Telemetry -->
    <rect x="24" y="330" width="334" height="138" rx="12" fill="url(#card)" stroke="{t['border']}"/>
    <text x="42" y="354" class="mono section" fill="{t['text']}">LANGUAGE TELEMETRY</text>
    <text x="340" y="354" text-anchor="end" class="mono tiny" fill="{t['cyan']}">{stats['lang_count']} STACKS</text>
    <path d="M42 366H340" stroke="{t['line']}"/>
    <rect x="42" y="388" width="302" height="10" rx="5" fill="{t['inner']}"/>
    {lang_rects_s}
    {lang_legends_s}

    <!-- Bottom-Middle Card: Repository Commit Pulse -->
    <rect x="374" y="330" width="334" height="138" rx="12" fill="url(#card)" stroke="{t['border']}"/>
    <text x="392" y="354" class="mono section" fill="{t['text']}">REPO COMMIT PULSE</text>
    <text x="690" y="354" text-anchor="end" class="mono tiny" fill="{t['emerald']}">{stats['active_year']}/{stats['total']} ACTIVE IN {stats['year']}</text>
    <path d="M392 366H690" stroke="{t['line']}"/>
    {pulse_bars_s}

    <!-- Right Card: Recent Transmissions -->
    <rect x="724" y="64" width="452" height="404" rx="12" fill="url(#card)" stroke="{t['border']}"/>
    <text x="744" y="90" class="mono section" fill="{t['text']}">RECENT TRANSMISSIONS // 近期源码动态</text>
    <text x="1156" y="90" text-anchor="end" class="mono tiny" fill="{t['cyan']}">TOP 06 REPOS</text>
    <path d="M740 100H1160" stroke="{t['line']}"/>
    {rec_cards_s}
  </g>
  <rect x="1" y="1" width="1198" height="484" rx="16" fill="none" stroke="{t['border']}" stroke-width="1.5"/>
</svg>
"""
    return "\n".join(line.rstrip() for line in svg.splitlines()) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--username", default="NextCandy")
    ap.add_argument("--output", default="assets")
    ap.add_argument("--check-readme", default=None)
    args = ap.parse_args()

    if args.check_readme:
        assert_readme_source_only(args.check_readme)

    projects = fetch_public_repos(args.username)
    stats = profile_stats(args.username, projects)

    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    for mode in ("light", "dark"):
        svg = render_dashboard(args.username, stats, mode)
        path = out / f"dashboard-{mode}.svg"
        path.write_text(svg, encoding="utf-8")
        print(f"wrote {path} ({len(svg)} bytes)")


if __name__ == "__main__":
    main()
