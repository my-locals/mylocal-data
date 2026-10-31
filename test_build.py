#!/usr/bin/env -S python3 -I
"""Tests of build.py, on made-up products: no network."""

import copy
import importlib.util
import json
import pathlib
import unittest

spec = importlib.util.spec_from_file_location("build", pathlib.Path(__file__).parent / "build.py")
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


def product(name, releases=None, **fields):
    return {
        "name": name,
        "category": "server-app",
        "releases": releases
        or [{"name": "1.0", "eolFrom": "2030-01-01", "isEol": False, "latest": {"name": "1.0.5"}}],
        **fields,
    }


def many(count=120):
    return [product(f"p{i}") for i in range(count)]


class Normalize(unittest.TestCase):
    def data(self, *products):
        return build.normalize(list(products), "2026-10-31")

    def test_a_release_line(self):
        d = self.data(product("redis"))
        self.assertEqual(d["products"]["redis"], [{"c": "1.0", "e": "2030-01-01", "l": "1.0.5"}])
        self.assertEqual(d["schema"], build.SCHEMA)

    def test_what_cannot_listen_stays_out(self):
        d = self.data({**product("ios"), "category": "device"}, product("nginx"))
        self.assertEqual(list(d["products"]), ["nginx"])

    def test_a_package_name_means_nothing_outside_its_ecosystem(self):
        d = self.data(product("nextjs", identifiers=[{"type": "purl", "id": "pkg:npm/next"}]))
        self.assertEqual(d["scoped"]["npm:next"], "nextjs")
        self.assertNotIn("next", d["names"])

    def test_docker_official_images_lose_their_library(self):
        d = self.data(
            product("postgresql", identifiers=[{"type": "purl", "id": "pkg:docker/library/postgres"}]),
            product("valkey", identifiers=[{"type": "purl", "id": "pkg:docker/valkey/valkey"}]),
        )
        self.assertEqual(d["scoped"]["docker:postgres"], "postgresql")
        self.assertEqual(d["scoped"]["docker:valkey/valkey"], "valkey")

    def test_python_packages_go_by_their_dist_info_folders(self):
        d = self.data(product("apache-airflow", identifiers=[{"type": "purl", "id": "pkg:pypi/apache-airflow"}]))
        self.assertEqual(d["scoped"]["pypi:apache_airflow"], "apache-airflow")

    def test_numbering_of_its_own_is_not_compared(self):
        rel = [{"name": "27", "isEol": False, "latest": {"name": "27.28.101"}}]
        self.assertNotIn("l", self.data(product("azul-zulu", rel))["products"]["azul-zulu"][0])

    def test_java_8_numbers(self):
        self.assertEqual(build.latest_of("8u504-b01"), "8.0.504")
        self.assertEqual(build.latest_of("27.0.1.0.2+1"), "27.0.1.0.2")
        self.assertEqual(build.latest_of("v1.2.3"), "1.2.3")
        self.assertIsNone(build.latest_of("latest"))

    def test_hostile_values_do_not_reach_the_file(self):
        rel = [
            {"name": "1.0", "eolFrom": "soon<script>", "isEol": False, "latest": {"name": "<img src=x>"}},
            {"name": "../../evil", "isEol": False},
        ]
        d = self.data(
            product("ok", rel, aliases=["bad name\n", "fine"]),
            product("bad\x1bname"),
        )
        self.assertEqual(d["products"], {"ok": [{"c": "1.0"}]})
        self.assertEqual(sorted(d["names"]), ["fine", "ok"])
        # Non-strings where strings belong.
        rel = [{"name": 5}, {"name": "2.0", "eolFrom": True, "isEol": True}]
        self.assertEqual(self.data(product("mixed", rel))["products"]["mixed"], [{"c": "2.0", "x": True}])


class Check(unittest.TestCase):
    def good(self):
        return build.normalize(many(), "2026-10-31")

    def test_good_data_passes(self):
        build.check(self.good())

    def test_bad_forms_are_refused(self):
        for change in (
            lambda d: d.update(schema=2),
            lambda d: d.update(as_of="yesterday"),
            lambda d: d["products"]["p0"][0].update(e="soon"),
            lambda d: d["products"]["p0"][0].update(l="1.x"),
            lambda d: d["products"]["p0"][0].update(c="one"),
            lambda d: d["names"].update({"x": "no-such-product"}),
            lambda d: d["names"].update({"bad name": "p0"}),
            lambda d: d["products"].clear(),
        ):
            d = self.good()
            change(d)
            with self.assertRaises((build.Refused, KeyError)):
                build.check(d)


class LargeChanges(unittest.TestCase):
    def setUp(self):
        self.old = build.normalize(many(), "2026-10-30")
        self.new = copy.deepcopy(self.old)

    def test_an_ordinary_day_passes(self):
        self.new["products"]["p0"][0]["l"] = "1.0.6"
        self.new["products"]["p1"][0]["e"] = "2030-06-01"
        del self.new["products"]["p2"]
        build.refuse_large_changes(self.old, self.new)

    def refused(self):
        with self.assertRaises(build.Refused):
            build.refuse_large_changes(self.old, self.new)

    def test_many_products_gone(self):
        for i in range(10):
            del self.new["products"][f"p{i}"]
        self.refused()

    def test_many_end_dates_later(self):
        for i in range(build.MAX_END_DATES_LATER + 1):
            self.new["products"][f"p{i}"][0]["e"] = "2099-01-01"
        self.refused()

    def test_end_dates_taken_away_count_as_later(self):
        for i in range(build.MAX_END_DATES_LATER + 1):
            del self.new["products"][f"p{i}"][0]["e"]
        self.refused()

    def test_many_latest_lowered(self):
        for i in range(build.MAX_LATEST_LOWERED + 1):
            self.new["products"][f"p{i}"][0]["l"] = "1.0.1"
        self.refused()

    def test_many_ended_lines_revived(self):
        for i in range(build.MAX_ENDED_UNDONE + 1):
            self.old["products"][f"p{i}"][0]["x"] = True
        self.refused()


class Text(unittest.TestCase):
    def test_it_reads_back_the_same_with_a_line_per_product(self):
        data = build.normalize(many(3) + [product("a", identifiers=[{"type": "purl", "id": "pkg:npm/a"}])], "2026-10-31")
        text = build.text_of(data)
        self.assertEqual(json.loads(text), data)
        self.assertIn('\n  "p1":[', text)


if __name__ == "__main__":
    unittest.main()
