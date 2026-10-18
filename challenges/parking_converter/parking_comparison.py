"""Interpret parking tags independently of the converter and render a GFM review table.

These are schematic interpretations of explicit tags, not a parking router or a
legal assessment. Unknown tags stay visible instead of counting as equivalent.
"""

import html
import os


DEFAULT_IMAGE_BASE_URL = (
    "https://raw.githubusercontent.com/wielandb/maproulette-tagfixes/main/"
    "challenges/parking_converter/visuals"
)
ORIENTATIONS = {"parallel", "diagonal", "perpendicular"}
POSITIONS = {"lane", "half_on_kerb", "on_kerb", "street_side", "shoulder", "yes", "no", "separate"}
RESTRICTIONS = {"no_parking", "no_stopping", "no_standing", "loading_only", "charging_only", "none"}
POSITION_ALIASES = {"on_street": "lane", "lay_by": "street_side"}
ATTRIBUTES = (
    "position", "orientation", "markings", "restriction", "fee", "maxstay",
    "access", "capacity",
)
LABELS = {
    "lane": "On carriageway", "half_on_kerb": "Half on kerb",
    "on_kerb": "On pavement", "street_side": "Street-side bay",
    "shoulder": "On shoulder", "yes": "Parking; position unknown",
    "no": "No street parking", "separate": "Mapped separately",
    "parallel": "Parallel", "diagonal": "Diagonal", "perpendicular": "Perpendicular",
    "no_parking": "No parking", "no_stopping": "No stopping",
    "no_standing": "No standing", "loading_only": "Loading only",
    "charging_only": "Charging only", "none": "No restriction",
}


def evaluate_side(tags, side, schema):
    """Return canonical explicit properties, resolving :both per property.

    Each schema has its own parser. In particular, this never calls the
    conversion rules whose output the user is checking. Conditional expressions
    are retained verbatim; no country, time zone or current-time defaults apply.
    """
    if side not in ("left", "right") or schema not in ("old", "new"):
        raise ValueError("Expected side left/right and schema old/new")
    result = dict.fromkeys(ATTRIBUTES)
    result.update(authentication={}, unsupported=[])
    consumed = set()
    prefixes = ("parking:lane:", "parking:condition:") if schema == "old" else ("parking:",)

    def read(prefix, suffix=""):
        keys = [f"{prefix}{which}{':' + suffix if suffix else ''}" for which in ("both", side)]
        consumed.update(key for key in keys if key in tags)
        return tags.get(keys[1], tags.get(keys[0]))

    def unknown(key, value):
        if value is not None:
            result["unsupported"].append(f"{key}={value}")

    if schema == "old":
        base = read("parking:lane:")
        if base in ORIENTATIONS or base == "marked":
            result["position"] = "yes"
            if base in ORIENTATIONS:
                result["orientation"] = base
            else:
                result["markings"] = "yes"
            position = read("parking:lane:", base)
            if position == "painted_area_only":
                result.update(position="lane", markings="yes")
            elif position == "marked":
                result["markings"] = "yes"
            elif position is not None:
                canonical = POSITION_ALIASES.get(position, position)
                result["position"] = canonical
                if canonical not in POSITIONS:
                    unknown(f"parking:lane:{side}:{base}", position)
        elif base in ("no", "separate", "yes"):
            result["position"] = base
        elif base in ("no_parking", "no_stopping", "no_standing"):
            result.update(position="no", restriction=base)
        elif base is not None:
            result["position"] = base
            unknown(f"parking:lane:{side}", base)

        condition = read("parking:condition:")
        interval = read("parking:condition:", "time_interval")

        def condition_property(attribute, value):
            if interval:
                result[f"{attribute}:conditional"] = f"{value} @ {interval}"
            else:
                result[attribute] = value

        if condition == "free":
            condition_property("fee", "no")
        elif condition == "ticket":
            condition_property("fee", "yes")
            if interval:
                result["authentication:ticket:conditional"] = f"yes @ {interval}"
            else:
                result["authentication"]["ticket"] = "yes"
        elif condition == "disc":
            if interval:
                result["authentication:disc:conditional"] = f"yes @ {interval}"
            else:
                result["authentication"]["disc"] = "yes"
        elif condition in ("no_parking", "no_stopping", "no_standing"):
            condition_property("restriction", condition)
            if not interval:
                result["position"] = "no"
        elif condition in ("private", "customers", "yes", "no", "permissive", "permit"):
            condition_property("access", condition)
        elif condition is not None:
            unknown(f"parking:condition:{side}", condition)
            if interval:
                unknown(f"parking:condition:{side}:time_interval", interval)
        if interval and condition is None:
            unknown(f"parking:condition:{side}:time_interval", interval)
        maxstay = read("parking:condition:", "maxstay")
        if maxstay is not None:
            condition_property("maxstay", maxstay)
        lane_capacity = read("parking:lane:", "capacity")
        condition_capacity = read("parking:condition:", "capacity")
        result["capacity"] = condition_capacity if condition_capacity is not None else lane_capacity
        if lane_capacity is not None and condition_capacity is not None and lane_capacity != condition_capacity:
            unknown(f"parking:lane:{side}:capacity", lane_capacity)
    else:
        for attribute in ATTRIBUTES:
            result[attribute] = read("parking:", "" if attribute == "position" else attribute)
        if result["position"] == "lay_by":
            result["position"] = "street_side"
        for attribute, allowed in (("position", POSITIONS), ("orientation", ORIENTATIONS),
                                   ("markings", {"yes", "no"}), ("restriction", RESTRICTIONS),
                                   ("fee", {"yes", "no"})):
            if result[attribute] is not None and result[attribute] not in allowed:
                unknown(f"parking:{side}:{attribute}", result[attribute])
        authentication = read("parking:", "authentication")
        if authentication in ("disc", "ticket"):
            result["authentication"][authentication] = "yes"
        elif authentication is not None:
            result["authentication"]["other"] = authentication
            unknown(f"parking:{side}:authentication", authentication)
        for kind in ("disc", "ticket"):
            value = read("parking:", f"authentication:{kind}")
            if value is not None:
                result["authentication"][kind] = value
        for attribute in (*ATTRIBUTES, "authentication", "authentication:disc", "authentication:ticket"):
            suffix = "conditional" if attribute == "position" else f"{attribute}:conditional"
            value = read("parking:", suffix)
            if value is not None:
                result[f"{attribute}:conditional"] = value

    # Leave every unhandled applicable tag in view, including leftover legacy
    # tags after a partial conversion. Tags on the opposite side do not apply.
    for key, value in sorted(tags.items()):
        applicable = False
        for prefix in prefixes:
            for which in ("both", side):
                base_key = prefix + which
                applicable |= key == base_key or key.startswith(base_key + ":")
        if schema == "new":
            applicable |= any(key == f"{prefix}{which}" or key.startswith(f"{prefix}{which}:")
                              for prefix in ("parking:lane:", "parking:condition:") for which in ("both", side))
        if applicable and key not in consumed:
            unknown(key, value)
    result["unsupported"] = sorted(set(result["unsupported"]))
    return result


def apply_cooperative_work(tags, payload, element_id):
    """Preview the actual ordered tag edits for this element, not a guessed fix.

    Fail closed on unsupported edits affecting this element rather than showing
    an invented result. Other elements' operations do not affect its preview.
    """
    updated = dict(tags)
    for operation in payload.get("operations", []):
        data = operation.get("data", {})
        if data.get("id") != element_id:
            continue
        if operation.get("operationType") != "modifyElement":
            raise ValueError("Cannot preview non-tag cooperative work")
        for edit in data.get("operations", []):
            if edit.get("operation") == "setTags" and isinstance(edit.get("data"), dict):
                updated.update(edit["data"])
            elif edit.get("operation") == "unsetTags" and isinstance(edit.get("data"), list):
                for key in edit["data"]:
                    updated.pop(key, None)
            else:
                raise ValueError("Cannot preview unsupported cooperative tag edit")
    return updated


def _text(value):
    """Escape untrusted OSM data for a single Markdown table cell."""
    value = html.escape(str(value), quote=True).replace("\r", " ").replace("\n", " ")
    for character in ("\\", "`", "*", "_", "[", "]", "(", ")", "!", "~"):
        value = value.replace(character, "\\" + character)
    return value.replace("|", "&#124;")


def _value(value):
    return "Not tagged" if value is None else _text(value)


def _image(name, alt, base_url):
    return f"![{alt}]({base_url.rstrip('/')}/{name}.svg)"


def _layout(state, side, base_url):
    position = state["position"]
    orientation = state["orientation"]
    if position in POSITIONS - {"no", "separate"}:
        angle = orientation if orientation in ORIENTATIONS else "unknown"
        marking = "marked" if state["markings"] == "yes" else "plain"
        name = f"layout-{side}-{position}-{angle}-{marking}"
    else:
        name = f"layout-{side}-{position if position in ('no', 'separate') else 'unknown'}"
    caption = _value(LABELS.get(position, position))
    if orientation is not None:
        caption += "; " + _value(LABELS.get(orientation, orientation) if orientation in ORIENTATIONS else orientation)
    elif position not in ("no", "separate", None):
        caption += "; orientation unknown"
    return _image(name, f"{side} parking layout", base_url) + " " + caption


def build_parking_comparison(original_tags, proposed_tags, *, image_base_url=None):
    """Build portable Markdown: four side views, then rules and differences."""
    base_url = image_base_url or os.environ.get("PARKING_VISUALS_BASE_URL", DEFAULT_IMAGE_BASE_URL)
    states = [evaluate_side(tags, side, schema)
              for tags, schema in ((original_tags, "old"), (proposed_tags, "new"))
              for side in ("left", "right")]
    rows = []
    changed = []

    def row(label, keys, render, always=False):
        values = [tuple(state.get(key) for key in keys) for state in states]
        differs = values[0] != values[2] or values[1] != values[3]
        if not always and not any(any(value not in (None, {}) for value in valueset) for valueset in values):
            return
        if differs:
            changed.append(label)
        status = "⚠️ " if differs else ""
        rows.append("| " + status + label + " | " + " | ".join(render(state, side) for state, side in zip(states, ("left", "right", "left", "right"))) + " |")

    row("Parking layout", ("position", "orientation"), lambda state, side: _layout(state, side, base_url), always=True)
    row("Markings", ("markings",), lambda state, side: _value(
        {"yes": "Marked", "no": "Unmarked"}.get(state["markings"], state["markings"])
    ), always=True)

    def rule(state, side):
        value = state["restriction"]
        icon = _image(f"rule-{value}", value.replace("_", " "), base_url) + " " if value in ("no_parking", "no_stopping", "no_standing") else ""
        return icon + _value(LABELS.get(value, value) if value in RESTRICTIONS else value)

    row("Restrictions", ("restriction",), rule, always=True)
    row("Fee", ("fee",), lambda state, side: (
        _image("rule-free" if state["fee"] == "no" else "rule-ticket", "fee", base_url) + " "
        if state["fee"] in ("yes", "no") else ""
    ) + ({"yes": "Paid", "no": "Free"}.get(state["fee"], _value(state["fee"]))))
    row("Authentication", ("authentication",), lambda state, side: "; ".join(
        (_image(f"rule-{kind}", kind, base_url) + " " if kind in ("disc", "ticket") and value == "yes" else "")
        + _text(kind) + ": " + _text(value) for kind, value in sorted(state["authentication"].items())
    ) or "Not tagged")
    for label, key in (("Maxstay", "maxstay"), ("Access", "access"), ("Capacity", "capacity")):
        row(label, (key,), lambda state, side, key=key: _value(state[key]))
    conditional_keys = sorted({key for state in states for key in state if key.endswith(":conditional")})
    conditional_labels = {
        "position": "Parking", "orientation": "Orientation", "markings": "Markings",
        "restriction": "Restrictions", "fee": "Fee", "maxstay": "Maxstay",
        "access": "Access", "capacity": "Capacity", "authentication": "Authentication",
        "authentication:disc": "Parking disc", "authentication:ticket": "Parking ticket",
    }
    for key in conditional_keys:
        label = conditional_labels[key.removesuffix(":conditional")] + " (conditional)"
        row(label, (key,), lambda state, side, key=key: _value(state.get(key)))
    if any(state["unsupported"] for state in states):
        row("Not fully interpreted", ("unsupported",), lambda state, side: "; ".join(_text(tag) for tag in state["unsupported"]) or "—", always=True)

    summary = "**Differences detected:** " + ", ".join(changed) + "." if changed else "No differences in interpreted values."
    if any(state["unsupported"] for state in states):
        summary += " **Not fully interpreted: check the raw tags below; equivalence cannot be confirmed.**"
    return "\n\n**Visual parking comparison**\n\n" + summary + "\n\n" + (
        "| Aspect | Old left | Old right | New left | New right |\n"
        "| --- | --- | --- | --- | --- |\n" + "\n".join(rows)
        + "\n\nLeft/right follow the OSM way direction (↑), not the map or driving direction. "
        "Old columns interpret legacy tags; new columns include retained modern tags. "
        "Images are schematic; not tagged means unknown, not unrestricted. "
        "Conditional rules are shown literally, without evaluating the current time.\n"
    )
