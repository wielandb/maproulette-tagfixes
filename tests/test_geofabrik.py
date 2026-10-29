import contextlib
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import osmium
import requests
from shared import geofabrik


class DownloadResponse:
    def __init__(self, content=b"extract", status=200, length=None):
        self.content = content
        self.status_code = status
        self.headers = {"Content-Length": str(len(content) if length is None else length)}
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass
    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))
    def iter_content(self, chunk_size):
        yield self.content


def write_fixture(path):
    header = osmium.io.Header()
    header.set("osmosis_replication_timestamp", "2026-10-29T00:00:00Z")
    with osmium.SimpleWriter(str(path), header=header) as writer:
        writer.add_node(osmium.osm.mutable.Node(id=1, location=(13, 51)))
        writer.add_node(osmium.osm.mutable.Node(id=2, location=(15, 53)))
        writer.add_node(osmium.osm.mutable.Node(id=3, location=(12, 50), tags={"website": "https://node.example/", "amenity": "restaurant", "name": "Vollständige Tags"}))
        writer.add_way(osmium.osm.mutable.Way(id=10, nodes=[1, 2]))
        writer.add_way(osmium.osm.mutable.Way(id=11, nodes=[1, 999], tags={"website": "https://broken.example/"}))
        writer.add_way(osmium.osm.mutable.Way(id=12, nodes=[1], tags={"website": "https://short.example/"}))
        writer.add_way(osmium.osm.mutable.Way(id=13, nodes=[1, 2], tags={"website": "https://way.example/"}))
        writer.add_relation(osmium.osm.mutable.Relation(id=20, members=[("w", 10, "outer"), ("n", 3, "label")], tags={"website": "https://relation.example/"}))
        writer.add_relation(osmium.osm.mutable.Relation(id=21, members=[("r", 20, ""), ("n", 2, "")], tags={"website": "https://nested.example/"}))
        writer.add_relation(osmium.osm.mutable.Relation(id=30, members=[("r", 31, "")], tags={"website": "https://cycle.example/"}))
        writer.add_relation(osmium.osm.mutable.Relation(id=31, members=[("r", 30, "")]))
        writer.add_relation(osmium.osm.mutable.Relation(id=40, members=[("w", 9999, "outer")], tags={"website": "https://missing.example/"}))


class GeofabrikTests(unittest.TestCase):
    def test_local_centers_resolve_untagged_references_and_nested_relations(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.osm.pbf"
            write_fixture(path)
            diagnostics = io.StringIO()
            with contextlib.redirect_stderr(diagnostics), patch("requests.get", side_effect=AssertionError("PBF scan must remain offline")), patch("requests.post", side_effect=AssertionError("PBF scan must remain offline")):
                elements = list(geofabrik.iter_pbf_elements(path, tag_keys=("website",)))
            indexed = {(item["type"], item["id"]): item for item in elements}
            self.assertEqual(set(indexed), {("node", 3), ("way", 13), ("relation", 20), ("relation", 21)})
            self.assertEqual(indexed[("node", 3)]["tags"]["amenity"], "restaurant")
            self.assertEqual(indexed[("node", 3)]["lon"], 12)
            self.assertEqual(indexed[("way", 13)]["center"], {"lat": 52, "lon": 14})
            self.assertEqual(indexed[("relation", 20)]["center"], {"lat": 51.5, "lon": 13.5})
            self.assertEqual(indexed[("relation", 21)]["center"], {"lat": 51.5, "lon": 13.5})
            self.assertEqual(indexed[("node", 3)]["pbf_timestamp"], "2026-10-29T00:00:00Z")
            self.assertIn("way/11", diagnostics.getvalue())
            self.assertIn("way/12", diagnostics.getvalue())
            self.assertIn("relation/30", diagnostics.getvalue())
            self.assertIn("relation/40", diagnostics.getvalue())

    def test_bbox_filters_calculated_center_and_predicate_gets_all_tags(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.osm.pbf"
            write_fixture(path)
            with contextlib.redirect_stderr(io.StringIO()):
                selected = list(geofabrik.iter_pbf_elements(path, tag_keys=("website",), bbox=(51.9, 13.9, 52.1, 14.1)))
                predicate_selected = list(geofabrik.iter_pbf_elements(path, tag_keys=("website",), predicate=lambda tags: tags.get("amenity") == "restaurant"))
            self.assertEqual([(item["type"], item["id"]) for item in selected], [("way", 13)])
            self.assertEqual([(item["type"], item["id"]) for item in predicate_selected], [("node", 3)])

    def test_reference_depth_limit_is_diagnosed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "deep.osm.pbf"
            with osmium.SimpleWriter(str(path)) as writer:
                writer.add_node(osmium.osm.mutable.Node(id=1, location=(13, 51)))
                for relation_id in range(1, 11):
                    members = [("r", relation_id + 1, "")] if relation_id < 10 else [("n", 1, "")]
                    writer.add_relation(osmium.osm.mutable.Relation(id=relation_id, members=members, tags={"website": "https://deep.example/"} if relation_id == 1 else {}))
            diagnostics = io.StringIO()
            with contextlib.redirect_stderr(diagnostics):
                self.assertEqual(list(geofabrik.iter_pbf_elements(path, tag_keys=("website",))), [])
            self.assertIn("tief", diagnostics.getvalue())

    def test_broken_header_does_not_leave_a_windows_file_handle(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "broken.osm.pbf"
            path.write_bytes(b"not an OSM PBF")
            source = geofabrik.iter_pbf_elements(path, tag_keys=("website",))
            try:
                list(source)
            except RuntimeError:
                source.close()
                # Deliberately unlink while the exception traceback is alive.
                path.unlink()
            else:
                self.fail("Broken PBF header was accepted")
            self.assertFalse(path.exists())

    def test_early_close_finalizes_candidate_cursor_before_scratch_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "many.osm.pbf"
            with osmium.SimpleWriter(str(path)) as writer:
                writer.add_node(osmium.osm.mutable.Node(id=1, location=(13, 52)))
                writer.add_node(osmium.osm.mutable.Node(id=2, location=(15, 54)))
                for object_id in range(1, 101):
                    writer.add_way(osmium.osm.mutable.Way(id=object_id, nodes=[1, 2], tags={"website": "https://example.org/"}))
            original_temporary_directory = tempfile.TemporaryDirectory
            scratch_paths = []
            def scratch_directory(*args, **kwargs):
                temporary = original_temporary_directory(*args, **kwargs)
                scratch_paths.append(Path(temporary.name))
                return temporary
            with patch.object(geofabrik.tempfile, "TemporaryDirectory", side_effect=scratch_directory), contextlib.redirect_stderr(io.StringIO()):
                source = geofabrik.iter_pbf_elements(path, tag_keys=("website",))
                first = next(source)
                self.assertEqual((first["type"], first["id"]), ("way", 1))
                self.assertTrue(scratch_paths[0].exists())
                source.close()
            self.assertTrue(scratch_paths)
            self.assertTrue(all(not scratch.exists() for scratch in scratch_paths))
            # No reference reader remains live after closing the outer iterator.
            path.unlink()
            self.assertFalse(path.exists())

    def test_nodes_stream_before_remaining_candidates_are_processed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "streaming.osm.pbf"
            with osmium.SimpleWriter(str(path)) as writer:
                for object_id in range(1, 101):
                    writer.add_node(osmium.osm.mutable.Node(id=object_id, location=(13, 52), tags={"website": "https://example.org/"}))
            calls = []
            def predicate(tags):
                calls.append(tags)
                return True
            with contextlib.redirect_stderr(io.StringIO()):
                source = geofabrik.iter_pbf_elements(path, tag_keys=("website",), predicate=predicate)
                first = next(source)
                self.assertEqual((first["type"], first["id"]), ("node", 1))
                self.assertEqual(len(calls), 1)
                source.close()
            path.unlink()
            self.assertFalse(path.exists())

    def test_invalid_bbox_is_rejected_before_pbf_access(self):
        with self.assertRaises(ValueError):
            list(geofabrik.iter_pbf_elements("missing.osm.pbf", tag_keys=("website",), bbox=(53, 13, 51, 14)))

    def test_download_24_hour_cache_deletes_expired_file_before_refresh(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "germany-latest.osm.pbf"
            path.write_bytes(b"old")
            os.utime(path, (100, 100))
            calls = []
            def get(*args, **kwargs):
                calls.append(args)
                return DownloadResponse(b"new")
            self.assertEqual(geofabrik.download_germany(directory, now=lambda: 101, get=get), path)
            self.assertEqual(calls, [])
            geofabrik.download_germany(directory, now=lambda: 100 + geofabrik.MAX_AGE, get=get)
            self.assertEqual(path.read_bytes(), b"new")
            os.utime(path, (100, 100))
            with self.assertRaises(requests.HTTPError):
                geofabrik.download_germany(directory, now=lambda: 100 + geofabrik.MAX_AGE, get=lambda *a, **kw: DownloadResponse(status=503))
            self.assertFalse(path.exists())
            self.assertFalse(path.with_suffix(".pbf.part").exists())

    def test_truncated_download_is_never_published(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "germany-latest.osm.pbf"
            with self.assertRaises(RuntimeError):
                geofabrik.download_germany(directory, get=lambda *a, **kw: DownloadResponse(b"short", length=100))
            self.assertFalse(path.exists())
            self.assertFalse(path.with_suffix(".pbf.part").exists())


if __name__ == "__main__":
    unittest.main()
