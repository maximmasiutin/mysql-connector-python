# Copyright (c) 2025 Oracle and/or its affiliates.
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


import warnings

from typing import Callable, Dict, Optional

from mysql.connector.cursor_cext import CMySQLCursor

import tests

import mysql.connector

from mysql.connector.conversion import MySQLConverterBase


class WL16752Tests(tests.MySQLConnectorTests):
    """Classic connector Tests for WL#16752."""

    @classmethod
    def deprecation_test_helper(
        cls, test_method: Callable, args: Optional[Dict] = None
    ) -> None:
        with warnings.catch_warnings(record=True) as warnings_stack:
            # Cause all warnings to always be triggered.
            warnings.simplefilter("always", DeprecationWarning)
            # execute the test method which raises the deprecation warning
            test_method(**args) if isinstance(args, dict) else test_method()
            cls.assertTrue(
                cls,
                len(warnings_stack) != 0,
                msg="No warnings were caught as warnings_stack was empty",
            )
            cls.assertTrue(cls, issubclass(warnings_stack[-1].category, DeprecationWarning))
            cls.assertTrue(cls, "deprecated" in str(warnings_stack[-1].message))
            warnings.resetwarnings()

    @tests.foreach_cnx()
    def test_deprecated_methods(self) -> None:

        class TestConverter(MySQLConverterBase): ...

        config = tests.get_mysql_config()
        with mysql.connector.connect(**config) as cnx:
            deprecated_methods = [
                (cnx.get_server_version, None),
                (cnx.get_server_info, None),
                (cnx.set_client_flags, {"flags": 1 << 0}),
                (cnx.set_unicode, {"value": True}),
                (cnx.set_converter_class, {"convclass": TestConverter}),
            ]

            with cnx.cursor() as cur:
                for pair in [
                    (cur.fetchwarnings, None),
                    (cur.stored_results, None),
                ]:
                    deprecated_methods.append(pair)
                if not isinstance(cur, CMySQLCursor):
                    deprecated_methods.append((cur.getlastrowid, None))

                for method, args in deprecated_methods:
                    self.deprecation_test_helper(method, args)


class WL16752Tests_async(tests.MySQLConnectorAioTestCase):
    """Async classic connector tests for WL#16752."""

    @tests.foreach_cnx_aio()
    async def test_deprecated_methods(self) -> None:

        class TestConverter(MySQLConverterBase): ...

        config = tests.get_mysql_config()
        async with await mysql.connector.aio.connect(**config) as cnx:
            deprecated_methods = [
                (cnx.get_server_version, None),
                (cnx.get_server_info, None),
                (cnx.set_client_flags, {"flags": 1 << 0}),
                (cnx.set_converter_class, {"convclass": TestConverter}),
            ]

            async with await cnx.cursor() as cur:
                for pair in [
                    (cur.fetchwarnings, None),
                    (cur.getlastrowid, None),
                    (cur.stored_results, None),
                ]:
                    deprecated_methods.append(pair)

                for method, args in deprecated_methods:
                    WL16752Tests.deprecation_test_helper(method, args)
