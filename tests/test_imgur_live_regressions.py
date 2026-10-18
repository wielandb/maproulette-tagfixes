import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import requests

from challenges.imgur404 import imgur_404_image as imgur
from challenges.imgur404 import valueFinder as finder


def response(status=200, payload=None):
    result = Mock(status_code=status, headers={})
    result.json.return_value = payload
    return result


def missing_response():
    return response(403, {
        "data": {"error": "Invalid URL - forbidden"},
        "success": False, "status": 403,
    })


class ImageAvailabilityTests(unittest.TestCase):
    @patch.object(imgur.requests, "get")
    def test_only_specific_oembed_error_identifies_missing_image(self, get):
        for payload in (
            None, "forbidden", {}, {"success": False, "status": 403},
            {"success": False, "status": 403, "data": {"error": "Imgur is temporarily over capacity"}},
        ):
            with self.subTest(payload=payload):
                get.return_value = response(403, payload)
                with self.assertRaises(ValueError):
                    imgur.check_imgur_404("https://i.imgur.com/Ab123.jpg")
        get.return_value = missing_response()
        self.assertTrue(imgur.check_imgur_404("https://i.imgur.com/Ab123.jpg"))

    @patch.object(imgur.requests, "get")
    def test_thumbnail_is_checked_against_existing_original(self, get):
        get.side_effect = [missing_response(), response()]
        self.assertFalse(imgur.check_imgur_404("https://i.imgur.com/ey6sACUl.jpg"))
        self.assertIn("imgur.com/ey6sACU", get.call_args.args[0])

    @patch.object(imgur.requests, "get")
    def test_existing_id_ending_in_thumbnail_suffix_is_not_truncated(self, get):
        get.return_value = response()
        self.assertFalse(imgur.check_imgur_404("https://i.imgur.com/abcdefgl.jpg"))
        get.assert_called_once()

    @patch.object(imgur.requests, "get")
    def test_deleted_thumbnail_and_original_are_missing(self, get):
        get.side_effect = [missing_response(), missing_response()]
        self.assertTrue(imgur.check_imgur_404("https://i.imgur.com/abcdefgl.jpg"))
        self.assertEqual(get.call_count, 2)

    @patch.object(imgur.requests, "get")
    def test_same_image_across_urls_is_cached_only_within_explicit_run(self, get):
        get.return_value = response()
        cache = {}
        self.assertFalse(imgur.check_imgur_404("https://i.imgur.com/Ab123.jpg", cache))
        self.assertFalse(imgur.check_imgur_404("http://i.imgur.com/Ab123.png", cache))
        get.assert_called_once()
        self.assertFalse(imgur.check_imgur_404("https://i.imgur.com/Ab123.jpg"))
        self.assertEqual(get.call_count, 2)

    @patch.object(imgur.requests, "get")
    def test_thumbnail_original_already_checked_reuses_same_run_cache(self, get):
        get.side_effect = [response(), missing_response()]
        cache = {}
        self.assertFalse(imgur.check_imgur_404("https://i.imgur.com/ey6sACU.jpg", cache))
        self.assertFalse(imgur.check_imgur_404("https://i.imgur.com/ey6sACUl.jpg", cache))
        self.assertEqual(get.call_count, 2)

    @patch.object(imgur, "sleep")
    @patch.object(imgur.requests, "get")
    def test_transient_errors_retry_with_bounded_backoff(self, get, sleep):
        get.side_effect = [requests.Timeout("timeout"), response(503), response()]
        self.assertFalse(imgur.check_imgur_404("https://i.imgur.com/Ab123.jpg"))
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [5, 10])
        self.assertEqual(get.call_args.kwargs["timeout"], 60)

    @patch.object(imgur, "sleep")
    @patch.object(imgur.requests, "get")
    def test_rate_limit_is_not_classified_as_missing(self, get, sleep):
        get.return_value = response(429)
        with self.assertRaises(ValueError):
            imgur.check_imgur_404("https://i.imgur.com/Ab123.jpg")
        self.assertEqual(get.call_count, 3)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [30, 30])

    def test_archive_and_other_host_urls_are_not_direct_imgur_links(self):
        for value in (
            "https://web.archive.org/web/20230501052752/https://i.imgur.com/ey6sACUl.jpg",
            "https://example.com/?url=https://i.imgur.com/Ab123.jpg",
            "https://notimgur.com/Ab123.jpg", "https://example.imgur.com/Ab123.jpg",
        ):
            with self.subTest(value=value):
                self.assertEqual(imgur.extract_imgur_links_from_string(value), [])

    def test_all_direct_links_are_extracted(self):
        self.assertEqual(imgur.extract_imgur_links_from_string(
            "Photos: https://i.imgur.com/Ab123.gif; i.imgur.com/Cd456.jpeg"
        ), ["https://i.imgur.com/Ab123.gif", "https://i.imgur.com/Cd456.jpeg"])


class GeneratorCompletenessTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.matches = self.directory / "matches.json"
        self.element = {
            "type": "node", "id": 123, "lat": 1.0, "lon": 2.0,
            "tags": {"image": "https://i.imgur.com/Ab123.jpg"},
        }
        self.matches.write_text(json.dumps([self.element]), encoding="utf-8")
        for context in (
            patch.object(imgur, "SCRIPT_DIR", self.directory),
            patch.object(finder, "MATCHES_FILE", self.matches),
            patch.object(finder, "main"),
        ):
            context.start()
            self.addCleanup(context.stop)

    @patch.object(imgur.requests, "get")
    def test_uncertain_check_preserves_previous_challenge_and_reports(self, get):
        get.return_value = response(403, {"error": "access forbidden"})
        output = self.directory / "imgur404.json"
        output.write_text("previous challenge", encoding="utf-8")
        reports = self.directory / "user_reports"
        reports.mkdir()
        (reports / "previous.txt").write_text("previous report", encoding="utf-8")
        with self.assertRaises(ValueError):
            imgur.main()
        self.assertEqual(output.read_text(encoding="utf-8"), "previous challenge")
        self.assertEqual((reports / "previous.txt").read_text(encoding="utf-8"), "previous report")

    @patch.object(imgur.random, "shuffle")
    @patch.object(imgur, "find_tag_setter", return_value=(None, None))
    @patch.object(imgur, "get_current_element")
    @patch.object(imgur, "check_imgur_404", side_effect=[True, ValueError("service unavailable")])
    def test_later_outage_does_not_publish_an_earlier_partial_task(self, check, current, setter, shuffle):
        second = dict(self.element, id=124)
        self.matches.write_text(json.dumps([self.element, second]), encoding="utf-8")
        current.return_value = self.element
        output = self.directory / "imgur404.json"
        output.write_text("previous complete challenge", encoding="utf-8")
        with self.assertRaises(ValueError):
            imgur.main()
        self.assertEqual(check.call_count, 2)
        self.assertEqual(output.read_text(encoding="utf-8"), "previous complete challenge")

    @patch.object(imgur, "find_tag_setter")
    @patch.object(imgur, "get_current_element", return_value=None)
    @patch.object(imgur, "check_imgur_404", return_value=True)
    def test_deleted_osm_object_is_not_a_task(self, check, current, setter):
        imgur.main()
        self.assertEqual((self.directory / "imgur404.json").read_text(encoding="utf-8"), "")
        setter.assert_not_called()

    @patch.object(imgur, "find_tag_setter")
    @patch.object(imgur, "get_current_element")
    @patch.object(imgur, "check_imgur_404", return_value=True)
    def test_changed_osm_tag_is_not_removed(self, check, current, setter):
        current.return_value = dict(self.element, tags={"image": "https://new.example/image.jpg"})
        imgur.main()
        self.assertEqual((self.directory / "imgur404.json").read_text(encoding="utf-8"), "")
        setter.assert_not_called()

    @patch.object(imgur, "find_tag_setter", return_value=(None, None))
    @patch.object(imgur, "get_current_element")
    @patch.object(imgur, "check_imgur_404", return_value=True)
    def test_overlapping_extracts_create_only_one_task(self, check, current, setter):
        self.matches.write_text(json.dumps([self.element, self.element]), encoding="utf-8")
        current.return_value = self.element
        imgur.main()
        self.assertEqual((self.directory / "imgur404.json").read_text(encoding="utf-8").count("\x1e"), 1)
        check.assert_called_once()

    @patch.object(imgur, "get_current_element")
    @patch.object(imgur, "check_imgur_404", side_effect=[True, False])
    def test_valid_second_link_prevents_whole_tag_removal(self, check, current):
        self.element["tags"]["image"] += ";https://i.imgur.com/Cd456.jpg"
        self.matches.write_text(json.dumps([self.element]), encoding="utf-8")
        imgur.main()
        self.assertEqual((self.directory / "imgur404.json").read_text(encoding="utf-8"), "")
        self.assertEqual(check.call_count, 2)
        current.assert_not_called()

    @patch.object(imgur, "get_current_element")
    @patch.object(imgur, "check_imgur_404", return_value=True)
    def test_other_provider_or_prose_prevents_whole_tag_removal(self, check, current):
        for value in (
            "https://i.imgur.com/Ab123.jpg;https://example.org/photo.jpg",
            "Photo of the entrance: https://i.imgur.com/Ab123.jpg",
            "Recovered: https://web.archive.org/web/20230501/https://i.imgur.com/Ab123.jpg",
        ):
            with self.subTest(value=value):
                self.element["tags"]["image"] = value
                self.matches.write_text(json.dumps([self.element]), encoding="utf-8")
                imgur.main()
                self.assertEqual((self.directory / "imgur404.json").read_text(encoding="utf-8"), "")
        check.assert_not_called()
        current.assert_not_called()


class AttributionTests(unittest.TestCase):
    @patch.object(imgur, "get_osm_history")
    def test_reintroduced_tag_is_attributed_to_current_setter(self, history):
        history.return_value = (
            '<osm><node version="1" user="alice"><tag k="image" v="old"/></node>'
            '<node version="2" user="bob"/>'
            '<node version="3" user="carol"><tag k="image" v="old"/></node>'
            '<node version="4" user="dan"><tag k="image" v="old"/></node></osm>'
        )
        self.assertEqual(imgur.find_tag_setter("node", 1, "image", "old"), ("carol", 3))

    @patch.object(imgur, "get_osm_history", return_value="<html>broken")
    def test_invalid_history_is_optional(self, history):
        self.assertEqual(imgur.find_tag_setter("node", 1, "image", "old"), (None, None))

    def test_windows_report_names_are_safe_and_collision_resistant(self):
        names = [imgur._report_filename(name) for name in ("a/b", "a\\b", "CON", "NUL.txt", "x" * 300, "alice")]
        self.assertEqual(names[-1], "alice.txt")
        self.assertEqual(len(names), len(set(names)))
        for name in names:
            self.assertLessEqual(len(name), 117)
            self.assertNotRegex(name, r'[<>:"/\\|?*]')
            self.assertNotIn(name.split(".")[0].upper(), ("CON", "NUL"))

    def test_report_users_with_only_case_difference_keep_separate_files(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(imgur, "SCRIPT_DIR", Path(directory)):
                imgur.create_user_reports({"Alice": [], "alice": []})
            files = list((Path(directory) / "user_reports").iterdir())
            self.assertEqual(len(files), 2)
            self.assertEqual(len({file.name.casefold() for file in files}), 2)


class DownloadTests(unittest.TestCase):
    @patch.object(finder, "sleep")
    @patch.object(finder.requests, "get")
    def test_interrupted_download_retries_atomically(self, get, sleep):
        failed = Mock(headers={})
        failed.__enter__ = Mock(return_value=failed)
        failed.__exit__ = Mock(return_value=False)
        failed.iter_content.side_effect = requests.exceptions.ChunkedEncodingError("interrupted")
        successful = Mock(headers={"content-length": "4"})
        successful.__enter__ = Mock(return_value=successful)
        successful.__exit__ = Mock(return_value=False)
        successful.iter_content.return_value = [b"data"]
        get.side_effect = [failed, successful]
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "data.pbf"
            destination.write_bytes(b"previous")
            finder.download_file("https://example.org/data.pbf", destination)
            self.assertEqual(destination.read_bytes(), b"data")
            self.assertFalse(destination.with_name("data.pbf.part").exists())
        sleep.assert_called_once_with(5)
        self.assertEqual(get.call_args.kwargs["timeout"], (10, 120))


if __name__ == "__main__":
    unittest.main()
