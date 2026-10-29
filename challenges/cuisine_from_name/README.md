# Cuisine from restaurant names

Generate reviewable TagFix suggestions for active `amenity=fast_food` and
`amenity=restaurant` objects in Germany. Each task changes only `cuisine` on one
existing node, way or relation. It does not edit OSM or publish to MapRoulette.

The name rules extend the [O-sus-M ideas](https://haukauntrie.de/projekte/osusm) to restaurants,
common spellings and compounds:

| Name contains (case insensitive) | Suggested value |
| --- | --- |
| Döner, Doener, Doner, Kebab, Kebap | `kebab` |
| Pizza, Pizzeria | `pizza` |

Substrings deliberately include compounds such as `Citydöner`, `Dönerhaus` and
`Pizzaservice`. These are name-based heuristics: a historic business name or an
unusual compound may still be a false positive. Mappers must check each proposal.
A name containing both signals produces one task and one combined TagFix.
No cuisine is inferred from `operator`, `brand` or nationality alone.

Existing semicolon-separated cuisine values keep their spelling, order and
spacing. Missing values are appended in the order `kebab`, then `pizza`; a
previously absent or blank cuisine is filled. Comparison uses complete tokens,
ignores case and surrounding whitespace, and treats `italian_pizza` as satisfying
the pizza rule, following the [cuisine documentation](https://wiki.openstreetmap.org/wiki/Key:cuisine).
Existing `italian` or `turkish` remains, for example `turkish;kebab;pizza`.
No suggestion is emitted when both hints are already covered. Lists containing
empty items or commas are skipped for manual repair rather than normalized.

Objects with lifecycle flags (for example `disused=yes`) or prefixed amenity,
name or cuisine tags (for example `disused:amenity=restaurant`) are excluded.
Negative lifecycle flags such as `disused=no` do not exclude an otherwise active
object. Unknown or missing geometry is skipped without aborting later tasks.

The German task instructions show the matched name, old and proposed values,
current OSM object, cuisine documentation, and existing website/menu links.
The generator does not fetch those business websites. Accept only after review;
correct a proposal in an editor, reject it, or skip when unsure.

## Run locally

Use the repository's virtual environment and dependencies, or install `requests`
and `shapely>=2` for this standalone generator. Shapely is required for the
default French Overpass server's exact country-boundary filtering.
Run from the repository root:

```powershell
.\.venv\Scripts\python.exe challenges/cuisine_from_name/generate.py
```

The default versionable output is `challenges/cuisine_from_name/cuisine_from_name.json`,
a UTF-8 JSON sequence with one task per record. Paths are resolved independently
of the shell's working directory; a relative `--output` is relative to the caller.
No empty placeholder output is committed before a real run.

For a smaller real sample:

```powershell
.\.venv\Scripts\python.exe challenges/cuisine_from_name/generate.py --bbox 51.025 13.70 51.09 13.79 --max-tasks 20 --output .venv/live-challenges/cuisine_dresden.json
```

`--bbox SOUTH WEST NORTH EAST` selects that rectangle instead of Germany.
`--max-tasks` must be positive and can only lower the shared 50,000-task limit.
The shared 99,000,000-byte limit also applies; generation stops before processing
another candidate once a limit is reached. Output directories are created as
needed. Query failures preserve previous output; a successful zero-result run
replaces it with an empty file. The shared Overpass failover and `OVERPASS_URLS`
configuration apply.

## Included initial data sample

The checked-in `cuisine_from_name.json` is a real **20-task sample from Dresden
and its surroundings**, generated on **2026-10-29** for bounding box
`50.95 13.60 51.12 13.90` and capped at 20 tasks. It is not a complete Germany
export. Candidate discovery used an outdated French Overpass snapshot because
current Overpass endpoints were unavailable; every included object's current
tags and coordinates were fetched again from the live OSM editing API before
task generation. No OSM changes were uploaded.

A normal run without `--bbox` or a manual workflow run with empty bbox input
replaces this sample with a new Germany export. API revalidation for this initial
sample was a separate preparation step; the generator itself uses the shared
Overpass client's freshness checks and does not accept outdated results.

## Manual GitHub Actions update

Run **Update Cuisine Challenge Data** using **Run workflow** on the intended
branch. It has no schedule. Optional inputs select a bounding box and smaller
maximum task count. The workflow runs the offline tests, generates the JSON,
uploads it as a downloadable artifact, and commits only that output when it
changed. It needs repository `contents: write` permission and no service secrets.
This does not create or update a MapRoulette challenge.

## Offline checks

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_cuisine_from_name.py" -v
```

Tests cover spelling/compound matches, preservation and idempotence, aliases,
combined suggestions, lifecycle exclusions, all three OSM types, malformed
coordinates, query/CLI selection, JSON-sequence output, task/byte limits, and
preservation of output after download failures. Network calls are mocked.
