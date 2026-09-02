#!/usr/bin/env python3
"""Generate self-hosted GitHub profile telemetry from public source repos only."""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


API_ROOT = "https://api.github.com"
REPO_LINK = re.compile(r"https://github\.com/([A-Za-z0-9-]+)/([A-Za-z0-9._-]+)")


def fetch_public_repos(username: str, token: str | None = None) -> list[dict[str, Any]]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "nextcandy-profile-dashboard",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    repos: list[dict[str, Any]] = []
    page = 1
    while True:
        url = (
            f"{API_ROOT}/users/{username}/repos?type=owner&sort=pushed"
            f"&per_page=100&page={page}"
        )
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                batch = json.load(response)
        except (urllib.error.URLError, json.JSONDecodeError) as error:
            raise RuntimeError(f"could not read GitHub repositories: {error}") from error
        if not isinstance(batch, list):
            raise RuntimeError("GitHub repository response was not a list")
        repos.extend(batch)
        if len(batch) < 100:
            return repos
        page += 1


def source_repos(repos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return public, non-fork repositories sorted by most recent push."""
    filtered = [repo for repo in repos if not repo.get("fork") and not repo.get("private")]
    return sorted(filtered, key=lambda repo: repo.get("pushed_at") or "", reverse=True)


def profile_stats(username: str, repos: list[dict[str, Any]]) -> dict[str, Any]:
    projects = [repo for repo in source_repos(repos) if repo.get("name") != username]
    if not projects:
        raise RuntimeError("no public source repositories found")

    languages = Counter(repo["language"] for repo in projects if repo.get("language"))
    latest_year = max(int(repo["pushed_at"][:4]) for repo in projects if repo.get("pushed_at"))
    active = [repo for repo in projects if (repo.get("pushed_at") or "").startswith(str(latest_year))]
    latest = projects[0]
    return {
        "source_count": len(projects),
        "language_count": len(languages),
        "languages": languages.most_common(6),
        "active_count": len(active),
        "active_year": latest_year,
        "latest_date": datetime.fromisoformat(latest["pushed_at"].replace("Z", "+00:00")),
        "recent": projects[:5],
        "source_names": {repo["name"] for repo in projects},
    }


def assert_readme_source_only(readme: Path, username: str, source_names: set[str]) -> None:
    invalid: list[str] = []
    for owner, repo in REPO_LINK.findall(readme.read_text(encoding="utf-8")):
        if owner.lower() == username.lower() and repo not in source_names and repo != username:
            invalid.append(repo)
    if invalid:
        names = ", ".join(sorted(set(invalid), key=str.lower))
        raise RuntimeError(f"README links to repositories that are not public source repos: {names}")


THEMES = {
    "dark": {
        "bg0": "#050B12",
        "bg1": "#0A1821",
        "panel": "#0B1D27",
        "panel2": "#0E2632",
        "grid": "#15313D",
        "line": "#244957",
        "text": "#E7F7FC",
        "muted": "#7897A4",
        "cyan": "#00D4FF",
        "pink": "#FF4D9D",
        "green": "#35F5A0",
        "amber": "#FFC857",
    },
    "light": {
        "bg0": "#F7FCFE",
        "bg1": "#EDF8FB",
        "panel": "#FFFFFF",
        "panel2": "#F1FAFC",
        "grid": "#D8EBF0",
        "line": "#A7C8D2",
        "text": "#0B2732",
        "muted": "#557581",
        "cyan": "#009FC7",
        "pink": "#E83E8C",
        "green": "#159A62",
        "amber": "#C27B00",
    },
}


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def render_dashboard(username: str, stats: dict[str, Any], mode: str) -> str:
    c = THEMES[mode]
    metrics = [
        ("SOURCE REPOS", stats["source_count"], "forks excluded", c["cyan"]),
        ("LANGUAGE NODES", stats["language_count"], "primary stacks", c["pink"]),
        (f"ACTIVE / {stats['active_year']}", stats["active_count"], "recently pushed", c["green"]),
        ("LATEST PUSH", stats["latest_date"].strftime("%m.%d"), stats["recent"][0]["name"], c["amber"]),
    ]

    metric_svg: list[str] = []
    for index, (label, value, note, color) in enumerate(metrics):
        x = 28 + index * 289
        metric_svg.append(
            f'''<g class="boot" style="animation-delay:{index * 0.12}s" transform="translate({x} 78)">
      <rect width="267" height="100" rx="12" fill="{c['panel']}" stroke="{c['line']}"/>
      <path d="M0 12Q0 0 12 0H267" fill="none" stroke="{color}" stroke-width="2"/>
      <text x="18" y="28" class="micro" fill="{c['muted']}">{esc(label)}</text>
      <text x="18" y="68" class="metric" fill="{color}">{esc(value)}</text>
      <text x="249" y="68" text-anchor="end" class="tiny" fill="{c['muted']}">{esc(note)}</text>
      <circle class="pulse" cx="249" cy="22" r="3" fill="{color}"/>
    </g>'''
        )

    max_count = max((count for _, count in stats["languages"]), default=1)
    language_svg: list[str] = []
    for index, (language, count) in enumerate(stats["languages"]):
        y = 247 + index * 34
        width = 330 * count / max_count
        color = c["cyan"] if index < 3 else c["pink"]
        language_svg.append(
            f'''<g transform="translate(48 {y})">
      <text x="0" y="13" class="row" fill="{c['text']}">{esc(language.upper())}</text>
      <rect x="112" y="3" width="350" height="10" rx="5" fill="{c['grid']}"/>
      <rect class="bar" style="animation-delay:{0.25 + index * 0.09}s" x="112" y="3" width="{width:.1f}" height="10" rx="5" fill="{color}"/>
      <text x="480" y="13" text-anchor="end" class="row" fill="{c['muted']}">{count:03d}</text>
    </g>'''
        )

    recent_svg: list[str] = []
    for index, repo in enumerate(stats["recent"]):
        y = 247 + index * 39
        pushed = datetime.fromisoformat(repo["pushed_at"].replace("Z", "+00:00"))
        language = repo.get("language") or "CONFIG"
        color = c["cyan"] if index % 2 == 0 else c["pink"]
        recent_svg.append(
            f'''<g class="boot" style="animation-delay:{0.3 + index * 0.1}s" transform="translate(646 {y})">
      <circle class="pulse" cx="5" cy="7" r="4" fill="{color}"/>
      <path d="M18 7H42" stroke="{color}" stroke-opacity=".55"/>
      <text x="52" y="11" class="repo" fill="{c['text']}">{esc(repo['name'])}</text>
      <text x="306" y="11" class="row" fill="{c['muted']}">{esc(language.upper())}</text>
      <text x="486" y="11" text-anchor="end" class="row" fill="{c['muted']}">{pushed:%Y.%m.%d}</text>
    </g>'''
        )

    latest_stamp = stats["latest_date"].strftime("%Y.%m.%d")
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="500" viewBox="0 0 1200 500" role="img" aria-label="{esc(username)} live GitHub source repository signals" data-mode="{mode}">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop stop-color="{c['bg0']}"/><stop offset="1" stop-color="{c['bg1']}"/></linearGradient>
    <linearGradient id="accent" x1="0" y1="0" x2="1" y2="0"><stop stop-color="{c['cyan']}"/><stop offset=".55" stop-color="{c['green']}"/><stop offset="1" stop-color="{c['pink']}"/></linearGradient>
    <pattern id="grid" width="28" height="28" patternUnits="userSpaceOnUse"><path d="M28 0H0V28" fill="none" stroke="{c['grid']}" stroke-width="1"/></pattern>
    <filter id="glow" x="-100%" y="-100%" width="300%" height="300%"><feGaussianBlur stdDeviation="5" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
    <clipPath id="frame"><rect x="1" y="1" width="1198" height="498" rx="18"/></clipPath>
  </defs>
  <style>
    text{{font-family:ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,"Liberation Mono",monospace}}
    .title{{font-size:15px;font-weight:800;letter-spacing:3px}}.micro{{font-size:10px;font-weight:700;letter-spacing:2px}}.tiny{{font-size:9px;letter-spacing:1px}}
    .metric{{font-size:34px;font-weight:900;letter-spacing:-1px}}.row{{font-size:11px;font-weight:700;letter-spacing:1px}}.repo{{font-size:13px;font-weight:800}}
    .pulse{{transform-box:fill-box;transform-origin:center;animation:pulse 2s ease-in-out infinite}}.scan{{animation:scan 6s linear infinite}}.bar{{transform-box:fill-box;transform-origin:left;animation:grow .9s cubic-bezier(.2,.8,.2,1) both}}.boot{{animation:boot .6s ease-out both}}
    @keyframes pulse{{50%{{opacity:.3;transform:scale(.65)}}}}@keyframes scan{{from{{transform:translateY(-70px)}}to{{transform:translateY(570px)}}}}@keyframes grow{{from{{transform:scaleX(.06)}}}}@keyframes boot{{from{{opacity:.45}}}}
    @media(prefers-reduced-motion:reduce){{.pulse,.scan,.bar,.boot{{animation:none}}}}
  </style>
  <g clip-path="url(#frame)">
    <rect width="1200" height="500" fill="url(#bg)"/><rect width="1200" height="500" fill="url(#grid)" opacity=".62"/>
    <path d="M0 0H1200" stroke="url(#accent)" stroke-width="3"/>
    <rect class="scan" x="0" y="-70" width="1200" height="70" fill="url(#accent)" opacity=".025"/>
    <text x="28" y="38" class="title" fill="{c['cyan']}">LIVE SIGNALS // SOURCE CONTROL</text>
    <g transform="translate(956 31)"><circle class="pulse" r="5" fill="{c['green']}" filter="url(#glow)"/><text x="14" y="4" class="micro" fill="{c['green']}">FORK FILTER: ON</text></g>
    <path d="M28 54H1172" stroke="{c['line']}"/>
    {''.join(metric_svg)}
    <g transform="translate(28 203)"><rect width="548" height="252" rx="14" fill="{c['panel']}" stroke="{c['line']}"/><text x="20" y="28" class="micro" fill="{c['cyan']}">LANGUAGE TELEMETRY</text><text x="520" y="28" text-anchor="end" class="tiny" fill="{c['muted']}">PRIMARY LANGUAGE / REPOSITORY</text></g>
    {''.join(language_svg)}
    <g transform="translate(594 203)"><rect width="578" height="252" rx="14" fill="{c['panel']}" stroke="{c['line']}"/><text x="20" y="28" class="micro" fill="{c['pink']}">RECENT TRANSMISSIONS</text><text x="550" y="28" text-anchor="end" class="tiny" fill="{c['muted']}">PUBLIC · ORIGINAL · PUSHED</text></g>
    {''.join(recent_svg)}
    <path d="M28 476H1172" stroke="{c['line']}"/><text x="28" y="491" class="tiny" fill="{c['muted']}">AUTO-SYNC · SOURCE ONLY · RAW GITHUB COUNTS · LAST SIGNAL {latest_stamp}</text><text x="1172" y="491" text-anchor="end" class="tiny" fill="{c['muted']}">github.com/{esc(username)}</text>
  </g>
  <rect x="1" y="1" width="1198" height="498" rx="18" fill="none" stroke="url(#accent)" stroke-opacity=".72"/>
</svg>\n'''


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--username", default="NextCandy")
    parser.add_argument("--output", type=Path, default=Path("assets"))
    parser.add_argument("--token", default=os.environ.get("GITHUB_TOKEN"))
    parser.add_argument("--check-readme", type=Path)
    args = parser.parse_args()

    repos = fetch_public_repos(args.username, args.token)
    stats = profile_stats(args.username, repos)
    if args.check_readme:
        assert_readme_source_only(args.check_readme, args.username, stats["source_names"])

    args.output.mkdir(parents=True, exist_ok=True)
    for mode in THEMES:
        target = args.output / f"dashboard-{mode}.svg"
        target.write_text(render_dashboard(args.username, stats, mode), encoding="utf-8")

    print(
        f"generated dashboards from {stats['source_count']} public source repos; "
        f"forks excluded; {stats['language_count']} languages"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1) from error
