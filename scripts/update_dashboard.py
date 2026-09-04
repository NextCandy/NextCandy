#!/usr/bin/env python3
"""Regenerate the live dashboard SVGs for the NextCandy profile README.

Fetches public (non-fork) repositories from the GitHub API, computes profile
statistics, and renders assets/dashboard-light.svg + assets/dashboard-dark.svg.
Designed to run in the 15-minute GitHub Actions workflow.
"""

import argparse
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
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
if GITHUB_TOKEN:
    HEADERS["Authorization"] = f"Bearer {GITHUB_TOKEN}"

try:
    BEIJING_TZ = ZoneInfo("Asia/Shanghai")
except ZoneInfoNotFoundError:
    # Keep local runs working on systems without an installed IANA tz database.
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
    projects = [r for r in repos if not r.get("fork")]
    projects.sort(key=lambda r: r.get("pushed_at") or "", reverse=True)
    return projects


def _pushed(repo):
    """Parse GitHub's UTC timestamp and render it in Beijing time."""
    return (datetime.strptime(repo["pushed_at"], "%Y-%m-%dT%H:%M:%SZ")
            .replace(tzinfo=timezone.utc)
            .astimezone(BEIJING_TZ))


def fetch_latest_commit(username, repo_name):
    """Return the latest public commit details, with a safe visual fallback."""
    url = f"{API}/repos/{username}/{repo_name}/commits?per_page=1"
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            commits = json.load(resp)
        commit = commits[0]
        subject = " ".join((commit.get("commit", {}).get("message") or "").splitlines()).strip()
        return {
            "sha": (commit.get("sha") or "")[:7] or "—",
            "message": subject or "latest public push",
        }
    except (HTTPError, URLError, TimeoutError, IndexError, KeyError, TypeError, json.JSONDecodeError):
        return {"sha": "—", "message": "latest public push"}


def profile_stats(username, projects):
    if not projects:
        raise SystemExit("no public source repositories found")
    total = len(projects)

    # language counts, ordered by count desc; ties keep first-seen order
    # (projects are already sorted by last push, newest first)
    counts, order = {}, []
    for p in projects:
        lang = p.get("language") or "TXT"
        if lang not in counts:
            order.append(lang)
            counts[lang] = 0
        counts[lang] += 1
    languages = sorted(order, key=lambda l: -counts[l])
    lang_rows = [(l, counts[l]) for l in languages[:5]]

    latest = projects[0]
    latest_dt = _pushed(latest)
    year = latest_dt.year
    active_year = sum(1 for p in projects if _pushed(p).year == year)

    recent = []
    for p in projects[:5]:
        commit = fetch_latest_commit(username, p["name"])
        recent.append({
            "name": p["name"],
            "lang": (p.get("language") or "TXT").upper(),
            "dt": _pushed(p),
            "branch": p.get("default_branch") or "main",
            "sha": commit["sha"],
            "message": commit["message"],
            "description": p.get("description") or "",
        })

    # 28 daily buckets ending at the latest push, counting each repo once on
    # the day it was last pushed. This keeps the chart honest without needing
    # a second authenticated contribution API.
    buckets = [latest_dt - timedelta(days=offset) for offset in range(27, -1, -1)]
    counts_by_day = {b.date(): 0 for b in buckets}
    for p in projects:
        d = _pushed(p)
        if d.date() in counts_by_day:
            counts_by_day[d.date()] += 1
    cadence = [(bucket, counts_by_day[bucket.date()]) for bucket in buckets]

    return {
        "total": total,
        "lang_count": len(counts),
        "langs": lang_rows,
        "active_year": active_year,
        "year": year,
        "latest_name": latest["name"],
        "latest_branch": recent[0]["branch"],
        "latest_sha": recent[0]["sha"],
        "latest_message": recent[0]["message"],
        "latest_description": recent[0]["description"],
        "latest_dt": latest_dt,
        "recent": recent,
        "cadence": cadence,
        "all": projects,
    }


def assert_readme_source_only(readme_path):
    """Sanity check: the README must reference the dashboard assets we generate."""
    text = Path(readme_path).read_text(encoding="utf-8")
    for needle in ("assets/dashboard-dark.svg", "assets/dashboard-light.svg"):
        if needle not in text:
            raise SystemExit(f"README does not reference {needle}; aborting")


THEMES = {
    "dark": {
        "bg": "#06182B", "panel": "#0B213A", "grid": "#1A3854", "line": "#3D5973",
        "text": "#F4F8FC", "muted": "#9FB2C3", "cyan": "#2AC2CE", "pink": "#FF6469",
        "green": "#2AC7AE", "amber": "#FFC44B", "violet": "#B27ACB", "blue": "#7896DB",
        "other": "#8E9EAE",
    },
    "light": {
        "bg": "#FFFFFF", "panel": "#FBFCFE", "grid": "#E7ECF2", "line": "#B8C3D1",
        "text": "#0A1D39", "muted": "#52627A", "cyan": "#1299A8", "pink": "#F05B60",
        "green": "#159A89", "amber": "#EBAA19", "violet": "#824DA8", "blue": "#405992",
        "other": "#B8C0CB",
    },
}


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def compact(s, limit):
    text = " ".join(str(s).split()).strip()
    return text if len(text) <= limit else f"{text[:limit - 1]}…"


def render_dashboard(username, stats, mode):
    t = THEMES[mode]
    latest_dt = stats["latest_dt"]
    latest = stats["recent"][0]
    latest_full = latest_dt.strftime("%Y-%m-%d")
    latest_slug = f"{username.lower()}/{stats['latest_name']}"
    latest_message = compact(stats["latest_message"], 54)
    latest_description = compact(stats["latest_description"] or "Latest public source update.", 58)
    frame_path = "M1 1H1199V485H1Z"

    rail_specs = [
        ("REPOS", str(stats["total"]), t["pink"], 54),
        ("LANGUAGES", str(stats["lang_count"]), t["cyan"], 88),
        (f"ACTIVE / {stats['year']}", str(stats["active_year"]), t["blue"], 108),
        ("LATEST", latest_dt.strftime("%m.%d"), t["pink"], 62),
    ]
    rail = []
    for i, (label, value, color, value_x) in enumerate(rail_specs):
        x = 398 + 150 * i
        separator = "" if i == len(rail_specs) - 1 else f'<path d="M{x + 137} 17V40" stroke="{t["line"]}"/>'
        rail.append(f"""<g class="boot" style="animation-delay:{round(0.06 + 0.06 * i, 2)}s" transform="translate({x} 0)">
      <text x="0" y="33" class="top-label" fill="{t['muted']}">{esc(label)}</text>
      <text x="{value_x}" y="33" class="top-value" fill="{color}">{esc(value)}</text>
      {separator}
    </g>""")

    lang_palette = [t["cyan"], t["blue"], t["pink"], t["violet"], t["amber"]]
    language_segments = list(stats["langs"])
    shown_total = sum(count for _, count in language_segments)
    language_segments.append(("OTHER", max(0, stats["total"] - shown_total)))

    segment_gap = 2.0
    segment_x = 28.0
    segment_width = 572.0
    available_width = segment_width - segment_gap * max(0, len(language_segments) - 1)
    lang_segments = []
    lang_items = []
    for i, (name, count) in enumerate(language_segments):
        width = round(available_width * count / stats["total"], 1)
        color = t["other"] if name == "OTHER" else lang_palette[i % len(lang_palette)]
        lang_segments.append(f'<rect class="bar" style="animation-delay:{round(0.16 + 0.06 * i, 2)}s" x="{segment_x:.1f}" y="404" width="{width:.1f}" height="13" fill="{color}"/>')
        pct = round(100 * count / stats["total"], 1)
        x = 28 + 95 * i
        display_name = "Other" if name == "OTHER" else name
        lang_items.append(f"""<g transform="translate({x} 0)">
      <circle cx="3" cy="440" r="3" fill="{color}"/>
      <text x="12" y="443" class="language-name" fill="{t['text']}">{esc(display_name)}</text>
      <text x="12" y="461" class="language-pct" fill="{t['muted']}">{pct}%</text>
    </g>""")
        segment_x += width + segment_gap

    max_cadence = max((count for _, count in stats["cadence"]), default=0)
    cad_rows = []
    chart_x = 666.0
    slot = 17.5
    for i, (month, count) in enumerate(stats["cadence"]):
        bar_width = 7.0
        height = round(4.0 + 48.0 * count / max_cadence, 1) if max_cadence else 4.0
        x = chart_x + slot * i + (slot - bar_width) / 2
        y = 456.0 - height
        color = t["grid"] if not count else lang_palette[i % len(lang_palette)]
        if i == len(stats["cadence"]) - 1 and count:
            color = t["cyan"]
        label = month.strftime("%b %d").upper() if i in (0, 7, 14, 21, 27) else ""
        value = str(count) if count else ""
        cad_rows.append(f"""<g transform="translate({x:.1f} 0)">
      <rect class="bar" style="animation-delay:{round(0.18 + 0.035 * i, 2)}s" x="0" y="{y:.1f}" width="{bar_width:.1f}" height="{height:.1f}" fill="{color}"/>
      <text x="{bar_width / 2:.1f}" y="{y - 5:.1f}" text-anchor="middle" class="chart-value" fill="{t['muted']}">{value}</text>
      <text x="{bar_width / 2:.1f}" y="476" text-anchor="middle" class="chart-label" fill="{t['muted']}">{label}</text>
    </g>""")

    rec_rows = []
    for i, item in enumerate(stats["recent"]):
        row_y = 105 + 45 * i
        color = t["pink"] if i == 0 else t["text"]
        fill = t["panel"] if i == 0 else "none"
        message = compact(item["message"], 40)
        rec_rows.append(f"""<g class="boot" style="animation-delay:{round(0.16 + 0.07 * i, 2)}s">
      <rect x="796" y="{row_y}" width="376" height="42" fill="{fill}"/>
      <path d="M796 {row_y + 42}H1172" stroke="{t['line']}"/>
      <circle cx="786" cy="{row_y + 16}" r="{4.5 if i == 0 else 3.2}" fill="{color}"/>
      <rect x="796" y="{row_y + 7}" width="22" height="22" fill="{color}"/>
      <text x="807" y="{row_y + 22}" text-anchor="middle" class="number" fill="{t['bg']}">{i + 1:02d}</text>
      <text x="838" y="{row_y + 17}" class="ledger-repo" fill="{color if i == 0 else t['text']}">{esc(f"{username.lower()}/{item['name']}")}</text>
      <text x="838" y="{row_y + 34}" class="ledger-message" clip-path="url(#message-clip)" fill="{t['muted']}">{esc(message)}</text>
      <text x="1148" y="{row_y + 17}" text-anchor="end" class="ledger-time" fill="{color}">{item['dt'].strftime('%H:%M')}</text>
      <text x="1148" y="{row_y + 34}" text-anchor="end" class="ledger-date" fill="{t['muted']}">{item['dt'].strftime('%b %d').upper()}</text>
    </g>""")

    rail_s = "\n" + "\n".join(rail)
    lang_segments_s = "\n" + "\n".join(lang_segments)
    lang_items_s = "\n" + "\n".join(lang_items)
    cad_s = "\n" + "\n".join(cad_rows)
    rec_s = "\n" + "\n".join(rec_rows)
    top_language = "Other" if language_segments[0][0] == "OTHER" else language_segments[0][0]
    cadence_max_label = max_cadence
    cadence_mid_label = max(1, round(max_cadence / 2))

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="486" viewBox="0 0 1200 486" role="img" aria-label="{esc(username)} live GitHub source repository signals, Beijing time UTC+8" data-mode="{mode}">
  <defs>
    <clipPath id="frame"><path d="{frame_path}"/></clipPath>
    <clipPath id="message-clip"><rect x="838" y="105" width="270" height="222"/></clipPath>
  </defs>
  <style>
    text{{font-family:"SFMono-Regular","SF Mono",Menlo,Monaco,Consolas,"Liberation Mono",monospace}}
    .title{{font-size:14px;font-weight:800;letter-spacing:2.7px}}.top-label{{font-size:9px;font-weight:700;letter-spacing:1.2px}}.top-value{{font-size:17px;font-weight:800}}
    .brand{{font-family:"Avenir Next","Helvetica Neue",Arial,sans-serif;font-size:25px;font-weight:800;letter-spacing:-1.4px}}.section{{font-size:11px;font-weight:800;letter-spacing:2px}}
    .hero-date{{font-family:"DIN Condensed","Avenir Next Condensed","Arial Narrow",sans-serif;font-size:72px;font-weight:700;letter-spacing:-1.5px}}.hero-repo{{font-size:26px;font-weight:800;letter-spacing:1px}}
    .meta{{font-size:10px;font-weight:700;letter-spacing:.8px}}.body-copy{{font-size:13px;font-weight:500;letter-spacing:.3px}}.tiny{{font-size:8px;letter-spacing:1px}}
    .ledger-repo{{font-size:11px;font-weight:800;letter-spacing:.1px}}.ledger-message{{font-size:9px;letter-spacing:.1px}}.ledger-time{{font-size:10px;font-weight:800}}.ledger-date{{font-size:8px;letter-spacing:1px}}.number{{font-size:8px;font-weight:900}}
    .language-name{{font-size:9px;font-weight:700}}.language-pct{{font-size:9px;letter-spacing:.5px}}.chart-value{{font-size:8px}}.chart-label{{font-size:8px;letter-spacing:.5px}}
    .pulse{{transform-box:fill-box;transform-origin:center;animation:pulse 2s ease-in-out infinite}}.bar{{transform-box:fill-box;transform-origin:center;animation:grow .8s cubic-bezier(.23,1,.32,1) both}}.boot{{animation:boot .35s ease-out both}}
    @keyframes pulse{{50%{{opacity:.35;transform:scale(.7)}}}}@keyframes grow{{from{{transform:scaleY(.05)}}}}@keyframes boot{{from{{opacity:.35;transform:translateY(3px)}}}}
    @media(prefers-reduced-motion:reduce){{.pulse,.bar,.boot{{animation:none}}}}
  </style>

  <g clip-path="url(#frame)">
    <rect width="1200" height="486" fill="{t['bg']}"/>

    <circle cx="30" cy="27" r="5" fill="{t['pink']}"/>
    <text x="52" y="33" class="title" fill="{t['text']}">LIVE SIGNALS // SOURCE CONTROL</text>
    {rail_s}
    <text x="1028" y="35" class="brand" fill="{t['text']}">{esc(username)}</text>
    <path d="M1152 20L1168 12L1165 20L1149 28ZM1156 29L1172 21L1169 29L1153 37Z" fill="{t['pink']}"/>
    <path d="M8 53H1192" stroke="{t['line']}"/>

    <path d="M16 66H28M16 66V78" stroke="{t['pink']}" stroke-width="1.5"/>
    <path d="M31 106V327" stroke="{t['line']}" stroke-width="2" stroke-dasharray="16 7"/>
    <circle cx="31" cy="196" r="14" fill="{t['bg']}" stroke="{t['pink']}" stroke-width="5"/>
    <circle cx="31" cy="196" r="4" fill="{t['pink']}"/>
    <text x="54" y="91" class="section" fill="{t['pink']}">LATEST PUSH</text>
    <path d="M54 102H86" stroke="{t['pink']}" stroke-width="3"/>
    <text x="116" y="193" class="hero-date" fill="{t['text']}">{latest_full}</text>
    <text x="116" y="230" class="hero-repo" fill="{t['text']}">{esc(latest_slug)}</text>
    <g transform="translate(116 256)">
      <circle cx="2" cy="-3" r="2" fill="none" stroke="{t['muted']}"/>
      <circle cx="2" cy="8" r="2" fill="none" stroke="{t['muted']}"/>
      <path d="M4 -3V8M4 2H13V6" fill="none" stroke="{t['muted']}"/>
      <text x="22" y="1" class="meta" fill="{t['muted']}">{esc(latest['branch'])}</text>
      <text x="60" y="1" class="meta" fill="{t['line']}">│</text>
      <text x="74" y="1" class="meta" fill="{t['cyan']}">{esc(latest['sha'])}</text>
      <text x="132" y="1" class="meta" fill="{t['line']}">│</text>
      <text x="146" y="1" class="meta" fill="{t['muted']}">{esc(latest_message)}</text>
    </g>
    <text x="116" y="295" class="body-copy" fill="{t['muted']}">{esc(latest_description)}</text>
    <text x="116" y="318" class="tiny" fill="{t['muted']}">PUBLIC SOURCE REPOSITORY · {latest_dt.strftime('%b %d').upper()}</text>
    <text x="116" y="340" class="tiny" fill="{t['cyan']}">TIMEZONE · BEIJING (UTC+8)</text>

    <g transform="translate(657 193)">
      <circle r="60" fill="none" stroke="{t['line']}" stroke-dasharray="2 6"/>
      <circle r="42" fill="none" stroke="{t['muted']}" stroke-opacity=".75" stroke-dasharray="1 5"/>
      <circle r="24" fill="none" stroke="{t['pink']}" stroke-opacity=".8"/>
      <path d="M-70 0H70M0 -70V70" stroke="{t['line']}"/>
      <circle class="pulse" r="6" fill="{t['pink']}"/>
    </g>
    <text x="657" y="274" text-anchor="middle" class="tiny" fill="{t['muted']}">SIGNAL STRENGTH</text>
    <text x="612" y="295" class="section" fill="{t['pink']}">STRONG</text>
    <rect x="674" y="285" width="3" height="12" fill="{t['pink']}"/><rect x="684" y="285" width="3" height="12" fill="{t['pink']}"/><rect x="694" y="285" width="3" height="12" fill="{t['pink']}"/><rect x="704" y="285" width="3" height="12" fill="{t['pink']}"/>

    <path d="M768 66V353" stroke="{t['line']}"/>
    <text x="786" y="82" class="section" fill="{t['text']}">RECENT TRANSMISSIONS</text>
    <text x="1172" y="82" text-anchor="end" class="section" fill="{t['cyan']}">VIEW ALL</text>
    <path d="M1178 77L1184 82L1178 87" fill="none" stroke="{t['cyan']}" stroke-width="1.5"/>
    <path d="M786 91H1172" stroke="{t['line']}"/>
    <path d="M786 105V327" stroke="{t['line']}"/>
    {rec_s}

    <path d="M8 365H1192" stroke="{t['line']}"/>
    <path d="M640 372V477" stroke="{t['line']}"/>
    <text x="28" y="382" class="section" fill="{t['text']}">LANGUAGE TELEMETRY</text>
    <text x="622" y="382" text-anchor="end" class="tiny" fill="{t['muted']}">REPOSITORY SHARE</text>
    <path d="M28 393H622" stroke="{t['line']}"/>
    <rect x="28" y="404" width="572" height="13" fill="{t['grid']}"/>
    {lang_segments_s}
    {lang_items_s}
    <text x="28" y="479" class="tiny" fill="{t['cyan']}">TOP LANGUAGE · {esc(top_language.upper())}</text>

    <text x="658" y="382" class="section" fill="{t['text']}">PUSH CADENCE</text>
    <text x="1172" y="382" text-anchor="end" class="tiny" fill="{t['muted']}">LAST 28 DAYS</text>
    <path d="M658 393H1172" stroke="{t['line']}"/>
    <path d="M658 406H1172M658 431H1172M658 456H1172" stroke="{t['line']}" stroke-dasharray="2 6"/>
    <text x="658" y="409" class="tiny" fill="{t['muted']}">{cadence_max_label}</text><text x="658" y="434" class="tiny" fill="{t['muted']}">{cadence_mid_label}</text><text x="658" y="459" class="tiny" fill="{t['muted']}">0</text>
    {cad_s}

  </g>
  <path d="{frame_path}" fill="none" stroke="{t['line']}" stroke-width="2"/>
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
