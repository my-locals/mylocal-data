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

# Main pages of products that do not release on GitHub, or whose links there lead elsewhere than
# their own repository. Looked at by a person, and never about one version. A product in neither
# has no page in the file, and the app opens its page on endoflife.date.
PAGES = {
    "akeneo-pim": "https://www.akeneo.com/akeneo-pim-community-edition/",
    "alibaba-dragonwell": "https://dragonwell-jdk.io/",
    "angularjs": "https://docs.angularjs.org/",
    "ansible": "https://docs.ansible.com/",
    "ant": "https://ant.apache.org/",
    "apache-activemq": "https://activemq.apache.org/",
    "apache-airflow": "https://airflow.apache.org/",
    "apache-artemis": "https://artemis.apache.org/",
    "apache-camel": "https://camel.apache.org/",
    "apache-cassandra": "https://cassandra.apache.org/",
    "apache-celeborn": "https://celeborn.apache.org/",
    "apache-couchdb": "https://couchdb.apache.org/",
    "apache-flink": "https://flink.apache.org/",
    "apache-groovy": "https://groovy-lang.org/",
    "apache-hadoop": "https://hadoop.apache.org/",
    "apache-hop": "https://hop.apache.org/",
    "apache-http-server": "https://httpd.apache.org/",
    "apache-kafka": "https://kafka.apache.org/",
    "apache-lucene": "https://lucene.apache.org/",
    "apache-maven": "https://maven.apache.org/",
    "apache-nifi": "https://nifi.apache.org/",
    "apache-pulsar": "https://pulsar.apache.org/",
    "apache-spark": "https://spark.apache.org/",
    "apache-struts": "https://struts.apache.org/",
    "apache-subversion": "https://subversion.apache.org/",
    "arangodb": "https://arango.ai/",
    "artifactory": "https://jfrog.com/artifactory/",
    "authentik": "https://goauthentik.io/",
    "azul-zulu": "https://www.azul.com/products/core/",
    "azure-devops-server": "https://azure.microsoft.com/products/devops/server/",
    "bamboo": "https://www.atlassian.com/software/bamboo",
    "beats": "https://www.elastic.co/beats",
    "bellsoft-liberica": "https://bell-sw.com/libericajdk/",
    "bind-9": "https://www.isc.org/bind/",
    "bitbucket": "https://www.atlassian.com/software/bitbucket",
    "bitcoin-core": "https://bitcoincore.org/",
    "blender": "https://www.blender.org/",
    "boundary": "https://developer.hashicorp.com/boundary",
    "cakephp": "https://cakephp.org/",
    "centreon": "https://www.centreon.com/",
    "ceph": "https://ceph.io/",
    "cfengine": "https://cfengine.com/",
    "checkmk": "https://checkmk.com/",
    "chef-infra-client": "https://docs.chef.io/client/",
    "chef-infra-server": "https://docs.chef.io/server/",
    "chef-inspec": "https://docs.chef.io/inspec/",
    "chef-supermarket": "https://docs.chef.io/supermarket/",
    "chef-workstation": "https://docs.chef.io/workstation/",
    "chrome": "https://www.google.com/chrome/",
    "citrix-vad": "https://www.citrix.com/platform/citrix-app-and-desktop-virtualization/",
    "ckeditor": "https://ckeditor.com/",
    "cockroachdb": "https://www.cockroachlabs.com/",
    "coldfusion": "https://www.adobe.com/products/coldfusion-family.html",
    "commvault": "https://www.commvault.com/",
    "composer": "https://getcomposer.org/",
    "concrete-cms": "https://www.concretecms.org/",
    "confluence": "https://www.atlassian.com/software/confluence",
    "contao": "https://contao.org/",
    "controlm": "https://www.bmc.com/it-solutions/control-m.html",
    "cortex-xdr": "https://www.paloaltonetworks.com/cortex/cortex-xdr",
    "couchbase-server": "https://www.couchbase.com/",
    "craft-cms": "https://craftcms.com/",
    "dce": "https://docs.daocloud.io/en/",
    "dependency-track": "https://dependencytrack.org/",
    "discourse": "https://www.discourse.org/",
    "django": "https://www.djangoproject.com/",
    "docker-engine": "https://docs.docker.com/engine/",
    "dotnet": "https://dotnet.microsoft.com/",
    "dotnetfx": "https://dotnet.microsoft.com/",
    "drupal": "https://www.drupal.org/",
    "eclipse-temurin": "https://adoptium.net/",
    "elasticsearch": "https://www.elastic.co/elasticsearch",
    "electron": "https://www.electronjs.org/",
    "emberjs": "https://emberjs.com/",
    "exim": "https://www.exim.org/",
    "ffmpeg": "https://ffmpeg.org/",
    "filemaker": "https://www.claris.com/filemaker/",
    "firefox": "https://www.firefox.com/",
    "foreman": "https://theforeman.org/",
    "forgejo": "https://forgejo.org/",
    "foundationdb": "https://www.foundationdb.org/",
    "freedesktop-sdk": "https://freedesktop-sdk.gitlab.io/",
    "gerrit": "https://www.gerritcodereview.com/",
    "ghc": "https://www.haskell.org/ghc/",
    "git": "https://git-scm.com/",
    "gitlab": "https://about.gitlab.com/",
    "gitlab-runner": "https://docs.gitlab.com/runner/",
    "go": "https://go.dev/",
    "goaccess": "https://goaccess.io/",
    "godot": "https://godotengine.org/",
    "gorilla": "https://github.com/gorilla",
    "graalvm-ce": "https://www.graalvm.org/",
    "graylog": "https://graylog.org/",
    "gstreamer": "https://gstreamer.freedesktop.org/",
    "guzzle": "https://github.com/guzzle/guzzle",
    "haproxy": "https://www.haproxy.org/",
    "hbase": "https://hbase.apache.org/",
    "horizon": "https://www.omnissa.com/products/horizon-8/",
    "ibm-db2": "https://www.ibm.com/products/db2",
    "ibm-mq": "https://www.ibm.com/products/mq",
    "ibm-semeru-runtime": "https://developer.ibm.com/languages/semeru-runtimes/",
    "icinga": "https://icinga.com/",
    "icinga-web": "https://github.com/Icinga/icingaweb2",
    "idl": "https://www.nv5geospatialsoftware.com/Products/IDL",
    "influxdb": "https://github.com/influxdata/influxdb",
    "internet-explorer": "https://www.microsoft.com/download/internet-explorer",
    "isc-dhcp": "https://www.isc.org/dhcp/",
    "istio": "https://istio.io/",
    "jfrog-xray": "https://jfrog.com/xray/",
    "jira-service-management": "https://www.atlassian.com/software/jira/service-management",
    "jira-software": "https://www.atlassian.com/software/jira",
    "joomla": "https://www.joomla.org/",
    "jquery": "https://jquery.com/",
    "jquery-ui": "https://jqueryui.com/",
    "keycloak": "https://www.keycloak.org/",
    "kibana": "https://www.elastic.co/kibana",
    "kirby": "https://getkirby.com/",
    "laravel": "https://laravel.com/",
    "libreoffice": "https://www.libreoffice.org/",
    "liquibase-secure": "https://www.liquibase.com/liquibase-secure",
    "log4j": "https://logging.apache.org/log4j/",
    "logstash": "https://www.elastic.co/logstash",
    "looker": "https://cloud.google.com/looker",
    "lua": "https://www.lua.org/",
    "magento": "https://github.com/magento/magento2",
    "mariadb": "https://mariadb.org/",
    "mattermost": "https://mattermost.com/",
    "mediawiki": "https://www.mediawiki.org/wiki/MediaWiki",
    "memcached": "https://www.memcached.org/",
    "metallb": "https://metallb.io/",
    "microsoft-build-of-openjdk": "https://learn.microsoft.com/java/openjdk/",
    "mongodb": "https://www.mongodb.com/",
    "moodle": "https://moodle.org/",
    "msexchange": "https://www.microsoft.com/microsoft-365/exchange/email",
    "mssqlserver": "https://www.microsoft.com/sql-server/",
    "mulesoft-runtime": "https://www.mulesoft.com/",
    "mysql": "https://www.mysql.com/",
    "neo4j": "https://neo4j.com/",
    "neos": "https://www.neos.io/",
    "nextcloud": "https://nextcloud.com/",
    "nexus": "https://www.sonatype.com/products/sonatype-nexus-repository",
    "nginx": "https://nginx.org/",
    "nix": "https://nixos.org/",
    "nodejs": "https://nodejs.org/",
    "notepad-plus-plus": "https://notepad-plus-plus.org/",
    "nutanix-files": "https://www.nutanix.com/products/files",
    "nutanix-prism": "https://www.nutanix.com/products/prism",
    "office": "https://www.microsoft.com/microsoft-365",
    "openjdk-builds-from-oracle": "https://jdk.java.net/",
    "opensearch": "https://opensearch.org/",
    "openssl": "https://openssl-library.org/",
    "opnsense": "https://opnsense.org/",
    "oracle-apex": "https://apex.oracle.com/",
    "oracle-database": "https://www.oracle.com/database/",
    "oracle-graalvm": "https://www.graalvm.org/",
    "oracle-jdk": "https://www.oracle.com/java/",
    "otobo": "https://otobo.io/",
    "pangp": "https://www.paloaltonetworks.com/sase/globalprotect",
    "perl": "https://www.perl.org/",
    "pgadmin": "https://www.pgadmin.org/",
    "php": "https://www.php.net/",
    "phpbb": "https://www.phpbb.com/",
    "phpmyadmin": "https://www.phpmyadmin.net/",
    "plesk": "https://www.plesk.com/",
    "plone": "https://plone.org/",
    "postfix": "https://www.postfix.org/",
    "postgresql": "https://www.postgresql.org/",
    "proxmox-backup-server": "https://www.proxmox.com/en/proxmox-backup-server",
    "proxmox-datacenter-manager": "https://www.proxmox.com/en/products/proxmox-datacenter-manager/overview",
    "proxmox-mail-gateway": "https://www.proxmox.com/en/products/proxmox-mail-gateway/overview",
    "puppet": "https://www.puppet.com/",
    "python": "https://www.python.org/",
    "qt": "https://www.qt.io/",
    "quarkus-framework": "https://quarkus.io/",
    "red-hat-ansible-automation-platform": "https://www.redhat.com/en/technologies/management/ansible",
    "red-hat-openshift": "https://www.redhat.com/en/technologies/cloud-computing/openshift",
    "redhat-build-of-openjdk": "https://developers.redhat.com/products/openjdk/overview",
    "redhat-jboss-eap": "https://www.redhat.com/en/technologies/jboss-middleware/application-platform",
    "redhat-satellite": "https://www.redhat.com/en/technologies/management/satellite",
    "redis": "https://redis.io/",
    "redmine": "https://www.redmine.org/",
    "robo": "https://github.com/consolidation/robo",
    "rtpengine": "https://github.com/sipwise/rtpengine",
    "ruby": "https://www.ruby-lang.org/",
    "rust": "https://www.rust-lang.org/",
    "salt": "https://saltproject.io/",
    "samba": "https://www.samba.org/",
    "sapmachine": "https://sapmachine.io/",
    "sharepoint": "https://www.microsoft.com/microsoft-365/sharepoint/collaboration",
    "silverstripe": "https://github.com/silverstripe/silverstripe-framework",
    "solr": "https://solr.apache.org/",
    "sonarqube-community": "https://www.sonarsource.com/open-source-editions/sonarqube-community-edition/",
    "sonarqube-server": "https://www.sonarsource.com/products/sonarqube/",
    "sourcegraph": "https://sourcegraph.com/",
    "splunk": "https://www.splunk.com/",
    "sqlite": "https://www.sqlite.org/",
    "squid": "https://www.squid-cache.org/",
    "suse-manager": "https://www.suse.com/products/multi-linux-manager/",
    "symfony": "https://symfony.com/",
    "tomcat": "https://tomcat.apache.org/",
    "twig": "https://twig.symfony.com/",
    "typo3": "https://typo3.org/",
    "umbraco": "https://umbraco.com/",
    "unity": "https://unity.com/",
    "unrealircd": "https://www.unrealircd.org/",
    "vcenter": "https://www.vmware.com/products/cloud-infrastructure/vcenter",
    "veeam-backup-and-replication": "https://www.veeam.com/products/veeam-data-platform/backup-recovery.html",
    "veeam-backup-for-microsoft-365": "https://www.veeam.com/products/saas/backup-microsoft-office-365.html",
    "veeam-one": "https://www.veeam.com/products/veeam-data-platform/monitoring-analytics.html",
    "vinyl-cache": "https://vinyl-cache.org/",
    "virtualbox": "https://www.virtualbox.org/",
    "visual-studio": "https://visualstudio.microsoft.com/",
    "vmware-cloud-foundation": "https://www.vmware.com/products/cloud-infrastructure/vmware-cloud-foundation",
    "vmware-harbor-registry": "https://techdocs.broadcom.com/us/en/vmware-tanzu/platform/harbor-registry/services/harbor/index.html",
    "vmware-srm": "https://www.vmware.com/products/cloud-infrastructure/advanced-services/live-recovery",
    "wagtail": "https://wagtail.org/",
    "windows-powershell": "https://learn.microsoft.com/powershell/",
    "wireshark": "https://www.wireshark.org/",
    "wordpress": "https://wordpress.org/",
    "youtrack": "https://www.jetbrains.com/youtrack/",
    "zabbix": "https://www.zabbix.com/",
    "zerto": "https://www.zerto.com/",
    "zookeeper": "https://zookeeper.apache.org/",
}

NUMBERS = re.compile(r"\d+(?:\.\d+)*")
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
AT = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
# What a name may be. They are lookup keys, and the app must be able to trust their form.
NAME = re.compile(r"[A-Za-z0-9@][A-Za-z0-9@._+:/-]{0,127}")
# What a release's page may be. No user, port or `http`: the app goes by the exact host.
PAGE = re.compile(r"https://[A-Za-z0-9.-]{1,253}(?:[/?#][A-Za-z0-9._~/%+#?=&:;,@!$()-]{0,255})?")
# Any page of a repository on GitHub goes by its front page, which stays and shows the latest.
GITHUB_REPOSITORY = re.compile(r"(https://github\.com/[^/?#]+/[^/?#]+)(?:[/?#].*)?")


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


def page_of(product, release):
    """A main page that stays as versions come. The source's link says where a repository is,
    and is not kept: its other pages are about one version, and of any host."""
    if product in PAGES:
        return PAGES[product]
    link = (release.get("latest") or {}).get("link")
    if isinstance(link, str) and PAGE.fullmatch(link):
        github = GITHUB_REPOSITORY.fullmatch(link)
        return github[1] if github else None
    return None


def line_of(product, release):
    """One release line, or None when its name is not the numbers a version starts with."""
    name = release.get("name")
    if not isinstance(name, str) or not NUMBERS.fullmatch(name):
        return None
    line = {"c": name}
    eol = date_of(release.get("eolFrom"))
    if eol:
        line["e"] = eol
    page = page_of(product, release)
    if page:
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


def stamp(new, old, now):
    """When the data last changed. Kept while it stays as it was, so that a run that found nothing
    new makes the same file and publishes nothing."""
    same = old is not None and {k: v for k, v in old.items() if k != "at"} == new
    new["at"] = old["at"] if same and "at" in old else now


def check(data):
    """That the file has the form the app accepts."""
    if data.get("schema") != SCHEMA or not DATE.fullmatch(data.get("as_of", "")):
        raise Refused("schema or date")
    if "at" in data and not AT.fullmatch(data["at"]):
        raise Refused(f"time {data['at']!r}")
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
    head = {k: data[k] for k in ("schema", "as_of", "at", "source") if k in data}
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
    now = datetime.datetime.now(datetime.timezone.utc)
    today = now.date().isoformat()
    try:
        new = normalize(fetch(), today)
        old = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else None
        stamp(new, old, now.strftime("%Y-%m-%dT%H:%M:%SZ"))
        check(new)
        if old is not None and not args.force:
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
