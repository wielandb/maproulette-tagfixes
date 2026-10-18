import gzip
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import requests

from challenges.imgur404 import imgur_404_image as imgur
from challenges.imgur404 import procPercent as progress
from challenges.imgur404 import valueFinder as finder


class OverpassResponseTests(unittest.TestCase):
    FIRST_URL = "https://first.example.invalid/api/interpreter"
    SECOND_URL = "https://second.example.invalid/api/interpreter"

    def setUp(self):
        for context in (
            patch.object(finder, "_overpass_client", None),
            patch.dict(os.environ, {"OVERPASS_URLS": f"{self.FIRST_URL},{self.SECOND_URL}"}),
        ):
            context.start()
            self.addCleanup(context.stop)

    @staticmethod
    def response(payload, status=200):
        result = Mock(status_code=status, text="test response", headers={})
        result.json.return_value = payload
        return result

    @patch("shared.challenge_builder.sleep")
    @patch("shared.challenge_builder.requests.post")
    def test_runtime_remark_is_retried_before_resolving_a_center(self, post, sleep):
        failed = self.response({
            "elements": [], "remark": "runtime error: Query timed out",
        })
        successful = self.response({"elements": [{"center": {"lat": 1.2, "lon": 3.4}}]})
        post.side_effect = [failed, successful]
        handler = finder.ValueFinderHandler("i.imgur.com", "unused-matches.json")
        self.assertEqual(handler.get_center_coordinates("way", 1), finder.Center(1.2, 3.4))
        self.assertEqual(post.call_count, 2)
        sleep.assert_called_once_with(finder.OVERPASS_RETRY_DELAY)

    @patch.object(finder, "OVERPASS_RETRY_COUNT", 2)
    @patch("shared.challenge_builder.sleep")
    @patch("shared.challenge_builder.requests.post")
    def test_malformed_payloads_exhaust_retries_and_return_none(self, post, sleep):
        for payload in (
            None, [], {}, {"elements": {}}, {"elements": [None]},
            {"remark": "runtime error: Query timed out"},
        ):
            with self.subTest(payload=payload):
                post.reset_mock()
                sleep.reset_mock()
                post.return_value = self.response(payload)
                self.assertIsNone(finder.post_overpass_query("way(1);out center;"))
                self.assertEqual(post.call_count, 2)
                sleep.assert_called_once_with(finder.OVERPASS_RETRY_DELAY)

    @patch.object(finder, "OVERPASS_RETRY_COUNT", 2)
    @patch("shared.challenge_builder.sleep")
    @patch("shared.challenge_builder.requests.post")
    def test_invalid_json_exhausts_retries_and_returns_none(self, post, sleep):
        post.return_value = self.response(None)
        post.return_value.json.side_effect = ValueError("invalid JSON")
        self.assertIsNone(finder.post_overpass_query("way(1);out center;"))
        self.assertEqual(post.call_count, 2)
        sleep.assert_called_once_with(finder.OVERPASS_RETRY_DELAY)

    @patch("shared.challenge_builder.sleep")
    @patch("shared.challenge_builder.requests.post")
    def test_valid_empty_result_is_returned_without_retry(self, post, sleep):
        post.return_value = self.response({"elements": []})
        self.assertEqual(finder.post_overpass_query("way(1);out center;"), {"elements": []})
        post.assert_called_once()
        sleep.assert_not_called()

    @patch.object(finder, "Overpass")
    def test_queries_share_one_client_and_keep_the_elements_wrapper(self, overpass):
        elements = [{"lat": 1.2, "lon": 3.4}]
        client = overpass.return_value
        client.getElementsFromQuery.return_value = elements
        self.assertEqual(finder.post_overpass_query("first query"), {"elements": elements})
        self.assertEqual(finder.post_overpass_query("second query"), {"elements": elements})
        overpass.assert_called_once_with(max_attempts=6, retry_delay=5)
        self.assertEqual(client.getElementsFromQuery.call_count, 2)
        client.getElementsFromQuery.assert_called_with("second query")

    @patch.object(finder, "Overpass")
    def test_shared_request_failure_returns_none(self, overpass):
        overpass.return_value.getElementsFromQuery.side_effect = ValueError("all servers unavailable")
        self.assertIsNone(finder.post_overpass_query("query"))
        overpass.return_value.getElementsFromQuery.assert_called_once_with("query")

    @patch("shared.challenge_builder.sleep")
    @patch("shared.challenge_builder.requests.post")
    def test_http_406_switches_server_and_reuses_successful_server(self, post, sleep):
        elements = [{"lat": 1.2, "lon": 3.4}]
        post.side_effect = [
            self.response(None, status=406),
            self.response({"elements": elements}),
            self.response({"elements": elements}),
        ]
        self.assertEqual(finder.post_overpass_query("first query"), {"elements": elements})
        self.assertEqual(finder.post_overpass_query("second query"), {"elements": elements})
        self.assertEqual(
            [request.args[0] for request in post.call_args_list],
            [self.FIRST_URL, self.SECOND_URL, self.SECOND_URL],
        )
        sleep.assert_called_once_with(30)
        self.assertEqual(post.call_args.kwargs["timeout"], (10, 300))
        self.assertIn("maproulette", post.call_args.kwargs["headers"]["User-Agent"])

    @patch("shared.challenge_builder.sleep")
    @patch("shared.challenge_builder.requests.post")
    def test_request_timeout_switches_server_after_retry_delay(self, post, sleep):
        post.side_effect = [requests.Timeout("read timed out"), self.response({"elements": []})]
        self.assertEqual(finder.post_overpass_query("query"), {"elements": []})
        self.assertEqual(
            [request.args[0] for request in post.call_args_list],
            [self.FIRST_URL, self.SECOND_URL],
        )
        sleep.assert_called_once_with(finder.OVERPASS_RETRY_DELAY)


class ValueFinderTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.directory = Path(temp.name)
        self.matches = self.directory / "matches.json"
        self.leafs = self.directory / "geofabrik_leafs.json"
        self.leafs.write_text("[]", encoding="utf-8")
        for name, value in {
            "SCRIPT_DIR": self.directory,
            "MATCHES_FILE": self.matches,
            "GEOFABRIK_JSON": self.leafs,
            "PROCESSED_URLS_FILE": self.directory / "processed_urls.json",
        }.items():
            context = patch.object(finder, name, value)
            context.start()
            self.addCleanup(context.stop)

    def handler(self):
        return finder.ValueFinderHandler("i.imgur.com", str(self.matches))

    def test_relation_without_center_has_no_nodes_fallback(self):
        handler = self.handler()
        with patch.object(handler, "get_center_coordinates", return_value=None):
            element = handler.create_overpass_element(
                "relation", SimpleNamespace(id=1, tags=[])
            )
        self.assertIsNone(element["lat"])
        self.assertIsNone(element["lon"])

    @patch.object(finder.random, "randint", return_value=1)
    def test_local_extract_scan_handles_missing_way_and_relation_centers(self, randint):
        extract = self.directory / "extract.osm"
        extract.write_text(
            '<osm version="0.6">'
            '<node id="1" lat="1" lon="2"><tag k="image" v="https://i.imgur.com/Ab123.png"/></node>'
            '<way id="2"><nd ref="1"/><tag k="image" v="https://i.imgur.com/Ab123.png"/></way>'
            '<relation id="3"><member type="node" ref="1" role=""/>'
            '<tag k="image" v="https://i.imgur.com/Ab123.png"/></relation>'
            '</osm>', encoding="utf-8",
        )
        handler = self.handler()
        with patch.object(handler, "get_center_coordinates", return_value=None):
            handler.apply_file(str(extract))
        elements = json.loads(self.matches.read_text(encoding="utf-8"))
        self.assertEqual([element["type"] for element in elements], ["node", "way", "relation"])
        self.assertEqual([elements[0]["lat"], elements[0]["lon"]], [1, 2])
        self.assertIsNone(elements[1]["lat"])
        self.assertIsNone(elements[2]["lat"])

    @patch.object(finder, "post_overpass_query")
    def test_relation_node_member_without_coordinates_is_resolved(self, query):
        query.side_effect = [
            {"elements": [{"members": [{"type": "node", "ref": 9}]}]},
            {"elements": [{"lat": 1.2, "lon": 3.4}]},
        ]
        center = self.handler().get_center_coordinates("relation", 7)
        self.assertEqual(center, finder.Center(1.2, 3.4))
        self.assertIn("node(9)", query.call_args.args[0])

    @patch.object(finder, "post_overpass_query")
    def test_relation_cycle_does_not_prevent_resolving_other_members(self, query):
        query.side_effect = [
            {"elements": [{"members": [
                {"type": "relation", "ref": 8},
                {"type": "node", "ref": 9},
            ]}]},
            {"elements": [{"members": [{"type": "relation", "ref": 7}]}]},
            {"elements": [{"lat": 1.2, "lon": 3.4}]},
        ]
        center = self.handler().get_center_coordinates("relation", 7)
        self.assertEqual(center, finder.Center(1.2, 3.4))
        self.assertEqual(query.call_count, 3)

    @patch.object(finder, "download_file")
    def test_find_without_matches_returns_empty_list_and_creates_file(self, download):
        self.assertEqual(finder.find_value_objects(), [])
        self.assertEqual(json.loads(self.matches.read_text(encoding="utf-8")), [])
        download.assert_not_called()

    @patch.object(finder, "ValueFinderHandler")
    @patch.object(finder, "download_file")
    def test_find_returns_scanned_matches(self, download, handler):
        self.leafs.write_text('["https://example.org/test.osm.pbf"]', encoding="utf-8")
        expected = [{"type": "node", "id": 5, "lat": 1, "lon": 2, "tags": {}}]
        download.side_effect = lambda url, filename: Path(filename).touch()
        handler.return_value.apply_file.side_effect = lambda filename: self.matches.write_text(
            json.dumps(expected), encoding="utf-8"
        )
        self.assertEqual(finder.find_value_objects("test", finder.MatchType.EXACT), expected)
        self.assertFalse((self.directory / "test.osm.pbf").exists())

    @patch.object(finder, "download_file")
    def test_resumed_scan_without_matches_has_readable_results(self, download):
        url = "https://example.org/already-processed.osm.pbf"
        self.leafs.write_text(json.dumps([url]), encoding="utf-8")
        finder.PROCESSED_URLS_FILE.write_text(json.dumps([url]), encoding="utf-8")
        finder.main()
        self.assertEqual(json.loads(self.matches.read_text(encoding="utf-8")), [])
        download.assert_not_called()

    @patch.object(finder.random, "randint", return_value=42)
    @patch.object(progress, "get_latest_created_ids", side_effect=requests.ConnectionError("offline"))
    def test_unavailable_progress_api_does_not_abort_scan(self, latest, randint):
        self.handler().display_progress("node", 1)


class ImgurGeneratorTests(unittest.TestCase):
    def test_value_finder_standalone_import_from_other_working_directory(self):
        script_directory = Path(__file__).resolve().parents[1] / "challenges" / "imgur404"
        code = (
            "import sys; "
            f"sys.path.insert(0, {str(script_directory)!r}); "
            "import valueFinder; "
            "assert valueFinder.Overpass.__module__ == 'shared.challenge_builder'; "
            "assert valueFinder._overpass_client is None"
        )
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [sys.executable, "-c", code], cwd=directory,
                capture_output=True, text=True, timeout=30,
            )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_import_from_other_working_directory(self):
        repository = Path(__file__).resolve().parents[1]
        code = (
            "import sys; "
            f"sys.path.insert(0, {str(repository)!r}); "
            "from challenges.imgur404 import imgur_404_image; "
            "assert imgur_404_image.SCRIPT_DIR.is_absolute()"
        )
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [sys.executable, "-c", code], cwd=directory,
                capture_output=True, text=True, timeout=30,
            )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_extract_id_for_supported_image_extensions_and_query_strings(self):
        for link in (
            "https://i.imgur.com/Ab123.jpg",
            "https://i.imgur.com/Ab123.jpeg",
            "https://i.imgur.com/Ab123.png?download=1#image",
            "i.imgur.com/Ab123.png",
            "https://imgur.com/Ab123",
        ):
            with self.subTest(link=link):
                self.assertEqual(imgur.extract_imgur_id_from_link(link), "Ab123")

    @patch.object(imgur.requests, "get")
    def test_check_png_image_uses_image_id_without_extension(self, get):
        get.return_value.status_code = 200
        self.assertFalse(imgur.check_imgur_404("https://i.imgur.com/Ab123.png"))
        self.assertEqual(
            get.call_args.args[0],
            "https://api.imgur.com/oembed.json?url=https://imgur.com/Ab123",
        )

    @patch.object(imgur, "get_osm_history")
    def test_history_parser_requires_no_optional_xml_parser(self, history):
        history.return_value = (
            '<osm><node id="1" version="1" user="alice">'
            '<tag k="image" v="https://i.imgur.com/Ab123.png"/>'
            '</node></osm>'
        )
        self.assertEqual(
            imgur.find_tag_setter("node", 1, "image", "https://i.imgur.com/Ab123.png"),
            ("alice", 1),
        )

    @patch.object(finder, "main")
    def test_no_matches_replaces_old_challenge_with_empty_file(self, scan):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            matches = path / "matches.json"
            matches.write_text("[]", encoding="utf-8")
            output = path / "imgur404.json"
            output.write_text("outdated tasks", encoding="utf-8")
            with patch.object(imgur, "SCRIPT_DIR", path), patch.object(finder, "MATCHES_FILE", matches):
                imgur.main()
            self.assertEqual(output.read_text(encoding="utf-8"), "")

    @patch.object(finder, "main")
    @patch.object(imgur, "check_imgur_404", return_value=True)
    @patch.object(imgur, "find_tag_setter", return_value=(None, None))
    def test_relation_without_center_is_skipped(self, setter, check, scan):
        element = {
            "type": "relation", "id": 1, "lat": None, "lon": None,
            "tags": {"image": "https://i.imgur.com/Ab123.png"},
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            matches = path / "matches.json"
            matches.write_text(json.dumps([element]), encoding="utf-8")
            with patch.object(imgur, "SCRIPT_DIR", path), patch.object(finder, "MATCHES_FILE", matches):
                imgur.main()
            self.assertEqual((path / "imgur404.json").read_text(encoding="utf-8"), "")


class ProgressCacheTests(unittest.TestCase):
    @patch.object(progress.requests, "get")
    def test_json_and_legacy_caches_are_read_without_network(self, get):
        ids = {"node": 100, "way": 20, "relation": 3}
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "latest_created_ids.json"
            with patch.object(progress, "CACHE_FILE", cache):
                for content in (json.dumps(ids), repr(ids)):
                    with self.subTest(content=content):
                        cache.write_text(content, encoding="utf-8")
                        self.assertEqual(progress.get_latest_created_ids(), ids)
        get.assert_not_called()

    @patch.object(progress.requests, "get")
    def test_replication_results_are_saved_as_json(self, get):
        state = Mock(text="sequenceNumber=123\n")
        xml = b'<osmChange>\n<create>\n<node id="100"/>\n<way id="20"/>\n<relation id="3"/>\n</create>\n</osmChange>'
        diff = Mock(status_code=200, content=gzip.compress(xml))
        get.side_effect = [state, diff]
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "latest_created_ids.json"
            with patch.object(progress, "CACHE_FILE", cache):
                ids = progress.get_latest_created_ids()
                self.assertEqual(ids, {"node": 100, "way": 20, "relation": 3})
                self.assertEqual(json.loads(cache.read_text(encoding="utf-8")), ids)


if __name__ == "__main__":
    unittest.main()
