# Copyright (c) 2024, Oracle and/or its affiliates.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License, version 2.0, as
# published by the Free Software Foundation.
#
# This program is designed to work with certain software (including
# but not limited to OpenSSL) that is licensed under separate terms,
# as designated in a particular file or component or in included license
# documentation. The authors of MySQL hereby grant you an
# additional permission to link the program and your derivative works
# with the separately licensed software that they have either included with
# the program or referenced in the documentation.
#
# Without limiting anything contained in the foregoing, this file,
# which is part of MySQL Connector/Python, is also subject to the
# Universal FOSS Exception, version 1.0, a copy of which can be found at
# http://oss.oracle.com/licenses/universal-foss-exception.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
# See the GNU General Public License, version 2.0, for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin St, Fifth Floor, Boston, MA 02110-1301  USA

"""
Script to update the copyright header of the source files of connectors distributed
with `connector-python`.

This program traverses each connector package included in the `connector-python`
looking for source code, configuration, installation, documentation, and supporting
files that include the `Copyright` header pattern.

As a result, such a `Copyright` header is updated based on the rules defined in this
very script. Also, this script expects no command-line arguments, however, a relative
location to the root folder `connector-python` is assumed, therefore, if you move this
script to another location, it won't work.

It's up to the developer to decide where or when this program
will be executed.

Use case example: In the event of a "Copyright" change, the developer can update the
rules found in this program and run it to make the changes effective across the
relevant code base.
"""

import datetime
import logging
import os
import re

from pathlib import Path
from typing import List, Tuple, Union

CURRENT_YEAR = datetime.date.today().year
DEFAULT_FOUND_YEAR = 2023

# `sol` stands for start-of-line
COPYRIGHT_HEADER = """{sol} Copyright (c) {creation_year}{current_year}, Oracle and/or its affiliates.
{sol}
{sol} This program is free software; you can redistribute it and/or modify
{sol} it under the terms of the GNU General Public License, version 2.0, as
{sol} published by the Free Software Foundation.
{sol}
{sol} This program is designed to work with certain software (including
{sol} but not limited to OpenSSL) that is licensed under separate terms,
{sol} as designated in a particular file or component or in included license
{sol} documentation. The authors of MySQL hereby grant you an
{sol} additional permission to link the program and your derivative works
{sol} with the separately licensed software that they have either included with
{sol} the program or referenced in the documentation.
{sol}
{sol} Without limiting anything contained in the foregoing, this file,
{sol} which is part of MySQL Connector/Python, is also subject to the
{sol} Universal FOSS Exception, version 1.0, a copy of which can be found at
{sol} http://oss.oracle.com/licenses/universal-foss-exception.
{sol}
{sol} This program is distributed in the hope that it will be useful, but
{sol} WITHOUT ANY WARRANTY; without even the implied warranty of
{sol} MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
{sol} See the GNU General Public License, version 2.0, for more details.
{sol}
{sol} You should have received a copy of the GNU General Public License
{sol} along with this program; if not, write to the Free Software Foundation, Inc.,
{sol} 51 Franklin St, Fifth Floor, Boston, MA 02110-1301  USA"""


RE_FLAGS = re.MULTILINE | re.DOTALL
PATTERN = r"^{sol_pattern}\sCopyright\s.*?\sMA\s+02110-1301\s+USA$"
PATTERN_HEADER_PY = re.compile(PATTERN.format(sol_pattern=r"#"), flags=RE_FLAGS)
PATTERN_HEADER_C = re.compile(PATTERN.format(sol_pattern=r"\s\*"), flags=RE_FLAGS)
PATTERN_HEADER_PLAIN = re.compile(
    r"^Copyright\s.*?\sMA\s+02110-1301\s+USA$", flags=RE_FLAGS
)
PATTERN_YEARS = r"Copyright\s+\(c\)\s+\d{4},\s*\d{4},\s+Oracle"

TARGET_SRC_PY_EXTS = [".py", ".sh", ".spec", ".postinst", ".postrm", ".toml"]
TARGET_SRC_C_EXTS = [".c", ".h", ".cpp", ".cc", ".proto"]
TARGET_SRC_PLAIN_EXTS = [".rst"]

TARGET_SRC_EXTS = TARGET_SRC_PY_EXTS + TARGET_SRC_C_EXTS + TARGET_SRC_PLAIN_EXTS

SRC_BUT_EXTENSIONLESS = ["rules", "Dockerfile"]

SHARED_FILES = [
    "pyproject.toml",
]

MYSQL_CONNECTORS = {
    "classic": "mysql-connector-python",
    "xdevapi": "mysqlx-connector-python",
}

EXCLUDE = [
    os.path.join(MYSQL_CONNECTORS["classic"], "build"),
    os.path.join(MYSQL_CONNECTORS["classic"], "lib", "mysql", "opentelemetry"),
    os.path.join(MYSQL_CONNECTORS["xdevapi"], "build"),
]

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("cpy.headerfy")


def update_header(root: Union[str, Path], filename: str) -> None:
    """Updates the Copyright header of the provided file.

    Args:
        root: Absolute path to the folder where `file` can be found.
        filename: File name to be updated.

    Returns:
        None

    Raises:
        PermissionError, FileNotFoundError, FileExistsError: If the opening of the
                                                             file fails.
        RuntimeError: The file extension isn't supported.
    """
    path_to_file = os.path.join(root, filename)

    pattern = None
    if (
        any((filename.endswith(ext) for ext in TARGET_SRC_PY_EXTS))
        or filename in SRC_BUT_EXTENSIONLESS
    ):
        pattern = PATTERN_HEADER_PY
    elif any((filename.endswith(ext) for ext in TARGET_SRC_C_EXTS)):
        pattern = PATTERN_HEADER_C
    elif any((filename.endswith(ext) for ext in TARGET_SRC_PLAIN_EXTS)):
        pattern = PATTERN_HEADER_PLAIN
    else:
        raise RuntimeError(f"Couldn't resolve extension for {filename}")

    sol = None
    if pattern == PATTERN_HEADER_PY:
        sol = "#"
    elif pattern == PATTERN_HEADER_C:
        sol = " *"
    elif pattern == PATTERN_HEADER_PLAIN:
        sol = ""

    with open(path_to_file, mode="r", encoding="utf8") as fp:
        text_old = fp.read()

    match_header = re.search(pattern, text_old)

    # no copyright header
    if match_header is None:
        return

    two_years_snippet = re.search(PATTERN_YEARS, match_header.group())
    creation_year = (
        two_years_snippet.group().split(",")[0].replace("Copyright (c)", "").strip()
        if two_years_snippet is not None
        else ""
    )


    logger.info("%s (%s)", path_to_file, creation_year if creation_year else "NULL")

    creation_year = f"{creation_year}, " if creation_year else f"{DEFAULT_FOUND_YEAR}, "

    text_new = re.sub(
        pattern,
        COPYRIGHT_HEADER.format(
            sol=sol, creation_year=creation_year, current_year=CURRENT_YEAR
        ),
        text_old,
    )

    with open(path_to_file, mode="w", encoding="utf8") as fp:
        fp.write(text_new)


def headerify(
    path_base: Union[str, Path], package_name: str
) -> List[Tuple[str, Exception]]:
    """Traverses the given package directory and hands over the relevant* files to be
    updated to `update_header` which drives the actual update.

    [*]: Including source, configuration, installation and further supporting files
         such as documentation files.

    Args:
        path_base: Absolute path to the folder where `package_name` can be found.
        package_name: The connector to be processed.

    Returns:
        issues: A list of 2-tuple items; 1st includes the absolute path to a file
                that couldn't be updated and 2nd informs the corresponding raised error.
    """
    warns: List[Tuple[str, Exception]] = []

    for root, _, files in os.walk(Path(path_base, package_name)):
        if any(
            (os.path.join(path_base, path_exclude) in root for path_exclude in EXCLUDE)
        ):
            continue
        for filename in files:
            if (
                any((filename.endswith(ext) for ext in TARGET_SRC_EXTS))
                or filename in SRC_BUT_EXTENSIONLESS
            ):
                try:
                    update_header(root, filename)
                except (PermissionError, FileNotFoundError, FileExistsError) as err:
                    warns.append((os.path.join(root, filename), err))
    return warns


if __name__ == "__main__":
    path_to_base = Path(__file__).parent.parent
    issues: List[Tuple[str, Exception]] = []

    for pkg_name in MYSQL_CONNECTORS.values():
        issues.extend(
            headerify(
                path_base=path_to_base,
                package_name=pkg_name,
            )
        )

    for file in SHARED_FILES:
        try:
            update_header(path_to_base, file)
        except (PermissionError, FileNotFoundError, FileExistsError) as error:
            issues.append((os.path.join(path_to_base, file), error))

    if issues:
        print("-" * 10 + "WARNING" + "-" * 10)
        for path_file, exc in issues:
            logger.warning("Couldn't update %s. Got %s", path_file, exc)
