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


def _svg(body: str, title: str, description: str, width=52, height=150) -> str:
    # Four layout diagrams must fit beside each other in a task sidebar.
    if width == 52 and height == 150:
        display_width, display_height = 40, 116
    else:
        scale = 0.7 if width == 40 else 1
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


def _car(x: int, y: int, angle: int, orientation: str, markings: bool, color="#74808a") -> str:
    pieces = [f'  <g transform="translate({x} {y}) rotate({angle}) scale(0.9)">']
    if markings:
        if orientation == "unknown":
            pieces.append('    <rect x="-9" y="-10" width="18" height="20" rx="0.6" fill="none" stroke="#f0f0e9" stroke-width="1" opacity="0.9"/>')
        else:
            pieces.append('    <rect x="-6.5" y="-12.5" width="13" height="25" rx="0.6" fill="none" stroke="#f0f0e9" stroke-width="1" opacity="0.9"/>')
    if orientation == "unknown":
        pieces.extend([
            '    <circle r="7.5" fill="#c4c7c4"/>',
            '    <text y="4.2" text-anchor="middle" font-size="13" font-weight="700" fill="#505957">?</text>',
        ])
    else:
        pieces.extend([
            '    <rect x="-4.9" y="-10" width="11" height="22" rx="2.8" fill="#202626" opacity="0.22" filter="url(#car-shadow)"/>',
            '    <path d="M-5.7-7V-3M5.7-7V-3M-5.7 4V8M5.7 4V8" stroke="#303636" stroke-width="1.7" stroke-linecap="round"/>',
            f'    <rect x="-5.3" y="-10.8" width="10.6" height="21.6" rx="2.7" fill="{color}" stroke="#505958" stroke-width="0.65"/>',
            '    <path d="M-3.8-7.1Q0-8.3 3.8-7.1L3-2.9H-3Z" fill="#30393e"/>',
            '    <path d="M-3 4H3L3.7 7.6Q0 8.7-3.7 7.6Z" fill="#353e41"/>',
            '    <path d="M-4-2V3M4-2V3" stroke="#d6dcda" stroke-opacity="0.3" stroke-width="0.6"/>',
            '    <path d="M-3.1-9.4H-1.6M1.6-9.4H3.1" stroke="#e7e7d7" stroke-opacity="0.8" stroke-width="0.9" stroke-linecap="round"/>',
            '    <path d="M-3.2 9.3H-1.9M1.9 9.3H3.2" stroke="#71585a" stroke-width="0.8" stroke-linecap="round"/>',
        ])
    pieces.append('  </g>')
    return "\n".join(pieces)


def _decorative_canopy(x: int, y: int) -> str:
    """Generic illustration context, never a value derived from parking tags."""
    return (
        f'  <g transform="translate({x} {y})">\n'
        '    <ellipse cx="0.8" cy="1.6" rx="11" ry="11.5" fill="#343d30" opacity="0.17" filter="url(#car-shadow)"/>\n'
        '    <path d="M-8-6C-7-12 2-14 6-9C12-9 15-1 10 4C10 11 3 15-2 10C-9 13-15 6-11 1C-15-2-12-7-8-6Z" fill="#699653"/>\n'
        '    <path d="M-8-6C-7-12 2-14 6-9C12-9 14-3 10 1C6-2 2 3-3 0C-4-3-9-1-8-6Z" fill="#77a65d" opacity="0.7"/>\n'
        '  </g>'
    )


def render_layout_svg(side, position, orientation="unknown", markings=False):
    """Return a half-street diagram, from its outside edge to the street center.

    Left/right refer to the upward OSM way direction. A left and right image can
    touch at their flat inner edges to form one complete schematic street.

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
    mirror = "" if left else ' transform="translate(52 0) scale(-1 1)"'
    frame = "M52 0H23A23 23 0 0 0 0 23V127A23 23 0 0 0 23 150H52Z" if left else "M0 0H29A23 23 0 0 1 52 23V127A23 23 0 0 1 29 150H0Z"
    label = POSITION_LABELS[position]
    pieces = [
        f'  <defs><clipPath id="frame"><path d="{frame}"/></clipPath><filter id="car-shadow" x="-40%" y="-25%" width="180%" height="160%"><feGaussianBlur stdDeviation="0.7"/></filter></defs>',
        '  <g clip-path="url(#frame)">',
        f'  <g{mirror}>',
        '  <path d="M0 0H52V150H0Z" fill="#9d9f9b"/>',
        '  <path d="M26 0H52V150H26Z" fill="#828683"/>',
    ]
    if position != "shoulder":
        pieces.append('  <path d="M26 0V150" fill="none" stroke="#ced0c9" stroke-width="1"/>')
    if position == "street_side":
        pieces.extend([
            '  <path d="M27 17H8Q1 17 1 24V126Q1 133 8 133H27Z" fill="#898c87"/>',
            '  <path d="M26 17H8Q1 17 1 24V126Q1 133 8 133H26" fill="none" stroke="#ced0c9" stroke-width="1"/>',
        ])
    elif position == "shoulder":
        pieces.append('  <path d="M0 0H26V150H0Z" fill="#969b95"/>')
    pieces.append('  </g>')

    if position in ("yes", "no", "separate", "unknown"):
        # A floating card deliberately avoids placing a car on any surface.
        card_center = 26
        pieces.append('  <rect x="4" y="50" width="44" height="49" rx="5" fill="#dedfd8" stroke="#b0b4ad" stroke-width="0.65"/>')
        if position == "yes":
            angle = {"parallel": 0, "diagonal": 45 if left else -45, "perpendicular": 90 if left else -90, "unknown": 0}[orientation]
            pieces.extend([
                '  <rect x="11" y="53" width="30" height="32" rx="3" fill="#8b918b"/>',
                _car(card_center, 69, angle, orientation, markings),
                f'  <text x="{card_center}" y="94" text-anchor="middle" font-size="8" fill="#606862">position ?</text>',
            ])
        elif position == "no":
            pieces.extend([
                f'  <text x="{card_center}" y="76" text-anchor="middle" font-size="24" font-weight="700" fill="#727c75">P</text>',
                f'  <text x="{card_center}" y="91" text-anchor="middle" font-size="7" fill="#606862">unavailable</text>',
            ])
        elif position == "separate":
            pieces.extend([
                f'  <path d="M{card_center} 84C{card_center - 4} 79 {card_center - 11} 74 {card_center - 11} 67A11 11 0 0 1 {card_center + 11} 67C{card_center + 11} 74 {card_center + 4} 79 {card_center} 84Z" fill="#7a867c"/>',
                f'  <text x="{card_center}" y="72" text-anchor="middle" font-size="13" font-weight="700" fill="#eeeee7">P</text>',
                f'  <text x="{card_center}" y="94" text-anchor="middle" font-size="6" fill="#606862">separate object</text>',
            ])
        else:
            pieces.extend([
                f'  <text x="{card_center}" y="78" text-anchor="middle" font-size="30" font-weight="700" fill="#727c75">?</text>',
                f'  <text x="{card_center}" y="92" text-anchor="middle" font-size="6.4" fill="#606862">no information</text>',
            ])
    else:
        if position == "lane":
            car_x = 34 if orientation == "parallel" else 39
        elif position == "half_on_kerb":
            car_x = 26
        else:
            car_x = 18 if position == "on_kerb" and orientation == "parallel" else 13
        if not left:
            car_x = 52 - car_x
        angle = {"parallel": 0, "diagonal": 45 if left else -45, "perpendicular": 90 if left else -90, "unknown": 0}[orientation]
        parked_cars = ((32, "#74808a"), (75, "#9a6265"), (118, "#d4cba5"))
        if position == "street_side":
            parked_cars = ((32, "#74808a"), (118, "#d4cba5"))
        pieces.extend(_car(car_x, y, angle, orientation, markings, color) for y, color in parked_cars)
        if position == "street_side":
            pieces.append(_decorative_canopy(13 if left else 39, 75))

    pieces.append('  </g>')
    title = f"{side.capitalize()} side: {'Parking unavailable' if position == 'no' else label}"
    descriptions = {
        "yes": f"Parking exists with {orientation} orientation, but its position is unknown. The floating card does not imply a position on the road or pavement. " + ("The white outline shows explicit parking-space markings." if markings else "No parking-space markings are inferred."),
        "no": "Parking is unavailable on this side. No physical layout or legal reason is inferred.",
        "separate": "Parking is mapped as a separate object; no position or geometry is inferred here.",
        "unknown": "No information about parking layout; this does not imply that parking is absent.",
    }
    description = descriptions.get(position, f"Muted {orientation} parked-car symbols on the {side} side, {label}. " + ("Thin white outlines show explicit parking-space markings." if markings else "No parking-space markings are inferred."))
    if position == "street_side":
        description += " A small decorative tree canopy provides generic illustration context; it does not represent an interpreted tag or an actual mapped tree."
    description += " Only this half of the street is shown, from its rounded outer edge to the flat street-center cut. Left and right are relative to the upward OSM way direction, as indicated by the surrounding table."
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
