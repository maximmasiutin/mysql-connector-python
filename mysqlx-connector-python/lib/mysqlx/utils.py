# Copyright (c) 2009, 2024, Oracle and/or its affiliates.
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

"""Utilities."""

import os
import subprocess
import sys
import warnings

from typing import Dict, Optional, Tuple

from .tls_ciphers import DEPRECATED_TLS_CIPHERSUITES, DEPRECATED_TLS_VERSIONS


def _parse_os_release() -> Dict[str, str]:
    """Parse the contents of /etc/os-release file.

    Returns:
        A dictionary containing release information.
    """
    distro: Dict[str, str] = {}
    os_release_file = os.path.join("/etc", "os-release")
    if not os.path.exists(os_release_file):
        return distro
    with open(os_release_file, encoding="utf-8") as file_obj:
        for line in file_obj:
            key_value = line.split("=")
            if len(key_value) != 2:
                continue
            key = key_value[0].lower()
            value = key_value[1].rstrip("\n").strip('"')
            distro[key] = value
    return distro


def _parse_lsb_release() -> Dict[str, str]:
    """Parse the contents of /etc/lsb-release file.

    Returns:
        A dictionary containing release information.
    """
    distro = {}
    lsb_release_file = os.path.join("/etc", "lsb-release")
    if os.path.exists(lsb_release_file):
        with open(lsb_release_file, encoding="utf-8") as file_obj:
            for line in file_obj:
                key_value = line.split("=")
                if len(key_value) != 2:
                    continue
                key = key_value[0].lower()
                value = key_value[1].rstrip("\n").strip('"')
                distro[key] = value
    return distro


def _parse_lsb_release_command() -> Optional[Dict[str, str]]:
    """Parse the output of the lsb_release command.

    Returns:
        A dictionary containing release information.
    """
    distro = {}
    with open(os.devnull, "w", encoding="utf-8") as devnull:
        try:
            stdout = subprocess.check_output(("lsb_release", "-a"), stderr=devnull)
        except OSError:
            return None
        lines = stdout.decode(sys.getfilesystemencoding()).splitlines()
        for line in lines:
            key_value = line.split(":")
            if len(key_value) != 2:
                continue
            key = key_value[0].replace(" ", "_").lower()
            value = key_value[1].strip("\t")
            distro[key] = value
    return distro


def linux_distribution() -> Tuple[str, str, str]:
    """Tries to determine the name of the Linux OS distribution name.

    First tries to get information from ``/etc/os-release`` file.
    If fails, tries to get the information of ``/etc/lsb-release`` file.
    And finally the information of ``lsb-release`` command.

    Returns:
        A tuple with (`name`, `version`, `codename`)
    """
    distro: Optional[Dict[str, str]] = _parse_lsb_release()
    if distro:
        return (
            distro.get("distrib_id", ""),
            distro.get("distrib_release", ""),
            distro.get("distrib_codename", ""),
        )

    distro = _parse_lsb_release_command()
    if distro:
        return (
            distro.get("distributor_id", ""),
            distro.get("release", ""),
            distro.get("codename", ""),
        )

    distro = _parse_os_release()
    if distro:
        return (
            distro.get("name", ""),
            distro.get("version_id", ""),
            distro.get("version_codename", ""),
        )

    return ("", "", "")


def warn_ciphersuites_deprecated(cipher_as_ossl: str, tls_version: str) -> None:
    """Emits a warning if a deprecated cipher is being utilized.

    Args:
        cipher: Must be ingested as OpenSSL name.
        tls_versions: TLS version to check the cipher against.

    Raises:
        DeprecationWarning: If the cipher is flagged as deprecated
                            according to the OSSA cipher list.
    """
    if cipher_as_ossl in DEPRECATED_TLS_CIPHERSUITES.get(tls_version, {}).values():
        warn_msg = (
            f"This connection is using TLS cipher {cipher_as_ossl} which is now "
            "deprecated and will be removed in a future release of "
            "MySQL Connector/Python."
        )
        warnings.warn(warn_msg, DeprecationWarning)


def warn_tls_version_deprecated(tls_version: str) -> None:
    """Emits a warning if a deprecated TLS version is being utilized.

    Args:
        tls_versions: TLS version to check.

    Raises:
        DeprecationWarning: If the TLS version is flagged as deprecated
                            according to the OSSA cipher list.
    """
    if tls_version in DEPRECATED_TLS_VERSIONS:
        warn_msg = (
            f"This connection is using TLS version {tls_version} which is now "
            "deprecated and will be removed in a future release of "
            "MySQL Connector/Python."
        )
        warnings.warn(warn_msg, DeprecationWarning)
