#!/usr/bin/env -S python3 -I
"""Builds data/advisories.json: the known security advisories of what MyLocal can tell the
version of, with their whole text, for the app to compare on the Mac.

Where each comes from, by how much it can be trusted to be complete (measured against
Node.js's own list: Bitnami matched it, NVD had one advisory in ten on recent versions):

  covered   OSV's data where it has been enough: no match can read as "no known advisories"
  partial   NVD and the rest of OSV's data: a match is real, no match says nothing

A product goes in a covered table only once it has been checked against its own list of
advisories, or belongs with those that have.

The file is only ever shown. A run that would change much more than a normal day stops, and
the last good file stays published.

  ./advisories.py            fetch, check against data/advisories.json, write it
  ./advisories.py --force    the same, past the check on how much changed (for a person)
"""

import argparse
import datetime
import gzip
import io
import json
import pathlib
import re
import sys
import urllib.request
import zipfile

OUT = pathlib.Path(__file__).resolve().parent / "data" / "advisories.json"
SUPPORT = OUT.parent / "support.json"
SCHEMA = 1

OSV = "https://osv-vulnerabilities.storage.googleapis.com/{}/all.zip"
NVD = "https://nvd.nist.gov/feeds/json/cve/2.0/nvdcve-2.0-{}.json.gz"
KEV = "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"
EOL = "https://endoflife.date/api/v1/products/full/"
NVD_FIRST_YEAR = 2002

# Bitnami's package names, by the product names of the support data. `java` is its own key:
# OpenJDK's advisories apply to the JDKs built from it, and the app maps them all to it.
BITNAMI = {
    "apache": "apache-http-server",
    "cassandra": "apache-cassandra",
    "clickhouse": "clickhouse",
    "consul": "consul",
    "dotnet": "dotnet",
    "elasticsearch": "elasticsearch",
    "envoy": "envoy",
    "etcd": "etcd",
    "grafana": "grafana",
    "haproxy": "haproxy",
    "java": "java",
    "kafka": "apache-kafka",
    "keycloak": "keycloak",
    "mariadb": "mariadb",
    "memcached": "memcached",
    "mongodb": "mongodb",
    "nginx": "nginx",
    "node": "nodejs",
    "php": "php",
    "postgresql": "postgresql",
    "python": "python",
    "rabbitmq": "rabbitmq",
    "redis": "redis",
    "ruby": "ruby",
    "tomcat": "tomcat",
    "valkey": "valkey",
    "wildfly": "wildfly",
}

# The frameworks the app tells apart in a jar (core `FRAMEWORKS`), by the artifacts that hold
# their advisories. `group:*` is every artifact of a group: Spring's are numbered as the whole
# is, so an advisory about any of them goes by the version the app reads from another, and a
# module added later needs nothing here. Only for a group numbered that way: Spring Cloud's
# 2025.1 and Spring Data's own numbers are in groups of their own, and stay out. The
# authorization server joined Spring Security in 7.0; its own 1.x ranges reach no version of
# Spring Security anyone runs.
MAVEN = {
    "org.springframework.boot:*": "spring-boot",
    "org.springframework:*": "spring-framework",
    "org.springframework.security:*": "spring-security",
    "org.apache.tomcat.embed:tomcat-embed-core": "tomcat",
    "org.apache.tomcat:tomcat": "tomcat",
    "org.apache.tomcat:tomcat-catalina": "tomcat",
    "org.apache.tomcat:tomcat-coyote": "tomcat",
    "org.eclipse.jetty:jetty-server": "eclipse-jetty",
    "org.eclipse.jetty:jetty-http": "eclipse-jetty",
    "io.netty:netty-common": "netty",
    "io.netty:netty-handler": "netty",
    "io.netty:netty-codec-http": "netty",
    "io.netty:netty-codec-http2": "netty",
    "io.undertow:undertow-core": "undertow",
    "io.micronaut:micronaut-core": "micronaut",
    "io.micronaut:micronaut-http": "micronaut",
    "io.quarkus:quarkus-core": "quarkus-framework",
    "org.hibernate.orm:hibernate-core": "hibernate-orm",
    "org.hibernate:hibernate-core": "hibernate-orm",
    "org.apache.logging.log4j:log4j-core": "log4j",
}

# Go's own toolchain and standard library, what `go 1.27.2` in a binary means.
GO = {"stdlib": "go", "toolchain": "go"}

# npm's servers whose own lists were compared on 2026-10-31: all of vite's 23 and Next.js's 72
# are in OSV. A value is `ecosystem:name`, what the app looks up for a package, and turns into
# the product when the support data knows one (`resolved`).
NPM = {"vite": "npm:vite", "next": "npm:next"}

# What else these sources know, for the partial view. Compared the same way, astro's and
# nuxt's lists had advisories OSV does not, so nothing here can read as complete. Only what
# runs as a server: adding every package would not fit, and a project's dependencies are what
# `pnpm audit` is for. Left out: MinIO's Go module, whose date-numbered releases do not compare
# with the 0.0.0 ranges it has.
BITNAMI_ALSO = {
    "airflow": "apache-airflow",
    "discourse": "discourse",
    "django": "django",
    "drupal": "drupal",
    "gitea": "golang:code.gitea.io/gitea",
    "gitlab": "gitlab",
    "jenkins": "jenkins",
    "joomla": "joomla",
    "kibana": "kibana",
    "magento": "magento",
    "mattermost": "mattermost",
    "mediawiki": "mediawiki",
    "moodle": "moodle",
    "phpmyadmin": "phpmyadmin",
    "prometheus": "prometheus",
    "rails": "rails",
    "solr": "solr",
    "vault": "hashicorp-vault",
    "wordpress": "wordpress",
    "zookeeper": "zookeeper",
}
GO_ALSO = {
    "code.gitea.io/gitea": "golang:code.gitea.io/gitea",
    "github.com/argoproj/argo-cd": "argo-cd",
    "github.com/argoproj/argo-cd/v2": "argo-cd",
    "github.com/caddyserver/caddy/v2": "caddy",
    "github.com/cilium/cilium": "cilium",
    "github.com/containerd/containerd": "containerd",
    "github.com/docker/docker": "docker-engine",
    "github.com/grafana/grafana": "grafana",
    "github.com/hashicorp/consul": "consul",
    "github.com/hashicorp/nomad": "nomad",
    "github.com/hashicorp/vault": "hashicorp-vault",
    "github.com/kyverno/kyverno": "kyverno",
    "github.com/nats-io/nats-server/v2": "golang:github.com/nats-io/nats-server/v2",
    "github.com/ollama/ollama": "golang:github.com/ollama/ollama",
    "github.com/openbao/openbao": "openbao",
    "github.com/prometheus/prometheus": "prometheus",
    "github.com/rancher/rancher": "rancher",
    "github.com/traefik/traefik": "traefik",
    "github.com/traefik/traefik/v2": "traefik",
    "github.com/traefik/traefik/v3": "traefik",
    "k8s.io/kubernetes": "kubernetes",
}
NPM_ALSO = {name: f"npm:{name}" for name in (
    "@strapi/strapi",
    "astro",
    "directus",
    "electron",
    "flowise",
    "gatsby",
    "n8n",
    "nocodb",
    "nuxt",
    "parse-server",
    "pm2",
    "serve",
    "storybook",
    "verdaccio",
    "webpack-dev-server",
    "wrangler",
)}
# As the app reads them from `*.dist-info` folders, which have `_` for `-`.
PYPI = {name: "pypi:" + name.replace("-", "_") for name in (
    "ansible",
    "apache-airflow",
    "celery",
    "daphne",
    "django",
    "fastapi",
    "flask",
    "gradio",
    "gunicorn",
    "jupyter-server",
    "jupyterlab",
    "litellm",
    "mkdocs",
    "mlflow",
    "notebook",
    "open-webui",
    "sanic",
    "streamlit",
    "tornado",
    "uvicorn",
    "wagtail",
    "waitress",
)}
# Rails has its advisories in the gems it is made of, all numbered as it is.
RUBYGEMS = {
    "actionmailer": "gem:rails",
    "actionpack": "gem:rails",
    "actionview": "gem:rails",
    "activerecord": "gem:rails",
    "activestorage": "gem:rails",
    "activesupport": "gem:rails",
    "jekyll": "gem:jekyll",
    "passenger": "gem:passenger",
    "puma": "gem:puma",
    "rails": "gem:rails",
    "railties": "gem:rails",
    "sidekiq": "gem:sidekiq",
}
PACKAGIST = {
    "craftcms/cms": "craft-cms",
    "drupal/core": "drupal",
    "laravel/framework": "laravel",
    "mautic/core": "mautic",
    "moodle/moodle": "moodle",
    "phpmyadmin/phpmyadmin": "phpmyadmin",
    "shopware/core": "shopware",
    "statamic/cms": "statamic",
    "symfony/symfony": "symfony",
    "typo3/cms-core": "typo3",
}

# OSV's name for each set of data, what it is called in the file, and its tables: covered,
# then partial.
OSV_DATA = (
    ("Bitnami", "bitnami", BITNAMI, BITNAMI_ALSO),
    ("Maven", "ghsa", MAVEN, {}),
    ("Go", "go", GO, GO_ALSO),
    ("npm", "ghsa", NPM, NPM_ALSO),
    ("PyPI", "pypi", {}, PYPI),
    ("RubyGems", "ghsa", {}, RUBYGEMS),
    ("Packagist", "ghsa", {}, PACKAGIST),
)

# What a package's data has wrongly, by (product, advisory). Measured: nginx 1.31.8 matched
# this one, which is about NGINX Unit.
WRONG = {("nginx", "CVE-2025-1695")}

# Products of the support data worth NVD's partial view: servers, not desktop software.
NVD_CATEGORIES = {"server-app", "database", "lang", "framework"}
# JDKs go by `java` above, with OpenJDK's advisories.
NVD_NOT = {
    "amazon-corretto",
    "azul-zulu",
    "bellsoft-liberica",
    "eclipse-temurin",
    "graalvm-ce",
    "ibm-semeru-runtime",
    "mandrel",
    "microsoft-build-of-openjdk",
    "openjdk-builds-from-oracle",
    "oracle-graalvm",
    "oracle-jdk",
    "redhat-build-of-openjdk",
    "sapmachine",
}

SEVERITIES = {"low", "medium", "high", "critical"}
# GitHub's word for medium.
SEVERITY_NAMES = {"moderate": "medium"}
TEXT_LIMIT = 20_000
TITLE_LIMIT = 300
# npm's data is 220 MB, nearly all of it reports of malicious packages.
FETCH_LIMIT = 512 << 20
FILE_LIMIT = 32 << 20
FEWEST = 1_000
MAX_LOST = 0.05

CVE = re.compile(r"CVE-\d{4}-\d{4,}")
ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
VERSION = re.compile(r"\d[A-Za-z0-9._+-]{0,63}")
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
AT = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")


class Refused(Exception):
    """The file would not be good to publish."""


def clean_text(text, limit=TEXT_LIMIT):
    """Text as it will be shown: as plain text, without what could steer a terminal."""
    if not isinstance(text, str):
        return ""
    kept = "".join(c for c in text if c in "\n\t" or (c.isprintable() and not 0x202A <= ord(c) <= 0x202E and not 0x2066 <= ord(c) <= 0x2069))
    return kept.strip()[:limit]


def severity_of(value):
    value = value.lower() if isinstance(value, str) else None
    value = SEVERITY_NAMES.get(value, value)
    return value if value in SEVERITIES else None


def product_in(table, package):
    """The product of a package in a table: by its name, or by its group (`group:*`)."""
    if not isinstance(package, str):
        return None
    return table.get(package) or table.get(f"{package.split(':')[0]}:*")


def resolved(table, scoped):
    """`table` with each `ecosystem:name` the support data has a product for as that product:
    the key the app will look for. The support data can gain one any day."""
    return {name: scoped.get(value, value) for name, value in table.items()}


def ranges_of_osv(affected):
    """OSV's events as ranges: `i` from (inclusive), `f` fixed in, `l` last affected. Only those
    that place a version: as with NVD, a start and no end says nothing about any one version,
    and it is mostly a program that does not release as a Go module, or a source that stopped
    looking (Grafana's from 2018, GitLab's from 2025, both long fixed). `0.0.0-` is a commit."""
    ranges = []
    for r in affected.get("ranges") or []:
        if r.get("type") not in ("SEMVER", "ECOSYSTEM"):
            continue
        current = None
        for event in r.get("events") or []:
            if "introduced" in event:
                if current is not None:
                    ranges.append(current)
                current = {"i": str(event["introduced"])}
            elif current is not None and "fixed" in event:
                current["f"] = str(event["fixed"])
                ranges.append(current)
                current = None
            elif current is not None and "last_affected" in event:
                current["l"] = str(event["last_affected"])
                ranges.append(current)
                current = None
        if current is not None:
            ranges.append(current)
    return [
        r for r in ranges
        if ("f" in r or "l" in r) and all(VERSION.fullmatch(v) and not v.startswith("0.0.0-") for v in r.values())
    ]


def ranges_of_nvd(match):
    """A CPE match as a range, `a` being from past (exclusive). None for "every version", which
    says nothing about any one of them."""
    version = match["criteria"].split(":")[5]
    if version not in ("*", "-"):
        return {"i": version, "l": version} if VERSION.fullmatch(version) else None
    keys = {"versionStartIncluding": "i", "versionStartExcluding": "a", "versionEndExcluding": "f", "versionEndIncluding": "l"}
    found = {key: match[name] for name, key in keys.items() if match.get(name)}
    if "f" not in found and "l" not in found:
        return None
    if not all(VERSION.fullmatch(v) for v in found.values()):
        return None
    return found


class Merged:
    """Advisories by their CVE (or own id): one source's product joins another's."""

    def __init__(self):
        self.items = {}
        self.names = {}

    def key_of(self, advisory_id, aliases):
        """Its CVE, or the name a record of the same advisory went by: an advisory without a
        CVE can have a record from GitHub and another from Go or PyPI, naming each other."""
        names = [a for a in [advisory_id, *aliases] if isinstance(a, str)]
        cve = next((a for a in names if CVE.fullmatch(a)), None)
        seen = next((self.names[a] for a in names if a in self.names), None)
        key = cve or seen or advisory_id
        if seen and seen != key and not CVE.fullmatch(seen) and key not in self.items:
            self.items[key] = {**self.items.pop(seen), "id": key}
            self.names = {a: key if k == seen else k for a, k in self.names.items()}
        self.names.update(dict.fromkeys(names, key))
        return key

    def add(self, advisory_id, aliases, product, ranges, severity, title, text, published, source):
        if (product, advisory_id) in WRONG or not ranges or not ID.fullmatch(advisory_id):
            return
        cve = self.key_of(advisory_id, aliases)
        if (product, cve) in WRONG:
            return
        item = self.items.setdefault(cve, {"id": cve, "products": {}, "sources": set()})
        for r in ranges:
            if r not in item["products"].setdefault(product, []):
                item["products"][product].append(r)
        item["sources"].add(source)
        if severity and "severity" not in item:
            item["severity"] = severity
        if title and "title" not in item:
            item["title"] = clean_text(title, TITLE_LIMIT)
        if text and len(text) > len(item.get("text", "")):
            item["text"] = clean_text(text)
        if published and DATE.fullmatch(published[:10]) and "published" not in item:
            item["published"] = published[:10]


def osv_records(name):
    with zipfile.ZipFile(io.BytesIO(fetch(OSV.format(name)))) as z:
        for member in z.infolist():
            if member.filename.startswith("MAL-"):
                continue
            if member.filename.endswith(".json") and member.file_size < 8 << 20:
                yield json.loads(z.read(member))


def add_osv(merged, name, table, source):
    for record in osv_records(name):
        # Bitnami's own Helm charts are under the names of what they install, with their numbers.
        if record.get("withdrawn") or "helm chart" in str(record.get("details")).lower():
            continue
        for affected in record.get("affected") or []:
            product = product_in(table, (affected.get("package") or {}).get("name"))
            if product:
                add_one(merged, record, affected, product, source)


def add_one(merged, record, affected, product, source):
    specific = record.get("database_specific") or {}
    merged.add(
        record.get("id", ""),
        record.get("aliases") or [],
        product,
        ranges_of_osv(affected),
        severity_of(specific.get("severity")),
        record.get("summary"),
        record.get("details"),
        record.get("published"),
        source,
    )


def nvd_severity(metrics):
    for key in ("cvssMetricV40", "cvssMetricV31", "cvssMetricV30", "cvssMetricV2"):
        for metric in metrics.get(key) or []:
            found = severity_of((metric.get("cvssData") or {}).get("baseSeverity") or metric.get("baseSeverity"))
            if found:
                return found
    return None


def add_nvd(merged, cpes, year_to):
    """NVD's advisories of `cpes`, and severities for those that came without one (Go's). Where
    a source above has this advisory for a product its ranges stand: they come from the package,
    NVD's from a product name. Where none has, NVD's are added even to a covered product, whose
    sources can be missing old versions: 49 of Quarkus's, 75 of Keycloak's."""
    for year in range(NVD_FIRST_YEAR, year_to + 1):
        feed = json.loads(gzip.decompress(fetch(NVD.format(year))))
        for wrapped in feed["vulnerabilities"]:
            cve = wrapped["cve"]
            if cve.get("vulnStatus") == "Rejected" or not CVE.fullmatch(cve.get("id", "")):
                continue
            severity = nvd_severity(cve.get("metrics") or {})
            known = merged.items.get(cve["id"])
            placed = set(known["products"]) if known is not None else set()
            if known is not None and severity and "severity" not in known:
                known["severity"] = severity
            text = next((d["value"] for d in cve.get("descriptions") or [] if d.get("lang") == "en"), "")
            for configuration in cve.get("configurations") or []:
                for node in configuration.get("nodes") or []:
                    for match in node.get("cpeMatch") or []:
                        if not match.get("vulnerable"):
                            continue
                        parts = match["criteria"].split(":")
                        product = cpes.get((parts[3], parts[4]))
                        if not product or product in placed:
                            continue
                        found = ranges_of_nvd(match)
                        if found:
                            merged.add(cve["id"], [], product, [found], severity, None, text, cve.get("published"), "nvd")


def cpes_of(products):
    found = {}
    for product in products:
        if product.get("category") not in NVD_CATEGORIES or product["name"] in NVD_NOT:
            continue
        for identifier in product.get("identifiers") or []:
            if identifier.get("type") != "cpe":
                continue
            parts = identifier["id"].replace("cpe:2.3:", "").replace("cpe:/", "").split(":")
            if len(parts) >= 3 and parts[0] == "a":
                found[(parts[1], parts[2])] = product["name"]
    return found


def finish(merged, exploited, today, covered):
    """A covered product with no advisory at all is not covered: its source has lost it, or
    never had it, and no match would read as none known."""
    advisories = []
    for cve in sorted(merged.items):
        item = merged.items[cve]
        out = {"id": cve}
        for key in ("severity", "title", "text", "published"):
            if key in item:
                out[key] = item[key]
        if cve in exploited:
            out["exploited"] = True
        out["sources"] = sorted(item["sources"])
        out["products"] = {p: item["products"][p] for p in sorted(item["products"])}
        advisories.append(out)
    products = {p for a in advisories for p in a["products"]}
    return {
        "schema": SCHEMA,
        "as_of": today,
        "sources": "OSV (Bitnami vulndb, GitHub Advisory Database, Go, PyPI), NVD, CISA KEV",
        "products": {p: ("covered" if p in covered and p in products else "partial") for p in sorted(products | covered)},
        "advisories": advisories,
    }


def stamp(new, old, now):
    """When the data last changed. Kept while it stays as it was, so that a run that found nothing
    new makes the same file and publishes nothing."""
    same = old is not None and {k: v for k, v in old.items() if k != "at"} == new
    new["at"] = old["at"] if same and "at" in old else now


def check(data):
    if data.get("schema") != SCHEMA or not DATE.fullmatch(data.get("as_of", "")):
        raise Refused("schema or date")
    if "at" in data and not AT.fullmatch(data["at"]):
        raise Refused(f"time {data['at']!r}")
    if len(data["advisories"]) < FEWEST:
        raise Refused(f"only {len(data['advisories'])} advisories")
    for advisory in data["advisories"]:
        if not ID.fullmatch(advisory["id"]) or advisory.get("severity", "low") not in SEVERITIES:
            raise Refused(f"advisory {advisory['id']!r}")
        for product, ranges in advisory["products"].items():
            if product not in data["products"] or not ranges:
                raise Refused(f"{advisory['id']}: {product}")
            for found in ranges:
                if not set(found) <= {"i", "a", "f", "l"} or not all(VERSION.fullmatch(v) for v in found.values()):
                    raise Refused(f"{advisory['id']}: range {found}")


def refuse_large_changes(old, new):
    lost = {a["id"] for a in old["advisories"]} - {a["id"] for a in new["advisories"]}
    if len(lost) > len(old["advisories"]) * MAX_LOST:
        raise Refused(f"{len(lost)} advisories gone")
    gone = [p for p, kind in old["products"].items() if kind == "covered" and new["products"].get(p) != "covered"]
    if gone:
        raise Refused(f"no longer covered: {', '.join(gone)}")


def text_of(data):
    """One advisory a line, so that a day's change reads as a short diff in git."""
    compact = lambda value: json.dumps(value, separators=(",", ":"), ensure_ascii=False)
    head = {k: data[k] for k in ("schema", "as_of", "at", "sources", "products") if k in data}
    lines = ",\n".join(compact(a) for a in data["advisories"])
    return f'{compact(head)[:-1]},\n"advisories":[\n{lines}\n]}}\n'


def fetch(url):
    request = urllib.request.Request(url, headers={"User-Agent": "mylocal-data"})
    with urllib.request.urlopen(request, timeout=180) as response:
        body = response.read(FETCH_LIMIT + 1)
    if len(body) > FETCH_LIMIT:
        raise Refused(f"{url} is too large")
    return body


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="publish however much changed")
    args = parser.parse_args()
    now = datetime.datetime.now(datetime.timezone.utc)
    today = now.date().isoformat()
    try:
        merged = Merged()
        scoped = json.loads(SUPPORT.read_text(encoding="utf-8"))["scoped"]
        covered = set()
        for name, source, complete, also in OSV_DATA:
            complete = resolved(complete, scoped)
            covered.update(complete.values())
            add_osv(merged, name, {**resolved(also, scoped), **complete}, source)
        products = json.loads(fetch(EOL))["result"]
        add_nvd(merged, cpes_of(products), now.year)
        exploited = {v["cveID"] for v in json.loads(fetch(KEV))["vulnerabilities"]}
        new = finish(merged, exploited, today, covered)
        old = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else None
        stamp(new, old, now.strftime("%Y-%m-%dT%H:%M:%SZ"))
        check(new)
        if old is not None and not args.force:
            if new["as_of"] < old["as_of"]:
                raise Refused("older than the last file")
            refuse_large_changes(old, new)
        text = text_of(new)
        if len(text.encode()) > FILE_LIMIT:
            raise Refused(f"the file is too large: {len(text.encode()) >> 20} MB")
    except Refused as refused:
        print(f"refused: {refused}", file=sys.stderr)
        return 1
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(text, encoding="utf-8")
    kinds = list(new["products"].values())
    print(
        f"{len(new['advisories'])} advisories, {kinds.count('covered')} products covered, "
        f"{kinds.count('partial')} partial, {len(text.encode()) // 1024} KB",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
