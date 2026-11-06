#!/usr/bin/env python3
"""Fetch GitHub activity and render the live profile cards.

    GITHUB_TOKEN=... python3 scripts/build_metrics.py --out dist

Writes stats.svg, streak.svg, languages.svg, weekday.svg, activity.svg,
trophies.svg, quote.svg and metrics.json. Runs daily in
.github/workflows/profile-metrics.yml, which publishes them to the `output`
branch. Standard library only.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from svgkit import (ICON_GRADIENT_ID, MONO, ROOT, SANS, animate_attr, card_frame, document, draw_on,
                    esc, fade_in, fmt_num, glow_filter, icon, icon_gradient, linear_gradient,
                    load_config, load_theme, rise_in, wrap, write)

API = "https://api.github.com/graphql"
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

COLLECTION_FIELDS = """
  totalCommitContributions totalIssueContributions totalPullRequestContributions
  totalPullRequestReviewContributions restrictedContributionsCount
  contributionCalendar { totalContributions weeks { contributionDays { date contributionCount } } }
"""


# ── GitHub API ──────────────────────────────────────────────────────────────

def graphql(query: str, variables: dict, token: str) -> dict:
    body = json.dumps({"query": query, "variables": variables}).encode()
    request = urllib.request.Request(API, data=body, method="POST", headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "User-Agent": "profile-metrics-generator",
    })
    for attempt in range(4):
        try:
            with urllib.request.urlopen(request, timeout=40) as response:
                payload = json.load(response)
        except urllib.error.HTTPError as exc:
            if exc.code >= 500 and attempt < 3:
                time.sleep(2 ** attempt * 2)
                continue
            raise SystemExit(f"GitHub API returned HTTP {exc.code}: {exc.read().decode()[:300]}")
        except urllib.error.URLError as exc:
            if attempt < 3:
                time.sleep(2 ** attempt * 2)
                continue
            raise SystemExit(f"Could not reach GitHub API: {exc.reason}")
        if payload.get("errors"):
            raise SystemExit("GitHub API error: " + "; ".join(e.get("message", "?") for e in payload["errors"]))
        return payload["data"]
    raise SystemExit("GitHub API kept failing")


def fetch(login: str, token: str, include_private: bool) -> dict:
    privacy = "" if include_private else ", privacy: PUBLIC"
    repos, cursor, created = [], None, None
    while True:
        data = graphql(f"""
          query($login: String!, $cursor: String) {{ user(login: $login) {{
            createdAt
            repositories(ownerAffiliations: OWNER, isFork: false, first: 100, after: $cursor{privacy}) {{
              pageInfo {{ hasNextPage endCursor }}
              nodes {{ name stargazerCount
                languages(first: 15, orderBy: {{field: SIZE, direction: DESC}}) {{ edges {{ size node {{ name }} }} }} }}
            }} }} }}""", {"login": login, "cursor": cursor}, token)
        user = data["user"]
        if user is None:
            raise SystemExit(f"GitHub user {login!r} not found")
        created = user["createdAt"]
        repos += user["repositories"]["nodes"]
        page = user["repositories"]["pageInfo"]
        if not page["hasNextPage"]:
            break
        cursor = page["endCursor"]

    created_at = datetime.fromisoformat(created.replace("Z", "+00:00"))
    now = datetime.now(timezone.utc)
    windows = []
    for year in range(created_at.year, now.year + 1):
        start = max(created_at, datetime(year, 1, 1, tzinfo=timezone.utc))
        end = min(now, datetime(year, 12, 31, 23, 59, 59, tzinfo=timezone.utc))
        windows.append(f'y{year}: contributionsCollection(from: "{start:%Y-%m-%dT%H:%M:%SZ}", '
                       f'to: "{end:%Y-%m-%dT%H:%M:%SZ}") {{ {COLLECTION_FIELDS} }}')
    data = graphql(f"""
      query($login: String!) {{ user(login: $login) {{
        last: contributionsCollection {{ {COLLECTION_FIELDS} totalRepositoriesWithContributedCommits }}
        {" ".join(windows)}
      }} }}""", {"login": login}, token)
    return {"created": created, "repos": repos, "collections": data["user"]}


# ── Aggregation ─────────────────────────────────────────────────────────────

@dataclass
class Streak:
    length: int = 0
    start: str | None = None
    end: str | None = None


@dataclass
class Metrics:
    created: str
    today: str
    total_all_time: int
    first_day: str | None
    current: Streak
    longest: Streak
    year: dict
    all_time: dict
    active_days: int
    days_in_year: int
    weekdays: list[int]
    weeks: list[tuple[str, int]]
    languages: list[tuple[str, float]]
    public_repos: int
    stars: int
    years_on_github: float
    language_count: int = 0
    extra: dict = field(default_factory=dict)


def _days(collection: dict) -> list[tuple[date, int]]:
    return [(date.fromisoformat(d["date"]), d["contributionCount"])
            for w in collection["contributionCalendar"]["weeks"] for d in w["contributionDays"]]


def _streaks(days: dict[date, int], today: date) -> tuple[Streak, Streak]:
    longest, run_start, run_len = Streak(), None, 0
    ordered = sorted(days)
    prev = None
    for d in ordered:
        if days[d] > 0:
            if prev is not None and run_len and d - prev == timedelta(days=1):
                run_len += 1
            else:
                run_start, run_len = d, 1
            if run_len > longest.length:
                longest = Streak(run_len, run_start.isoformat(), d.isoformat())
        else:
            run_len = 0
        prev = d

    # Current streak: today counts if active; an inactive today doesn't break yesterday's run.
    cursor = today if days.get(today, 0) > 0 else today - timedelta(days=1)
    length, end = 0, cursor
    while days.get(cursor, 0) > 0:
        length += 1
        cursor -= timedelta(days=1)
    current = Streak(length, (cursor + timedelta(days=1)).isoformat(), end.isoformat()) if length else Streak()
    return current, longest


def aggregate(raw: dict, cfg: dict) -> Metrics:
    collections = raw["collections"]
    last = collections["last"]
    days: dict[date, int] = {}
    all_time = defaultdict(int)
    for key, coll in collections.items():
        if key == "last":
            continue
        for d, n in _days(coll):
            days[d] = n
        for k in ("totalCommitContributions", "totalPullRequestContributions",
                  "totalIssueContributions", "totalPullRequestReviewContributions"):
            all_time[k] += coll[k]
    year_days = _days(last)
    for d, n in year_days:          # the rolling-year window is the freshest data
        days[d] = n
    today = max(days) if days else date.today()
    current, longest = _streaks(days, today)

    # The calendar starts on a week boundary (~371 days); stats use exactly the last 365.
    window = [(d, n) for d, n in year_days if d > today - timedelta(days=365)]
    weekdays = [0] * 7
    for d, n in window:
        weekdays[d.weekday()] += n
    weeks = []
    for w in last["contributionCalendar"]["weeks"]:
        wd = w["contributionDays"]
        weeks.append((wd[0]["date"], sum(d["contributionCount"] for d in wd)))

    # Languages: blend byte size and repo count (sqrt each) so one huge repo can't drown the rest.
    excluded = set(cfg["metrics"].get("exclude_languages", []))
    size, count = defaultdict(int), defaultdict(int)
    for repo in raw["repos"]:
        for edge in repo["languages"]["edges"]:
            name = edge["node"]["name"]
            if name in excluded:
                continue
            size[name] += edge["size"]
            count[name] += 1
    weight = {k: math.sqrt(size[k]) * math.sqrt(count[k]) for k in size}
    total_weight = sum(weight.values()) or 1
    langs = sorted(((k, 100 * v / total_weight) for k, v in weight.items()), key=lambda kv: -kv[1])

    created = datetime.fromisoformat(raw["created"].replace("Z", "+00:00"))
    active = [d for d, n in days.items() if n > 0]
    return Metrics(
        created=created.date().isoformat(),
        today=today.isoformat(),
        total_all_time=sum(days.values()),
        first_day=min(active).isoformat() if active else None,
        current=current,
        longest=longest,
        year={
            "contributions": last["contributionCalendar"]["totalContributions"],
            "commits": last["totalCommitContributions"],
            "prs": last["totalPullRequestContributions"],
            "issues": last["totalIssueContributions"],
            "reviews": last["totalPullRequestReviewContributions"],
            "private": last["restrictedContributionsCount"],
            "repos_contributed": last["totalRepositoriesWithContributedCommits"],
        },
        all_time=dict(all_time),
        active_days=sum(1 for _, n in window if n > 0),
        days_in_year=len(window),
        weekdays=weekdays,
        weeks=weeks,
        languages=langs[: cfg["metrics"].get("languages_count", 8)],
        language_count=len(langs),
        public_repos=sum(1 for _ in raw["repos"]),
        stars=sum(r["stargazerCount"] for r in raw["repos"]),
        years_on_github=round((datetime.now(timezone.utc) - created).days / 365.25, 2),
    )


# ── Formatting helpers ──────────────────────────────────────────────────────

def nice_date(iso: str | None, year: bool = True) -> str:
    if not iso:
        return "—"
    d = date.fromisoformat(iso)
    return f"{d:%b} {d.day}, {d.year}" if year else f"{d:%b} {d.day}"


def streak_range(s: Streak, today: str) -> str:
    if not s.length:
        return "No active streak"
    end = "Today" if s.end == today else nice_date(s.end, year=False)
    if s.start == s.end:
        return end if end == "Today" else nice_date(s.end)
    return f"{nice_date(s.start, year=False)} – {end}"


def title_row(title: str, glyph: str, T, sub: str = "", width: float = 480) -> str:
    out = (f'{icon(glyph, 24, 21, 20, f"url(#{ICON_GRADIENT_ID})", 2.2)}'
           f'<text x="54" y="37" font-family="{SANS}" font-size="17" font-weight="700" '
           f'fill="url(#titleGrad)">{esc(title)}</text>')
    if sub:
        out += (f'<text x="{width - 24}" y="36" text-anchor="end" font-family="{MONO}" font-size="11.5" '
                f'fill="{T.muted}">{esc(sub)}</text>')
    return out


def common_defs(T) -> str:
    return linear_gradient("titleGrad", T.gradient, cycle=7) + icon_gradient(T.gradient) + glow_filter("glow", 4, 0.8)


def ring(cx: float, cy: float, r: float, width: float, pct: float, stroke: str, T, begin: float = 0.2) -> str:
    pct = max(0.0, min(pct, 100.0))
    return (f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{T.raised}" stroke-width="{width}"/>'
            f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{stroke}" stroke-width="{width}" '
            f'stroke-linecap="round" pathLength="100" stroke-dasharray="{pct:.2f} 100" '
            f'transform="rotate(-90 {cx} {cy})">'
            f'{animate_attr("stroke-dasharray", "0 100", f"{pct:.2f} 100", begin, 1.3)}</circle>')


# ── Cards ───────────────────────────────────────────────────────────────────

def stats_card(m: Metrics, T) -> str:
    W, H = 480, 220
    defs, bg = card_frame(T, W, H)
    y = m.year
    rows = [
        ("activity", "Contributions", y["contributions"], T.mint),
        ("commit", "Commits", y["commits"], T.cyan),
        ("pr", "Pull requests", y["prs"], T.azure),
        ("eye", "Code reviews", y["reviews"], T.violet),
        ("issue", "Issues opened", y["issues"], T.rose),
        ("repo", "Repos contributed to", y["repos_contributed"], T.amber),
    ]
    body = [title_row("GitHub Stats", "chart", T, "last 12 months", W)]
    for i, (glyph, label, value, color) in enumerate(rows):
        ry = 72 + i * 24
        body.append(f'<g>{rise_in(0.1 + 0.08 * i, 0.4, 6)}{icon(glyph, 24, ry - 12, 16, color, 2)}'
                    f'<text x="50" y="{ry + 1}" font-family="{SANS}" font-size="14" fill="{T.text_dim}">{esc(label)}</text>'
                    f'<text x="300" y="{ry + 1}" text-anchor="end" font-family="{MONO}" font-size="14.5" '
                    f'font-weight="700" fill="{T.text}">{fmt_num(value)}</text></g>')
    pct = 100 * m.active_days / max(m.days_in_year, 1)
    cx, cy = 392, 120
    body.append(
        f'<defs>{linear_gradient("ringG", T.gradient, x2="1", y2="1")}</defs>'
        + ring(cx, cy, 52, 10, pct, "url(#ringG)", T)
        + f'<text x="{cx}" y="{cy + 4}" text-anchor="middle" font-family="{SANS}" font-size="26" '
          f'font-weight="800" fill="{T.text}">{pct:.0f}%</text>'
        + f'<text x="{cx}" y="{cy + 22}" text-anchor="middle" font-family="{MONO}" font-size="10.5" '
          f'fill="{T.muted}">active days</text>'
        + f'<text x="{cx}" y="{cy + 80}" text-anchor="middle" font-family="{MONO}" font-size="11" '
          f'fill="{T.text_dim}">{m.active_days} of {m.days_in_year} days</text>'
    )
    return document(W, H, f'<defs>{defs}{common_defs(T)}</defs>{bg}{"".join(body)}', "GitHub stats",
                    f"{y['contributions']} contributions, {y['commits']} commits, {y['prs']} pull requests "
                    f"in the last 12 months.")


def streak_card(m: Metrics, T) -> str:
    W, H = 480, 220
    defs, bg = card_frame(T, W, H, accent=T.amber)
    fire = linear_gradient("fire", [T.amber, T.rose], x2="0", y2="1")
    since = nice_date(m.first_day or m.created)
    cols = [
        (80, fmt_num(m.total_all_time), "Total Contributions", T.mint, f"{since} – Present"),
        (240, str(m.current.length), "Current Streak", T.amber, streak_range(m.current, m.today)),
        (400, str(m.longest.length), "Longest Streak", T.cyan, streak_range(m.longest, m.today)),
    ]
    body = [f'<line x1="160" y1="40" x2="160" y2="196" stroke="{T.border}"/>'
            f'<line x1="320" y1="40" x2="320" y2="196" stroke="{T.border}"/>']
    cx, cy, r = 240, 96, 46
    ring_pct = 100 if m.current.length else 0
    body.append(ring(cx, cy, r, 7, ring_pct, "url(#fire)", T)
                + f'<circle cx="{cx}" cy="{cy - r}" r="15" fill="{T.surface}"/>'
                + f'<g transform="translate({cx - 11} {cy - r - 12}) scale(0.92)">'
                  f'<path d="{_FLAME}" fill="url(#fire)" stroke="{T.amber}" stroke-width="1.2" stroke-linejoin="round">'
                  f'<animateTransform attributeName="transform" type="scale" values="1 1;1.04 0.95;1 1" '
                  f'dur="1.6s" repeatCount="indefinite" additive="sum"/></path></g>')
    for i, (x, value, label, color, sub) in enumerate(cols):
        body.append(
            f'<g>{rise_in(0.15 + 0.12 * i, 0.5, 8)}'
            f'<text x="{x}" y="{cy + 11}" text-anchor="middle" font-family="{SANS}" font-size="{30 if i else 28}" '
            f'font-weight="800" fill="{T.text}">{esc(value)}</text>'
            f'<text x="{x}" y="170" text-anchor="middle" font-family="{SANS}" font-size="14" font-weight="700" '
            f'fill="{color}">{esc(label)}</text>'
            f'<text x="{x}" y="192" text-anchor="middle" font-family="{MONO}" font-size="11" fill="{T.muted}">'
            f'{esc(sub)}</text></g>')
    return document(W, H, f'<defs>{defs}{fire}{common_defs(T)}</defs>{bg}{"".join(body)}', "Contribution streak",
                    f"{m.total_all_time} total contributions; current streak {m.current.length} days; "
                    f"longest streak {m.longest.length} days.")


_FLAME = "M12 2c1 4 5 6 5 11a5 5 0 0 1-10 0c0-2.5 1.5-4 2.5-5 .3 2 1.2 3 2.5 3.5C11 9 11 5.5 12 2z"


def languages_card(m: Metrics, T) -> str:
    W, H = 480, 220
    defs, bg = card_frame(T, W, H)
    body = [title_row("Top Languages", "code", T, f"{m.language_count} languages · public repos", W)]
    langs = m.languages
    if not langs:
        body.append(f'<text x="{W / 2}" y="120" text-anchor="middle" font-family="{SANS}" font-size="14" '
                    f'fill="{T.muted}">No public code yet</text>')
    else:
        bx, bw, by = 24, W - 48, 58
        segs, x = [], bx
        shown = sum(p for _, p in langs)
        for i, (_, pct) in enumerate(langs):
            w = bw * pct / shown
            segs.append(f'<rect x="{x:.2f}" y="{by}" width="{max(w - 2, 1):.2f}" height="10" '
                        f'fill="{T.series[i % len(T.series)]}">{animate_attr("width", 0, f"{max(w - 2, 1):.2f}", 0.15 + 0.08 * i, 0.5)}</rect>')
            x += w
        body.append(f'<clipPath id="barClip"><rect x="{bx}" y="{by}" width="{bw}" height="10" rx="5"/></clipPath>'
                    f'<rect x="{bx}" y="{by}" width="{bw}" height="10" rx="5" fill="{T.raised}"/>'
                    f'<g clip-path="url(#barClip)">{"".join(segs)}</g>')
        for i, (name, pct) in enumerate(langs):
            col, row = divmod(i, 4)
            x, y = 24 + col * 228, 104 + row * 28
            c = T.series[i % len(T.series)]
            body.append(f'<g>{rise_in(0.25 + 0.06 * i, 0.4, 6)}'
                        f'<circle cx="{x + 6}" cy="{y - 5}" r="5.5" fill="{c}"/>'
                        f'<text x="{x + 20}" y="{y}" font-family="{SANS}" font-size="14" fill="{T.text}">{esc(name)}</text>'
                        f'<text x="{x + 204}" y="{y}" text-anchor="end" font-family="{MONO}" font-size="12.5" '
                        f'fill="{T.text_dim}">{pct:.1f}%</text></g>')
    return document(W, H, f'<defs>{defs}{common_defs(T)}</defs>{bg}{"".join(body)}', "Top languages",
                    ", ".join(f"{n} {p:.1f}%" for n, p in langs))


def weekday_card(m: Metrics, T) -> str:
    W, H = 480, 220
    defs, bg = card_frame(T, W, H, accent=T.azure)
    peak = max(range(7), key=lambda i: m.weekdays[i]) if any(m.weekdays) else None
    sub = f"peak · {WEEKDAYS[peak]}" if peak is not None else "no activity yet"
    body = [title_row("Weekly Rhythm", "calendar", T, sub, W)]
    top, base, bw, gap = 70, 184, 38, 25
    hi = max(m.weekdays) or 1
    grads = ""
    for i, total in enumerate(m.weekdays):
        x = 32 + i * (bw + gap)
        h = max((base - top) * total / hi, 4)
        color = T.amber if i == peak else T.series[i % 3]
        grads += linear_gradient(f"wd{i}", [color, color], x2="0", y2="1", opacities=[1, 0.25])
        delay = 0.15 + 0.07 * i
        body.append(
            f'<rect x="{x}" y="{base - h:.1f}" width="{bw}" height="{h:.1f}" rx="7" fill="url(#wd{i})">'
            f'{animate_attr("height", 0, f"{h:.1f}", delay, 0.7)}{animate_attr("y", base, f"{base - h:.1f}", delay, 0.7)}</rect>'
            f'<g>{fade_in(delay + 0.5, 0.3)}<text x="{x + bw / 2}" y="{base - h - 7:.1f}" text-anchor="middle" '
            f'font-family="{MONO}" font-size="11" font-weight="700" fill="{T.amber if i == peak else T.text_dim}">'
            f'{fmt_num(total)}</text></g>'
            f'<text x="{x + bw / 2}" y="204" text-anchor="middle" font-family="{MONO}" font-size="11.5" '
            f'fill="{T.text if i == peak else T.muted}">{WEEKDAYS[i]}</text>')
    body.insert(1, f'<line x1="24" y1="{base + 0.5}" x2="{W - 24}" y2="{base + 0.5}" stroke="{T.border}"/>')
    return document(W, H, f'<defs>{defs}{grads}{common_defs(T)}</defs>{bg}{"".join(body)}', "Weekly rhythm",
                    "Contributions by weekday over the last year: "
                    + ", ".join(f"{d} {n}" for d, n in zip(WEEKDAYS, m.weekdays)))


def _monotone(points: list[tuple[float, float]]) -> str:
    """Monotone cubic (Fritsch–Carlson) path: smooth, never overshoots the data."""
    n = len(points)
    if n < 2:
        return f"M{points[0][0]} {points[0][1]}" if points else ""
    xs, ys = zip(*points)
    d = [(ys[i + 1] - ys[i]) / (xs[i + 1] - xs[i]) for i in range(n - 1)]
    t = [d[0]] + [0.0 if d[i - 1] * d[i] <= 0 else (d[i - 1] + d[i]) / 2 for i in range(1, n - 1)] + [d[-1]]
    for i in range(n - 1):
        if d[i] == 0:
            t[i] = t[i + 1] = 0.0
            continue
        a, b = t[i] / d[i], t[i + 1] / d[i]
        s = a * a + b * b
        if s > 9:
            k = 3 / math.sqrt(s)
            t[i], t[i + 1] = k * a * d[i], k * b * d[i]
    path = f"M{xs[0]:.1f} {ys[0]:.1f}"
    for i in range(n - 1):
        h = xs[i + 1] - xs[i]
        path += (f" C{xs[i] + h / 3:.1f} {ys[i] + t[i] * h / 3:.1f} {xs[i + 1] - h / 3:.1f} "
                 f"{ys[i + 1] - t[i + 1] * h / 3:.1f} {xs[i + 1]:.1f} {ys[i + 1]:.1f}")
    return path


def _nice_ceiling(v: float) -> tuple[float, float]:
    if v <= 0:
        return 4, 1
    raw = v / 4
    mag = 10 ** math.floor(math.log10(raw))
    step = next(s * mag for s in (1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10) if s * mag >= raw)
    return step * 4, step


def activity_card(m: Metrics, T) -> str:
    W, H = 960, 300
    defs, bg = card_frame(T, W, H)
    weeks = m.weeks
    total = sum(n for _, n in weeks)
    peak_i = max(range(len(weeks)), key=lambda i: weeks[i][1]) if weeks else 0
    sub = (f"{fmt_num(total)} contributions · best week {nice_date(weeks[peak_i][0], year=False)} "
           f"({weeks[peak_i][1]})") if weeks and total else "no contributions in the last year"
    x0, x1, y0, y1 = 64, W - 28, 72, 244
    ymax, ystep = _nice_ceiling(max((n for _, n in weeks), default=0))
    body = [title_row("Contribution Activity", "activity", T, sub, W)]
    for k in range(5):
        v = ystep * k
        y = y1 - (y1 - y0) * v / ymax
        body.append(f'<line x1="{x0}" y1="{y:.1f}" x2="{x1}" y2="{y:.1f}" stroke="{T.border}" '
                    f'stroke-dasharray="{"0" if k == 0 else "3 5"}"/>'
                    f'<text x="{x0 - 12}" y="{y + 4:.1f}" text-anchor="end" font-family="{MONO}" font-size="10.5" '
                    f'fill="{T.muted}">{v:g}</text>')
    if weeks:
        step = (x1 - x0) / max(len(weeks) - 1, 1)
        pts = [(x0 + i * step, y1 - (y1 - y0) * n / ymax) for i, (_, n) in enumerate(weeks)]
        line = _monotone(pts)
        area = f"{line} L{pts[-1][0]:.1f} {y1} L{pts[0][0]:.1f} {y1} Z"
        defs += (linear_gradient("areaG", [T.mint, T.cyan], x2="0", y2="1", opacities=[0.42, 0])
                 + linear_gradient("lineG", T.gradient, x1=str(x0), x2=str(x1), units="userSpaceOnUse"))
        body.append(f'<path d="{area}" fill="url(#areaG)" opacity="1">{fade_in(0.6, 1.0)}</path>'
                    f'<path d="{line}" fill="none" stroke="url(#lineG)" stroke-width="2.6" stroke-linecap="round" '
                    f'filter="url(#glow)" pathLength="1" stroke-dasharray="1">{draw_on(0.15, 1.6)}</path>')
        last_month = None
        last_x = -999.0
        for i, (start, _) in enumerate(weeks):
            d = date.fromisoformat(start) + timedelta(days=6)
            if d.month != last_month and pts[i][0] - last_x > 44:
                body.append(f'<text x="{pts[i][0]:.1f}" y="270" text-anchor="middle" font-family="{MONO}" '
                            f'font-size="11" fill="{T.muted}">{d:%b}</text>')
                last_x = pts[i][0]
            last_month = d.month
        dots = "".join(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2.4" fill="{T.surface}" stroke="{T.cyan}" '
                       f'stroke-width="1.4"/>' for x, y in pts)
        body.append(f'<g>{fade_in(1.2, 0.5)}{dots}</g>')
        if total:
            px, py = pts[peak_i]
            body.append(f'<g>{fade_in(1.6, 0.4)}<circle cx="{px:.1f}" cy="{py:.1f}" r="5.5" fill="{T.amber}" '
                        f'filter="url(#glow)"/><text x="{px:.1f}" y="{py - 12:.1f}" text-anchor="middle" '
                        f'font-family="{MONO}" font-size="11.5" font-weight="700" fill="{T.amber}">'
                        f'{weeks[peak_i][1]}</text></g>')
    return document(W, H, f'<defs>{defs}{common_defs(T)}</defs>{bg}{"".join(body)}', "Contribution activity",
                    f"Weekly contributions over the last 12 months; {total} in total.")


TIERS = [("C", "azure"), ("B", "cyan"), ("A", "mint"), ("S", "amber")]


def trophies_card(m: Metrics, T) -> str:
    W, H, tw, gap = 960, 196, 126, 13
    a = m.all_time
    items = [
        ("Committer", "commit", a.get("totalCommitContributions", 0), "commits", (10, 100, 500, 1000)),
        ("Contributor", "activity", m.total_all_time, "contributions", (50, 250, 1000, 2500)),
        ("Collaborator", "pr", a.get("totalPullRequestContributions", 0), "pull requests", (1, 10, 50, 150)),
        ("Reviewer", "eye", a.get("totalPullRequestReviewContributions", 0), "reviews", (1, 10, 50, 150)),
        ("Polyglot", "globe", m.language_count, "languages", (2, 4, 6, 9)),
        ("Consistency", "flame", m.longest.length, "day streak", (3, 7, 21, 60)),
        ("Veteran", "clock", int(m.years_on_github), "years on GitHub", (1, 2, 4, 6)),
    ]
    defs = glow_filter("glow", 4, 0.8)
    tiles = []
    for i, (title, glyph, value, unit, steps) in enumerate(items):
        x = i * (tw + gap)
        level = sum(1 for s in steps if value >= s)
        locked = level == 0
        letter, color_name = TIERS[level - 1] if level else ("?", "muted")
        color = getattr(T, color_name)
        if level < len(steps):
            prev = steps[level - 1] if level else 0
            progress = (value - prev) / (steps[level] - prev)
            hint = f"next {TIERS[level][0]} at {fmt_num(steps[level])}"
        else:
            progress, hint = 1.0, "max tier reached"
        cx, cy, r = x + tw / 2, 62, 34
        dash = ' stroke-dasharray="4 4"' if locked else ""
        hexagon = " ".join(f"{cx + r * math.cos(math.radians(-90 + 60 * k)):.1f},"
                           f"{cy + r * math.sin(math.radians(-90 + 60 * k)):.1f}" for k in range(6))
        defs += (f'<radialGradient id="tg{i}"><stop offset="0" stop-color="{color}" stop-opacity="0.32"/>'
                 f'<stop offset="1" stop-color="{color}" stop-opacity="0"/></radialGradient>')
        delay = 0.1 + 0.1 * i
        tiles.append(
            f'<g>{rise_in(delay, 0.5, 10)}'
            f'<rect x="{x + 0.75}" y="0.75" width="{tw - 1.5}" height="{H - 1.5}" rx="16" fill="{T.surface}" '
            f'stroke="{T.border if locked else color}" stroke-opacity="{1 if locked else 0.55}" stroke-width="1.5"/>'
            f'<circle cx="{cx}" cy="{cy}" r="56" fill="url(#tg{i})"/>'
            f'<polygon points="{hexagon}" fill="{color}" fill-opacity="{0.06 if locked else 0.14}" stroke="{color}" '
            f'stroke-width="2" stroke-linejoin="round"{dash}/>'
            f'{icon("lock" if locked else glyph, cx - 13, cy - 13, 26, color, 2)}'
            f'<circle cx="{cx + 27}" cy="{cy - 25}" r="12" fill="{color if not locked else T.raised}" '
            f'stroke="{T.surface}" stroke-width="3"/>'
            f'<text x="{cx + 27}" y="{cy - 20.5}" text-anchor="middle" font-family="{SANS}" font-size="13" '
            f'font-weight="800" fill="{T.ink if not locked else T.muted}">{letter}</text>'
            f'<text x="{cx}" y="124" text-anchor="middle" font-family="{SANS}" font-size="14" font-weight="700" '
            f'fill="{T.text if not locked else T.muted}">{title}</text>'
            f'<text x="{cx}" y="143" text-anchor="middle" font-family="{MONO}" font-size="11" fill="{T.text_dim}">'
            f'{fmt_num(value)} {esc(unit)}</text>'
            f'<rect x="{x + 18}" y="156" width="{tw - 36}" height="5" rx="2.5" fill="{T.raised}"/>'
            f'<rect x="{x + 18}" y="156" width="{max((tw - 36) * min(progress, 1), 2):.1f}" height="5" rx="2.5" '
            f'fill="{color}">{animate_attr("width", 0, f"{max((tw - 36) * min(progress, 1), 2):.1f}", delay + 0.4, 0.8)}</rect>'
            f'<text x="{cx}" y="180" text-anchor="middle" font-family="{MONO}" font-size="9.5" fill="{T.muted}">'
            f'{esc(hint)}</text></g>')
    return document(W, H, f"<defs>{defs}</defs>{''.join(tiles)}", "Achievements",
                    "; ".join(f"{t}: {v} {u}" for t, _, v, u, _ in items))


def quote_card(cfg: dict, T, today: date) -> str:
    quotes = cfg["metrics"]["quotes"]
    q = quotes[today.toordinal() % len(quotes)]
    lines = wrap(q["text"], 64)
    W = 840
    H = 92 + 32 * len(lines) + 20
    defs, bg = card_frame(T, W, H, accent=T.violet)
    text = "".join(f'<text x="96" y="{62 + 32 * i}" font-family="{SANS}" font-size="21" font-style="italic" '
                   f'fill="{T.text}">{esc(line)}</text>' for i, line in enumerate(lines))
    ay = 62 + 32 * len(lines) + 12
    body = (
        f'<rect x="28" y="30" width="48" height="48" rx="14" fill="{T.violet}" fill-opacity="0.12"/>'
        f'{icon("quote", 38, 40, 28, f"url(#{ICON_GRADIENT_ID})", 2.2)}'
        f'<g>{rise_in(0.1, 0.6, 8)}{text}</g>'
        f'<g>{fade_in(0.6, 0.5)}<rect x="96" y="{ay - 5}" width="28" height="2" rx="1" fill="url(#titleGrad)"/>'
        f'<text x="134" y="{ay}" font-family="{MONO}" font-size="14" font-weight="700" fill="{T.mint}">'
        f'{esc(q["author"])}</text></g>'
        f'<text x="{W - 24}" y="{H - 18}" text-anchor="end" font-family="{MONO}" font-size="11" fill="{T.muted}">'
        f'quote of the day · {nice_date(today.isoformat())}</text>'
    )
    return document(W, H, f'<defs>{defs}{common_defs(T)}</defs>{bg}{body}', "Quote of the day",
                    f'"{q["text"]}" — {q["author"]}')


# ── Entry point ─────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Render live GitHub profile cards.")
    parser.add_argument("--out", type=Path, default=ROOT / "dist")
    parser.add_argument("--user", help="GitHub login (default: profile.username in profile.toml)")
    args = parser.parse_args()

    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        sys.exit("Set GITHUB_TOKEN (or GH_TOKEN) to a token that can read public GitHub data.")
    cfg = load_config()
    T = load_theme(cfg)
    login = args.user or cfg["profile"]["username"]
    include_private = bool(cfg["metrics"].get("include_private_languages", False))

    print(f"Fetching GitHub data for {login} …")
    m = aggregate(fetch(login, token, include_private), cfg)
    out: Path = args.out
    write(out / "stats.svg", stats_card(m, T))
    write(out / "streak.svg", streak_card(m, T))
    write(out / "languages.svg", languages_card(m, T))
    write(out / "weekday.svg", weekday_card(m, T))
    write(out / "activity.svg", activity_card(m, T))
    write(out / "trophies.svg", trophies_card(m, T))
    write(out / "quote.svg", quote_card(cfg, T, datetime.now(timezone.utc).date()))
    summary = asdict(m)
    summary.pop("weeks")
    summary["generated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    write(out / "metrics.json", json.dumps(summary, indent=2) + "\n")
    print(f"Done: {m.total_all_time} contributions all-time, current streak {m.current.length}, "
          f"longest {m.longest.length}, {len(m.languages)} languages shown.")


if __name__ == "__main__":
    main()
