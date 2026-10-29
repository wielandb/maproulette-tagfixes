# maproulette-tagfixes

Generator scripts for tagfix challenges.

Install the dependencies in a virtual environment (Python 3.12):

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Run an individual generator from the repository root, for example:

```powershell
.\.venv\Scripts\python.exe challenges/note_abgerissen/note_abgerissen.py
```

Generators resolve their imports, input files and output files relative to their
script directory. On Windows, `update_all_challenges.bat` runs all implemented
generators and uses `.venv` when available. It returns a nonzero exit code if any
generator fails. Generation needs internet access; the Imgur scan downloads
Geofabrik extracts and can take a long time.

All challenge generators stop at 50,000 tasks or before adding a task that would
exceed 99 MB (99,000,000 bytes), whichever comes first. Exactly reaching a limit
is allowed. The byte limit includes the complete UTF-8 JSON sequence, geometry,
instructions, cooperative edits, record separators and platform-native line
endings. An oversized task is excluded and generation ends; it is not skipped
in favour of later tasks. Completed tasks are saved normally, and no further
per-task processing is performed. Initial candidate/context downloads may still
be necessary before tasks can be built. The shared writer rechecks both limits
and replaces the previous output atomically.

The parking converter works without the optional AI helper. AI conversion requires
its separate local configuration and dependencies. Each old parking-side tag is
queried separately to stay within Overpass's global query timeout; duplicate ways
are merged before conversion.

The stop-area generator also accepts `--bbox SOUTH WEST NORTH EAST`, `--output`
and `--max-tasks` for a smaller live run. Without these options it processes all
of Germany in batches of 100 stations, merging results and excluding existing
members across all batches. Current relations are read from the OSM editing API
in batches of up to 100 as needed while building OSC changes; reaching an output
limit avoids further relation batches. The [stop-area catalogue and
review instructions](challenges/add_objects_to_stop_area/README.md) describe the
equipment and access infrastructure included. For example, after creating the
output directory:

```powershell
New-Item -ItemType Directory -Force .venv/live-challenges | Out-Null
.\.venv\Scripts\python.exe challenges/add_objects_to_stop_area/generate.py --bbox 51.025 13.70 51.09 13.79 --output .venv/live-challenges/stop_area_dresden.json
```

The shared Overpass client starts with `overpass.openstreetmap.fr`, followed by
`overpass-api.de`, `overpass.private.coffee`, and `maps.mail.ru`, with at most six
attempts per top-level query. The last successful
server is preferred for the next query. Connection timeout is 10 seconds; read
timeout is 300 seconds so queries with a 250-second server timeout can complete.
Failures use increasing delays of 5, 10, 20, 40 and 60 seconds. HTTP 406 and 429
always wait at least 30 seconds, following the [Overpass usage policy](https://wiki.openstreetmap.org/wiki/Overpass_API#Public_Overpass_API_instances).
Invalid queries stop immediately; exhausted retries report the server and reason
without dumping an HTML error page into the terminal.

The French instance serves global data but does not generate Overpass areas.
For the generators' explicit country areas, the client loads the actual boundary
relation and retrieves matching candidates inside its bounding box. It then
checks the exact geometry locally and inserts typed object IDs into the original
query. Country holes, islands and the query's subsequent set operations are
preserved. Large country selections use smaller spatial requests to avoid server
timeouts, with a 60-second query timeout and at most 128 requests per selection.
Borders and selections are cached for the lifetime of the client.
An incomplete border way is repaired from the official OSM API only when its
endpoints still match; unusable borders fail explicitly instead of producing an
empty challenge. Unsupported area syntax falls back to another server.
Overpass responses with a database timestamp older than seven days are rejected.

To use your own ordered list of Overpass servers, set `OVERPASS_URLS` before
running a generator:

```powershell
$env:OVERPASS_URLS = "https://overpass.openstreetmap.fr/api/interpreter,https://overpass-api.de/api/interpreter"
```

Python callers can also pass `overpass_urls=[...]`, `max_attempts=...`,
`retry_delay=...`, and `request_timeout=...` to `Overpass`.

Run the offline regression tests with:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## Website redirects

The [website redirect generator](challenges/website_redirects/README.md) creates
German TagFix tasks for permanent 301/308 redirects of `website` and
`contact:website`. It includes HTTPS, www, slash and domain changes, with human
review of the destination's identity and current OSM tags. Candidates and
node/way/relation centres come entirely from a Germany Geofabrik PBF through
`shared/geofabrik.py`; there are no Overpass or OSM API requests. An automatic
extract is reused for at most 24 hours, then deleted before downloading its
replacement. `--pbf` selects an existing extract and `--bbox` filters its local
display centres; both options can be combined. The default shared cache is
`.cache/geofabrik`. Website HTTP results have a separate SQLite cache in that
directory. A manual GitHub Actions workflow tests the source and generator and
updates only this challenge's generated JSON; there is no scheduled run.

## Parking conversion comparison

Every newly generated parking task includes a Markdown comparison table with
four small views: old left/right and proposed new left/right. The first row
shows position and orientation, with explicit parking-space markings in the
diagram. Each side shows only half the street, from its outer pavement to the
street centre; adjacent left and right images form a complete street. Further
rows compare markings, restrictions, fees, authentication,
maximum stay, access, capacity, and any supported conditional rules that occur.
Changed rows are flagged. Left/right are relative to the OSM way direction,
indicated by an upward arrow, rather than the map or driving direction.

The legacy and modern parsers are independent of the conversion rules. The new
columns use the actual cooperative-work operations, including AI proposals and
the no-op used for manual tasks; retained modern tags are included. The old
columns interpret the legacy schema. Missing information stays unknown and
unhandled values/tags remain visible with a warning. Conditional expressions
are compared literally, without evaluating time or local parking law. This is
a schematic review aid, not a guarantee that all tag meanings are equivalent.

MapRoulette supports Markdown images and tables but not raw HTML, so the small
SVGs are hosted as ordinary repository files. **Publish the `visuals/` assets
before uploading generated tasks.** By default image links point to
`https://raw.githubusercontent.com/wielandb/maproulette-tagfixes/main/challenges/parking_converter/visuals`.
For a fork, another branch, or a different static host, set
`PARKING_VISUALS_BASE_URL` to the public HTTPS directory containing those SVGs
before running the generator. Existing challenge data is updated on regeneration.

Preview representative comparisons locally, without Overpass or AI access:

```powershell
.\.venv\Scripts\python.exe challenges/parking_converter/preview_parking_comparison.py
```

Open the printed `comparison_preview.html` path in a browser. This generated,
Git-ignored HTML embeds the repository SVGs and works offline. An optional
`--output PATH` selects its destination. The MapRoulette instructions themselves
use portable Markdown, not this HTML preview. Regenerate the finite icon set
after changing its drawing code with:

```powershell
.\.venv\Scripts\python.exe challenges/parking_converter/generate_parking_icons.py
```

The interpretation follows the OSM wiki's [legacy parking tags](https://wiki.openstreetmap.org/wiki/Key:parking:lane)
and [current street parking schema](https://wiki.openstreetmap.org/wiki/Street_parking).
See also [MapRoulette's Markdown support](https://learn.maproulette.org/en-US/documentation/markdown/).

## Optional parking AI setup

Run the parking generator from the repository root with:

```powershell
.\.venv\Scripts\python.exe challenges/parking_converter/parking_converter.py
```

The normal rules work without an API key. AI is only attempted for conversions
that the rules cannot complete and that have no conflicting modern parking tags.
If AI dependencies, configuration, quota service, or a usable AI result are
unavailable, rule-based conversion continues. With the current
`ONLY_AUTO_TASKS = True`, ways that cannot be converted completely are skipped.

To enable the existing AI helper locally:

1. Install the optional SDK; it is not included in `requirements.txt`:

   ```powershell
   .\.venv\Scripts\python.exe -m pip install openai
   ```

2. Create `challenges/parking_converter/creds.json` with your own configuration:

   ```json
   {
     "prompt_id": "YOUR_EXISTING_PROMPT_ID",
     "prompt_version": "YOUR_PROMPT_VERSION",
     "openai_key": "YOUR_OPENAI_API_KEY"
   }
   ```

   This file is ignored by Git. The helper reads the key explicitly from this
   file; setting `OPENAI_API_KEY` alone does not configure the current code.
   The key needs access to the referenced prompt and a supported model.

3. Supply the separate local `free_tokens.py` helper, for example at
   `shared/free_tokens.py`. This helper is ignored by Git and is not included in
   a fresh checkout. Its quota service must be reachable; configure
   `FREE_TOKENS_URL` and `FREE_TOKENS_API_KEY` in the process environment for
   your service. The current local helper otherwise defaults to
   `http://localhost/free-tokens.php` and the placeholder `CHANGE_ME`.
   Its quota accounting does not itself establish whether OpenAI API usage is
   free. The configured model order is `gpt-5-mini`, then `gpt-5.1`.

There is currently no parking GitHub Actions workflow. The existing workflow
only updates the stopsign challenge and does not provision an OpenAI key.
Repository files cannot show whether Actions secrets have already been configured
on GitHub. For a future parking workflow, store the key as an Actions secret
such as `OPENAI_API_KEY`, then explicitly pass it to the job. The current helper
would also need to read that environment variable, or the job would need to
create the ignored credentials file at runtime. Provision the prompt configuration,
quota helper, and quota service configuration as well. Do not commit credential
files or print secret values in workflow logs.

The current integration uses a stored OpenAI prompt ID. As of October 18, 2026,
the [official OpenAI documentation](https://developers.openai.com/api/docs/guides/prompting)
announces retirement of prompt objects on November 30, 2026. Move the prompt
content into versioned application code before that retirement when maintaining
this integration.
