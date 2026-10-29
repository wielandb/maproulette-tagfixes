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

## Run locally from Geofabrik PBF

Install the repository dependencies, or `requests` and `osmium>=4.0` for this
generator. Run from the repository root:

```powershell
.\.venv\Scripts\python.exe challenges/cuisine_from_name/generate.py
```

The default input is the [Geofabrik Germany extract](https://download.geofabrik.de/europe/germany.html).
The shared helper downloads `germany-latest.osm.pbf` into repository
`.cache/geofabrik` and reuses its download cache. Cache files are ignored by Git.
This is a large download. All candidate tags and node, way and relation display
centres are read locally from that PBF; the generator makes no Overpass or OSM
editing API requests. Website links appear only as manual review aids and are
not fetched by the generator. The scope follows the extract, including its
border objects, rather than a separate exact country polygon.

Use an existing extract or a different shared download cache:

```powershell
.\.venv\Scripts\python.exe challenges/cuisine_from_name/generate.py --pbf C:\osm\germany-latest.osm.pbf
.\.venv\Scripts\python.exe challenges/cuisine_from_name/generate.py --cache-dir .venv/geofabrik-cache
```

`--pbf` skips downloading; the caller is responsible for that file's provenance,
region and freshness. `--bbox SOUTH WEST NORTH EAST` filters object display
centres inside the PBF locally and can be combined with `--pbf`. It does not
make a regional download or reduce the source extract before scanning.

For a smaller real sample:

```powershell
.\.venv\Scripts\python.exe challenges/cuisine_from_name/generate.py --pbf C:\osm\germany-latest.osm.pbf --bbox 50.95 13.60 51.12 13.90 --max-tasks 20 --output .venv/live-challenges/cuisine_dresden.json
```

The default versionable output is `challenges/cuisine_from_name/cuisine_from_name.json`,
a UTF-8 JSON sequence with one task per record. Default paths are relative to
the repository/script; relative explicit `--pbf`, `--cache-dir` and `--output`
paths are relative to the caller. Output directories are created as needed.

`--max-tasks` must be positive and can only lower the shared 50,000-task limit.
The shared 99,000,000-byte limit also applies. The PBF iterator is closed at a
limit without advancing another candidate; loading initial geometry context
may require extra passes through the file. A download or PBF-read failure
preserves previous output. A successful zero-result run replaces it with an
empty file. No tags or geometry are refreshed from another remote data source.

## Included real PBF test run

The checked-in `cuisine_from_name.json` contains **20 real tasks** from a
successful CLI run on **2026-10-29**, with **exit status 0**. The source was the
complete Geofabrik `germany-latest.osm.pbf`, downloaded that day (**4,871,369,043
bytes**), with PBF header timestamp **2026-10-28T21:21:02Z**. The run used the
shared download cache, local bounding box **50.95 13.60 51.12 13.90** around
Dresden and Freital, and `--max-tasks 20`.

Equivalent command from the repository root, with the freshly populated shared
cache:

```powershell
.\.venv\Scripts\python.exe challenges/cuisine_from_name/generate.py --cache-dir .venv/geofabrik-cache --bbox 50.95 13.60 51.12 13.90 --max-tasks 20 --output .venv/live-challenges/cuisine_pbf.json
```

The log reports `Challenge limit reached: 20 tasks` followed by `Saved 20 cuisine
tasks`; the wrapper recorded exit status `0`. The successful output was copied
to the versioned default output. This replaces the earlier API-revalidated
sample: tags, candidates and coordinates in the current file all come solely
from the PBF. No Overpass or OSM API calls or mocked results were used.

All 20 name-based suggestions were checked for additive cuisine changes and
retention of existing values. These capped first results are nodes; local
way/relation geometry is covered by real miniature PBF integration tests. The
sample is not a complete Germany export or a full scan of all eligible objects.
Every task shows its source filename and PBF timestamp for mapper review.

## Manual GitHub Actions update

Run **Update Cuisine Challenge Data** using **Run workflow** on the intended
branch. It has no schedule. Optional inputs select a local PBF bounding-box
filter and a smaller maximum task count. The workflow installs `requests` and
`osmium>=4.0`, runs offline tests, downloads the Germany PBF, generates the JSON,
uploads it as a downloadable artifact, and commits only that output when it
changed. It needs repository `contents: write` permission and no service secrets.
This does not create or update a MapRoulette challenge.

## Offline checks

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_cuisine_from_name.py" -v
```

Tests cover spelling/compound matches, preservation and idempotence, aliases,
combined suggestions, lifecycle exclusions, all three OSM types, malformed
coordinates, CLI selection, JSON-sequence output, task/byte limits, and
preservation of output after download/PBF failures. A real small PBF fixture
exercises nodes, ways, relations, the predicate and local bbox without network.
