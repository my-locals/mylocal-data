#!/usr/bin/env -S python3 -I
"""Tests of advisories.py, on made-up records: no network."""

import copy
import gzip
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
        _, a = record(events=[{"introduced": "0"}, {"fixed": "22.1"}, {"introduced": "23.0"}, {"last_affected": "24.0"}])
        self.assertEqual(adv.ranges_of_osv(a), [{"i": "0", "f": "22.1"}, {"i": "23.0", "l": "24.0"}])

    def test_git_ranges_say_nothing_of_versions(self):
        self.assertEqual(adv.ranges_of_osv({"ranges": [{"type": "GIT", "events": [{"introduced": "0"}]}]}), [])

    def test_hostile_versions_are_dropped(self):
        _, a = record(events=[{"introduced": "<img src=x>"}, {"fixed": "1.0"}])
        self.assertEqual(adv.ranges_of_osv(a), [])

    def test_ranges_must_place_a_version(self):
        for events in ([{"introduced": "0"}], [{"introduced": "11.0.0"}], [{"introduced": "0"}, {"fixed": "0.0.0-20230101"}]):
            _, a = record(events=events)
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
    def test_drupals_records_are_named_for_it(self):
        def osv_with(*records):
            merged = adv.Merged()
            shown = []
            for r, a in records:
                shown.append({**r, "affected": [{**a, "package": {"name": "drupal/core"}}]})
            real = adv.osv_records
            adv.osv_records = lambda name: shown
            try:
                adv.add_osv(merged, "Packagist", {"drupal/core": "drupal"}, "ghsa")
            finally:
                adv.osv_records = real
            return merged.items

        items = osv_with(
            record(rid="DRUPAL-CORE-2026-013", aliases=()),
            record(rid="GHSA-aaaa-bbbb-cccc"),
            record(rid="DRUPAL-CORE-2026-001"),
        )
        self.assertEqual(items["DRUPAL-CORE-2026-013"]["sources"], {"drupal"})
        # One advisory from both keeps both.
        self.assertEqual(items["CVE-2026-1234"]["sources"], {"ghsa", "drupal"})

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

    def test_records_naming_each_other_are_one_advisory(self):
        merged = adv.Merged()
        for rid, aliases in (("GHSA-aaaa", ["GO-2026-1"]), ("GO-2026-1", ["GHSA-aaaa"])):
            r, a = record(rid=rid, aliases=aliases)
            adv.add_one(merged, r, a, "traefik", "go")
        self.assertEqual(list(merged.items), ["GHSA-aaaa"])

    def test_a_cve_learned_later_names_the_advisory(self):
        merged = adv.Merged()
        r, a = record(rid="GHSA-aaaa", aliases=[])
        adv.add_one(merged, r, a, "traefik", "go")
        r, a = record(rid="GO-2026-1", aliases=["GHSA-aaaa", "CVE-2026-9999"])
        adv.add_one(merged, r, a, "traefik", "go")
        self.assertEqual(list(merged.items), ["CVE-2026-9999"])
        self.assertEqual(merged.items["CVE-2026-9999"]["id"], "CVE-2026-9999")
        r, a = record(rid="GHSA-aaaa", aliases=[])
        adv.add_one(merged, r, a, "caddy", "ghsa")
        self.assertEqual(sorted(merged.items["CVE-2026-9999"]["products"]), ["caddy", "traefik"])

    def test_githubs_moderate_is_medium(self):
        self.assertEqual(adv.severity_of("MODERATE"), "medium")
        self.assertEqual(adv.severity_of("HIGH"), "high")
        self.assertIsNone(adv.severity_of("UNKNOWN"))

    def test_a_spring_module_goes_by_its_group(self):
        find = lambda package: adv.product_in(adv.MAVEN, package)
        self.assertEqual(find("org.springframework:spring-expression"), "spring-framework")
        self.assertEqual(find("org.springframework:spring-not-yet-written"), "spring-framework")
        self.assertEqual(find("org.springframework.boot:spring-boot-loader"), "spring-boot")
        self.assertEqual(find("org.springframework.security:spring-security-crypto"), "spring-security")
        # Numbered their own way.
        self.assertIsNone(find("org.springframework.cloud:spring-cloud-gateway"))
        self.assertIsNone(find("org.springframework.data:spring-data-jpa"))
        self.assertIsNone(find("org.springframework.security.oauth:spring-security-oauth2"))
        # The rest still go by name.
        self.assertEqual(find("io.netty:netty-common"), "netty")
        self.assertIsNone(find("io.netty:netty-transport"))
        self.assertIsNone(find(None))

    def test_a_package_goes_by_its_product_when_there_is_one(self):
        table = {"next": "npm:next", "vite": "npm:vite", "airflow": "apache-airflow"}
        self.assertEqual(
            adv.resolved(table, {"npm:next": "nextjs"}),
            {"next": "nextjs", "vite": "npm:vite", "airflow": "apache-airflow"},
        )

    def test_nvd_adds_what_the_sources_lack_and_leaves_what_they_have(self):
        merged = adv.Merged()
        r, a = record()
        adv.add_one(merged, r, a, "tomcat", "ghsa")
        cpe = "cpe:2.3:a:apache:tomcat:*:*:*:*:*:*:*:*"
        match = {"vulnerable": True, "criteria": cpe, "versionEndExcluding": "99.0"}
        feed = {"vulnerabilities": [
            {"cve": {"id": i, "configurations": [{"nodes": [{"cpeMatch": [match]}]}]}}
            for i in ("CVE-2026-1234", "CVE-2026-5678")
        ]}
        fetch, adv.fetch = adv.fetch, lambda url: gzip.compress(json.dumps(feed).encode())
        self.addCleanup(setattr, adv, "fetch", fetch)
        adv.NVD_FIRST_YEAR, first = 2026, adv.NVD_FIRST_YEAR
        self.addCleanup(setattr, adv, "NVD_FIRST_YEAR", first)
        adv.add_nvd(merged, {("apache", "tomcat"): "tomcat"}, 2026)
        self.assertEqual(merged.items["CVE-2026-1234"]["products"]["tomcat"], [{"i": "0", "f": "1.2.3"}])
        self.assertEqual(merged.items["CVE-2026-1234"]["sources"], {"ghsa"})
        self.assertEqual(merged.items["CVE-2026-5678"]["products"]["tomcat"], [{"f": "99.0"}])

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

    def test_covered_without_a_single_advisory_is_not_covered(self):
        merged = adv.Merged()
        r, a = record()
        adv.add_one(merged, r, a, "tomcat", "ghsa")
        data = adv.finish(merged, set(), "2026-10-31", {"tomcat", "minio"})
        self.assertEqual(data["products"], {"minio": "partial", "tomcat": "covered"})

    def test_a_product_its_source_lost_stops_a_publish(self):
        old = many()
        merged = adv.Merged()
        r, a = record()
        adv.add_one(merged, r, a, "mysql", "ghsa")
        for i in range(1100):
            r, a = record(rid=f"GHSA-{i}", aliases=[f"CVE-2026-{10000 + i}"])
            adv.add_one(merged, r, a, "mysql", "ghsa")
        new = adv.finish(merged, set(), "2026-10-31", {"tomcat"})
        with self.assertRaisesRegex(adv.Refused, "no longer covered: tomcat"):
            adv.refuse_large_changes(old, new)

    def test_the_time_stays_while_the_data_does_and_moves_when_it_changes(self):
        old = many()
        old["at"] = "2026-10-31T00:00:00Z"
        same = copy.deepcopy(old)
        del same["at"]
        adv.stamp(same, old, "2026-10-31T06:00:00Z")
        self.assertEqual(same, old, "a run that found nothing new makes the same file")
        changed = copy.deepcopy(old)
        del changed["at"]
        changed["as_of"] = "2026-11-01"
        adv.stamp(changed, old, "2026-11-01T00:00:00Z")
        self.assertEqual(changed["at"], "2026-11-01T00:00:00Z")
        without = copy.deepcopy(old)
        del without["at"], old["at"]
        adv.stamp(without, old, "2026-10-31T06:00:00Z")
        self.assertEqual(without["at"], "2026-10-31T06:00:00Z", "a file from before it had one")
        adv.check(without)
        self.assertIn('"at":"2026-10-31T06:00:00Z"', adv.text_of(without).splitlines()[0])

    def test_good_data_passes_and_bad_forms_do_not(self):
        adv.check(many())
        for change in (
            lambda d: d.update(schema=2),
            lambda d: d.update(as_of="soon"),
            lambda d: d.update(at="this morning"),
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
