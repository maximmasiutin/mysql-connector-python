# Copyright (c) 2020, 2024, Oracle and/or its affiliates.
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

"""Implements the Distutils command 'sdist'.

Creates a source distribution.
"""

import logging
import os
import shutil
import sys

from pathlib import Path
from sysconfig import get_python_version

from setuptools.command.sdist import sdist

try:
    from setuptools.logging import set_threshold
except ImportError:
    set_threshold = None

from . import COMMON_USER_OPTIONS, EDITION, LOGGER, VERSION
from .utils import create_tree, get_dist_name, write_info_bin, write_info_src


class DistSource(sdist):
    """Create a generic source distribution.

    DistSource is meant to replace distutils.sdist.
    """

    description = "create a source distribution (tarball, zip file, etc.)"
    user_options = COMMON_USER_OPTIONS + [
        (
            "prune",
            None,
            "specifically exclude files/directories that should not be "
            "distributed (build tree, RCS/CVS dirs, etc.) "
            "[default; disable with --no-prune]",
        ),
        ("no-prune", None, "don't automatically exclude anything"),
        (
            "formats=",
            None,
            "formats for source distribution (comma-separated list)",
        ),
        (
            "keep-temp",
            "k",
            "keep the distribution tree around after creating archive file(s)",
        ),
        (
            "dist-dir=",
            "d",
            "directory to put the source distribution archive(s) in [default: dist]",
        ),
        (
            "owner=",
            "u",
            "Owner name used when creating a tar file [default: current user]",
        ),
        (
            "group=",
            "g",
            "Group name used when creating a tar file [default: current group]",
        ),
    ]
    boolean_options = ["prune", "force-manifest", "keep-temp"]
    negative_opt = {"no-prune": "prune"}
    default_format = {"posix": "gztar", "nt": "zip"}
    log = LOGGER

    def initialize_options(self):
        """Initialize the options."""
        self.edition = EDITION
        self.label = ""
        self.debug = False
        sdist.initialize_options(self)

    def finalize_options(self):
        """Finalize the options."""

        def _get_fullname():
            # Comply with [PEP 625](https://peps.python.org/pep-0625/).
            # Use the normalized project name 'mysql_connector_python'.
            distribution = self.distribution.get_name().replace("-", "_")
            label = f"-{self.label}" if self.label else ""
            version = self.distribution.get_version()
            edition = self.edition or ""
            return f"{distribution}{label}-{version}{edition}"

        self.distribution.get_fullname = _get_fullname
        sdist.finalize_options(self)
        if self.debug:
            self.log.setLevel(logging.DEBUG)
            if set_threshold:
                # Set setuptools logging level to DEBUG
                set_threshold(1)

    def make_release_tree(self, base_dir, files):
        """Make the release tree."""
        Path(base_dir).mkdir(parents=True, exist_ok=True)
        create_tree(base_dir, files)

        if not files:
            self.log.warning("no files to distribute -- empty manifest?")
        else:
            self.log.info("copying files to %s...", base_dir)
        for filename in files:
            if not os.path.isfile(filename):
                self.log.warning("'%s' not a regular file -- skipping", filename)
            else:
                dest = os.path.join(base_dir, filename)
                shutil.copyfile(filename, dest)

        self.distribution.metadata.write_pkg_info(base_dir)

    def run(self):
        """Run the command."""
        self.log.info("generating INFO_SRC and INFO_BIN files")
        write_info_src(VERSION)
        write_info_bin()
        self.distribution.data_files = None
        super().run()


class SourceGPL(sdist):
    """Create source GNU GPLv2 distribution for specific Python version.

    This class generates a source distribution GNU GPLv2 licensed for the
    Python version that is used. SourceGPL is used by other commands to
    generate RPM or other packages.
    """

    description = (
        f"create a source distribution for Python v{get_python_version()[0]}.x"
    )
    user_options = [
        ("debug", None, "turn debugging on"),
        (
            "bdist-dir=",
            "d",
            "temporary directory for creating the distribution",
        ),
        (
            "keep-temp",
            "k",
            "keep the pseudo-installation tree around after "
            "creating the distribution archive",
        ),
        ("dist-dir=", "d", "directory to put final built distributions in"),
    ]
    boolean_options = ["keep-temp"]
    negative_opt = []

    def initialize_options(self):
        """Initialize the options."""
        self.bdist_dir = None
        self.keep_temp = 0
        self.dist_dir = None
        self.plat_name = ""
        self.debug = False

    def finalize_options(self):
        """Finalize the options."""
        if self.bdist_dir is None:
            bdist_base = self.get_finalized_command("bdist").bdist_base
            self.bdist_dir = os.path.join(bdist_base, "dist")

        self.set_undefined_options("bdist", ("dist_dir", "dist_dir"))

        python_version = get_python_version()
        pyver = python_version[0:2]

        # Change classifiers
        new_classifiers = []
        for classifier in self.distribution.metadata.classifiers:
            if (
                classifier.startswith("Programming Language ::")
                and pyver not in classifier
            ):
                self.log.info("removing classifier %s" % classifier)
                continue
            new_classifiers.append(classifier)
        self.distribution.metadata.classifiers = new_classifiers

        with open("README.txt", "r") as file_handler:
            license = file_handler.read()
            self.distribution.metadata.long_description += f"\n{license}"

        if self.debug:
            self.log.setLevel(logging.DEBUG)
            set_threshold(1)  # Set Setuptools logging level to DEBUG

    def run(self):
        """Run the command."""
        self.log.info("installing library code to %s", self.bdist_dir)
        self.log.info("generating INFO_SRC and INFO_BIN files")
        write_info_src(VERSION)
        write_info_bin()

        self.dist_name = get_dist_name(
            self.distribution,
            source_only_dist=True,
            python_version=get_python_version()[0],
        )
        self.dist_target = os.path.join(self.dist_dir, self.dist_name)
        self.log.info("distribution will be available as '%s'", self.dist_target)

        # build command: just to get the build_base
        cmdbuild = self.get_finalized_command("build")
        self.build_base = cmdbuild.build_base

        # install command
        install = self.reinitialize_command("install_lib", reinit_subcommands=1)
        install.compile = False
        install.warn_dir = 0
        install.install_dir = self.bdist_dir

        self.log.info("installing to %s", self.bdist_dir)
        self.run_command("install_lib")

        # install_egg_info command
        cmd_egginfo = self.get_finalized_command("install_egg_info")
        cmd_egginfo.install_dir = self.bdist_dir
        self.run_command("install_egg_info")
        # we need the py2.x converted to py2 in the filename
        old_egginfo = cmd_egginfo.get_outputs()[0]
        new_egginfo = old_egginfo.replace(
            f"-py{sys.version[:3]}",
            f"-py{get_python_version()[0]}",
        )
        shutil.move(old_egginfo, new_egginfo)

        # create distribution
        info_files = [
            ("README.txt", "README.txt"),
            ("LICENSE.txt", "LICENSE.txt"),
            ("README.rst", "README.rst"),
            ("CONTRIBUTING.md", "CONTRIBUTING.md"),
            ("SECURITY.md", "SECURITY.md"),
            ("docs/INFO_SRC", "INFO_SRC"),
            ("docs/INFO_BIN", "INFO_BIN"),
        ]

        shutil.copytree(self.bdist_dir, self.dist_target, dirs_exist_ok=True)
        Path(self.dist_target).mkdir(parents=True, exist_ok=True)

        for src, dst in info_files:
            shutil.copyfile(src, os.path.join(self.dist_target, dst))

        if not self.keep_temp:
            shutil.rmtree(self.build_base, dry_run=self.dry_run)
