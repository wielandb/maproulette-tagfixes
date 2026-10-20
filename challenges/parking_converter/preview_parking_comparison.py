"""Create an offline HTML preview of the actual comparison Markdown and SVGs."""

import argparse
import base64
import html
from pathlib import Path
import re
import sys

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR.parents[1]))
from challenges.parking_converter.parking_comparison import build_parking_comparison


EXAMPLES = [
    ("Marked parking and a stopping restriction", {
        "parking:lane:left": "parallel", "parking:lane:left:parallel": "painted_area_only",
        "parking:lane:right": "no_stopping", "parking:condition:left": "free",
    }, {
        "parking:left": "lane", "parking:left:orientation": "parallel", "parking:left:markings": "yes",
        "parking:left:fee": "no", "parking:right": "no", "parking:right:restriction": "no_stopping",
    }),
    ("Different positions on each side", {
        "parking:lane:both": "diagonal", "parking:lane:left:diagonal": "half_on_kerb",
        "parking:lane:right:diagonal": "lay_by",
    }, {
        "parking:both:orientation": "diagonal", "parking:left": "half_on_kerb", "parking:right": "street_side",
    }),
    ("Parking disc and a time limit", {
        "parking:lane:both": "perpendicular", "parking:lane:both:perpendicular": "on_kerb",
        "parking:condition:both": "disc", "parking:condition:both:maxstay": "2 hours",
        "parking:condition:both:time_interval": "(Mo-Fr 08:00-18:00)",
    }, {
        "parking:both": "on_kerb", "parking:both:orientation": "perpendicular",
        "parking:both:authentication:disc:conditional": "yes @ (Mo-Fr 08:00-18:00)",
        "parking:both:maxstay:conditional": "2 hours @ (Mo-Fr 08:00-18:00)",
    }),
    ("A changed orientation is flagged", {
        "parking:lane:both": "parallel", "parking:lane:both:parallel": "on_street",
    }, {
        "parking:both": "lane", "parking:both:orientation": "perpendicular",
    }),
    ("Unknown information remains unknown", {
        "parking:lane:left": "marked", "parking:lane:right": "unusual_value",
    }, {
        "parking:left": "yes", "parking:left:markings": "yes", "parking:right": "unusual_value",
    }),
]


def _plain(text):
    # This preview only renders our generated table subset, never arbitrary HTML.
    text = re.sub(r"\\([\\`*_\[\]()!~])", r"\1", text.replace("**", ""))
    return html.escape(html.unescape(text))


def _embedded_icon(filename, alt):
    image = base64.b64encode((SCRIPT_DIR / "visuals" / filename).read_bytes()).decode("ascii")
    return f'<img src="data:image/svg+xml;base64,{image}" alt="{html.escape(alt, quote=True)}">'


def _cell(text):
    result, start = [], 0
    for match in re.finditer(r"!\[([^\]]*)\]\(visuals/([a-z_-]+\.svg)\)", text):
        result.append(_plain(text[start:match.start()]))
        result.append(_embedded_icon(match[2], match[1]))
        start = match.end()
    result.append(_plain(text[start:]))
    return "".join(result)


def render_preview():
    orientation_samples = []
    for orientation, label in (("parallel", "Parallel"), ("diagonal", "Diagonal"), ("perpendicular", "Perpendicular")):
        halves = "".join('<div class="half-view">' + _embedded_icon(
            f"layout-{side}-street_side-{orientation}-marked.svg",
            f"{side.capitalize()} street half, {orientation} parking",
        ) + f'<span>{side.capitalize()}</span></div>' for side in ("left", "right"))
        orientation_samples.append(f'<figure><div class="street-pair">{halves}</div><figcaption>{label}</figcaption></figure>')
    sample_gallery = '<section class="samples"><h2>Parking orientation</h2><p>One narrow street half for each side.</p><div class="orientations">' + "".join(orientation_samples) + '</div></section>'
    sections = []
    for title, old, new in EXAMPLES:
        markdown = build_parking_comparison(old, new, image_base_url="visuals")
        lines = markdown.strip().splitlines()
        summary = next(line for line in lines[1:] if line.strip())
        rows = [line for line in lines if line.startswith("|")]
        header = "".join(f"<th>{_plain(cell.strip())}</th>" for cell in rows[0].strip("|").split("|"))
        body = "".join("<tr>" + "".join(f"<td>{_cell(cell.strip())}</td>" for cell in row.strip("|").split("|")) + "</tr>" for row in rows[2:])
        status = "changed" if "Differences detected" in summary else "same"
        sections.append(f'<section><h2>{html.escape(title)}</h2><p class="{status}">{_plain(summary)}</p><div class="table"><table><thead><tr>{header}</tr></thead><tbody>{body}</tbody></table></div></section>')
    return '''<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Parking converter — visual comparison</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#edf1f4;color:#203748;font:15px/1.5 system-ui,sans-serif}
main{max-width:1080px;margin:auto;padding:38px 24px}h1{font-size:30px;letter-spacing:-.6px;margin:8px 0}
.eyebrow{color:#006e84;text-transform:uppercase;letter-spacing:2px;font-size:12px;font-weight:750}
.intro{max-width:850px;color:#506373}section{margin:28px 0;background:white;border:1px solid #d5dfe6;border-radius:12px;padding:22px;box-shadow:0 3px 14px #193b5010}
.samples{background:#282828;color:#eee;border-color:#3d3d3d;box-shadow:none}.samples p{margin:0 0 22px;color:#bbb;font-size:13px}.orientations{display:flex;justify-content:space-around;gap:12px}.orientations figure{margin:0;text-align:center;flex:1;min-width:0}.street-pair{display:flex;max-width:90px;margin:0 auto;gap:10px;align-items:flex-start}.half-view{display:flex;flex:1;min-width:0;flex-direction:column;align-items:center;gap:8px}.half-view img{display:block;width:40px;max-width:100%;height:auto}.half-view span{font-size:10px;color:#aaa}.orientations figcaption{margin-top:12px;font-size:13px;font-weight:400}
h2{font-size:19px;margin:0 0 12px}.same,.changed{padding:10px 13px;border-radius:6px}.same{background:#e7f5ed;color:#245e44}.changed{background:#fff2d5;color:#79520b}
.table{overflow-x:auto}table{width:100%;border-collapse:collapse;table-layout:fixed;min-width:410px}th,td{border:1px solid #dbe3e9;padding:10px;vertical-align:top;text-align:left;overflow-wrap:anywhere}
th{background:#f3f6f8;font-size:13px}th:first-child,td:first-child{width:19%;font-weight:650}td{font-size:13px}td img{display:block;max-width:100%;margin:0 auto 8px}td img[src]{object-fit:contain}
footer{color:#506373;font-size:13px}code{background:#e3e9ed;padding:2px 4px;border-radius:3px}
@media(max-width:600px){main{padding:24px 12px}section{padding:12px}th,td{padding:6px;font-size:11px}th:first-child,td:first-child{width:18%}h1{font-size:26px}}
</style><main><div class="eyebrow">Parking converter / review aid</div>
<h1>Two halves. One street.</h1>
<p class="intro">Each diagram shows only its own half of the street, from the outer pavement to the centre. The pictograms use a restrained gray palette, small coloured cars and subtle parking-space markings. Left and right follow the OSM way direction, shown upward.</p>
''' + sample_gallery + "\n".join(sections) + '''<footer>Examples are schematic. Missing tags mean unknown. Old columns interpret legacy tags; new columns include retained modern tags. Conditional rules are shown literally, without evaluating the current time. Unhandled values remain visible and require checking.</footer></main></html>'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=SCRIPT_DIR / "comparison_preview.html")
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render_preview(), encoding="utf-8")
    print(args.output.resolve())


if __name__ == "__main__":
    main()
