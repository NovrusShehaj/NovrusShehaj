"""Shared helpers for the profile SVG generators. Standard library only.

Everything visual reads its colors from the [theme] table in profile.toml, so
the whole profile can be recolored from one place.

Animation convention: every SMIL animation starts at t=0 and holds its "from"
value until its own begin time (via keyTimes). Renderers without SMIL support
therefore show the final, fully visible state instead of a blank image.
"""
from __future__ import annotations

import tomllib
from pathlib import Path
from types import SimpleNamespace
from xml.sax.saxutils import escape as _escape

ROOT = Path(__file__).resolve().parent.parent

SANS = "'Segoe UI', Inter, 'Helvetica Neue', Helvetica, Arial, sans-serif"
MONO = "'JetBrains Mono', 'SF Mono', 'Cascadia Code', Menlo, Consolas, 'DejaVu Sans Mono', monospace"
MONO_EM = 0.6  # advance width of a monospace glyph, in em (textLength pins it exactly)


def load_config(path: Path | None = None) -> dict:
    with open(path or ROOT / "profile.toml", "rb") as fh:
        return tomllib.load(fh)


def load_theme(cfg: dict) -> SimpleNamespace:
    return SimpleNamespace(**cfg["theme"])


def esc(value) -> str:
    return _escape(str(value), {'"': "&quot;"})


def mono_width(text: str, size: float) -> float:
    return round(len(text) * size * MONO_EM, 2)


def fmt_num(n: int) -> str:
    if n >= 100_000:
        return f"{n / 1000:.0f}k"
    if n >= 10_000:
        return f"{n / 1000:.1f}k"
    return f"{n:,}"


def _rgb(color: str) -> tuple[int, int, int]:
    color = color.lstrip("#")
    return tuple(int(color[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def mix(a: str, b: str, t: float) -> str:
    ra, rb = _rgb(a), _rgb(b)
    return "#" + "".join(f"{round(x + (y - x) * t):02X}" for x, y in zip(ra, rb))


def ramp(colors: list[str], t: float) -> str:
    """Sample a multi-stop gradient at t ∈ [0, 1]."""
    t = min(max(t, 0.0), 1.0)
    if len(colors) == 1:
        return colors[0]
    pos = t * (len(colors) - 1)
    i = min(int(pos), len(colors) - 2)
    return mix(colors[i], colors[i + 1], pos - i)


def wrap(text: str, max_chars: int) -> list[str]:
    lines, line = [], ""
    for word in text.split():
        candidate = f"{line} {word}".strip()
        if len(candidate) > max_chars and line:
            lines.append(line)
            line = word
        else:
            line = candidate
    if line:
        lines.append(line)
    return lines


def document(width: float, height: float, body: str, title: str, desc: str = "") -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-labelledby="t d">\n'
        f'<title id="t">{esc(title)}</title><desc id="d">{esc(desc or title)}</desc>\n'
        f"{body}\n</svg>\n"
    )


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    print(f"  wrote {path.relative_to(ROOT) if path.is_relative_to(ROOT) else path}")


# ── Gradients ───────────────────────────────────────────────────────────────

def linear_gradient(gid: str, colors: list[str], *, x2: str = "1", y2: str = "0",
                    cycle: float | None = None, units: str | None = None,
                    x1: str = "0", y1: str = "0", opacities: list[float] | None = None) -> str:
    """A linear gradient. With `cycle`, each stop rotates through the palette."""
    unit_attr = f' gradientUnits="{units}"' if units else ""
    stops = []
    n = len(colors)
    for i, color in enumerate(colors):
        offset = 0 if n == 1 else i / (n - 1)
        op = f' stop-opacity="{opacities[i]}"' if opacities else ""
        anim = ""
        if cycle:
            loop = colors[i:] + colors[:i]
            loop = loop + [loop[0]]
            anim = (f'<animate attributeName="stop-color" values="{";".join(loop)}" '
                    f'dur="{cycle}s" repeatCount="indefinite"/>')
        stops.append(f'<stop offset="{offset:.3f}" stop-color="{color}"{op}>{anim}</stop>')
    return (f'<linearGradient id="{gid}" x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}"{unit_attr}>'
            f'{"".join(stops)}</linearGradient>')


def glow_filter(fid: str, blur: float = 6, strength: float = 1.0) -> str:
    return (f'<filter id="{fid}" x="-30%" y="-30%" width="160%" height="160%">'
            f'<feGaussianBlur in="SourceGraphic" stdDeviation="{blur}" result="b"/>'
            f'<feComponentTransfer in="b" result="g"><feFuncA type="linear" slope="{strength}"/></feComponentTransfer>'
            f'<feMerge><feMergeNode in="g"/><feMergeNode in="SourceGraphic"/></feMerge></filter>')


# ── Animation helpers (all start at t=0; see module docstring) ──────────────

def _key(begin: float, dur: float) -> tuple[float, str]:
    total = begin + dur
    if begin <= 0:
        return dur, "0;1"
    return total, f"0;{begin / total:.4f};1"


def fade_in(begin: float, dur: float = 0.45) -> str:
    total, keys = _key(begin, dur)
    values = "0;1" if begin <= 0 else "0;0;1"
    return (f'<animate attributeName="opacity" values="{values}" keyTimes="{keys}" '
            f'dur="{total:.3f}s" fill="freeze"/>')


def rise_in(begin: float, dur: float = 0.5, dy: float = 10) -> str:
    """Fade + slide up. Apply to a <g> that has no transform of its own."""
    total, keys = _key(begin, dur)
    shift = f"0 {dy};0 0" if begin <= 0 else f"0 {dy};0 {dy};0 0"
    return (fade_in(begin, dur) +
            f'<animateTransform attributeName="transform" type="translate" values="{shift}" '
            f'keyTimes="{keys}" dur="{total:.3f}s" fill="freeze" calcMode="spline" '
            f'keySplines="{"0.2 0.8 0.2 1" if begin <= 0 else "0 0 1 1;0.2 0.8 0.2 1"}"/>')


def animate_attr(attr: str, start, end, begin: float, dur: float, spline: bool = True) -> str:
    total, keys = _key(begin, dur)
    values = f"{start};{end}" if begin <= 0 else f"{start};{start};{end}"
    ease = ""
    if spline:
        splines = "0.2 0.8 0.2 1" if begin <= 0 else "0 0 1 1;0.2 0.8 0.2 1"
        ease = f' calcMode="spline" keySplines="{splines}"'
    return (f'<animate attributeName="{attr}" values="{values}" keyTimes="{keys}" '
            f'dur="{total:.3f}s" fill="freeze"{ease}/>')


def draw_on(begin: float, dur: float = 1.2) -> str:
    """Stroke draw-on for elements carrying pathLength="1" stroke-dasharray="1"."""
    return animate_attr("stroke-dashoffset", 1, 0, begin, dur)


def blink(dur: float = 1.0) -> str:
    return (f'<animate attributeName="opacity" values="1;1;0;0" keyTimes="0;0.5;0.5;1" '
            f'dur="{dur}s" repeatCount="indefinite"/>')


def pulse(attr: str, values: str, dur: float, begin: float = 0) -> str:
    return (f'<animate attributeName="{attr}" values="{values}" dur="{dur}s" '
            f'begin="{begin}s" repeatCount="indefinite"/>')


# ── Icons: 24×24 stroke glyphs, drawn for this profile ─────────────────────

ICONS = {
    "user": '<circle cx="12" cy="8" r="4"/><path d="M4 21c0-4.4 3.6-7 8-7s8 2.6 8 7"/>',
    "code": '<path d="M8 7l-5 5 5 5M16 7l5 5-5 5M14 4l-4 16"/>',
    "trophy": '<path d="M7 4h10v5a5 5 0 0 1-10 0z"/><path d="M7 6H4a3 3 0 0 0 3 4M17 6h3a3 3 0 0 1-3 4"/>'
              '<path d="M12 14v4M8 21h8M9.5 18h5"/>',
    "chart": '<path d="M3 20h18M6 16v-4M10 16V8M14 16v-6M18 16V5"/>',
    "grid": '<rect x="3" y="3" width="5" height="5" rx="1"/><rect x="10" y="3" width="5" height="5" rx="1"/>'
            '<rect x="17" y="3" width="4" height="5" rx="1"/><rect x="3" y="10" width="5" height="5" rx="1"/>'
            '<rect x="10" y="10" width="5" height="5" rx="1"/><rect x="17" y="10" width="4" height="5" rx="1"/>'
            '<rect x="3" y="17" width="5" height="4" rx="1"/><rect x="10" y="17" width="5" height="4" rx="1"/>',
    "layers": '<path d="M12 2l9 5-9 5-9-5z"/><path d="M3 12l9 5 9-5"/><path d="M3 16.5l9 5 9-5"/>',
    "bolt": '<path d="M13 2L4 14h7l-1 8 9-12h-7z"/>',
    "send": '<path d="M22 2L11 13"/><path d="M22 2l-7 20-4-9-9-4z"/>',
    "quote": '<path d="M10 11H6a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v6c0 3-2 5-5 6"/>'
             '<path d="M20 11h-4a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v6c0 3-2 5-5 6"/>',
    "terminal": '<rect x="2" y="4" width="20" height="16" rx="2"/><path d="M6 9l4 3-4 3M12 15h6"/>',
    "shield": '<path d="M12 2l8 3v6c0 5-3.4 9.3-8 11-4.6-1.7-8-6-8-11V5z"/><path d="M9 12l2 2 4-4"/>',
    "cpu": '<rect x="6" y="6" width="12" height="12" rx="2"/><rect x="9.5" y="9.5" width="5" height="5" rx="1"/>'
           '<path d="M9 2v4M15 2v4M9 18v4M15 18v4M2 9h4M2 15h4M18 9h4M18 15h4"/>',
    "spark": '<path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z"/>'
             '<path d="M19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z"/>',
    "scan": '<path d="M3 7V5a2 2 0 0 1 2-2h2M17 3h2a2 2 0 0 1 2 2v2M21 17v2a2 2 0 0 1-2 2h-2M7 21H5a2 2 0 0 1-2-2v-2"/>'
            '<path d="M7 12h10"/>',
    "layout": '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18M9 9v12"/>',
    "pin": '<path d="M12 22s7-6.2 7-12a7 7 0 0 0-14 0c0 5.8 7 12 7 12z"/><circle cx="12" cy="10" r="2.5"/>',
    "cap": '<path d="M2 9l10-5 10 5-10 5z"/><path d="M6 11v5c0 1.7 2.7 3 6 3s6-1.3 6-3v-5"/><path d="M22 9v6"/>',
    "briefcase": '<rect x="3" y="7" width="18" height="13" rx="2"/><path d="M8 7V5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M3 13h18"/>',
    "flame": '<path d="M12 2c1 4 5 6 5 11a5 5 0 0 1-10 0c0-2.5 1.5-4 2.5-5 .3 2 1.2 3 2.5 3.5C11 9 11 5.5 12 2z"/>',
    "commit": '<circle cx="12" cy="12" r="4"/><path d="M2 12h6M16 12h6"/>',
    "pr": '<circle cx="6" cy="6" r="2.5"/><circle cx="6" cy="18" r="2.5"/><circle cx="18" cy="18" r="2.5"/>'
          '<path d="M6 8.5v7M18 15.5V9a3 3 0 0 0-3-3h-4M13 3.5L10.5 6 13 8.5"/>',
    "eye": '<path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
    "issue": '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="1.5"/>',
    "repo": '<path d="M5 4a2 2 0 0 1 2-2h12v16H7a2 2 0 0 0-2 2z"/><path d="M5 20a2 2 0 0 0 2 2h12v-4"/>',
    "calendar": '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/>',
    "globe": '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c2.5 2.5 3.8 5.5 3.8 9s-1.3 6.5-3.8 9'
             'c-2.5-2.5-3.8-5.5-3.8-9S9.5 5.5 12 3z"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "activity": '<path d="M3 12h4l3-8 4 16 3-8h4"/>',
    "arrow": '<path d="M7 17L17 7M8 7h9v9"/>',
    "users": '<circle cx="9" cy="8" r="3.5"/><path d="M2 20c0-3.6 3-6 7-6s7 2.4 7 6"/>'
             '<path d="M16 4.5a3.5 3.5 0 0 1 0 7M18 14c2.4.6 4 2.6 4 6"/>',
    "lock": '<rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
}


def icon(name: str, x: float, y: float, size: float, stroke: str, width: float = 2) -> str:
    scale = size / 24
    return (f'<g transform="translate({x} {y}) scale({scale:.4f})" fill="none" stroke="{stroke}" '
            f'stroke-width="{width}" stroke-linecap="round" stroke-linejoin="round">{ICONS[name]}</g>')


ICON_GRADIENT_ID = "iconGrad"


def icon_gradient(colors: list[str]) -> str:
    """Gradient in icon-local (0..24) space, so `icon(..., stroke=url(#iconGrad))` works."""
    return linear_gradient(ICON_GRADIENT_ID, colors, x1="0", y1="0", x2="24", y2="24",
                           units="userSpaceOnUse")


# ── Card chrome shared by the metric cards ─────────────────────────────────

def card_frame(T, width: float, height: float, *, accent: str | None = None, radius: float = 16) -> tuple[str, str]:
    """Returns (defs, background) for a dark, self-contained card."""
    accent = accent or T.gradient[1]
    defs = (
        f'<clipPath id="cardClip"><rect width="{width}" height="{height}" rx="{radius}"/></clipPath>'
        f'<radialGradient id="cardGlow" cx="1" cy="0" r="0.9">'
        f'<stop offset="0" stop-color="{accent}" stop-opacity="0.16"/>'
        f'<stop offset="1" stop-color="{accent}" stop-opacity="0"/></radialGradient>'
        + linear_gradient("cardBar", T.gradient, cycle=8)
    )
    bg = (
        f'<g clip-path="url(#cardClip)">'
        f'<rect width="{width}" height="{height}" fill="{T.surface}"/>'
        f'<rect width="{width}" height="{height}" fill="url(#cardGlow)"/>'
        f'<rect width="{width}" height="3" fill="url(#cardBar)"/></g>'
        f'<rect x="0.75" y="0.75" width="{width - 1.5}" height="{height - 1.5}" rx="{radius - 0.75}" '
        f'fill="none" stroke="{T.border}" stroke-width="1.5"/>'
    )
    return defs, bg
