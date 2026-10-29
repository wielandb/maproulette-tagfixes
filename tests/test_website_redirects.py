import importlib.util
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch

import requests
from shared import challenge_builder as mrcb

ROOT = Path(__file__).resolve().parents[1]
DIRECTORY = ROOT / "challenges" / "website_redirects"
sys.path.insert(0, str(DIRECTORY))
import http_checks as http
SPEC = importlib.util.spec_from_file_location("website_redirect_generator", DIRECTORY / "generate.py")
generator = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = generator
SPEC.loader.exec_module(generator)


class Response:
    encoding = "utf-8"
    def __init__(self, status=200, location=None, content=b"<title>Testladen Berlin</title>", headers=None):
        self.status_code = status
        self.headers = dict(headers or {})
        if location is not None:
            self.headers["Location"] = location
        self.content = content
        self.closed = False
    def iter_content(self, chunk_size):
        for start in range(0, len(self.content), chunk_size):
            yield self.content[start:start + chunk_size]
    def close(self):
        self.closed = True
    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))
    def __enter__(self):
        return self
    def __exit__(self, *args):
        self.close()


class NoWait:
    def __init__(self):
        self.delays = []
    def wait(self, host):
        return True
    def postpone(self, host, seconds):
        self.delays.append((host, seconds))


class HTTPTests(unittest.TestCase):
    def check(self, source, responses):
        calls = []
        queue = iter(responses)
        def get(url, **kwargs):
            calls.append((url, kwargs))
            response = next(queue)
            if isinstance(response, Exception):
                raise response
            return response
        checker = http.RedirectChecker(get=get, limiter=NoWait(), host_check=lambda host: None, clock=lambda: 100)
        return checker.check(source), calls, checker

    def test_permanent_chain_includes_relative_location_and_both_statuses(self):
        responses = [Response(301, "/neu"), Response(308, "https://neu.example/standort"), Response()]
        result, calls, _ = self.check("http://alt.example/alt", responses)
        self.assertTrue(result.eligible)
        self.assertEqual(result.target, "https://neu.example/standort")
        self.assertEqual([hop["status"] for hop in result.hops], [301, 308])
        self.assertEqual(result.title, "Testladen Berlin")
        self.assertTrue(all(response.closed for response in responses))
        self.assertFalse(calls[0][1]["allow_redirects"])
        self.assertEqual(calls[0][1]["timeout"], (10, 20))

    def test_fragment_inheritance_explicit_clear_and_query_preservation(self):
        result, calls, _ = self.check("http://alt.example/p?q=1#ort", [Response(301, "https://neu.example/neuer-pfad?filiale=2"), Response()])
        self.assertEqual(result.target, "https://neu.example/neuer-pfad?filiale=2#ort")
        self.assertEqual(calls[-1][0], "https://neu.example/neuer-pfad?filiale=2")
        self.assertEqual(http.resolve_location("https://a.example/p#alt", "/neu#"), "https://a.example/neu")
        self.assertEqual(http.resolve_location("https://a.example/p#alt", "/neu#anders"), "https://a.example/neu#anders")

    def test_all_cosmetic_redirects_are_retained(self):
        for before, after in (("http://a.example/", "https://a.example/"),
                              ("https://a.example/", "https://www.a.example/"),
                              ("https://a.example", "https://a.example/")):
            with self.subTest(before=before):
                result, _, _ = self.check(before, [Response(301, after), Response()])
                self.assertTrue(result.eligible)
                self.assertEqual(result.target, after)

    def test_temporary_and_mixed_chains_never_produce_edits(self):
        for status in (302, 303, 307, 403, 404, 429, 500, 503):
            with self.subTest(status=status):
                result, _, _ = self.check("http://a.example/", [Response(301, "/neu"), Response(status, "https://b.example/")])
                self.assertFalse(result.eligible)

    def test_loop_and_missing_location_are_skipped(self):
        for responses, reason in (([Response(301, "/" )], "loop"),
                                  ([Response(301)], "invalid_redirect")):
            with self.subTest(reason=reason):
                result, _, _ = self.check("https://a.example/", responses)
                self.assertEqual(result.reason, reason)
                self.assertFalse(result.eligible)

    def test_https_to_http_permanent_redirect_is_included(self):
        result, _, _ = self.check("https://a.example/", [Response(301, "http://a.example/neu"), Response()])
        self.assertTrue(result.eligible)
        self.assertEqual(result.target, "http://a.example/neu")

    def test_ten_hops_allowed_eleventh_redirect_rejected(self):
        redirects = [Response(301, f"/{index}") for index in range(1, 11)]
        result, calls, _ = self.check("https://a.example/", redirects + [Response()])
        self.assertTrue(result.eligible)
        self.assertEqual(len(calls), 11)
        result, calls, _ = self.check("https://a.example/", redirects + [Response(301, "/11")])
        self.assertEqual(result.reason, "too_many_redirects")
        self.assertEqual(len(calls), 11)

    def test_transport_failure_marks_global_outage(self):
        result, _, checker = self.check("https://a.example/", [requests.ConnectionError("DNS unavailable")])
        self.assertEqual(result.reason, "transport_error")
        with self.assertRaisesRegex(RuntimeError, "Kein Website-Abruf"):
            checker.ensure_network_worked()

    def test_only_blocked_sites_are_an_inconclusive_run(self):
        result, _, checker = self.check("https://a.example/", [Response(403)])
        self.assertFalse(result.eligible)
        with self.assertRaisesRegex(RuntimeError, "eindeutiges Ergebnis"):
            checker.ensure_network_worked()

    def test_invalid_urls_never_reach_http(self):
        for url in ("example.org", "file:///tmp/local", "https://user:secret@a.example/", "https://a.example:bad/", "https://a.example/ https://b.example/", "https://a.example/;https://b.example/"):
            with self.subTest(url=url):
                result, calls, _ = self.check(url, [])
                self.assertEqual(result.reason, "invalid_url")
                self.assertEqual(calls, [])

    def test_public_host_validation_rejects_private_and_mixed_dns(self):
        def resolver(host, port, **kwargs):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0))]
        with self.assertRaises(ValueError):
            http.public_host("a.example", resolver)
        with self.assertRaises(ValueError):
            http.public_host("localhost", resolver)

    def test_rate_limiter_and_retry_after(self):
        now = [0.0]
        sleeps = []
        def sleep(seconds):
            sleeps.append(seconds)
            now[0] += seconds
        limiter = http.HostLimiter(clock=lambda: now[0], sleep=sleep)
        self.assertTrue(limiter.wait("a.example"))
        self.assertTrue(limiter.wait("a.example"))
        self.assertEqual(sleeps, [1.0])
        self.assertTrue(limiter.wait("b.example"))
        limiter.postpone("a.example", 120)
        self.assertFalse(limiter.wait("a.example"))
        self.assertEqual(http.retry_after_seconds("120", 0), 120)
        self.assertEqual(http.retry_after_seconds("Thu, 01 Jan 1970 00:02:00 GMT", 0), 120)
        self.assertEqual(http.retry_after_seconds("invalid", 0), 0)

    def test_retry_after_from_another_worker_is_rechecked_after_sleep(self):
        now = [0.0]
        def sleep(seconds):
            now[0] += seconds
            limiter.postpone("a.example", 120)
        limiter = http.HostLimiter(clock=lambda: now[0], sleep=sleep)
        self.assertTrue(limiter.wait("a.example"))
        self.assertFalse(limiter.wait("a.example"))
        self.assertEqual(now[0], 1)

    def test_retry_after_on_redirect_applies_to_destination_host(self):
        result, _, checker = self.check("https://a.example/", [Response(301, "https://b.example/", headers={"Retry-After": "10"}), Response()])
        self.assertTrue(result.eligible)
        self.assertIn(("b.example", 10), checker.limiter.delays)


class CacheTests(unittest.TestCase):
    def test_expiration_and_ambiguous_errors_are_not_reused(self):
        with tempfile.TemporaryDirectory() as directory:
            now = [100.0]
            cache = http.ResultCache(Path(directory) / "results.sqlite3", clock=lambda: now[0])
            try:
                result = http.RedirectResult("https://a.example/", 100, target="https://b.example/", hops=[{}], reason="permanent")
                cache.put(result)
                self.assertEqual(cache.get(result.source), result)
                now[0] = 100 + http.MAX_AGE
                self.assertIsNone(cache.get(result.source))
                error = http.RedirectResult("https://error.example/", now[0], reason="transport_error")
                cache.put(error)
                self.assertIsNone(cache.get(error.source))
            finally:
                cache.close()


class FakeCache:
    def __init__(self):
        self.results = {}
    def get(self, url):
        return self.results.get(url)
    def put(self, result):
        self.results[result.source] = result


class FakeChecker:
    def __init__(self):
        self.calls = []
    def check(self, url):
        self.calls.append(url)
        return http.RedirectResult(url, 100, target=url.replace("http:", "https:"),
            hops=[{"url": url, "status": 301, "target": url.replace("http:", "https:")}], reason="permanent")
    def ensure_network_worked(self):
        pass


class FakeOverpass:
    def __init__(self, elements):
        self.elements = elements
        self.calls = []
    def getElementsFromQuery(self, query):
        self.calls.append(query)
        return self.elements


class GeneratorTests(unittest.TestCase):
    def element(self, osm_type="node", osm_id=1):
        item = {"type": osm_type, "id": osm_id, "tags": {"website": "http://a.example/", "contact:website": "http://a.example/", "name": "Laden", "addr:city": "Berlin"}}
        item.update({"lat": 52, "lon": 13} if osm_type == "node" else {"center": {"lat": 52, "lon": 13}})
        return item

    def test_all_osm_types_combine_both_keys_and_deduplicate_http(self):
        elements = [self.element(osm_type, index) for index, osm_type in enumerate(("node", "way", "relation"), 1)]
        checker = FakeChecker()
        overpass = FakeOverpass(elements)
        challenge = generator.generate([generator.candidate(item) for item in elements], overpass, FakeCache(), checker)
        self.assertEqual(checker.calls, ["http://a.example/"])
        self.assertEqual(len(overpass.calls), 1)
        self.assertIn("relation(id:3)", overpass.calls[0])
        self.assertEqual(len(challenge.tasks), 3)
        for task in challenge.tasks:
            operations = task.cooperativeWork.to_dict()["operations"][0]["data"]["operations"]
            self.assertEqual(operations[0]["data"], {"website": "https://a.example/", "contact:website": "https://a.example/"})
            self.assertEqual(operations[1]["data"], [])
            self.assertIn("Berlin", task.mainFeature.properties["task_instruction"])

    def test_current_tag_changes_and_missing_geometry_are_respected(self):
        original = self.element()
        result = FakeChecker().check("http://a.example/")
        current = self.element()
        current["tags"]["website"] = "https://other.example/"
        task = generator.task_for(current, generator.candidate(original), {result.source: result})
        self.assertEqual(task.cooperativeWork.tagsToSet, {"contact:website": "https://a.example/"})
        del current["tags"]["contact:website"]
        self.assertIsNone(generator.task_for(current, generator.candidate(original), {result.source: result}))
        current = self.element()
        del current["lat"]
        self.assertIsNone(generator.task_for(current, generator.candidate(original), {result.source: result}))

    def test_invalid_coordinates_are_never_serialized(self):
        for lon, lat in ((float("nan"), 52), (13, float("inf")), (181, 52), (13, 91), (True, 52)):
            with self.subTest(lon=lon, lat=lat):
                current = self.element()
                current["lon"], current["lat"] = lon, lat
                original = generator.candidate(current)
                result = FakeChecker().check("http://a.example/")
                self.assertIsNone(generator.task_for(current, original, {result.source: result}))

    def test_domain_and_lost_location_path_are_marked(self):
        original = self.element()
        original["tags"] = {"website": "https://alt.example/filiale?x=1#karte"}
        result = http.RedirectResult(original["tags"]["website"], 100, target="https://neu.example/", hops=[{"url": original["tags"]["website"], "status": 301, "target": "https://neu.example/"}], reason="permanent")
        task = generator.task_for(original, generator.candidate(original), {result.source: result})
        instruction = task.mainFeature.properties["task_instruction"]
        self.assertIn("Hostname/Domain geändert", instruction)
        self.assertIn("Unterseitenpfad entfällt", instruction)
        self.assertIn("?x=1#karte", instruction)

    def test_http_downgrade_is_flagged_for_manual_review(self):
        element = self.element()
        element["tags"] = {"website": "https://a.example/alt"}
        result = http.RedirectResult("https://a.example/alt", 100, target="http://a.example/neu", hops=[{"url": "https://a.example/alt", "status": 301, "target": "http://a.example/neu"}], reason="permanent")
        task = generator.task_for(element, generator.candidate(element), {result.source: result})
        self.assertEqual(task.cooperativeWork.tagsToSet, {"website": "http://a.example/neu"})
        self.assertIn("Ziel verwendet HTTP statt HTTPS", task.mainFeature.properties["task_instruction"])

    def test_task_and_byte_limits_stop_before_next_batch(self):
        for limits in ({"max_tasks": 1}, {"max_output_bytes": 1}):
            with self.subTest(limits=limits):
                checker = FakeChecker()
                elements = [self.element()]
                def candidates():
                    yield generator.candidate(elements[0])
                    raise AssertionError("Must stop before reading another candidate")
                with patch.object(generator, "BATCH_SIZE", 1):
                    challenge = generator.generate(candidates(), FakeOverpass(elements), FakeCache(), checker, challenge=mrcb.Challenge(**limits))
                self.assertTrue(challenge.limit_reached)
                self.assertEqual(len(checker.calls), 1)

    def test_prefilled_limit_avoids_source_and_http(self):
        challenge = mrcb.Challenge(max_tasks=1)
        challenge.addTask(mrcb.Task(mrcb.GeoFeature([13, 52])))
        checker = FakeChecker()
        generator.generate(iter(()), FakeOverpass([]), FakeCache(), checker, challenge=challenge)
        self.assertEqual(checker.calls, [])

    def test_main_preserves_previous_output_on_source_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "existing.json"
            output.write_text("previous valid tasks", encoding="utf-8")
            with patch.object(generator, "bbox_candidates", side_effect=RuntimeError("Overpass unavailable")):
                with self.assertRaises(RuntimeError):
                    generator.main(["--bbox", "52", "13", "53", "14", "--cache-dir", directory, "--output", str(output)])
            self.assertEqual(output.read_text(encoding="utf-8"), "previous valid tasks")

    def test_pbf_candidate_scan_needs_no_geometry_or_network(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.osm"
            path.write_text('<osm version="0.6"><node id="1" lat="52" lon="13"><tag k="website" v="https://a.example/"/></node><way id="2"><nd ref="1"/><tag k="contact:website" v="https://b.example/"/></way><relation id="3"><member type="way" ref="2" role="outer"/><tag k="website" v="https://c.example/"/></relation></osm>', encoding="utf-8")
            with patch("requests.get", side_effect=AssertionError("No network during tag scan")):
                candidates = list(generator.pbf_candidates(path))
            self.assertEqual([(item["type"], item["id"]) for item in candidates], [("node", 1), ("way", 2), ("relation", 3)])

    def test_download_cache_expiration_and_failed_refresh_preserves_extract(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "germany-latest.osm.pbf"
            path.write_bytes(b"old extract")
            import os
            os.utime(path, (100, 100))
            calls = []
            def get(*args, **kwargs):
                calls.append(args)
                return Response(content=b"new extract")
            self.assertEqual(generator.download_germany(directory, now=lambda: 101, get=get), path)
            self.assertEqual(calls, [])
            generator.download_germany(directory, now=lambda: 100 + http.MAX_AGE, get=get)
            self.assertEqual(path.read_bytes(), b"new extract")
            os.utime(path, (100, 100))
            def failure(*args, **kwargs):
                return Response(503)
            with self.assertRaises(requests.HTTPError):
                generator.download_germany(directory, now=lambda: 100 + http.MAX_AGE, get=failure)
            self.assertEqual(path.read_bytes(), b"new extract")
            self.assertFalse(path.with_suffix(".pbf.part").exists())


if __name__ == "__main__":
    unittest.main()
