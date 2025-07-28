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

import re
import string
import unittest

from itertools import product
from typing import Generator
from unittest.mock import _patch, patch

import tests

from tests.ai.constants import AI_SKIP_MESSAGE, MYSQL_CONNECTOR_RANDOM_NAME_SPACE

import mysql.connector

from mysql.connector.abstracts import MySQLCursorAbstract


def _lexicographic_names(length: int = 16) -> Generator[str, None, None]:
    """
    Generate lexicographically ordered uppercase names.

    Args:
        length: The length of each generated name. Default is 16.

    Yields:
        str: The next name in lexicographic sequence, using uppercase A-Z characters.

    Notes:
        Names are generated as all possible combinations of uppercase ASCII letters of the given length,
        starting from 'A' * length (e.g., 'TEST_MYSQL_CONNECTOR_AAAA...A', 'TEST_MYSQL_CONNECTOR_AAAA...B')
        and incrementing lexicographically. This is useful for deterministic and exhaustive name generation
        for testing or mocking scenarios.
    """
    chars = string.ascii_uppercase
    for name_tuple in product(chars, repeat=length):
        yield f"""{MYSQL_CONNECTOR_RANDOM_NAME_SPACE}_{"".join(name_tuple)}"""


def random_name_patcher() -> _patch:
    """
    Create a patch for the mysql.ai.utils._get_name function to return lexicographically generated names.

    Returns:
        unittest.mock._patch: A patch object that replaces mysql.ai.utils._get_name,
        yielding deterministic lexicographic names on each invocation.

    Notes:
        The patch uses the _lexicographic_names generator to ensure names are produced in deterministic order, rather than randomly.
        Useful for testing scenarios where reproducible name generation is required.
    """
    name_gen = _lexicographic_names()
    return patch("mysql.ai.utils.utils._get_name", side_effect=lambda: next(name_gen))


@unittest.skipIf(not tests.MYSQL_ML_ENABLED, AI_SKIP_MESSAGE)
class MyAITest(tests.MySQLConnectorTests):

    @staticmethod
    def _safe_uninstall(cursor: MySQLCursorAbstract, uninstall_sql: str):
        """
        Attempts to uninstall a component or plugin, suppressing errors
        if it is already uninstalled/not present.
        """
        try:
            cursor.execute(uninstall_sql)
            cursor.fetchall()
        except mysql.connector.Error as e:
            # Suppress errors for things that are already uninstalled/not present
            error_codes = [
                3530,  # not installed
                3537,  # not loaded
                1125,  # unknown plugin
            ]
            if e.errno not in error_codes:
                raise

    @staticmethod
    def _safe_install(cursor: MySQLCursorAbstract, install_sql: str):
        """
        Attempts to install a component or plugin, suppressing errors
        if it is already installed.
        """
        try:
            cursor.execute(install_sql)
            cursor.fetchall()
        except mysql.connector.Error as e:
            # Suppress errors for things that are already installed
            error_codes = [
                3531,  # ER_COMPONENT_EXISTS
                1126,  # ER_PLUGIN_IS_BUSY
            ]
            if e.errno not in error_codes:
                raise

    @staticmethod
    def uninstall_ai_dependencies():
        # Install AI dependencies
        with (
            mysql.connector.connect(**tests.get_mysql_config()) as cnx,
            cnx.cursor() as cursor,
        ):

            stmts = [
                "UNINSTALL COMPONENT 'file://component_vector';",
                "UNINSTALL COMPONENT 'file://component_vector_store_load';",
            ]
            for stmt in stmts:
                MyAITest._safe_uninstall(cursor, stmt)

    @staticmethod
    def install_ai_dependencies():
        with (
            mysql.connector.connect(**tests.get_mysql_config()) as cnx,
            cnx.cursor() as cursor,
        ):

            stmts = [
                "INSTALL COMPONENT 'file://component_vector_store_load';",
                "GRANT VECTOR_STORE_LOAD_EXEC on *.* to current_user();",
                "SELECT mysql_task_management_ensure_schema();",
                "INSTALL COMPONENT 'file://component_vector';",
            ]
            for stmt in stmts:
                MyAITest._safe_install(cursor, stmt)

    def _drop_test_tables(cursor: MySQLCursorAbstract):
        cursor.execute(f"SHOW TABLES LIKE '{MYSQL_CONNECTOR_RANDOM_NAME_SPACE}_%'")
        test_tables = cursor.fetchall()

        for (table_name,) in test_tables:
            cursor.execute(f"DROP TABLE IF EXISTS {table_name}")

    def _clear_random_models(cursor: MySQLCursorAbstract):
        cursor.execute("SELECT CURRENT_USER()")
        current_user = cursor.fetchone()[0].split("@")[0]

        if not re.match(r"^\w+$", current_user):
            raise ValueError(f"Unsafe DB user for schema: {current_user}")

        schema, name = f"ML_SCHEMA_{current_user}", "MODEL_CATALOG"
        cursor.execute(
            """
            SELECT TABLE_NAME
            FROM INFORMATION_SCHEMA.TABLES
            WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s
            """,
            (schema, name),
        )
        if cursor.fetchone() is None:
            return

        qualified_model_catalog = f"{schema}.{name}"

        cursor.execute(
            f"SELECT `model_handle` FROM {qualified_model_catalog} WHERE `model_handle` LIKE '{MYSQL_CONNECTOR_RANDOM_NAME_SPACE}_%'"
        )
        model_handles = cursor.fetchall()

        for (model_handle,) in model_handles:
            cursor.execute(
                f"DELETE FROM {qualified_model_catalog} WHERE `model_handle` = %s",
                (model_handle,),
            )

    def setUp(self):
        super().setUp()
        with (
            mysql.connector.connect(**tests.get_mysql_config()) as cnx,
            cnx.cursor() as cursor,
        ):
            MyAITest._drop_test_tables(cursor)
            MyAITest._clear_random_models(cursor)
            cnx.commit()

    def tearDown(self):
        with (
            mysql.connector.connect(**tests.get_mysql_config()) as cnx,
            cnx.cursor() as cursor,
        ):
            MyAITest._drop_test_tables(cursor)
            MyAITest._clear_random_models(cursor)
            cnx.commit()
        super().tearDown()

    @classmethod
    def setUpClass(cls):
        MyAITest.uninstall_ai_dependencies()
        MyAITest.install_ai_dependencies()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        MyAITest.uninstall_ai_dependencies()
