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

The parking converter works without the optional AI helper. AI conversion requires
its separate local configuration and dependencies. Each old parking-side tag is
queried separately to stay within Overpass's global query timeout; duplicate ways
are merged before conversion.

The stop-area generator also accepts `--bbox SOUTH WEST NORTH EAST`, `--output`
and `--max-tasks` for a smaller live run. Without these options it processes all
of Germany in batches of 100 stations, merging results and excluding existing
members across all batches. Current relations are read from the OSM editing API
in batches of 100 before building OSC changes. For example, after creating the
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
