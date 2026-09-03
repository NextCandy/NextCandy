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
    latest_dt = stats["latest_dt"]
    latest_full = latest_dt.strftime("%Y.%m.%d")
    frame_path = "M12 1H1188L1199 12V548L1188 559H12L1 548V12Z"

    rail_specs = [
        ("SOURCE REPOS", str(stats["total"]), t["cyan"]),
        ("LANGUAGE NODES", str(stats["lang_count"]), t["pink"]),
        (f"ACTIVE / {stats['year']}", str(stats["active_year"]), t["green"]),
        ("LATEST PUSH", latest_dt.strftime("%m.%d"), t["amber"]),
    ]
    rail = []
    for i, (label, value, color) in enumerate(rail_specs):
        x = 398 + 158 * i
        separator = "" if i == len(rail_specs) - 1 else f'<path d="M{x + 145} 20V52" stroke="{t["line"]}"/>'
        rail.append(f"""<g class="boot" style="animation-delay:{round(0.08 + 0.08 * i, 2)}s" transform="translate({x} 0)">
      <text x="0" y="27" class="rail-label" fill="{t['muted']}">{esc(label)}</text>
      <text x="0" y="48" class="rail-value" fill="{color}">{esc(value)}</text>
      {separator}
    </g>""")

    lang_palette = [t["cyan"], t["violet"], t["pink"], t["green"], t["amber"]]
    language_segments = list(stats["langs"])
    shown_total = sum(count for _, count in language_segments)
    if stats["total"] > shown_total:
        language_segments.append(("OTHER", stats["total"] - shown_total))

    segment_x = 28.0
    segment_width = 544.0
    lang_segments = []
    lang_items = []
    for i, (name, count) in enumerate(language_segments):
        width = round(segment_width * count / stats["total"], 1)
        color = lang_palette[i % len(lang_palette)]
        lang_segments.append(f'<rect class="bar" style="animation-delay:{round(0.18 + 0.08 * i, 2)}s" x="{segment_x:.1f}" y="383" width="{width:.1f}" height="14" fill="{color}"/>')
        pct = round(100 * count / stats["total"])
        col = i % 3
        row = i // 3
        x = 28 + 181 * col
        y = 426 + 28 * row
        lang_items.append(f"""<g transform="translate({x} {y})">
      <circle cx="3" cy="-4" r="3" fill="{color}"/>
      <text x="13" y="0" class="ledger-label" fill="{t['text']}">{esc(name.upper())}</text>
      <text x="168" y="0" text-anchor="end" class="tiny" fill="{t['muted']}">{count:02d} · {pct}%</text>
    </g>""")
        segment_x += width

    max_cadence = max((count for _, count in stats["cadence"]), default=0)
    cad_rows = []
    chart_x = 636.0
    slot = 43.0
    for i, (month, count) in enumerate(stats["cadence"]):
        bar_width = 16.0
        height = round(8.0 + 68.0 * count / max_cadence, 1) if max_cadence else 8.0
        x = chart_x + slot * i + (slot - bar_width) / 2
        y = 493.0 - height
        color = t["grid"] if not count else lang_palette[i % len(lang_palette)]
        if i == len(stats["cadence"]) - 1 and count:
            color = t["pink"]
        label = month.strftime("%b").upper() if i in (0, 5, 11) else ""
        value = str(count) if count else ""
        cad_rows.append(f"""<g transform="translate({x:.1f} 0)">
      <rect class="bar" style="animation-delay:{round(0.22 + 0.035 * i, 2)}s" x="0" y="{y:.1f}" width="{bar_width:.1f}" height="{height:.1f}" fill="{color}"/>
      <text x="{bar_width / 2:.1f}" y="{y - 6:.1f}" text-anchor="middle" class="tiny" fill="{t['muted']}">{value}</text>
      <text x="{bar_width / 2:.1f}" y="508" text-anchor="middle" class="tiny" fill="{t['muted']}">{label}</text>
    </g>""")

    rec_palette = [t["cyan"], t["pink"], t["violet"], t["green"], t["amber"]]
    rec_rows = []
    for i, (name, lang, dt) in enumerate(stats["recent"]):
        row_y = 137 + 35 * i
        color = rec_palette[i % len(rec_palette)]
        fill = t["panel2"] if i == 0 else "none"
        label = "01" if i == 0 else f"{i + 1:02d}"
        rec_rows.append(f"""<g class="boot" style="animation-delay:{round(0.22 + 0.08 * i, 2)}s">
      <rect x="796" y="{row_y}" width="356" height="31" fill="{fill}"/>
      <rect x="804" y="{row_y + 5}" width="24" height="21" fill="{color}"/>
      <text x="816" y="{row_y + 19}" text-anchor="middle" class="number" fill="{t['bg0']}">{label}</text>
      <text x="840" y="{row_y + 14}" class="ledger-repo" fill="{t['text']}">{esc(name)}</text>
      <text x="1148" y="{row_y + 14}" text-anchor="end" class="tiny" fill="{color}">{esc(lang)}</text>
      <text x="1148" y="{row_y + 25}" text-anchor="end" class="tiny" fill="{t['muted']}">{dt.strftime('%m.%d')}</text>
    </g>""")

    rail_s = "\n" + "\n".join(rail)
    lang_segments_s = "\n" + "\n".join(lang_segments)
    lang_items_s = "\n" + "\n".join(lang_items)
    cad_s = "\n" + "\n".join(cad_rows)
    rec_s = "\n" + "\n".join(rec_rows)
    top_language = language_segments[0][0].upper()

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="560" viewBox="0 0 1200 560" role="img" aria-label="{esc(username)} live GitHub source repository signals" data-mode="{mode}">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop stop-color="{t['bg0']}"/><stop offset="1" stop-color="{t['bg1']}"/></linearGradient>
    <linearGradient id="accent" x1="0" y1="0" x2="1" y2="0"><stop stop-color="{t['cyan']}"/><stop offset=".5" stop-color="{t['violet']}"/><stop offset="1" stop-color="{t['pink']}"/></linearGradient>
    <radialGradient id="aur1" cx=".5" cy=".5" r=".5"><stop stop-color="{t['cyan']}" stop-opacity=".10"/><stop offset="1" stop-color="{t['cyan']}" stop-opacity="0"/></radialGradient>
    <radialGradient id="aur2" cx=".5" cy=".5" r=".5"><stop stop-color="{t['pink']}" stop-opacity=".09"/><stop offset="1" stop-color="{t['pink']}" stop-opacity="0"/></radialGradient>
    <radialGradient id="signal-glow" cx=".5" cy=".5" r=".5"><stop stop-color="{t['pink']}" stop-opacity=".18"/><stop offset="1" stop-color="{t['pink']}" stop-opacity="0"/></radialGradient>
    <pattern id="grid" width="28" height="28" patternUnits="userSpaceOnUse"><path d="M28 0H0V28" fill="none" stroke="{t['grid']}" stroke-width="1"/></pattern>
    <filter id="glow" x="-100%" y="-100%" width="300%" height="300%"><feGaussianBlur stdDeviation="5" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
    <clipPath id="frame"><path d="{frame_path}"/></clipPath>
  </defs>
  <style>
    text{{font-family:ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,"Liberation Mono",monospace}}
    .title{{font-size:15px;font-weight:800;letter-spacing:3px}}.micro{{font-size:10px;font-weight:700;letter-spacing:2px}}.tiny{{font-size:9px;letter-spacing:1px}}
    .rail-label{{font-size:8px;font-weight:700;letter-spacing:1.3px}}.rail-value{{font-size:17px;font-weight:900;letter-spacing:-.5px}}
    .section{{font-size:11px;font-weight:800;letter-spacing:2px}}.hero-date{{font-size:57px;font-weight:900;letter-spacing:-3px}}.hero-year{{font-size:10px;font-weight:700;letter-spacing:2px}}
    .hero-repo{{font-size:25px;font-weight:900;letter-spacing:-.5px}}.ledger-label{{font-size:10px;font-weight:800;letter-spacing:1px}}.ledger-repo{{font-size:11px;font-weight:800}}.number{{font-size:9px;font-weight:900}}
    .pulse{{transform-box:fill-box;transform-origin:center;animation:pulse 2s ease-in-out infinite}}
    .bar{{transform-box:fill-box;transform-origin:center;animation:grow .9s cubic-bezier(.2,.8,.2,1) both}}
    .boot{{animation:boot .6s ease-out both}}
    @keyframes pulse{{50%{{opacity:.3;transform:scale(.65)}}}}@keyframes grow{{from{{transform:scaleY(.05)}}}}@keyframes boot{{from{{opacity:.45}}}}
    @media(prefers-reduced-motion:reduce){{.pulse,.bar,.boot{{animation:none}}}}
  </style>

<g clip-path="url(#frame)">
    <rect width="1200" height="560" fill="url(#bg)"/>
    <ellipse cx="100" cy="0" rx="380" ry="200" fill="url(#aur1)"/>
    <ellipse cx="1150" cy="560" rx="420" ry="220" fill="url(#aur2)"/>
    <rect width="1200" height="560" fill="url(#grid)" opacity=".32"/>

    <circle cx="32" cy="37" r="5" fill="{t['pink']}" filter="url(#glow)"/>
    <text x="48" y="42" class="title" fill="{t['text']}">LIVE SIGNALS // SOURCE CONTROL</text>
    {rail_s}
    <text x="1172" y="42" text-anchor="end" class="hero-repo" fill="{t['text']}">{esc(username)}</text>
    <path d="M28 64H1172" stroke="{t['line']}"/>
    <path d="M28 64H258" stroke="{t['cyan']}" stroke-width="2"/>

    <g class="boot" style="animation-delay:.18s">
      <rect x="28" y="82" width="704" height="238" fill="{t['panel2']}" opacity=".76"/>
      <path d="M28 82V320" stroke="{t['pink']}" stroke-width="4"/>
      <path d="M28 82H732M28 320H732" stroke="{t['line']}"/>
      <path d="M28 82H58M28 82V112" stroke="{t['pink']}" stroke-width="2"/>
      <text x="54" y="112" class="section" fill="{t['pink']}">LATEST PUSH</text>
      <path d="M54 124H102" stroke="{t['pink']}" stroke-width="4"/>
      <text x="54" y="193" class="hero-date" fill="{t['text']}">{latest_full}</text>
      <text x="54" y="216" class="hero-year" fill="{t['muted']}">UTC SOURCE EVENT · PUBLIC REPOSITORY</text>
      <text x="54" y="256" class="hero-repo" fill="{t['text']}" textLength="420" lengthAdjust="spacingAndGlyphs">{esc(stats['latest_name'])}</text>
      <path d="M54 274H468" stroke="{t['line']}"/>
      <text x="54" y="297" class="tiny" fill="{t['muted']}">LATEST SOURCE SIGNAL · {latest_dt.strftime('%b %d').upper()}</text>
      <g transform="translate(620 190)">
        <circle r="78" fill="url(#signal-glow)"/>
        <circle r="61" fill="none" stroke="{t['line']}" stroke-dasharray="2 6"/>
        <circle r="43" fill="none" stroke="{t['muted']}" stroke-opacity=".65" stroke-dasharray="1 5"/>
        <circle r="24" fill="none" stroke="{t['pink']}" stroke-opacity=".7"/>
        <path d="M-70 0H70M0 -70V70" stroke="{t['line']}" stroke-opacity=".8"/>
        <circle class="pulse" r="7" fill="{t['pink']}" filter="url(#glow)"/>
      </g>
      <text x="620" y="292" text-anchor="middle" class="tiny" fill="{t['pink']}">SIGNAL / ACTIVE</text>
    </g>

    <path d="M760 82V320" stroke="{t['line']}"/>
    <path d="M772 82H1172M772 320H1172" stroke="{t['line']}"/>
    <path d="M772 82V320" stroke="url(#accent)" stroke-width="2"/>
    <text x="796" y="110" class="section" fill="{t['text']}">RECENT TRANSMISSIONS</text>
    <text x="1152" y="110" text-anchor="end" class="tiny" fill="{t['muted']}">LAST 5 · PUSHED</text>
    <path d="M796 122H1152" stroke="{t['line']}"/>
    <path d="M786 152V291" stroke="{t['line']}"/>
    {rec_s}

    <path d="M28 338H1172" stroke="{t['line']}"/>
    <path d="M596 344V514" stroke="{t['line']}"/>
    <text x="28" y="365" class="section" fill="{t['cyan']}">LANGUAGE TELEMETRY</text>
    <text x="572" y="365" text-anchor="end" class="tiny" fill="{t['muted']}">{stats['total']} SOURCE REPOSITORIES</text>
    <path d="M28 378H572" stroke="{t['line']}"/>
    <rect x="28" y="383" width="544" height="14" fill="{t['grid']}"/>
    {lang_segments_s}
    {lang_items_s}
    <text x="28" y="499" class="tiny" fill="{t['muted']}">TOP LANGUAGE · {esc(top_language)}</text>

    <text x="620" y="365" class="section" fill="{t['green']}">PUSH CADENCE</text>
    <text x="1172" y="365" text-anchor="end" class="tiny" fill="{t['muted']}">12 MONTHS · LAST-PUSH RHYTHM</text>
    <path d="M620 378H1172" stroke="{t['line']}"/>
    <path d="M620 425H1172M620 459H1172M620 493H1172" stroke="{t['line']}" stroke-dasharray="2 6"/>
    {cad_s}

    <path d="M28 526H1172" stroke="{t['line']}"/>
    <text x="28" y="548" class="tiny" fill="{t['muted']}">AUTO-SYNC · SOURCE ONLY · RAW GITHUB COUNTS · LAST SIGNAL {latest_full}</text>
    <text x="1172" y="548" text-anchor="end" class="tiny" fill="{t['muted']}">github.com/{esc(username)}</text>
  </g>
  <path d="{frame_path}" fill="none" stroke="{t['line']}" stroke-width="2"/>
  <path d="M12 1H258M1 12V70" fill="none" stroke="{t['cyan']}" stroke-width="2"/>
  <path d="M942 559H1188M1199 490V548" fill="none" stroke="{t['pink']}" stroke-width="2"/>
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
