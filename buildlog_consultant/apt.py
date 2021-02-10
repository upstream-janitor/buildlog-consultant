#!/usr/bin/python
# Copyright (C) 2019-2021 Jelmer Vernooij <jelmer@jelmer.uk>
# encoding: utf-8
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

import re

from debian.deb822 import PkgRelation
import yaml

from . import Problem
from .common import NoSpaceOnDevice


class DpkgError(Problem):

    kind = "dpkg-error"

    def __init__(self, error):
        self.error = error

    def __eq__(self, other):
        return isinstance(other, type(self)) and self.error == other.error

    def __str__(self):
        return "Dpkg Error: %s" % self.error

    def __repr__(self):
        return "%s(%r)" % (type(self).__name__, self.error)


class AptUpdateError(Problem):
    """Apt update error."""

    kind = "apt-update-error"


class AptFetchFailure(AptUpdateError):
    """Apt file fetch failed."""

    kind = "apt-file-fetch-failure"

    def __init__(self, url, error):
        self.url = url
        self.error = error

    def __eq__(self, other):
        if not isinstance(other, type(self)):
            return False
        if self.url != other.url:
            return False
        if self.error != other.error:
            return False
        return True

    def __str__(self):
        return "Apt file fetch error: %s" % self.error


class AptMissingReleaseFile(AptUpdateError):

    kind = "missing-release-file"

    def __init__(self, url):
        self.url = url

    def __eq__(self, other):
        if not isinstance(other, type(self)):
            return False
        if self.url != self.url:
            return False
        return True

    def __str__(self):
        return "Missing release file: %s" % self.url


class AptPackageUnknown(Problem):

    kind = "apt-package-unknown"

    def __init__(self, package):
        self.package = package

    def __eq__(self, other):
        return isinstance(other, type(self)) and self.package == other.package

    def __str__(self):
        return "Unknown package: %s" % self.package

    def __repr__(self):
        return "%s(%r)" % (type(self).__name__, self.package)


class AptBrokenPackages(Problem):

    kind = "apt-broken-packages"

    def __init__(self, description):
        self.description = description

    def __str__(self):
        return "Broken apt packages: %s" % (self.description,)

    def __repr__(self):
        return "%s(%r)" % (type(self).__name__, self.description)

    def __eq__(self, other):
        return isinstance(other, type(self)) and self.description == other.description


def find_apt_get_failure(lines):
    """Find the key failure line in apt-get-output.

    Returns:
      tuple with (line offset, line, error object)
    """
    ret = (None, None, None)
    OFFSET = 50
    for i in range(1, OFFSET):
        lineno = len(lines) - i
        if lineno < 0:
            break
        line = lines[lineno].strip("\n")
        if line.startswith("E: Failed to fetch "):
            m = re.match("^E: Failed to fetch ([^ ]+)  (.*)", line)
            if m:
                return lineno + 1, line, AptFetchFailure(m.group(1), m.group(2))
            return lineno + 1, line, None
        if line in (
            "E: Broken packages",
            "E: Unable to correct problems, you have held broken " "packages.",
        ):
            error = AptBrokenPackages(lines[lineno - 1].strip())
            return lineno, lines[lineno - 1].strip(), error
        m = re.match("E: The repository '([^']+)' does not have a Release file.", line)
        if m:
            return lineno + 1, line, AptMissingReleaseFile(m.group(1))
        m = re.match(
            "dpkg-deb: error: unable to write file '(.*)': " "No space left on device",
            line,
        )
        if m:
            return lineno + 1, line, NoSpaceOnDevice()
        m = re.match(r"E: You don't have enough free space in (.*)\.", line)
        if m:
            return lineno + 1, line, NoSpaceOnDevice()
        if line.startswith("E: ") and ret[0] is None:
            ret = (lineno + 1, line, None)
        m = re.match(r"E: Unable to locate package (.*)", line)
        if m:
            return lineno + 1, line, AptPackageUnknown(m.group(1))
        m = re.match(r"dpkg: error: (.*)", line)
        if m:
            if m.group(1).endswith(": No space left on device"):
                return lineno + 1, line, NoSpaceOnDevice()
            return lineno + 1, line, DpkgError(m.group(1))
        m = re.match(r"dpkg: error processing package (.*) \((.*)\):", line)
        if m:
            return (
                lineno + 2,
                lines[lineno + 1].strip(),
                DpkgError("processing package %s (%s)" % (m.group(1), m.group(2))),
            )

    for i, line in enumerate(lines):
        m = re.match(
            r" cannot copy extracted data for '(.*)' to "
            r"'(.*)': failed to write \(No space left on device\)",
            line,
        )
        if m:
            return lineno + i, line, NoSpaceOnDevice()
        m = re.match(r" .*: No space left on device", line)
        if m:
            return lineno + i, line, NoSpaceOnDevice()

    return ret


def find_apt_get_update_failure(paragraphs):
    focus_section = "update chroot"
    lines = paragraphs.get(focus_section, [])
    offset, line, error = find_apt_get_failure(lines)
    return focus_section, offset, line, error


def find_cudf_output(lines):
    for i in range(len(lines) - 1, 0, -1):
        if lines[i].startswith("output-version: "):
            break
    else:
        return None
    output = []
    while lines[i].strip():
        output.append(lines[i])
        i += 1

    return yaml.safe_load("\n".join(output))


class UnsatisfiedDependencies(Problem):

    kind = "unsatisfied-dependencies"

    def __init__(self, relations):
        self.relations = relations

    def __eq__(self, other):
        return isinstance(other, type(self)) and self.relations == other.relations

    def __str__(self):
        return "Unsatisfied dependencies: %s" % PkgRelation.str(self.relations)

    def __repr__(self):
        return "%s(%r)" % (type(self).__name__, self.relations)


class UnsatisfiedConflicts(Problem):

    kind = "unsatisfied-conflicts"

    def __init__(self, relations):
        self.relations = relations

    def __eq__(self, other):
        return isinstance(other, type(self)) and self.relations == other.relations

    def __str__(self):
        return "Unsatisfied conflicts: %s" % PkgRelation.str(self.relations)

    def __repr__(self):
        return "%s(%r)" % (type(self).__name__, self.relations)


def error_from_dose3_report(report):
    packages = [entry["package"] for entry in report]
    assert packages == ["sbuild-build-depends-main-dummy"]
    if report[0]["status"] != "broken":
        return None
    missing = []
    conflict = []
    for reason in report[0]["reasons"]:
        if "missing" in reason:
            relation = PkgRelation.parse_relations(
                reason["missing"]["pkg"]["unsat-dependency"]
            )
            missing.extend(relation)
        if "conflict" in reason:
            relation = PkgRelation.parse_relations(
                reason["conflict"]["pkg1"]["unsat-conflict"]
            )
            conflict.extend(relation)
    if missing:
        return UnsatisfiedDependencies(missing)
    if conflict:
        return UnsatisfiedConflicts(conflict)


def find_install_deps_failure_description(paragraphs):
    error = None
    DOSE3_SECTION = "install dose3 build dependencies (aspcud-based resolver)"
    dose3_lines = paragraphs.get(DOSE3_SECTION)
    if dose3_lines:
        dose3_output = find_cudf_output(dose3_lines)
        if dose3_output:
            error = error_from_dose3_report(dose3_output["report"])

    for focus_section, lines in paragraphs.items():
        if focus_section is None:
            continue
        if re.match("install (.*) build dependencies.*", focus_section):
            offset, line, v_error = find_apt_get_failure(lines)
            if error is None:
                error = v_error
            if offset is not None:
                return focus_section, offset, line, error

    return focus_section, None, None, error
