#!/usr/bin/env python3
"""Build the static profile artwork (./assets/*.svg) from profile.toml.

    python3 scripts/build_assets.py
"""
from __future__ import annotations

import argparse
from pathlib import Path

from svgkit import (ICON_GRADIENT_ID, MONO, MONO_EM, ROOT, SANS, animate_attr, blink, document,
                    draw_on, esc, fade_in, glow_filter, icon, icon_gradient, linear_gradient,
                    load_config, load_theme, mono_width, pulse, ramp, rise_in, wrap, write)

SECTIONS = [
    ("about", "About Me", "user"),
    ("work", "Featured Work", "code"),
    ("trophies", "Achievements", "trophy"),
    ("stats", "GitHub Analytics", "chart"),
    ("snake", "Contribution Snake", "grid"),
    ("tech", "Tech Stack", "layers"),
    ("building", "Building & Learning", "bolt"),
    ("connect", "Let's Connect", "send"),
    ("quote", "Quote of the Day", "quote"),
]


def _rng(seed: int):
    state = seed
    while True:
        state = (1103515245 * state + 12345) % 2**31
        yield state / 2**31


# ── Typing effect ───────────────────────────────────────────────────────────

def _discrete(attr: str, points: list[tuple[float, float | str]], total: float, *, repeat: bool) -> str:
    """A discrete SMIL animation through (time, value) points."""
    keys, values, last = [], [], None
    for t, v in points:
        k = round(t / total, 4)
        if keys and k <= keys[-1]:
            values[-1] = v
            continue
        keys.append(k)
        values.append(v)
        last = k
    keys[0] = 0.0
    if last is not None and last < 1:
        keys.append(1.0)
        values.append(values[-1] if not repeat else points[0][1])
    rep = ' repeatCount="indefinite"' if repeat else ' fill="freeze"'
    return (f'<animate attributeName="{attr}" calcMode="discrete" dur="{total:.3f}s"{rep} '
            f'keyTimes="{";".join(f"{k:g}" for k in keys)}" values="{";".join(str(v) for v in values)}"/>')


def typed_cycle(prefix_id: str, phrases: list[str], colors: list[str], x: float, y: float,
                size: float, start: float = 0.9) -> str:
    """Types each phrase, holds it, erases it, then moves on. Loops forever."""
    cw = size * MONO_EM
    schedule, t = [], start
    for phrase in phrases:
        n = len(phrase)
        typing, hold, erase = 0.065 * n, 2.0, 0.028 * n
        schedule.append((t, n, typing, hold, erase))
        t += typing + hold + erase + 0.35
    total = t

    out, cursor_pts, color_pts = [], [(0.0, round(x, 2))], []
    for i, (phrase, (s, n, typing, hold, erase)) in enumerate(zip(phrases, schedule)):
        pts = [(0.0, 0)]
        pts += [(s + typing * k / n, round(k * cw, 2)) for k in range(n + 1)]
        pts += [(s + typing + hold + erase * k / n, round((n - k) * cw, 2)) for k in range(1, n + 1)]
        cursor_pts += [(tt, round(x + w, 2)) for tt, w in pts[1:]]
        color_pts.append((s, colors[i % len(colors)]))
        full = round(n * cw, 2)
        cid = f"{prefix_id}{i}"
        out.append(
            f'<clipPath id="{cid}"><rect x="{x}" y="{y - size}" height="{size * 1.5}" '
            f'width="{full if i == 0 else 0}">{_discrete("width", pts, total, repeat=True)}</rect></clipPath>'
            f'<text x="{x}" y="{y}" font-family="{MONO}" font-size="{size}" font-weight="600" '
            f'fill="{colors[i % len(colors)]}" textLength="{full}" lengthAdjust="spacing" '
            f'clip-path="url(#{cid})">{esc(phrase)}</text>'
        )
    color_pts[0] = (0.0, color_pts[0][1])
    first_full = round(len(phrases[0]) * cw, 2)
    out.append(
        f'<rect x="{x + first_full + 3}" y="{y - size * 0.82}" width="{size * 0.55}" height="{size * 1.02}" '
        f'rx="2" fill="{colors[0]}">'
        f'{_discrete("x", [(tt, v + 3) for tt, v in cursor_pts], total, repeat=True)}'
        f'{_discrete("fill", color_pts, total, repeat=True)}{blink(0.9)}</rect>'
    )
    return "".join(out)


# ── Header ──────────────────────────────────────────────────────────────────

def _chip(x: float, y: float, label: str, glyph: str | None, color: str, T, delay: float) -> tuple[str, float]:
    size, pad, iw, h = 14, 14, 18, 34
    tw = mono_width(label, size)
    w = pad + iw + 9 + tw + pad
    if glyph:
        mark = icon(glyph, x + pad, y + 8, iw, color, 2)
    else:  # live status dot with a ripple
        cx, cy = x + pad + iw / 2, y + h / 2
        mark = (f'<circle cx="{cx}" cy="{cy}" r="4.5" fill="{color}"/>'
                f'<circle cx="{cx}" cy="{cy}" r="4.5" fill="none" stroke="{color}" stroke-width="2">'
                f'{pulse("r", "4.5;11", 1.8)}{pulse("opacity", "0.8;0", 1.8)}</circle>')
    svg = (f'<g>{rise_in(delay, 0.5, 8)}'
           f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{h / 2}" fill="{T.raised}" fill-opacity="0.9" '
           f'stroke="{color}" stroke-opacity="0.5"/>{mark}'
           f'<text x="{x + pad + iw + 9}" y="{y + 22}" font-family="{MONO}" font-size="{size}" fill="{T.text}" '
           f'textLength="{tw}" lengthAdjust="spacing">{esc(label)}</text></g>')
    return svg, w


def header(cfg: dict, T) -> str:
    P = cfg["profile"]
    W, H = 1200, 380
    g = T.gradient
    cx, cy, s = 980, 190, 2.6           # monogram centre and scale (64-unit glyph box)
    ox, oy = cx - 32 * s, cy - 32 * s

    defs = [
        linear_gradient("nameGrad", g, cycle=6),
        linear_gradient("barGrad", g, cycle=6),
        linear_gradient("ringGrad", [g[0], g[2], g[1]], cycle=9),
        linear_gradient("sGrad", [T.mint, T.cyan], x2="1", y2="1"),
        f'<linearGradient id="bgGrad" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{T.bg}"/>'
        f'<stop offset="0.55" stop-color="{T.surface}"/><stop offset="1" stop-color="{T.bg}"/></linearGradient>',
        *[f'<radialGradient id="{gid}"><stop offset="0" stop-color="{c}" stop-opacity="{o}"/>'
          f'<stop offset="1" stop-color="{c}" stop-opacity="0"/></radialGradient>'
          for gid, c, o in (("glowA", T.mint, 0.42), ("glowB", T.azure, 0.45), ("glowC", T.cyan, 0.3))],
        f'<radialGradient id="gridFade" cx="0.8" cy="0.5" r="0.8"><stop offset="0" stop-color="#fff" '
        f'stop-opacity="0.95"/><stop offset="1" stop-color="#fff" stop-opacity="0.1"/></radialGradient>',
        f'<mask id="gridMask"><rect width="{W}" height="{H}" fill="url(#gridFade)"/></mask>',
        f'<pattern id="grid" width="40" height="40" patternUnits="userSpaceOnUse">'
        f'<path d="M40 0H0V40" fill="none" stroke="{T.grid}" stroke-width="1"/></pattern>',
        f'<clipPath id="card"><rect width="{W}" height="{H}" rx="24"/></clipPath>',
        glow_filter("glow", 5, 0.9),
        glow_filter("softGlow", 10, 0.6),
    ]

    # Background: gradient, masked grid, slow "aurora" blobs, twinkling stars.
    rnd = _rng(7)
    stars = []
    for _ in range(26):
        sx, sy = 640 + next(rnd) * 560, 12 + next(rnd) * 356
        r, d = 0.7 + next(rnd) * 1.1, 2.5 + next(rnd) * 4
        stars.append(f'<circle cx="{sx:.1f}" cy="{sy:.1f}" r="{r:.2f}" fill="{T.text}" opacity="0.5">'
                     f'{pulse("opacity", "0.15;0.85;0.15", round(d, 2), round(next(rnd) * 3, 2))}</circle>')
    background = (
        f'<g clip-path="url(#card)">'
        f'<rect width="{W}" height="{H}" fill="url(#bgGrad)"/>'
        f'<rect width="{W}" height="{H}" fill="url(#grid)" mask="url(#gridMask)"/>'
        f'<ellipse cx="170" cy="30" rx="430" ry="250" fill="url(#glowA)">{pulse("opacity", "0.6;1;0.6", 9)}</ellipse>'
        f'<ellipse cx="1090" cy="370" rx="470" ry="280" fill="url(#glowB)">{pulse("opacity", "0.55;0.95;0.55", 11)}</ellipse>'
        f'<ellipse cx="760" cy="20" rx="320" ry="190" fill="url(#glowC)">{pulse("opacity", "0.4;0.9;0.4", 13)}</ellipse>'
        f'{"".join(stars)}'
        f'<rect width="{W}" height="4" fill="url(#barGrad)"/>'
        f'<rect y="{H - 2}" width="{W}" height="2" fill="url(#barGrad)" opacity="0.55"/>'
        f'</g>'
        f'<rect x="0.75" y="0.75" width="{W - 1.5}" height="{H - 1.5}" rx="23.5" fill="none" '
        f'stroke="url(#barGrad)" stroke-opacity="0.45" stroke-width="1.5"/>'
    )

    # Circuit traces leaving the monogram, with pulses travelling outwards.
    top, bottom, left, right = oy + s, oy + 63 * s, ox + s, ox + 63 * s
    traces = [
        (f"M940 {top:.1f} V64 H872 V-4", T.mint, 3.6, 0.0),
        (f"M1022 {top:.1f} V52 H1120 V-4", T.cyan, 4.2, 1.3),
        (f"M{right:.1f} 160 H1126 V118 H1204", T.azure, 3.2, 0.6),
        (f"M{right:.1f} 222 H1146 V262 H1204", T.mint, 4.6, 2.1),
        (f"M948 {bottom:.1f} V324 H866 V384", T.cyan, 3.8, 0.9),
        (f"M1014 {bottom:.1f} V340 H1098 V384", T.azure, 4.4, 2.6),
        (f"M{left:.1f} 190 H846 V246 H808", T.mint, 3.0, 1.7),
    ]
    circuit = []
    for d, color, dur, begin in traces:
        circuit.append(f'<path d="{d}" fill="none" stroke="{T.border}" stroke-width="2.2" stroke-linejoin="round"/>'
                       f'<path d="{d}" fill="none" stroke="{color}" stroke-opacity="0.22" stroke-width="2.2"/>')
        circuit.append(
            f'<circle r="3.4" fill="{color}" filter="url(#glow)" opacity="0">'
            f'<animateMotion path="{d}" dur="{dur}s" begin="{begin}s" repeatCount="indefinite"/>'
            f'<animate attributeName="opacity" values="0;1;1;0" keyTimes="0;0.08;0.8;1" dur="{dur}s" '
            f'begin="{begin}s" repeatCount="indefinite"/></circle>')
    circuit.append(f'<circle cx="808" cy="246" r="5" fill="{T.surface}" stroke="{T.mint}" stroke-width="2"/>'
                   f'<circle cx="808" cy="246" r="2" fill="{T.mint}">{pulse("opacity", "1;0.2;1", 2)}</circle>')
    for vx, vy in ((940, 64), (1120, 52), (1126, 118), (1146, 262), (866, 324), (1098, 340), (846, 246)):
        circuit.append(f'<circle cx="{vx}" cy="{vy}" r="3.2" fill="{T.raised}" stroke="{T.muted}" stroke-width="1.2"/>')

    orbit = f"M{cx + 126} {cy} a126 126 0 1 1 -252 0 a126 126 0 1 1 252 0"
    monogram = (
        f'<circle cx="{cx}" cy="{cy}" r="150" fill="url(#glowC)" opacity="0.8"/>'
        f'<g opacity="0.75"><circle cx="{cx}" cy="{cy}" r="126" fill="none" stroke="{T.cyan}" stroke-width="1.2" '
        f'stroke-dasharray="2 11"><animateTransform attributeName="transform" type="rotate" '
        f'from="0 {cx} {cy}" to="360 {cx} {cy}" dur="40s" repeatCount="indefinite"/></circle></g>'
        f'<circle cx="{cx}" cy="{cy}" r="108" fill="none" stroke="url(#ringGrad)" stroke-width="2.5" '
        f'stroke-linecap="round" stroke-dasharray="70 36 12 36"><animateTransform attributeName="transform" '
        f'type="rotate" from="360 {cx} {cy}" to="0 {cx} {cy}" dur="22s" repeatCount="indefinite"/></circle>'
        f'<circle r="5" fill="{T.mint}" filter="url(#glow)" opacity="0"><set attributeName="opacity" to="1" begin="0s"/>'
        f'<animateMotion path="{orbit}" dur="9s" repeatCount="indefinite"/></circle>'
        f'<g transform="translate({ox:.1f} {oy:.1f}) scale({s})">'
        f'<rect x="1" y="1" width="62" height="62" rx="16" fill="{T.surface}" stroke="url(#nameGrad)" '
        f'stroke-width="1.1" filter="url(#softGlow)"/>'
        f'<rect x="1" y="1" width="62" height="62" rx="16" fill="{T.surface}" fill-opacity="0.92"/>'
        f'<rect x="1" y="1" width="62" height="62" rx="16" fill="none" stroke="url(#nameGrad)" stroke-width="1.1"/>'
        f'<path d="M14 43V21L29 43V21" fill="none" stroke="{T.text}" stroke-width="3.6" stroke-linecap="square" '
        f'stroke-linejoin="round" pathLength="1" stroke-dasharray="1">{draw_on(0.3, 1.1)}</path>'
        f'<path d="M50 21H40L36 25V29L40 33H46L50 37V39L46 43H36" fill="none" stroke="url(#sGrad)" '
        f'stroke-width="3.6" stroke-linecap="square" stroke-linejoin="round" pathLength="1" '
        f'stroke-dasharray="1">{draw_on(0.9, 1.1)}</path>'
        f'<circle cx="55" cy="9" r="2.2" fill="{T.mint}">{pulse("opacity", "1;0.25;1", 1.6)}</circle>'
        f'</g>'
    )

    # Left column: prompt → name → tagline → typed roles → chips.
    user = P["name"].split()[0].lower()
    prompt = [(user, T.mint), ("@", T.muted), (P["host"], T.cyan), (":~$ ", T.text_dim), ("whoami", T.text)]
    prompt_text = "".join(p for p, _ in prompt)
    pw = mono_width(prompt_text, 20)
    kicker = (
        f'<g>{fade_in(0.05, 0.4)}<text x="72" y="84" font-family="{MONO}" font-size="20" textLength="{pw}" '
        f'lengthAdjust="spacing">{"".join(f"<tspan fill=\"{c}\">{esc(p)}</tspan>" for p, c in prompt)}</text>'
        f'<rect x="{72 + pw + 6}" y="68" width="11" height="20" rx="2" fill="{T.mint}">{blink(1)}</rect></g>'
    )
    name = (
        f'<g>{rise_in(0.15, 0.7, 14)}<text x="68" y="164" font-family="{SANS}" font-size="80" font-weight="800" '
        f'letter-spacing="-1.5" fill="url(#nameGrad)" filter="url(#glow)">{esc(P["name"])}</text></g>'
    )
    tagline = (
        f'<g>{rise_in(0.45, 0.6, 10)}<text x="72" y="216" font-family="{SANS}" font-size="30" font-weight="600" '
        f'fill="{T.text}">{esc(P["tagline"])}</text></g>'
    )
    roles = (
        f'<g>{fade_in(0.7, 0.4)}<text x="72" y="268" font-family="{MONO}" font-size="22" font-weight="700" '
        f'fill="{T.mint}">&gt;</text>'
        + typed_cycle("role", P["roles"], [T.mint, T.cyan, T.azure, T.violet], 72 + 22 * MONO_EM * 2, 268, 22)
        + "</g>"
    )
    chips, x = [], 72
    for i, (label, glyph, color) in enumerate(zip(P["chips"], ("pin", "cap", None), (T.cyan, T.azure, T.mint))):
        svg, w = _chip(x, 300, label, glyph, color, T, 0.9 + 0.15 * i)
        chips.append(svg)
        x += w + 12

    body = (f'<defs>{"".join(defs)}</defs>{background}{"".join(circuit)}{monogram}'
            f'{kicker}{name}{tagline}{roles}{"".join(chips)}')
    return document(W, H, body, P["name"],
                    f'{P["tagline"]} {" · ".join(P["roles"])}. Animated NS monogram with circuit traces.')


# ── Terminal (fastfetch-style intro) ────────────────────────────────────────

GLYPHS = {
    "N": ["X...X", "XX..X", "XX..X", "X.X.X", "X..XX", "X..XX", "X...X"],
    "S": [".XXXX", "X....", "X....", ".XXX.", "....X", "....X", "XXXX."],
}


def terminal(cfg: dict, T) -> str:
    P, rows = cfg["profile"], cfg["terminal"]
    W = 900
    user, host = P["name"].split()[0].lower(), P["host"]
    row_y0, step = 182, 25
    rows_end = row_y0 + step * (len(rows) - 1)
    blocks_y = rows_end + 20
    prompt2_y = blocks_y + 56
    H = prompt2_y + 30
    out_t = 1.75                         # when the command's output appears

    defs = (linear_gradient("termLine", T.gradient, cycle=6) + glow_filter("tglow", 4, 0.8)
            + f'<clipPath id="win"><rect width="{W}" height="{H}" rx="14"/></clipPath>'
            + f'<radialGradient id="tGlow" cx="0.15" cy="0.25" r="0.7"><stop offset="0" stop-color="{T.mint}" '
              f'stop-opacity="0.09"/><stop offset="1" stop-color="{T.mint}" stop-opacity="0"/></radialGradient>')

    chrome = (
        f'<g clip-path="url(#win)"><rect width="{W}" height="{H}" fill="{T.surface}"/>'
        f'<rect width="{W}" height="{H}" fill="url(#tGlow)"/>'
        f'<rect width="{W}" height="44" fill="{T.raised}"/><rect y="44" width="{W}" height="1" fill="{T.border}"/>'
        f'<rect width="{W}" height="2" fill="url(#termLine)"/></g>'
        f'<rect x="0.75" y="0.75" width="{W - 1.5}" height="{H - 1.5}" rx="13.5" fill="none" stroke="{T.border}" stroke-width="1.5"/>'
        + "".join(f'<circle cx="{24 + 22 * i}" cy="22" r="6.5" fill="{c}"/>' for i, c in enumerate((T.rose, T.amber, T.mint)))
        + f'<text x="{W / 2}" y="27" text-anchor="middle" font-family="{MONO}" font-size="13" fill="{T.muted}">'
          f'{esc(f"{user}@{host}: ~/profile — zsh")}</text>'
        + f'<text x="{W - 22}" y="27" text-anchor="end" font-family="{MONO}" font-size="11" fill="{T.mint}">● live</text>'
    )

    def prompt_line(y: float) -> tuple[str, float]:
        parts = [(user, T.mint), ("@", T.muted), (host, T.cyan), (" ~/profile", T.azure), (" ❯ ", T.mint)]
        text = "".join(p for p, _ in parts)
        w = mono_width(text, 16)
        spans = "".join(f'<tspan fill="{c}"{" font-weight=\"700\"" if c == T.mint else ""}>{esc(p)}</tspan>'
                        for p, c in parts)
        return (f'<text x="32" y="{y}" font-family="{MONO}" font-size="16" textLength="{w}" '
                f'lengthAdjust="spacing" xml:space="preserve">{spans}</text>'), 32 + w

    # Line 1: prompt + typed command, cursor rides along then hides.
    p1, cmd_x = prompt_line(84)
    command = "fastfetch --logo ns"
    cw = 16 * MONO_EM
    n = len(command)
    t0, per = 0.35, 0.055
    pts = [(0.0, 0)] + [(t0 + per * k, round(k * cw, 2)) for k in range(n + 1)]
    full = round(n * cw, 2)
    line1 = (
        p1
        + f'<clipPath id="cmdClip"><rect x="{cmd_x}" y="66" height="26" width="{full}">'
          f'{_discrete("width", pts + [(out_t, full)], out_t, repeat=False)}</rect></clipPath>'
        + f'<text x="{cmd_x}" y="84" font-family="{MONO}" font-size="16" fill="{T.text}" textLength="{full}" '
          f'lengthAdjust="spacing" clip-path="url(#cmdClip)">{esc(command)}</text>'
        + f'<rect x="{cmd_x}" y="70" width="9" height="18" rx="1.5" fill="{T.mint}" opacity="0">'
          f'{_discrete("x", [(t, round(cmd_x + w + 2, 2)) for t, w in pts] + [(out_t, cmd_x + full + 2)], out_t, repeat=False)}'
          f'{_discrete("opacity", [(0.0, 1), (out_t - 0.01, 0)], out_t, repeat=False)}</rect>'
    )

    # Pixel logo: the NS monogram drawn as a contribution graph.
    pitch, cell = 28, 24
    logo_cols = GLYPHS["N"][0].__len__() * 2 + 1
    logo_w, logo_h = logo_cols * pitch - (pitch - cell), 7 * pitch - (pitch - cell)
    lx = 36
    area_top, area_bottom = 112, blocks_y + 18
    ly = area_top + ((area_bottom - area_top) - (logo_h + 44)) / 2
    cells = []
    for r in range(7):
        row = GLYPHS["N"][r] + "." + GLYPHS["S"][r]
        for c, ch in enumerate(row):
            x, y = lx + c * pitch, ly + r * pitch
            delay = out_t + 0.03 * (c + r)
            if ch == "X":
                color = ramp(T.gradient, c / (logo_cols - 1))
                cells.append(f'<rect x="{x}" y="{y:.1f}" width="{cell}" height="{cell}" rx="5" fill="{color}" opacity="1">'
                             f'{fade_in(delay, 0.3)}{pulse("fill-opacity", "1;0.7;1", 3.2, round(c * 0.18, 2))}</rect>')
            else:
                cells.append(f'<rect x="{x}" y="{y:.1f}" width="{cell}" height="{cell}" rx="5" fill="{T.raised}" '
                             f'stroke="{T.border}" opacity="1">{fade_in(delay, 0.3)}</rect>')
    legend_y = ly + logo_h + 30
    levels = [T.raised] + [ramp([T.mint, T.cyan], t) for t in (0, 0.33, 0.66, 1)]
    lg_w = 34 + 5 * 17 + 34
    lg_x = lx + (logo_w - lg_w) / 2
    legend = (f'<g>{fade_in(out_t + 0.5)}<text x="{lg_x}" y="{legend_y + 10}" font-family="{MONO}" font-size="11" '
              f'fill="{T.muted}">Less</text>'
              + "".join(f'<rect x="{lg_x + 34 + i * 17}" y="{legend_y}" width="12" height="12" rx="3" fill="{c}" '
                        f'fill-opacity="{1 if i == 0 else 0.35 + 0.65 * i / 4:.2f}"/>' for i, c in enumerate(levels))
              + f'<text x="{lg_x + 34 + 5 * 17 + 4}" y="{legend_y + 10}" font-family="{MONO}" font-size="11" '
                f'fill="{T.muted}">More</text></g>')

    # Info column.
    ix = lx + logo_w + 40
    title = f"{user}@{host}"
    info = [f'<g>{fade_in(out_t)}<text x="{ix}" y="136" font-family="{MONO}" font-size="18" font-weight="700">'
            f'<tspan fill="{T.mint}">{esc(user)}</tspan><tspan fill="{T.text_dim}">@</tspan>'
            f'<tspan fill="{T.cyan}">{esc(host)}</tspan></text>'
            f'<rect x="{ix}" y="148" width="{mono_width(title, 18)}" height="2" rx="1" fill="url(#termLine)"/></g>']
    key_w = max(len(r["key"]) for r in rows) + 2
    for i, r in enumerate(rows):
        y = row_y0 + i * step
        color = ramp(T.gradient, i / max(len(rows) - 1, 1))
        info.append(
            f'<g>{rise_in(out_t + 0.1 + 0.09 * i, 0.35, 6)}'
            f'<text x="{ix}" y="{y}" font-family="{MONO}" font-size="15"><tspan fill="{color}" font-weight="700">'
            f'{esc(r["key"])}</tspan><tspan fill="{T.muted}">:</tspan></text>'
            f'<text x="{ix + mono_width("x" * key_w, 15)}" y="{y}" font-family="{MONO}" font-size="15" '
            f'fill="{T.text}">{esc(r["value"])}</text></g>')
    blocks_t = out_t + 0.15 + 0.09 * len(rows)
    info.append(f'<g>{fade_in(blocks_t, 0.4)}' + "".join(
        f'<rect x="{ix + i * 38}" y="{blocks_y}" width="32" height="18" rx="4" fill="{c}"/>'
        for i, c in enumerate(T.series)) + "</g>")

    p2, cur_x = prompt_line(prompt2_y)
    final = (f'<g>{fade_in(blocks_t + 0.3, 0.3)}{p2}'
             f'<rect x="{cur_x + 2}" y="{prompt2_y - 14}" width="9" height="18" rx="1.5" fill="{T.mint}">{blink(1)}</rect></g>')

    body = (f'<defs>{defs}</defs>{chrome}{line1}{"".join(cells)}{legend}{"".join(info)}{final}')
    desc = "; ".join(f'{r["key"]}: {r["value"]}' for r in rows)
    return document(W, H, body, f"{P['name']} — terminal profile", desc)


# ── Section titles, divider ─────────────────────────────────────────────────

def section_chip(T, title: str, glyph: str, index: int) -> tuple[str, float]:
    size, H = 21, 56
    tw = round(len(title) * size * 0.57, 1)
    idx = f"{index:02d}"
    W = round(66 + tw + 22 + mono_width(idx, 12) + 20, 1)
    defs = (linear_gradient("chipGrad", T.gradient, x2=str(W), units="userSpaceOnUse", cycle=7)
            + linear_gradient("titleGrad", T.gradient, cycle=7) + icon_gradient(T.gradient))
    body = (
        f'<defs>{defs}</defs>'
        f'<rect x="0.75" y="0.75" width="{W - 1.5}" height="{H - 1.5}" rx="15" fill="{T.surface}" '
        f'stroke="url(#chipGrad)" stroke-width="1.5"/>'
        f'<rect x="12" y="11" width="34" height="34" rx="10" fill="url(#chipGrad)" fill-opacity="0.14"/>'
        f'{icon(glyph, 17, 16, 24, f"url(#{ICON_GRADIENT_ID})", 2.2)}'
        f'<text x="62" y="36" font-family="{SANS}" font-size="{size}" font-weight="700" fill="url(#titleGrad)" '
        f'textLength="{tw}" lengthAdjust="spacingAndGlyphs">{esc(title)}</text>'
        f'<text x="{W - 18}" y="35" text-anchor="end" font-family="{MONO}" font-size="12" fill="{T.muted}">{idx}</text>'
    )
    return document(W, H, body, title), W


def divider(T) -> str:
    W, H = 900, 16
    defs = (linear_gradient("dg", [T.mint, T.mint, T.cyan, T.azure, T.azure], opacities=[0, 1, 1, 1, 0])
            + f'<linearGradient id="glint"><stop offset="0" stop-color="#fff" stop-opacity="0"/>'
              f'<stop offset="0.5" stop-color="#fff" stop-opacity="0.95"/>'
              f'<stop offset="1" stop-color="#fff" stop-opacity="0"/></linearGradient>')
    body = (
        f'<defs>{defs}</defs><rect x="0" y="7" width="{W}" height="2" rx="1" fill="url(#dg)"/>'
        f'<rect x="-140" y="7" width="140" height="2" fill="url(#glint)" opacity="0.85">'
        f'<animate attributeName="x" values="-140;{W}" dur="4.5s" repeatCount="indefinite"/></rect>'
        f'<g transform="translate({W / 2} 8)"><rect x="-5" y="-5" width="10" height="10" rx="1.5" '
        f'fill="{T.surface}" stroke="{T.cyan}" stroke-width="1.6"><animateTransform attributeName="transform" '
        f'type="rotate" values="45;225;405" dur="8s" repeatCount="indefinite"/></rect>'
        f'<circle r="1.8" fill="{T.mint}"/></g>'
        + "".join(f'<circle cx="{W / 2 + dx}" cy="8" r="2" fill="{c}"/>'
                  for dx, c in ((-28, T.mint), (28, T.azure)))
    )
    return document(W, H, body, "divider")


# ── Project cards ───────────────────────────────────────────────────────────

def project_card(T, p: dict, idx: int) -> str:
    W, H = 480, 236
    palette = [T.mint, T.cyan, T.azure, T.violet, T.rose, T.amber]
    accent, nxt = palette[idx % len(palette)], palette[(idx + 1) % len(palette)]
    lines = wrap(p["description"], 54)[:4]
    defs = (f'<clipPath id="pc"><rect width="{W}" height="{H}" rx="18"/></clipPath>'
            f'<radialGradient id="pglow" cx="1" cy="0" r="0.85"><stop offset="0" stop-color="{accent}" '
            f'stop-opacity="0.2"/><stop offset="1" stop-color="{accent}" stop-opacity="0"/></radialGradient>'
            + linear_gradient("pbar", [accent, nxt], cycle=5))
    tags, tx = [], 24.0
    for j, tag in enumerate(p["tags"]):
        c = palette[(idx + j) % len(palette)]
        w = mono_width(tag, 12) + 22
        tags.append(f'<rect x="{tx}" y="{H - 46}" width="{w}" height="26" rx="13" fill="{c}" fill-opacity="0.1" '
                    f'stroke="{c}" stroke-opacity="0.55"/><text x="{tx + 11}" y="{H - 28.5}" font-family="{MONO}" '
                    f'font-size="12" fill="{c}" textLength="{mono_width(tag, 12)}" lengthAdjust="spacing">{esc(tag)}</text>')
        tx += w + 8
    body = (
        f'<defs>{defs}</defs><g clip-path="url(#pc)"><rect width="{W}" height="{H}" fill="{T.surface}"/>'
        f'<rect width="{W}" height="{H}" fill="url(#pglow)"/><rect width="{W}" height="4" fill="url(#pbar)"/></g>'
        f'<rect x="0.75" y="0.75" width="{W - 1.5}" height="{H - 1.5}" rx="17.25" fill="none" stroke="{T.border}" stroke-width="1.5"/>'
        f'<rect x="24" y="24" width="46" height="46" rx="13" fill="{accent}" fill-opacity="0.13" stroke="{accent}" stroke-opacity="0.45"/>'
        f'{icon(p["icon"], 35, 35, 24, accent, 2)}'
        f'<text x="86" y="42" font-family="{MONO}" font-size="11.5" font-weight="700" letter-spacing="0.8" '
        f'fill="{accent}">{esc(p["kind"].upper())}</text>'
        f'<text x="86" y="67" font-family="{SANS}" font-size="22" font-weight="700" fill="{T.text}">{esc(p["title"])}</text>'
        f'{icon("arrow", W - 42, 26, 18, T.muted, 2)}'
        + "".join(f'<text x="24" y="{106 + i * 21}" font-family="{SANS}" font-size="14.5" fill="{T.text_dim}">'
                  f'{esc(line)}</text>' for i, line in enumerate(lines))
        + "".join(tags)
    )
    return document(W, H, body, p["title"], f'{p["kind"]}. {p["description"]}')


# ── Footer ──────────────────────────────────────────────────────────────────

def _wave(y: float, amp: float, period: float = 600, width: float = 2400, height: float = 230) -> str:
    half = period / 2
    d = f"M0 {y} Q{half / 2} {y - amp} {half} {y}"
    x = half
    while x < width:
        x += half
        d += f" T{x:g} {y}"
    return d + f" V{height} H0 Z"


def footer(cfg: dict, T) -> str:
    P = cfg["profile"]
    W, H = 1200, 230
    defs = (linear_gradient("fg", T.gradient, x2=str(W), units="userSpaceOnUse")
            + f'<mask id="frontMask"><path d="{_wave(128, 20)}" fill="#fff">'
              f'<animateTransform attributeName="transform" type="translate" values="0 0;-1200 0" dur="9s" '
              f'repeatCount="indefinite"/></path></mask>')
    layers = []
    for y, amp, color, op, dur, rev in ((78, 28, T.cyan, 0.22, 15, False), (102, 24, T.azure, 0.35, 11, True)):
        values = "-1200 0;0 0" if rev else "0 0;-1200 0"
        layers.append(f'<path d="{_wave(y, amp)}" fill="{color}" fill-opacity="{op}"><animateTransform '
                      f'attributeName="transform" type="translate" values="{values}" dur="{dur}s" '
                      f'repeatCount="indefinite"/></path>')
    body = (
        f'<defs>{defs}</defs>{"".join(layers)}'
        f'<rect width="{W}" height="{H}" fill="url(#fg)" mask="url(#frontMask)"/>'
        f'<text x="{W / 2}" y="184" text-anchor="middle" font-family="{SANS}" font-size="23" font-weight="700" '
        f'font-style="italic" fill="{T.ink}">“{esc(P["motto"])}”</text>'
        f'<text x="{W / 2}" y="212" text-anchor="middle" font-family="{MONO}" font-size="13" fill="{T.ink}" '
        f'fill-opacity="0.78">crafted by {esc(P["name"].lower())} · refreshed daily by github actions</text>'
    )
    return document(W, H, body, "Footer", P["motto"])


# ── Entry point ─────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=ROOT / "assets")
    args = parser.parse_args()
    cfg = load_config()
    T = load_theme(cfg)
    out: Path = args.out

    print("Building static assets:")
    write(out / "header.svg", header(cfg, T))
    write(out / "terminal.svg", terminal(cfg, T))
    write(out / "divider.svg", divider(T))
    write(out / "footer.svg", footer(cfg, T))
    widths = {}
    for i, (key, title, glyph) in enumerate(SECTIONS, start=1):
        svg, w = section_chip(T, title, glyph, i)
        widths[key] = w
        write(out / f"section-{key}.svg", svg)
    for i, p in enumerate(cfg["projects"]):
        write(out / f"project-{p['slug']}.svg", project_card(T, p, i))
    print("Section chip widths (56px tall; README shows them at height=48):", {k: round(v) for k, v in widths.items()})


if __name__ == "__main__":
    main()
