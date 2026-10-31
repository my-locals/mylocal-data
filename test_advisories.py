#!/usr/bin/env -S python3 -I
"""Tests of advisories.py, on made-up records: no network."""

import copy
import importlib.util
import json
import pathlib
import unittest

spec = importlib.util.spec_from_file_location("advisories", pathlib.Path(__file__).parent / "advisories.py")
adv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adv)


def record(rid="GHSA-aaaa-bbbb-cccc", aliases=("CVE-2026-1234",), events=None, **fields):
    return {
        "id": rid,
        "aliases": list(aliases),
        "summary": "A title",
        "details": "The whole text.\nWith lines.",
        "published": "2026-01-02T03:04:05Z",
        "database_specific": {"severity": "HIGH"},
        **fields,
    }, {"ranges": [{"type": "SEMVER", "events": events or [{"introduced": "0"}, {"fixed": "1.2.3"}]}]}


class Ranges(unittest.TestCase):
    def test_events_become_ranges(self):
        _, a = record(events=[{"introduced": "0"}, {"fixed": "22.1"}, {"introduced": "23.0"}, {"last_affected": "24.0"}, {"introduced": "25.0"}])
        self.assertEqual(adv.ranges_of_osv(a), [{"i": "0", "f": "22.1"}, {"i": "23.0", "l": "24.0"}, {"i": "25.0"}])

    def test_git_ranges_say_nothing_of_versions(self):
        self.assertEqual(adv.ranges_of_osv({"ranges": [{"type": "GIT", "events": [{"introduced": "0"}]}]}), [])

    def test_hostile_versions_are_dropped(self):
        _, a = record(events=[{"introduced": "<img src=x>"}, {"fixed": "1.0"}])
        self.assertEqual(adv.ranges_of_osv(a), [])

    def test_nvd_ranges(self):
        cpe = "cpe:2.3:a:oracle:mysql:{}:*:*:*:*:*:*:*"
        self.assertEqual(adv.ranges_of_nvd({"criteria": cpe.format("8.4.1")}), {"i": "8.4.1", "l": "8.4.1"})
        self.assertEqual(
            adv.ranges_of_nvd({"criteria": cpe.format("*"), "versionStartIncluding": "8.0.0", "versionEndExcluding": "8.0.5"}),
            {"i": "8.0.0", "f": "8.0.5"},
        )
        self.assertEqual(adv.ranges_of_nvd({"criteria": cpe.format("*"), "versionEndIncluding": "8.4"}), {"l": "8.4"})
        # "Every version" and only a start say nothing about any one version.
        self.assertIsNone(adv.ranges_of_nvd({"criteria": cpe.format("*")}))
        self.assertIsNone(adv.ranges_of_nvd({"criteria": cpe.format("*"), "versionStartIncluding": "8.0"}))


class Merging(unittest.TestCase):
    def test_sources_of_one_cve_join(self):
        merged = adv.Merged()
        r, a = record()
        adv.add_one(merged, r, a, "tomcat", "ghsa")
        r2, a2 = record(rid="BIT-tomcat-2026-1234", events=[{"introduced": "9.0"}, {"fixed": "9.1"}])
        r2["details"] = "Short."
        adv.add_one(merged, r2, a2, "tomcat", "bitnami")
        self.assertEqual(list(merged.items), ["CVE-2026-1234"])
        item = merged.items["CVE-2026-1234"]
        self.assertEqual(len(item["products"]["tomcat"]), 2)
        self.assertEqual(item["sources"], {"ghsa", "bitnami"})
        # The longer text stays.
        self.assertEqual(item["text"], "The whole text.\nWith lines.")
        self.assertEqual(item["severity"], "high")

    def test_a_wrong_match_is_left_out(self):
        merged = adv.Merged()
        r, a = record(rid="BIT-nginx-2025-1695", aliases=["CVE-2025-1695"])
        adv.add_one(merged, r, a, "nginx", "bitnami")
        self.assertEqual(merged.items, {})

    def test_text_cannot_steer_a_terminal(self):
        self.assertEqual(adv.clean_text("a\x1b[31mb‮c\nd\te"), "a[31mbc\nd\te")
        self.assertEqual(len(adv.clean_text("x" * 50_000)), adv.TEXT_LIMIT)
        self.assertEqual(adv.clean_text(None), "")


def many(count=1100):
    merged = adv.Merged()
    for i in range(count):
        r, a = record(rid=f"GHSA-{i}", aliases=[f"CVE-2026-{10000 + i}"])
        adv.add_one(merged, r, a, "tomcat" if i else "mysql", "ghsa")
    return adv.finish(merged, {"CVE-2026-10001"}, "2026-10-31", {"tomcat"})


class File(unittest.TestCase):
    def test_coverage_is_said_per_product(self):
        data = many()
        self.assertEqual(data["products"], {"mysql": "partial", "tomcat": "covered"})
        self.assertTrue(data["advisories"][1]["exploited"])
        self.assertNotIn("exploited", data["advisories"][0])

    def test_good_data_passes_and_bad_forms_do_not(self):
        adv.check(many())
        for change in (
            lambda d: d.update(schema=2),
            lambda d: d.update(as_of="soon"),
            lambda d: d["advisories"][0].update(severity="<b>"),
            lambda d: d["advisories"][0].update(id="../evil"),
            lambda d: d["advisories"][0]["products"].update({"no-such": [{"f": "1"}]}),
            lambda d: d["advisories"][0]["products"]["mysql"][0].update(f="<x>"),
            lambda d: d["advisories"][0]["products"]["mysql"][0].update(z="1"),
            lambda d: d["advisories"].clear(),
        ):
            data = many()
            change(data)
            with self.assertRaises(adv.Refused):
                adv.check(data)

    def test_large_losses_stop_a_publish(self):
        old = many()
        new = copy.deepcopy(old)
        del new["advisories"][1:5]
        adv.refuse_large_changes(old, new)
        del new["advisories"][1:200]
        with self.assertRaises(adv.Refused):
            adv.refuse_large_changes(old, new)
        new = copy.deepcopy(old)
        del new["products"]["tomcat"]
        with self.assertRaises(adv.Refused):
            adv.refuse_large_changes(old, new)

    def test_it_reads_back_the_same_with_a_line_per_advisory(self):
        data = many(3)
        text = adv.text_of(data)
        self.assertEqual(json.loads(text), data)
        self.assertEqual(text.count('\n{"id"'), 3)


if __name__ == "__main__":
    unittest.main()
