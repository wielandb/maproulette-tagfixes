"""Geofabrik download and selective, local PBF reference resolution.

Candidates and references use a temporary SQLite database. There is no global
node-location index: only IDs needed by tag-selected candidates reach the
coordinate pass. pyosmium's C++ ID filters hold those selected IDs, while tags,
member lists and coordinates stay on disk. Closing the iterator removes the
scratch database, including when a caller reaches its task limit early.
"""
from contextlib import closing
import json
import math
from pathlib import Path
import sqlite3
import sys
import tempfile
import time

import requests

GERMANY_PBF = "https://download.geofabrik.de/europe/germany-latest.osm.pbf"
MAX_AGE = 24 * 60 * 60
MAX_RELATION_DEPTH = 8
USER_AGENT = "maproulette-tagfixes/1.0 (+https://github.com/wielandb/maproulette-tagfixes)"


def download_germany(cache_dir, *, now=time.time, get=None):
    """Delete an expired automatic extract, then stream its replacement."""
    directory = Path(cache_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "germany-latest.osm.pbf"
    if path.is_file() and path.stat().st_size > 0 and 0 <= now() - path.stat().st_mtime < MAX_AGE:
        return path
    if path.is_file():
        path.unlink()
    temporary = path.with_suffix(path.suffix + ".part")
    session = None
    try:
        if get is None:
            session = requests.Session()
            session.trust_env = False
            get = session.get
        with get(GERMANY_PBF, stream=True, timeout=(10, 120),
                 headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity"}) as response:
            response.raise_for_status()
            length = response.headers.get("Content-Length")
            expected = int(length) if length and length.isdigit() else None
            downloaded = 0
            with temporary.open("wb") as output:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    downloaded += output.write(chunk)
            if not downloaded or (expected is not None and downloaded != expected):
                raise RuntimeError("Deutschland-Extrakt ist leer oder unvollständig.")
        temporary.replace(path)
        return path
    finally:
        temporary.unlink(missing_ok=True)
        if session is not None:
            session.close()




def _validate_pbf_header(path):
    # Reject broken/truncated envelopes before libosmium opens the file. Some
    # Windows pyosmium builds retain a file handle after a native header error.
    def varint(data, offset):
        value = 0
        for shift in range(0, 70, 7):
            if offset >= len(data):
                raise ValueError("unvollständiger Varint")
            byte = data[offset]
            offset += 1
            value |= (byte & 127) << shift
            if not byte & 128:
                return value, offset
        raise ValueError("ungültiger Varint")
    try:
        with Path(path).open("rb") as stream:
            prefix = stream.read(4)
            size = int.from_bytes(prefix, "big")
            if len(prefix) != 4 or not 0 < size <= 65536:
                raise ValueError("ungültige BlobHeader-Länge")
            header = stream.read(size)
            if len(header) != size:
                raise ValueError("unvollständiger BlobHeader")
            offset, blob_type, data_size = 0, None, None
            while offset < len(header):
                key, offset = varint(header, offset)
                field, wire = key >> 3, key & 7
                if wire == 0:
                    value, offset = varint(header, offset)
                    if field == 3:
                        data_size = value
                elif wire == 2:
                    length, offset = varint(header, offset)
                    value = header[offset:offset + length]
                    offset += length
                    if len(value) != length:
                        raise ValueError("unvollständiges Header-Feld")
                    if field == 1:
                        blob_type = value
                elif wire in (1, 5):
                    offset += 8 if wire == 1 else 4
                else:
                    raise ValueError("ungültiger Header-Feldtyp")
            if (offset != len(header) or blob_type != b"OSMHeader" or data_size is None
                    or not 0 < data_size <= 32 * 1024 * 1024
                    or Path(path).stat().st_size < 4 + size + data_size):
                raise ValueError("ungültiger oder unvollständiger OSMHeader-Blob")
    except ValueError as exc:
        raise RuntimeError(f"Ungültige PBF-Datei {Path(path).name}: {exc}") from exc


def _pbf_objects(path, entities, filters=()):
    # Explicitly clear native readers/iterators even when libosmium raises.
    # Keeping them in an exception traceback otherwise retains Windows handles.
    import osmium
    reader = osmium.io.Reader(str(path), entities)
    iterator = None
    try:
        iterator = osmium.OsmFileIterator(reader, *filters)
        yield from iterator
    finally:
        iterator = None
        try:
            reader.close()
        finally:
            reader = None


def _valid_point(lon, lat):
    return (math.isfinite(lon) and math.isfinite(lat)
            and -180 <= lon <= 180 and -90 <= lat <= 90)


def _merge(bounds):
    items = list(bounds)
    if not items:
        raise ValueError("keine auflösbaren geometrischen Mitglieder")
    return (min(item[0] for item in items), min(item[1] for item in items),
            max(item[2] for item in items), max(item[3] for item in items))


def iter_pbf_elements(path, *, tag_keys, predicate=None, bbox=None):
    """Yield complete candidate tags and a reference-derived display centre.

    `tag_keys` selects candidates only; `predicate` receives their full tag dict.
    A bounding box filters the locally calculated display centre. Ways need all
    referenced nodes; relations need all geometric members, including nested
    relations up to depth eight. Missing references and cycles are diagnosed and
    skipped, rather than replaced with an arbitrary member's position.
    """
    import osmium
    path = Path(path)
    keys = tuple(tag_keys)
    if not keys:
        raise ValueError("Mindestens ein Kandidaten-Tag ist erforderlich.")
    if bbox is not None:
        if len(bbox) != 4:
            raise ValueError("bbox benötigt SÜD WEST NORD OST")
        south, west, north, east = bbox
        if not (-90 <= south < north <= 90 and -180 <= west < east <= 180):
            raise ValueError("Ungültige Bounding Box")
    _validate_pbf_header(path)
    reader = osmium.io.Reader(str(path), osmium.osm.NOTHING)
    try:
        timestamp = reader.header().get("osmosis_replication_timestamp") or None
    finally:
        try:
            reader.close()
        finally:
            reader = None
    print(f"PBF {path.name}: Stand {timestamp or 'im Header unbekannt'}; Kandidatensuche startet.", file=sys.stderr)
    with tempfile.TemporaryDirectory(prefix="maproulette-pbf-refs-") as temporary:
        with closing(sqlite3.connect(Path(temporary) / "refs.sqlite3")) as database:
            database.executescript("""
                PRAGMA journal_mode=OFF;
                PRAGMA synchronous=OFF;
                PRAGMA temp_store=FILE;
                PRAGMA cache_size=-16384;
                CREATE TABLE candidates (seq INTEGER PRIMARY KEY, kind TEXT, id INTEGER, tags TEXT);
                CREATE TABLE ways (id INTEGER PRIMARY KEY, refs TEXT);
                CREATE TABLE relations (id INTEGER PRIMARY KEY, members TEXT);
                CREATE TABLE need_nodes (id INTEGER PRIMARY KEY, lon REAL, lat REAL);
                CREATE TABLE need_ways (id INTEGER PRIMARY KEY);
                CREATE TABLE need_relations (id INTEGER PRIMARY KEY, depth INTEGER);
                CREATE TABLE bounds (kind TEXT, id INTEGER, west REAL, south REAL, east REAL, north REAL, height INTEGER DEFAULT 0, PRIMARY KEY(kind,id));
            """)
            diagnostics = {"count": 0}
            def report(kind, object_id, reason):
                diagnostics["count"] += 1
                if diagnostics["count"] <= 20:
                    print(f"PBF: {kind}/{object_id} übersprungen: {reason}", file=sys.stderr)

            def keep_way(obj):
                refs = [item.ref for item in obj.nodes]
                database.execute("INSERT OR REPLACE INTO ways VALUES (?, ?)", (obj.id, json.dumps(refs)))
                database.executemany("INSERT OR IGNORE INTO need_nodes(id) VALUES (?)", ((ref,) for ref in refs))

            def keep_relation(obj):
                members = [(str(member.type), member.ref) for member in obj.members]
                database.execute("INSERT OR REPLACE INTO relations VALUES (?, ?)", (obj.id, json.dumps(members)))

            streamed_nodes = 0
            with closing(_pbf_objects(path, osmium.osm.NODE | osmium.osm.WAY | osmium.osm.RELATION, (osmium.filter.KeyFilter(*keys),))) as processor:
                for obj in processor:
                    tags = dict(obj.tags)
                    if predicate is not None and not predicate(tags):
                        continue
                    if isinstance(obj, osmium.osm.Node):
                        if not obj.location.valid() or not _valid_point(obj.location.lon, obj.location.lat):
                            report("node", obj.id, "keine gültigen Koordinaten")
                            continue
                        lon, lat = obj.location.lon, obj.location.lat
                        if bbox is not None and not (west <= lon <= east and south <= lat <= north):
                            continue
                        database.execute("INSERT OR REPLACE INTO need_nodes VALUES (?, ?, ?)", (obj.id, lon, lat))
                        streamed_nodes += 1
                        # Nodes are already complete; an early task limit must
                        # not wait for nationwide way/relation resolution.
                        yield {"type": "node", "id": obj.id, "tags": tags,
                               "lat": lat, "lon": lon,
                               "pbf_timestamp": timestamp, "pbf_source": path.name}
                        continue
                    if isinstance(obj, osmium.osm.Way):
                        kind = "way"
                        keep_way(obj)
                    elif isinstance(obj, osmium.osm.Relation):
                        kind = "relation"
                        keep_relation(obj)
                        database.execute("INSERT OR IGNORE INTO need_relations VALUES (?, 0)", (obj.id,))
                    else:
                        continue
                    database.execute("INSERT INTO candidates(kind,id,tags) VALUES (?, ?, ?)", (kind, obj.id, json.dumps(tags, ensure_ascii=False)))
            database.commit()

            count = database.execute("SELECT count(*) FROM candidates").fetchone()[0]
            print(f"PBF: {streamed_nodes} Nodes direkt ausgegeben; {count} Way-/Relations-Kandidaten, lokale Referenzauflösung startet.", file=sys.stderr)

            # Breadth-first relation expansion. IDs are passed directly from
            # SQLite into the C++ filter, without a second Python set of IDs.
            for depth in range(MAX_RELATION_DEPTH + 1):
                missing = "SELECT n.id FROM need_relations n LEFT JOIN relations r ON n.id=r.id WHERE n.depth=? AND r.id IS NULL"
                count = database.execute("SELECT count(*) FROM (" + missing + ")", (depth,)).fetchone()[0]
                if count:
                    print(f"PBF: {count} Relations-Referenzen auf Ebene {depth} werden aufgelöst.", file=sys.stderr)
                    ids = (row[0] for row in database.execute(missing, (depth,)))
                    processor = _pbf_objects(path, osmium.osm.RELATION, (osmium.filter.IdFilter(ids),))
                    for obj in processor:
                        keep_relation(obj)
                with closing(database.execute("SELECT r.members FROM need_relations n JOIN relations r ON n.id=r.id WHERE n.depth=?", (depth,))) as rows:
                    # Use a separate read cursor; inserts into the needed-ID tables
                    # never grow this depth's result with a greater child depth.
                    for (encoded,) in rows:
                        for kind, ref in json.loads(encoded):
                            if kind == "n":
                                database.execute("INSERT OR IGNORE INTO need_nodes(id) VALUES (?)", (ref,))
                            elif kind == "w":
                                database.execute("INSERT OR IGNORE INTO need_ways VALUES (?)", (ref,))
                            elif kind == "r" and depth < MAX_RELATION_DEPTH:
                                database.execute("INSERT INTO need_relations VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET depth=MIN(depth,excluded.depth)", (ref, depth + 1))
                database.commit()

            missing = "SELECT n.id FROM need_ways n LEFT JOIN ways w ON n.id=w.id WHERE w.id IS NULL"
            count = database.execute("SELECT count(*) FROM (" + missing + ")").fetchone()[0]
            if count:
                print(f"PBF: {count} Way-Referenzen werden aufgelöst.", file=sys.stderr)
                ids = (row[0] for row in database.execute(missing))
                processor = _pbf_objects(path, osmium.osm.WAY, (osmium.filter.IdFilter(ids),))
                for obj in processor:
                    keep_way(obj)
                database.commit()

            missing = "SELECT id FROM need_nodes WHERE lon IS NULL OR lat IS NULL"
            count = database.execute("SELECT count(*) FROM (" + missing + ")").fetchone()[0]
            if count:
                print(f"PBF: {count} benötigte Node-Koordinaten werden selektiv gelesen.", file=sys.stderr)
                ids = (row[0] for row in database.execute(missing))
                processor = _pbf_objects(path, osmium.osm.NODE, (osmium.filter.IdFilter(ids),))
                for obj in processor:
                    if obj.location.valid() and _valid_point(obj.location.lon, obj.location.lat):
                        database.execute("UPDATE need_nodes SET lon=?, lat=? WHERE id=?", (obj.location.lon, obj.location.lat, obj.id))
                database.commit()

            def geometry(kind, object_id, stack=()):
                if kind == "r" and (object_id in stack or len(stack) > MAX_RELATION_DEPTH):
                    raise ValueError("zyklische oder zu tief verschachtelte Relation")
                if kind == "n":
                    point = database.execute("SELECT lon,lat FROM need_nodes WHERE id=?", (object_id,)).fetchone()
                    if point is None or point[0] is None or point[1] is None:
                        raise ValueError(f"Node-Referenz {object_id} fehlt oder hat keine Koordinaten")
                    return (point[0], point[1], point[0], point[1]), 0
                cached = database.execute("SELECT west,south,east,north,height FROM bounds WHERE kind=? AND id=?", (kind, object_id)).fetchone()
                if cached is not None:
                    if kind == "r" and len(stack) + cached[4] > MAX_RELATION_DEPTH:
                        raise ValueError("zu tief verschachtelte Relation")
                    return cached[:4], cached[4]
                height = 0
                if kind == "w":
                    row = database.execute("SELECT refs FROM ways WHERE id=?", (object_id,)).fetchone()
                    if row is None:
                        raise ValueError(f"Way-Referenz {object_id} fehlt")
                    refs = json.loads(row[0])
                    if len(refs) < 2:
                        raise ValueError("Way hat weniger als zwei Node-Referenzen")
                    bounds = _merge(geometry("n", ref)[0] for ref in refs)
                elif kind == "r":
                    row = database.execute("SELECT members FROM relations WHERE id=?", (object_id,)).fetchone()
                    if row is None:
                        raise ValueError(f"Relations-Referenz {object_id} fehlt")
                    parts = []
                    for member_kind, ref in json.loads(row[0]):
                        if member_kind not in ("n", "w", "r"):
                            raise ValueError("unbekannter Relation-Mitgliedstyp")
                        member_bounds, member_height = geometry(member_kind, ref, stack + (object_id,))
                        parts.append(member_bounds)
                        if member_kind == "r":
                            height = max(height, member_height + 1)
                    bounds = _merge(parts)
                else:
                    raise ValueError("unbekannter Geometrietyp")
                database.execute("INSERT OR REPLACE INTO bounds VALUES (?, ?, ?, ?, ?, ?, ?)", (kind, object_id, *bounds, height))
                return bounds, height

            print("PBF: Displayzentren werden aus vollständigen Referenzen berechnet.", file=sys.stderr)
            kinds = {"node": "n", "way": "w", "relation": "r"}
            with closing(database.execute("SELECT kind,id,tags FROM candidates ORDER BY seq")) as rows:
                for kind, object_id, encoded_tags in rows:
                    try:
                        bounds, _ = geometry(kinds[kind], object_id)
                    except ValueError as exc:
                        report(kind, object_id, exc)
                        continue
                    lon, lat = (bounds[0] + bounds[2]) / 2, (bounds[1] + bounds[3]) / 2
                    if bbox is not None and not (west <= lon <= east and south <= lat <= north):
                        continue
                    element = {"type": kind, "id": object_id, "tags": json.loads(encoded_tags),
                               "pbf_timestamp": timestamp, "pbf_source": path.name}
                    if kind == "node":
                        element.update({"lat": lat, "lon": lon})
                    else:
                        element["center"] = {"lat": lat, "lon": lon}
                    yield element
            if diagnostics["count"] > 20:
                print(f'PBF: insgesamt {diagnostics["count"]} Kandidaten ohne vollständig auflösbare Geometrie übersprungen.', file=sys.stderr)
