#!/usr/bin/env -S python3 -I
"""Builds data/support.json from endoflife.date for MyLocal to show which versions are
still supported.

The file is only ever shown: no decision in the app reads it. So the worst a bad file can do
is say something false, and that is what the checks here are for: a run that would change
much more than a normal day does stops, and leaves the last good file published. Its links
open only when someone clicks them, and only on hosts the app itself lists.

  ./build.py            fetch, check against data/support.json, write it
  ./build.py --force    the same, past the checks on how much changed (for a person)
"""

import argparse
import datetime
import json
import pathlib
import re
import sys
import urllib.request

SOURCE = "https://endoflife.date/api/v1/products/full/"
OUT = pathlib.Path(__file__).resolve().parent / "data" / "support.json"
SCHEMA = 1

# What can listen on a port. Operating systems, devices and cloud services cannot.
CATEGORIES = {"server-app", "database", "lang", "framework", "app"}

# Package ecosystems whose names say nothing outside them: the npm package `redis` is a
# client, not the server. Looked up only as `ecosystem:name`.
SCOPED = {"npm", "pypi", "gem", "golang", "maven", "composer", "nuget", "docker"}
# Ecosystems whose names are the program's own.
PLAIN = {"generic", "brew", "apk"}

# Names Homebrew, version managers and process names use that the data does not list.
EXTRA_NAMES = {
    "node": "nodejs",
    "httpd": "apache-http-server",
    "kafka": "apache-kafka",
    "cassandra": "apache-cassandra",
    "couchdb": "apache-couchdb",
    "activemq": "apache-activemq",
    "artemis": "apache-artemis",
    "pulsar": "apache-pulsar",
    "flink": "apache-flink",
    "airflow": "apache-airflow",
    "spark": "apache-spark",
    "solr": "solr",
    "mongodb-community": "mongodb",
    "mongod": "mongodb",
    "elasticsearch-full": "elasticsearch",
    "golang": "go",
    "vault": "hashicorp-vault",
    "dotnet-sdk": "dotnet",
    "jetty": "eclipse-jetty",
    "influxd": "influxdb",
    "mongo": "mongodb",
    # The folders their downloads unpack to.
    "apache-tomcat": "tomcat",
    "neo4j-community": "neo4j",
    "neo4j-enterprise": "neo4j",
    "rabbitmq_server": "rabbitmq",
}

# Release numbers that do not follow the Java version a JDK reports: Zulu's own 27.28.101,
# GraalVM's 25.4.4. Only their end dates are used.
NO_LATEST = {"azul-zulu", "graalvm-ce", "graalvm"}

# A larger answer or file is not what these should be.
FETCH_LIMIT = 32 << 20
FILE_LIMIT = 2 << 20
FEWEST_PRODUCTS = 100

# How much one day may change: a few products and a few releases, not many of them at once.
# Past these a person looks first (--force).
MAX_PRODUCTS_LOST = 0.05
MAX_LINES_LOST = 0.05
MAX_END_DATES_LATER = 25
MAX_LATEST_LOWERED = 10
MAX_ENDED_UNDONE = 10

NUMBERS = re.compile(r"\d+(?:\.\d+)*")
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
# What a name may be. They are lookup keys, and the app must be able to trust their form.
NAME = re.compile(r"[A-Za-z0-9@][A-Za-z0-9@._+:/-]{0,127}")
# What a release's page may be. No user, port or `http`: the app goes by the exact host.
PAGE = re.compile(r"https://[A-Za-z0-9.-]{1,253}(?:[/?#][A-Za-z0-9._~/%+#?=&:;,@!$()-]{0,255})?")


class Refused(Exception):
    """The file would not be good to publish."""


def latest_of(name):
    """The numbers of a release name, or None when they would not compare with what a
    program reports: `8u504-b01` is 8.0.504, `27.0.1.0.2+1` is 27.0.1.0.2."""
    java_8 = re.fullmatch(r"(\d+)u(\d+)(?:-b\d+)?", name)
    if java_8:
        return f"{java_8[1]}.0.{java_8[2]}"
    found = NUMBERS.match(name.lstrip("vV"))
    return found[0] if found else None


def date_of(value):
    return value if isinstance(value, str) and DATE.fullmatch(value) else None


def line_of(product, release):
    """One release line, or None when its name is not the numbers a version starts with."""
    name = release.get("name")
    if not isinstance(name, str) or not NUMBERS.fullmatch(name):
        return None
    line = {"c": name}
    eol = date_of(release.get("eolFrom"))
    if eol:
        line["e"] = eol
    page = (release.get("latest") or {}).get("link")
    if isinstance(page, str) and PAGE.fullmatch(page):
        line["n"] = page
    if release.get("isEol"):
        line["x"] = True
    else:
        latest = (release.get("latest") or {}).get("name")
        if isinstance(latest, str) and product not in NO_LATEST:
            latest = latest_of(latest)
            if latest:
                line["l"] = latest
    return line


def normalize(products, today):
    names, scoped, kept = {}, {}, {}
    for product in sorted(products, key=lambda p: p["name"]):
        slug = product["name"]
        if product.get("category") not in CATEGORIES or not NAME.fullmatch(slug):
            continue
        lines = [line_of(slug, release) for release in product.get("releases", [])]
        lines = [line for line in lines if line]
        if not lines:
            continue
        kept[slug] = lines
        names[slug] = slug
        for alias in product.get("aliases") or []:
            if isinstance(alias, str) and NAME.fullmatch(alias):
                names.setdefault(alias, slug)
        for identifier in product.get("identifiers") or []:
            if identifier.get("type") != "purl":
                continue
            found = re.fullmatch(r"pkg:([a-z]+)/(?:(.+)/)?([^/@]+)(?:@.*)?", identifier.get("id", ""))
            if not found:
                continue
            ecosystem, namespace, name = found.groups()
            if ecosystem in PLAIN and NAME.fullmatch(name):
                names.setdefault(name, slug)
            elif ecosystem in SCOPED:
                if ecosystem == "docker" and namespace == "library":
                    namespace = None
                # As the app reads it from `*.dist-info` folders, which have `_` for `-`.
                if ecosystem == "pypi":
                    name = name.replace("-", "_")
                key = f"{ecosystem}:{namespace}/{name}" if namespace else f"{ecosystem}:{name}"
                if NAME.fullmatch(key):
                    scoped.setdefault(key, slug)
    for name, slug in EXTRA_NAMES.items():
        if slug in kept:
            names[name] = slug
    return {
        "schema": SCHEMA,
        "as_of": today,
        "source": "https://endoflife.date (MIT)",
        "names": dict(sorted(names.items())),
        "scoped": dict(sorted(scoped.items())),
        "products": kept,
    }


def check(data):
    """That the file has the form the app accepts."""
    if data.get("schema") != SCHEMA or not DATE.fullmatch(data.get("as_of", "")):
        raise Refused("schema or date")
    if len(data["products"]) < FEWEST_PRODUCTS:
        raise Refused(f"only {len(data['products'])} products")
    for table in (data["names"], data["scoped"]):
        for name, product in table.items():
            if not NAME.fullmatch(name) or product not in data["products"]:
                raise Refused(f"name {name!r}")
    for product, lines in data["products"].items():
        for line in lines:
            if not NUMBERS.fullmatch(line["c"]):
                raise Refused(f"{product}: release line {line['c']!r}")
            if "e" in line and not DATE.fullmatch(line["e"]):
                raise Refused(f"{product}: date {line['e']!r}")
            if "l" in line and not NUMBERS.fullmatch(line["l"]):
                raise Refused(f"{product}: latest {line['l']!r}")
            if "n" in line and not PAGE.fullmatch(line["n"]):
                raise Refused(f"{product}: page {line['n']!r}")


def numbers(version):
    return [int(part) for part in version.split(".")]


def changes(old, new):
    """What differs from the last file, in the ways that would mislead if false."""
    def lines_of(data):
        return {(p, line["c"]): line for p, lines in data["products"].items() for line in lines}

    before, after = lines_of(old), lines_of(new)
    kept = [(after[k], before[k]) for k in after.keys() & before.keys()]
    return {
        "products_lost": sorted(old["products"].keys() - new["products"].keys()),
        "lines_lost": sorted(before.keys() - after.keys()),
        "end_dates_later": [
            n for n, o in kept if "e" in o and (n.get("e", "9999-12-31") > o["e"])
        ],
        "latest_lowered": [
            n for n, o in kept if "l" in o and "l" in n and numbers(n["l"]) < numbers(o["l"])
        ],
        "ended_undone": [n for n, o in kept if o.get("x") and not n.get("x")],
    }


def refuse_large_changes(old, new):
    found = changes(old, new)
    problems = []
    if len(found["products_lost"]) > len(old["products"]) * MAX_PRODUCTS_LOST:
        problems.append(f"{len(found['products_lost'])} products gone")
    lines = sum(len(lines) for lines in old["products"].values())
    if len(found["lines_lost"]) > lines * MAX_LINES_LOST:
        problems.append(f"{len(found['lines_lost'])} release lines gone")
    if len(found["end_dates_later"]) > MAX_END_DATES_LATER:
        problems.append(f"{len(found['end_dates_later'])} end dates moved later")
    if len(found["latest_lowered"]) > MAX_LATEST_LOWERED:
        problems.append(f"{len(found['latest_lowered'])} latest versions lowered")
    if len(found["ended_undone"]) > MAX_ENDED_UNDONE:
        problems.append(f"{len(found['ended_undone'])} ended lines supported again")
    if problems:
        raise Refused("; ".join(problems))


def text_of(data):
    """One product a line, so that a day's change reads as a short diff in git."""
    head = {k: data[k] for k in ("schema", "as_of", "source")}
    compact = lambda value: json.dumps(value, separators=(",", ":"), ensure_ascii=False)
    def table(values):
        return ",\n".join(f"  {compact(k)}:{compact(v)}" for k, v in values.items())
    parts = [compact(head)[:-1]]
    parts.append(f',\n"names":{{\n{table(data["names"])}\n}}')
    parts.append(f',\n"scoped":{{\n{table(data["scoped"])}\n}}')
    parts.append(f',\n"products":{{\n{table(data["products"])}\n}}')
    return "".join(parts) + "}\n"


def fetch():
    request = urllib.request.Request(SOURCE, headers={"User-Agent": "mylocal-data"})
    with urllib.request.urlopen(request, timeout=60) as response:
        body = response.read(FETCH_LIMIT + 1)
    if len(body) > FETCH_LIMIT:
        raise Refused("the answer is too large")
    return json.loads(body)["result"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="publish however much changed")
    args = parser.parse_args()
    today = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
    try:
        new = normalize(fetch(), today)
        check(new)
        if OUT.exists() and not args.force:
            old = json.loads(OUT.read_text(encoding="utf-8"))
            if new["as_of"] < old["as_of"]:
                raise Refused("older than the last file")
            refuse_large_changes(old, new)
        text = text_of(new)
        if len(text.encode()) > FILE_LIMIT:
            raise Refused("the file is too large")
    except Refused as refused:
        print(f"refused: {refused}", file=sys.stderr)
        return 1
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(text, encoding="utf-8")
    lines = sum(len(v) for v in new["products"].values())
    print(f"{len(new['products'])} products, {lines} release lines, {len(text.encode()) // 1024} KB", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
