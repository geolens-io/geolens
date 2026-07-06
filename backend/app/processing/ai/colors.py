"""CSS-color shape validation for AI-produced style values.

fix(#394) CH-02 (codex round 2): the first-pass regex accepted any 3-30
letter word ("notacolor") and any parenthesized junk ("rgb(foo)"), so
unparseable values still reached MapLibre paint validation — exactly what
the sanitizer exists to prevent. Named colors now validate against the real
CSS keyword set and functional args are restricted to numeric/separator
characters. MapLibre remains the final validator; this is the cheap junk
gate, byte-parity with the frontend mirror in ChatPanel.tsx.
"""

import re

# 3/4/6/8 hex digits only (#12345 is not a CSS color).
_HEX_RE = re.compile(r"^#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")

# Functional args restricted to digits, separators, %, and d/e/g (hue units).
# Letter junk like rgb(foo) fails; residual near-misses (e.g. "rgb(ded)") are
# left to MapLibre's own validation.
_FUNCTIONAL_RE = re.compile(r"^(?:rgb|rgba|hsl|hsla)\(\s*[0-9deg.,%\s/+-]{1,60}\s*\)$")

# CSS named colors (CSS Color Level 4 keyword set) + transparent.
CSS_NAMED_COLORS = frozenset(
    """aliceblue antiquewhite aqua aquamarine azure beige bisque black
    blanchedalmond blue blueviolet brown burlywood cadetblue chartreuse
    chocolate coral cornflowerblue cornsilk crimson cyan darkblue darkcyan
    darkgoldenrod darkgray darkgreen darkgrey darkkhaki darkmagenta
    darkolivegreen darkorange darkorchid darkred darksalmon darkseagreen
    darkslateblue darkslategray darkslategrey darkturquoise darkviolet
    deeppink deepskyblue dimgray dimgrey dodgerblue firebrick floralwhite
    forestgreen fuchsia gainsboro ghostwhite gold goldenrod gray green
    greenyellow grey honeydew hotpink indianred indigo ivory khaki lavender
    lavenderblush lawngreen lemonchiffon lightblue lightcoral lightcyan
    lightgoldenrodyellow lightgray lightgreen lightgrey lightpink lightsalmon
    lightseagreen lightskyblue lightslategray lightslategrey lightsteelblue
    lightyellow lime limegreen linen magenta maroon mediumaquamarine
    mediumblue mediumorchid mediumpurple mediumseagreen mediumslateblue
    mediumspringgreen mediumturquoise mediumvioletred midnightblue mintcream
    mistyrose moccasin navajowhite navy oldlace olive olivedrab orange
    orangered orchid palegoldenrod palegreen paleturquoise palevioletred
    papayawhip peachpuff peru pink plum powderblue purple rebeccapurple red
    rosybrown royalblue saddlebrown salmon sandybrown seagreen seashell
    sienna silver skyblue slateblue slategray slategrey snow springgreen
    steelblue tan teal thistle tomato turquoise violet wheat white
    whitesmoke yellow yellowgreen transparent""".split()
)


def is_css_colorish(value: object) -> bool:
    """True when ``value`` is a string MapLibre can plausibly parse as a color."""
    if not isinstance(value, str):
        return False
    candidate = value.strip()
    if _HEX_RE.match(candidate) or _FUNCTIONAL_RE.match(candidate):
        return True
    return candidate.lower() in CSS_NAMED_COLORS


# --- AI label halo derivation ---------------------------------------------
# #394 shipped a fixed "#ffffff" halo. When the model picks a light text color
# (it does whenever it assumes a "dark" basemap), light-text + white-halo washes
# out on relief / imagery / any pale area. Derive the halo from the text
# luminance instead so AI labels stay legible on any basemap.
_DARK_HALO = "#1a1a1a"
_LIGHT_HALO = "#ffffff"
_LIGHT_NAMED_COLORS = frozenset(
    """white whitesmoke ivory snow floralwhite ghostwhite azure mintcream
    honeydew aliceblue lightyellow lightgoldenrodyellow lemonchiffon cornsilk
    beige oldlace linen seashell lavenderblush mistyrose lightcyan lightgray
    lightgrey gainsboro antiquewhite blanchedalmond papayawhip moccasin
    navajowhite bisque wheat peachpuff""".split()
)


def _hex_luminance(value: str) -> float | None:
    """Perceived luminance (0-1, Rec.601) of a ``#hex`` color, else ``None``."""
    if not value.startswith("#"):
        return None
    digits = value[1:]
    if len(digits) in (3, 4):
        digits = "".join(ch * 2 for ch in digits[:3])
    elif len(digits) in (6, 8):
        digits = digits[:6]
    else:
        return None
    try:
        r, g, b = (int(digits[i : i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return None
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255


def label_halo_color(text_color: str) -> str:
    """A halo that contrasts the label text so it reads on any basemap."""
    candidate = text_color.strip().lower()
    luminance = _hex_luminance(candidate)
    if luminance is not None:
        return _DARK_HALO if luminance > 0.6 else _LIGHT_HALO
    if candidate in _LIGHT_NAMED_COLORS:
        return _DARK_HALO
    return _LIGHT_HALO
