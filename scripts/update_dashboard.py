#!/usr/bin/env python3
"""Regenerate the live dashboard SVGs for the NextCandy profile README.

Fetches public (non-fork) repositories from the GitHub API, computes profile
statistics, and renders assets/dashboard-light.svg + assets/dashboard-dark.svg.
Designed to run in the weekly GitHub Actions workflow.
"""

import argparse
import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

API = "https://api.github.com"
HEADERS = {
    "Accept": "application/vnd.github+json",
    "User-Agent": "nextcandy-profile-dashboard",
}


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
    return datetime.strptime(repo["pushed_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def profile_stats(projects):
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

    recent = [
        (p["name"], (p.get("language") or "TXT").upper(), _pushed(p))
        for p in projects[:5]
    ]

    # 12 monthly buckets ending at the latest push month, counting each repo
    # in the month it was last pushed
    buckets = []
    y, m = latest_dt.year, latest_dt.month
    for _ in range(12):
        buckets.append((y, m))
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    buckets.reverse()
    counts_by_month = {(b[0], b[1]): 0 for b in buckets}
    for p in projects:
        d = _pushed(p)
        key = (d.year, d.month)
        if key in counts_by_month:
            counts_by_month[key] += 1
    cadence = [(datetime(b[0], b[1], 1), counts_by_month[(b[0], b[1])]) for b in buckets]

    return {
        "total": total,
        "lang_count": len(counts),
        "langs": lang_rows,
        "active_year": active_year,
        "year": year,
        "latest_name": latest["name"],
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
        "bg0": "#04070D", "bg1": "#0A1220", "panel": "#0A1420", "panel2": "#0E1B29",
        "grid": "#12202E", "line": "#1E3446", "text": "#EAF6FC", "muted": "#7E96A6",
        "cyan": "#2FD8FF", "pink": "#FF5CA8", "green": "#3DF2A6", "amber": "#FFC857", "violet": "#9D8CFF",
    },
    "light": {
        "bg0": "#F7FBFD", "bg1": "#EEF6FA", "panel": "#FFFFFF", "panel2": "#F2F8FB",
        "grid": "#DCEAF0", "line": "#B9D2DC", "text": "#0C2733", "muted": "#5B7885",
        "cyan": "#0099C4", "pink": "#E83E8C", "green": "#12995F", "amber": "#B57400", "violet": "#6A54D8",
    },
}


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def render_dashboard(username, stats, mode):
    t = THEMES[mode]

    cards = []
    card_specs = [
        ("SOURCE REPOS", str(stats["total"]), "forks excluded", t["cyan"]),
        ("LANGUAGE NODES", str(stats["lang_count"]), "primary stacks", t["pink"]),
        (f"ACTIVE / {stats['year']}", str(stats["active_year"]), "pushed this year", t["green"]),
        ("LATEST PUSH", stats["latest_dt"].strftime("%m.%d"), stats["latest_name"], t["amber"]),
    ]
    for i, (title, value, sub, color) in enumerate(card_specs):
        cards.append(f"""<g class="boot" style="animation-delay:{0.12 * i}s" transform="translate({28 + 289 * i} 80)">
      <rect width="267" height="104" rx="14" fill="{t['panel']}" stroke="{t['line']}"/>
      <rect width="267" height="4" rx="2" fill="{color}"/>
      <text x="20" y="34" class="micro" fill="{t['muted']}">{title}</text>
      <text x="20" y="76" class="metric" fill="{color}">{esc(value)}</text>
      <text x="247" y="76" text-anchor="end" class="tiny" fill="{t['muted']}">{esc(sub)}</text>
      <circle class="pulse" cx="247" cy="28" r="3.5" fill="{color}"/>
    </g>""")

    lang_palette = [t["cyan"], t["violet"], t["pink"], t["green"], t["amber"]]
    max_lang = max(c for _, c in stats["langs"])
    lang_rows = []
    for i, (name, count) in enumerate(stats["langs"]):
        w = round(250 * count / max_lang, 1)
        pct = round(100 * count / stats["total"])
        color = lang_palette[i % len(lang_palette)]
        lang_rows.append(f"""<g transform="translate(52 {258 + 44 * i})">
      <text x="0" y="13" class="row" fill="{t['text']}">{esc(name.upper())}</text>
      <rect x="120" y="3" width="250" height="11" rx="5.5" fill="{t['grid']}"/>
      <rect class="bar" style="animation-delay:{round(0.25 + 0.09 * i, 2)}s" x="120" y="3" width="{w}" height="11" rx="5.5" fill="{color}"/>
      <text x="400" y="13" text-anchor="end" class="row" fill="{t['muted']}">{count:02d} · {pct}%</text>
    </g>""")

    cad_rows = []
    for i, (month, count) in enumerate(stats["cadence"]):
        h = 24.0 * count + 8.0 if count else 4.0
        y = 470.0 - h
        label = month.strftime("%m") if i in (0, 11) else ""
        fill = t["green"] if count else t["grid"]
        cad_rows.append(f"""<g transform="translate({544 + 22 * i} 0)">
      <rect class="bar" style="animation-delay:{round(0.3 + 0.05 * i, 2)}s" x="0" y="{y}" width="12" height="{h}" rx="6" fill="{fill}"/>
      <text x="6" y="492" text-anchor="middle" class="tiny" fill="{t['muted']}">{label}</text>
    </g>""")

    rec_palette = [t["cyan"], t["pink"], t["violet"], t["green"], t["amber"]]
    rec_rows = []
    for i, (name, lang, dt) in enumerate(stats["recent"]):
        row_y = 52 + 46 * i
        color = rec_palette[i % len(rec_palette)]
        label = "LATEST" if i == 0 else f"{i + 1:02d}"
        stroke = color if i == 0 else t["line"]
        stroke_width = "1.5" if i == 0 else "1"
        stroke_opacity = ".78" if i == 0 else ".9"
        row_filter = "url(#glow)" if i == 0 else "none"
        connector = "" if i == len(stats["recent"]) - 1 else (
            f'<path d="M12 36V46" stroke="{color}" stroke-opacity=".28" stroke-width="1.5"/>'
        )
        rec_rows.append(f"""<g class="boot" style="animation-delay:{round(0.3 + 0.1 * i, 2)}s" transform="translate(846 {210 + row_y})">
      {connector}
      <rect x="18" y="0" width="308" height="36" rx="9" fill="{t['panel']}" stroke="{stroke}" stroke-width="{stroke_width}" stroke-opacity="{stroke_opacity}"/>
      <rect x="18" y="0" width="3" height="36" rx="1.5" fill="{color}"/>
      <circle class="pulse" cx="12" cy="18" r="{5 if i == 0 else 3.5}" fill="{color}" filter="{row_filter}"/>
      <text x="32" y="14" class="tiny" fill="{color}">{label}</text>
      <text x="58" y="24" class="repo" fill="{t['text']}">{esc(name)}</text>
      <text x="296" y="14" text-anchor="end" class="tiny" fill="{t['muted']}">{esc(lang)}</text>
      <text x="296" y="27" text-anchor="end" class="tiny" fill="{t['muted']}">{dt.strftime('%m.%d')}</text>
    </g>""")

    cards_s = "\n" + "\n".join(cards)
    lang_head = (f'\n<g transform="translate(28 210)"><rect width="452" height="304" rx="14" fill="{t["panel"]}" stroke="{t["line"]}"/>'
                 f'<text x="22" y="30" class="micro" fill="{t["cyan"]}">LANGUAGE TELEMETRY</text>'
                 f'<text x="430" y="30" text-anchor="end" class="tiny" fill="{t["muted"]}">PRIMARY / REPO</text></g>')
    lang_s = "\n" + "\n".join(lang_rows)
    cad_head = (f'\n<g transform="translate(496 210)"><rect width="316" height="304" rx="14" fill="{t["panel"]}" stroke="{t["line"]}"/>'
                f'<text x="22" y="30" class="micro" fill="{t["green"]}">PUSH CADENCE</text>'
                f'<text x="294" y="30" text-anchor="end" class="tiny" fill="{t["muted"]}">12 MO / LAST-PUSH</text></g>')
    cad_s = "\n" + "\n".join(cad_rows)
    rec_head = (
        f'\n<g clip-path="url(#recent-frame)">'
        f'<rect x="828" y="210" width="344" height="304" rx="14" fill="{t["panel2"]}"/>'
        f'<rect class="recent-sweep" x="828" y="214" width="344" height="34" fill="url(#accent)" opacity=".04"/>'
        f'</g>'
        f'<g transform="translate(828 210)">'
        f'<rect width="344" height="304" rx="14" fill="none" stroke="{t["line"]}" stroke-width="1"/>'
        f'<path d="M14 0H330" stroke="url(#accent)" stroke-width="3" stroke-linecap="round"/>'
        f'<path d="M300 0H330V30" fill="none" stroke="{t["pink"]}" stroke-width="2" stroke-linecap="round" opacity=".8"/>'
        f'<path d="M12 58V262" stroke="url(#accent)" stroke-width="1" stroke-opacity=".38"/>'
        f'<path d="M16 48H328" stroke="{t["line"]}" stroke-width="1"/>'
        f'<text x="22" y="30" class="micro" fill="{t["pink"]}">RECENT TRANSMISSIONS</text>'
        f'<text x="322" y="30" text-anchor="end" class="tiny" fill="{t["muted"]}">PUBLIC · PUSHED</text></g>'
    )
    rec_s = "\n" + "\n".join(rec_rows)
    last_signal = stats["latest_dt"].strftime("%Y.%m.%d")

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="560" viewBox="0 0 1200 560" role="img" aria-label="{esc(username)} live GitHub source repository signals" data-mode="{mode}">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop stop-color="{t['bg0']}"/><stop offset="1" stop-color="{t['bg1']}"/></linearGradient>
    <linearGradient id="accent" x1="0" y1="0" x2="1" y2="0"><stop stop-color="{t['cyan']}"/><stop offset=".5" stop-color="{t['violet']}"/><stop offset="1" stop-color="{t['pink']}"/></linearGradient>
    <radialGradient id="aur1" cx=".5" cy=".5" r=".5"><stop stop-color="{t['cyan']}" stop-opacity=".10"/><stop offset="1" stop-color="{t['cyan']}" stop-opacity="0"/></radialGradient>
    <radialGradient id="aur2" cx=".5" cy=".5" r=".5"><stop stop-color="{t['pink']}" stop-opacity=".09"/><stop offset="1" stop-color="{t['pink']}" stop-opacity="0"/></radialGradient>
    <pattern id="grid" width="28" height="28" patternUnits="userSpaceOnUse"><path d="M28 0H0V28" fill="none" stroke="{t['grid']}" stroke-width="1"/></pattern>
    <filter id="glow" x="-100%" y="-100%" width="300%" height="300%"><feGaussianBlur stdDeviation="5" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
    <clipPath id="frame"><rect x="1" y="1" width="1198" height="558" rx="20"/></clipPath>
    <clipPath id="recent-frame"><rect x="828" y="210" width="344" height="304" rx="14"/></clipPath>
  </defs>
  <style>
    text{{font-family:ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,"Liberation Mono",monospace}}
    .title{{font-size:15px;font-weight:800;letter-spacing:3px}}.micro{{font-size:10px;font-weight:700;letter-spacing:2px}}.tiny{{font-size:9px;letter-spacing:1px}}
    .metric{{font-size:36px;font-weight:900;letter-spacing:-1px}}.row{{font-size:11px;font-weight:700;letter-spacing:1px}}.repo{{font-size:13px;font-weight:800}}
    .pulse{{transform-box:fill-box;transform-origin:center;animation:pulse 2s ease-in-out infinite}}
    .scan{{animation:scan 7s linear infinite}}
    .bar{{transform-box:fill-box;transform-origin:center;animation:grow .9s cubic-bezier(.2,.8,.2,1) both}}
    .boot{{animation:boot .6s ease-out both}}
    .recent-sweep{{animation:recentSweep 5.5s linear infinite}}
    @keyframes pulse{{50%{{opacity:.3;transform:scale(.65)}}}}@keyframes scan{{from{{transform:translateY(-70px)}}to{{transform:translateY(630px)}}}}
    @keyframes grow{{from{{transform:scaleY(.05)}}}}@keyframes boot{{from{{opacity:.45}}}}@keyframes recentSweep{{from{{transform:translateY(-46px)}}to{{transform:translateY(310px)}}}}
    @media(prefers-reduced-motion:reduce){{.pulse,.scan,.bar,.boot,.recent-sweep{{animation:none}}}}
  </style>

<g clip-path="url(#frame)">
    <rect width="1200" height="560" fill="url(#bg)"/>
    <ellipse cx="100" cy="0" rx="380" ry="200" fill="url(#aur1)"/>
    <ellipse cx="1150" cy="560" rx="420" ry="220" fill="url(#aur2)"/>
    <rect width="1200" height="560" fill="url(#grid)" opacity=".55"/>
    <path d="M0 1.5H1200" stroke="url(#accent)" stroke-width="3"/>
    <rect class="scan" x="0" y="-70" width="1200" height="70" fill="url(#accent)" opacity=".03"/>

    <text x="28" y="40" class="title" fill="{t['cyan']}">LIVE SIGNALS // SOURCE CONTROL</text>

<g transform="translate(940 33)"><circle class="pulse" r="5" fill="{t['green']}" filter="url(#glow)"/><text x="14" y="4" class="micro" fill="{t['green']}">FORK FILTER: ON</text></g>
    <path d="M28 58H1172" stroke="{t['line']}"/>

    {cards_s}

    {lang_head}

    {lang_s}

    {cad_head}

    {cad_s}

    {rec_head}

    {rec_s}

    <path d="M28 532H1172" stroke="{t['line']}"/><text x="28" y="549" class="tiny" fill="{t['muted']}">AUTO-SYNC · SOURCE ONLY · RAW GITHUB COUNTS · LAST SIGNAL {last_signal}</text><text x="1172" y="549" text-anchor="end" class="tiny" fill="{t['muted']}">github.com/{esc(username)}</text>
  </g>
  <rect x="1" y="1" width="1198" height="558" rx="20" fill="none" stroke="url(#accent)" stroke-opacity=".8"/>
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
    stats = profile_stats(projects)

    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    for mode in ("light", "dark"):
        svg = render_dashboard(args.username, stats, mode)
        path = out / f"dashboard-{mode}.svg"
        path.write_text(svg, encoding="utf-8")
        print(f"wrote {path} ({len(svg)} bytes)")


if __name__ == "__main__":
    main()
