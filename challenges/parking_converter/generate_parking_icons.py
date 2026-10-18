"""Regenerate the small, dependency-free parking comparison diagrams.

Run ``python challenges/parking_converter/generate_parking_icons.py`` from the
repository root. The SVGs have small intrinsic dimensions so Markdown image
links also fit in MapRoulette's comparison tables without HTML sizing.
"""

from pathlib import Path


SIDES = ("left", "right")
POSITIONS = ("lane", "half_on_kerb", "on_kerb", "street_side", "shoulder", "yes")
ORIENTATIONS = ("parallel", "diagonal", "perpendicular", "unknown")
SPECIAL_POSITIONS = ("no", "separate", "unknown")
OUTPUT_DIRECTORY = Path(__file__).with_name("visuals")

POSITION_LABELS = {
    "lane": "carriageway",
    "half_on_kerb": "half on kerb",
    "on_kerb": "on pavement",
    "street_side": "roadside bay",
    "shoulder": "shoulder",
    "yes": "position ?",
    "no": "unavailable",
    "separate": "mapped apart",
    "unknown": "no data",
}


def _svg(body: str, title: str, description: str, width=100, height=110) -> str:
    # Four layout diagrams must fit beside each other in a task sidebar.
    scale = 0.64 if width == 100 else 0.7
    display_width, display_height = round(width * scale), round(height * scale)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{display_width}" height="{display_height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">\n'
        f'  <title id="title">{title}</title>\n'
        f'  <desc id="desc">{description}</desc>\n'
        '  <style>text{font-family:Arial,Helvetica,sans-serif}</style>\n'
        f'{body}\n</svg>\n'
    )


def _car(x: int, y: int, angle: int, orientation: str, markings: bool) -> str:
    pieces = [f'  <g transform="translate({x} {y}) rotate({angle})">']
    if markings:
        if orientation == "unknown":
            pieces.append('    <rect x="-10" y="-11" width="20" height="22" rx="1" fill="none" stroke="#fff" stroke-width="1.6"/>')
        else:
            pieces.append('    <rect x="-8" y="-14" width="16" height="28" rx="1" fill="none" stroke="#fff" stroke-width="1.6"/>')
    if orientation == "unknown":
        pieces.extend([
            '    <circle r="8" fill="#24c8df" stroke="#123f53" stroke-width="1.2"/>',
            '    <text y="4.2" text-anchor="middle" font-size="13" font-weight="700" fill="#123f53">?</text>',
        ])
    else:
        pieces.extend([
            '    <rect x="-5.5" y="-10.5" width="11" height="21" rx="3" fill="#24c8df" stroke="#123f53" stroke-width="1.2"/>',
            '    <path d="M-3.7-6.3Q0-7.7 3.7-6.3L3-2.3H-3Z" fill="#174f65"/>',
            '    <path d="M-3 4H3L3.6 7Q0 8-3.6 7Z" fill="#174f65"/>',
            '    <path d="M-5.8-5H-6.7M5.8-5H6.7" stroke="#123f53" stroke-width="1.5" stroke-linecap="round"/>',
            '    <path d="M-3.5-9H-1.5M1.5-9H3.5" stroke="#edfbff" stroke-width="1" stroke-linecap="round"/>',
        ])
    pieces.append('  </g>')
    return "\n".join(pieces)


def render_layout_svg(side, position, orientation="unknown", markings=False):
    """Return one diagram; left/right refer to the upward OSM way direction.

    ``yes`` explicitly means parking exists but its position is unknown. It does
    not imply parking on the carriageway. ``unknown`` means no layout data;
    ``no`` means parking is unavailable, without inferring a physical layout or
    the legal reason.
    """
    if side not in SIDES:
        raise ValueError(f"Unsupported side: {side}")
    if position not in (*POSITIONS, *SPECIAL_POSITIONS):
        raise ValueError(f"Unsupported position: {position}")
    if orientation not in ORIENTATIONS:
        raise ValueError(f"Unsupported orientation: {orientation}")

    left = side == "left"
    selected_x = 0 if left else 76
    edge_x = 24 if left else 76
    outside_x = 12 if left else 88
    label = POSITION_LABELS[position]
    pieces = [
        '  <defs><clipPath id="frame"><rect x="0.5" y="0.5" width="99" height="109" rx="7"/></clipPath></defs>',
        '  <g clip-path="url(#frame)">',
        '  <path d="M0 0H100V100H0Z" fill="#e9dfc9"/>',
        '  <path d="M24 0H76V100H24Z" fill="#596575"/>',
        '  <path d="M24 0V100M76 0V100" fill="none" stroke="#f4ebd7" stroke-width="2"/>',
    ]
    if position == "street_side":
        pieces.append(f'  <rect x="{selected_x}" y="11" width="24" height="74" rx="5" fill="#7a8795"/>')
        pieces.append(f'  <path d="M{edge_x} 12V84" stroke="#7a8795" stroke-width="3"/>')
    elif position == "shoulder":
        pieces.append(f'  <rect x="{selected_x}" width="24" height="100" fill="#85929c"/>')
        pieces.append(f'  <path d="M{edge_x} 0V100" stroke="#85929c" stroke-width="2"/>')

    # The arrow is a way-direction cue, not a claimed road marking.
    pieces.extend([
        '  <rect x="43" y="80" width="14" height="17" rx="7" fill="#334353"/>',
        '  <path d="M50 93V85M46.5 88.5 50 85 53.5 88.5" fill="none" stroke="#fff" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>',
    ])

    if position in ("yes", "no", "separate", "unknown"):
        # A floating card deliberately avoids placing a car on any surface.
        card_x = 3 if left else 39
        card_center = card_x + 29
        pieces.append(f'  <rect x="{card_x}" y="18" width="58" height="49" rx="6" fill="#fffdf8" stroke="#97a3aa"/>')
        if position == "yes":
            angle = {"parallel": 0, "diagonal": 45 if left else -45, "perpendicular": 90 if left else -90, "unknown": 0}[orientation]
            pieces.extend([
                f'  <rect x="{card_center - 18}" y="20" width="36" height="34" rx="4" fill="#73818d"/>',
                _car(card_center, 37, angle, orientation, markings),
                f'  <text x="{card_center}" y="63" text-anchor="middle" font-size="9" fill="#3e4d59">position ?</text>',
            ])
        elif position == "no":
            pieces.extend([
                f'  <text x="{card_center}" y="43" text-anchor="middle" font-size="24" font-weight="700" fill="#73818d">P</text>',
                f'  <text x="{card_center}" y="58" text-anchor="middle" font-size="9" fill="#3e4d59">unavailable</text>',
            ])
        elif position == "separate":
            pieces.extend([
                f'  <path d="M{card_center} 52C{card_center - 4} 47 {card_center - 11} 42 {card_center - 11} 35A11 11 0 0 1 {card_center + 11} 35C{card_center + 11} 42 {card_center + 4} 47 {card_center} 52Z" fill="#007e9b"/>',
                f'  <text x="{card_center}" y="40" text-anchor="middle" font-size="13" font-weight="700" fill="#fff">P</text>',
                f'  <text x="{card_center}" y="61" text-anchor="middle" font-size="7.6" fill="#3e4d59">separate object</text>',
            ])
        else:
            pieces.extend([
                f'  <text x="{card_center}" y="46" text-anchor="middle" font-size="30" font-weight="700" fill="#73818d">?</text>',
                f'  <text x="{card_center}" y="60" text-anchor="middle" font-size="8" fill="#3e4d59">no information</text>',
            ])
    else:
        if position == "lane":
            car_x = 37 if left else 63
        elif position == "half_on_kerb":
            car_x = edge_x
        else:
            car_x = outside_x
        angle = {"parallel": 0, "diagonal": 45 if left else -45, "perpendicular": 90 if left else -90, "unknown": 0}[orientation]
        pieces.extend(_car(car_x, y, angle, orientation, markings) for y in (31, 66))

    pieces.extend([
        f'  <rect x="{2 if left else 86}" y="3" width="12" height="13" rx="3" fill="#fffdf8"/>',
        f'  <text x="{8 if left else 92}" y="12.5" text-anchor="middle" font-size="9" font-weight="700" fill="#304756">{"L" if left else "R"}</text>',
        '  <rect y="100" width="100" height="10" fill="#fffdf8"/>',
        f'  <text x="50" y="107.5" text-anchor="middle" font-size="8" fill="#304756">{label}</text>',
        '  </g>',
        '  <rect x="0.5" y="0.5" width="99" height="109" rx="7" fill="none" stroke="#b5bec5"/>',
    ])
    title = f"{side.capitalize()} side: {'Parking unavailable' if position == 'no' else label}"
    descriptions = {
        "yes": f"Parking exists with {orientation} orientation, but its position is unknown. The floating card does not imply a position on the road or pavement. " + ("The white outline shows explicit parking-space markings." if markings else "No parking-space markings are inferred."),
        "no": "Parking is unavailable on this side. No physical layout or legal reason is inferred.",
        "separate": "Parking is mapped as a separate object; no position or geometry is inferred here.",
        "unknown": "No information about parking layout; this does not imply that parking is absent.",
    }
    description = descriptions.get(position, f"Two cyan {orientation} parking symbols on the {side} side, {label}. " + ("White outlines show explicit parking-space markings." if markings else "No parking-space markings are inferred."))
    description += " The arrow points in the OSM way direction; left and right are relative to that arrow."
    return _svg("\n".join(pieces), title, description)


def render_rule_svg(rule):
    """Return one compact status badge used beside restriction explanations."""
    descriptions = {
        "no_parking": "Parking prohibited",
        "no_stopping": "Stopping prohibited",
        "no_standing": "Standing prohibited",
        "disc": "Parking disc required",
        "ticket": "Parking ticket required",
        "free": "Parking is free of charge",
        "access": "Parking access restriction; see accompanying text",
        "unknown": "Parking restriction unknown; see accompanying text",
    }
    if rule not in descriptions:
        raise ValueError(f"Unsupported rule: {rule}")
    body = ['  <rect x="0.5" y="0.5" width="39" height="39" rx="7" fill="#fffdf8" stroke="#b5bec5"/>']
    if rule in ("no_parking", "no_stopping"):
        body.extend([
            '  <circle cx="20" cy="20" r="14" fill="#145ca0" stroke="#dc3d45" stroke-width="3"/>',
            '  <path d="M10 30 30 10" stroke="#dc3d45" stroke-width="3"/>',
        ])
        if rule == "no_stopping":
            body.append('  <path d="M10 10 30 30" stroke="#dc3d45" stroke-width="3"/>')
    elif rule == "disc":
        body.extend([
            '  <rect x="9" y="6" width="22" height="29" rx="2" fill="#176ba7"/>',
            '  <text x="20" y="16" text-anchor="middle" font-size="10" font-weight="700" fill="#fff">P</text>',
            '  <circle cx="20" cy="25" r="7" fill="#fff"/>',
            '  <path d="M20 20V25H24" fill="none" stroke="#176ba7" stroke-width="1.5" stroke-linecap="round"/>',
        ])
    elif rule == "ticket":
        body.extend([
            '  <path d="M10 7H30V15Q25 15 25 20T30 25V33H10V25Q15 25 15 20T10 15Z" fill="#f2ce70" stroke="#85651e" stroke-width="1.5"/>',
            '  <text x="20" y="24" text-anchor="middle" font-size="15" font-weight="700" fill="#6f5215">P</text>',
        ])
    elif rule == "access":
        body.extend([
            '  <rect x="9" y="17" width="22" height="16" rx="3" fill="#8462aa"/>',
            '  <path d="M14 17V12A6 6 0 0 1 26 12V17" fill="none" stroke="#67448d" stroke-width="3"/>',
            '  <circle cx="20" cy="24" r="2" fill="#fff"/>',
            '  <path d="M20 25V28" stroke="#fff" stroke-width="2"/>',
        ])
    else:
        text, size, color = {"no_standing": ("NO WAIT", 7, "#b53340"), "free": ("FREE", 10, "#24704f"), "unknown": ("?", 27, "#657583")}[rule]
        body.append(f'  <text x="20" y="{29 if rule == "unknown" else 24}" text-anchor="middle" font-size="{size}" font-weight="700" fill="{color}">{text}</text>')
    return _svg("\n".join(body), descriptions[rule], descriptions[rule] + ". A badge summarizes the rule; accompanying text contains conditions and details.", 40, 40)


def generate_assets(output_directory=None):
    """Write the finite asset set and return its paths in a stable order."""
    destination = Path(output_directory) if output_directory is not None else OUTPUT_DIRECTORY
    destination.mkdir(parents=True, exist_ok=True)
    paths = []
    for side in SIDES:
        for position in POSITIONS:
            for orientation in ORIENTATIONS:
                for markings in (False, True):
                    path = destination / f"layout-{side}-{position}-{orientation}-{'marked' if markings else 'plain'}.svg"
                    path.write_text(render_layout_svg(side, position, orientation, markings), encoding="utf-8", newline="\n")
                    paths.append(path)
        for position in SPECIAL_POSITIONS:
            path = destination / f"layout-{side}-{position}.svg"
            path.write_text(render_layout_svg(side, position), encoding="utf-8", newline="\n")
            paths.append(path)
    for rule in ("no_parking", "no_stopping", "no_standing", "disc", "ticket", "free", "access", "unknown"):
        path = destination / f"rule-{rule}.svg"
        path.write_text(render_rule_svg(rule), encoding="utf-8", newline="\n")
        paths.append(path)
    return paths


if __name__ == "__main__":
    generated = generate_assets()
    print(f"Generated {len(generated)} parking diagrams in {OUTPUT_DIRECTORY}")
