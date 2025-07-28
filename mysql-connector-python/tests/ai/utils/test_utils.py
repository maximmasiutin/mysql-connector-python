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

import json
import random
import unittest

from unittest.mock import MagicMock, patch

import tests

from tests import foreach_cnx
from tests.ai.constants import (
    AI_SKIP_MESSAGE,
    DEFAULT_CONNECTION_TIMEOUT,
    DEFAULT_SCHEMA,
)
from tests.ai.utilities import random_name_patcher

from mysql.connector.errors import DatabaseError

if tests.MYSQL_ML_ENABLED:
    import mysql.ai.utils
    import numpy as np
    import pandas as pd

    from mysql.ai.utils import (
        atomic_transaction,
        convert_to_df,
        delete_sql_table,
        execute_sql,
        format_value_sql,
        get_random_name,
        is_table_empty,
        source_schema,
        sql_response_to_df,
        sql_table_from_df,
        sql_table_to_df,
        table_exists,
        temporary_sql_tables,
        validate_name,
    )
    from pandas import Timestamp


@unittest.skipIf(not tests.MYSQL_ML_ENABLED, AI_SKIP_MESSAGE)
class TestUtils(tests.MySQLConnectorTests):

    @foreach_cnx(always_setup=True, connection_timeout=DEFAULT_CONNECTION_TIMEOUT)
    def test_execute_sql(self):
        with atomic_transaction(self.cnx) as cursor:
            malicious_input = "Hello World!'); DROP TABLE test; --"
            execute_sql(cursor, "SELECT %s;", (malicious_input,))
            self.assertEqual(sql_response_to_df(cursor).iloc[0, 0], malicious_input)

    @foreach_cnx(always_setup=True, connection_timeout=DEFAULT_CONNECTION_TIMEOUT)
    def test_format_value_sql(self):
        """
        Test None-like arguments
        """
        argument = None
        expected_string, expected_values = "%s", [None]
        param_string, param_values = format_value_sql(argument)
        self.assertEqual(param_string, expected_string)
        self.assertEqual(expected_values, param_values)

        argument = []
        expected_string, expected_values = "%s", [None]
        param_string, param_values = format_value_sql(argument)
        self.assertEqual(param_string, expected_string)
        self.assertEqual(expected_values, param_values)

        argument = {}
        expected_string, expected_values = "%s", [None]
        param_string, param_values = format_value_sql(argument)
        self.assertEqual(param_string, expected_string)
        self.assertEqual(expected_values, param_values)

        """
        Test primitives
        """
        argument = 0
        expected_string, expected_values = "%s", [argument]
        param_string, param_values = format_value_sql(argument)
        self.assertEqual(param_string, expected_string)
        self.assertEqual(expected_values, param_values)

        argument = 1.21
        expected_string, expected_values = "%s", [argument]
        param_string, param_values = format_value_sql(argument)
        self.assertEqual(param_string, expected_string)
        self.assertEqual(expected_values, param_values)

        argument = ";,().=<>!+-*/%&|^~[]{}@#?$`'\"\\"
        expected_string, expected_values = "%s", [argument]
        param_string, param_values = format_value_sql(argument)
        self.assertEqual(param_string, expected_string)
        self.assertEqual(expected_values, param_values)

        argument = True
        expected_string, expected_values = "%s", [argument]
        param_string, param_values = format_value_sql(argument)
        self.assertEqual(param_string, expected_string)
        self.assertEqual(expected_values, param_values)

        """
        Test json-like
        """
        argument = [{"A": []}, [{"B": []}], "C"]
        expected_string, expected_values = "CAST(%s as JSON)", [json.dumps(argument)]
        param_string, param_values = format_value_sql(argument)
        self.assertEqual(param_string, expected_string)
        self.assertEqual(expected_values, param_values)

        argument = {1: {"A": []}, 2: [{"B": []}], 3: "C"}
        expected_string, expected_values = "CAST(%s as JSON)", [json.dumps(argument)]
        param_string, param_values = format_value_sql(argument)
        self.assertEqual(param_string, expected_string)
        self.assertEqual(expected_values, param_values)

        """
        Test escape other object types
        """
        argument = object()
        expected_string, expected_values = "%s", [argument]
        param_string, param_values = format_value_sql(argument)
        self.assertEqual(param_string, expected_string)
        self.assertEqual(expected_values, param_values)

    @foreach_cnx(always_setup=True, connection_timeout=DEFAULT_CONNECTION_TIMEOUT)
    def test_is_table_empty(self):
        with (
            atomic_transaction(self.cnx) as cursor,
            temporary_sql_tables(self.cnx) as temporary_tables,
        ):
            schema_name = DEFAULT_SCHEMA
            table_name = "ABC"

            qualified_name = f"{schema_name}.{table_name}"
            self.assertTrue(not table_exists(cursor, schema_name, table_name))

            # Create table
            execute_sql(
                cursor,
                f"CREATE TABLE IF NOT EXISTS {qualified_name} (id INT PRIMARY KEY);",
            )
            temporary_tables.append((schema_name, table_name))

            self.assertTrue(table_exists(cursor, schema_name, table_name))
            self.assertTrue(is_table_empty(cursor, schema_name, table_name))

            # Insert an element
            execute_sql(
                cursor, f"INSERT INTO {qualified_name}  (id) VALUES (%s);", (1,)
            )
            self.assertTrue(not is_table_empty(cursor, schema_name, table_name))

            # Delete the element
            execute_sql(cursor, f"DELETE FROM {qualified_name}  WHERE id = %s;", (1,))
            self.assertTrue(is_table_empty(cursor, schema_name, table_name))

        with atomic_transaction(self.cnx) as cursor:
            self.assertTrue(not table_exists(cursor, schema_name, table_name))

    @foreach_cnx(always_setup=True, connection_timeout=DEFAULT_CONNECTION_TIMEOUT)
    def test_source_schema(self):
        schema_name = source_schema(self.cnx)
        self.assertEqual(schema_name, DEFAULT_SCHEMA)

        # Test default without making a new schema
        with patch("mysql.ai.utils.utils.execute_sql") as mock_exec:
            mock_conn = MagicMock()
            mock_conn.database = None

            mock_cursor = MagicMock()
            mock_conn.cursor.return_value = mock_cursor

            schema_name = source_schema(mock_conn)
            self.assertEqual(schema_name, mysql.ai.utils.DEFAULT_SCHEMA)

            self.assertEqual(len(mock_exec.call_args_list), 1)
            self.assertEqual(
                mock_exec.call_args_list[0].args[1],
                f"CREATE DATABASE IF NOT EXISTS {mysql.ai.utils.DEFAULT_SCHEMA}",
            )

    @foreach_cnx(always_setup=True, connection_timeout=DEFAULT_CONNECTION_TIMEOUT)
    def test_sql_table_from_df(self):
        # Validates DataFrame round-trip, SQL statement construction, and correct call order using mock_exec
        with (
            atomic_transaction(self.cnx) as cursor,
            temporary_sql_tables(self.cnx) as temporary_tables,
            patch(
                "mysql.ai.utils.utils.execute_sql", wraps=mysql.ai.utils.execute_sql
            ) as mock_exec,
        ):
            df_og = pd.DataFrame(
                {
                    "id": [1, 2],
                    "string": [";,().=<>!+-*/%&|^~[]{}@#?$`'\"\\", "ABC"],
                    "score": [95.0, 89.5],
                }
            )
            qualified_table_name, table_name = sql_table_from_df(
                cursor, DEFAULT_SCHEMA, df_og
            )
            temporary_tables.append((DEFAULT_SCHEMA, table_name))

            split = qualified_table_name.split(".")
            self.assertEqual(len(split), 2)
            self.assertEqual(split[0], DEFAULT_SCHEMA)
            self.assertEqual(split[1], table_name)

            df_copy = sql_table_to_df(cursor, DEFAULT_SCHEMA, table_name)
            self.assertTrue(df_og.equals(df_copy))
            delete_sql_table(cursor, DEFAULT_SCHEMA, table_name)

            expected_calls = [
                (
                    f"CREATE TABLE {qualified_table_name} (id BIGINT, string LONGTEXT, score DOUBLE, PRIMARY KEY (id))",
                    None,
                ),
                (
                    f"INSERT INTO {qualified_table_name} (id, string, score) VALUES (%s, %s, %s)",
                    [1, ";,().=<>!+-*/%&|^~[]{}@#?$`'\"\\", 95.0],
                ),
                (
                    f"INSERT INTO {qualified_table_name} (id, string, score) VALUES (%s, %s, %s)",
                    [2, "ABC", 89.5],
                ),
                (f"SELECT * FROM {qualified_table_name}", None),
                (f"DROP TABLE IF EXISTS {qualified_table_name}", None),
            ]
            self.assertTrue(len(mock_exec.call_args_list), len(expected_calls))

            for call_args, (sql_stmt, params) in zip(
                mock_exec.call_args_list, expected_calls
            ):
                self.assertEqual(call_args.args[1], sql_stmt)

                if params is None:
                    self.assertEqual(0, len(call_args.kwargs))
                else:
                    self.assertEqual({"params": params}, call_args.kwargs)

    @foreach_cnx(always_setup=True, connection_timeout=DEFAULT_CONNECTION_TIMEOUT)
    def test_sql_table_to_df(self):
        with (
            atomic_transaction(self.cnx) as cursor,
            temporary_sql_tables(self.cnx) as temporary_tables,
        ):
            table_name = get_random_name(
                lambda table_name: not table_exists(cursor, DEFAULT_SCHEMA, table_name)
            )
            temporary_tables.append((DEFAULT_SCHEMA, table_name))

            create_table_stmt = f"""
            CREATE TABLE {DEFAULT_SCHEMA}.{table_name} (
                `json` JSON,
                `json2` JSON,
                `int` BIGINT,
                `float` DOUBLE,
                `string` VARCHAR(128),
                `datetime` DATETIME
            );
            """
            execute_sql(cursor, create_table_stmt)

            insert_stmt = f"INSERT INTO {DEFAULT_SCHEMA}.{table_name} (`json`, `json2`, `int`, `float`, `string`, `datetime`) VALUES (CAST(%s as JSON), CAST(%s as JSON), %s, %s, %s, %s)"
            parameters = [
                json.dumps({"A": [1, 2]}),
                json.dumps([]),
                42,
                3.14,
                "hello",
                "2024-06-15 12:34:56",
            ]
            execute_sql(cursor, insert_stmt, parameters)
            expected_row = [
                {"A": [1, 2]},
                [],
                42,
                3.14,
                "hello",
                Timestamp("2024-06-15 12:34:56"),
            ]

            df = sql_table_to_df(cursor, DEFAULT_SCHEMA, table_name)
            row_values = df.iloc[0].values

            for expected, actual in zip(expected_row, row_values):
                self.assertEqual(expected, actual)

    @patch("mysql.ai.utils.utils.extend_sql_table")
    @foreach_cnx(always_setup=True, connection_timeout=DEFAULT_CONNECTION_TIMEOUT)
    def test_sql_table_from_df_fail(self, mock_extend):
        # Tests table cleanup and error handling by simulating backend failure via mock_extend
        with (
            random_name_patcher(),
            patch(
                "mysql.ai.utils.utils.execute_sql", wraps=mysql.ai.utils.execute_sql
            ) as mock_exec,
        ):
            mock_extend.side_effect = DatabaseError("Mock Exception")

            with atomic_transaction(self.cnx) as cursor:
                df_og = pd.DataFrame(
                    {
                        "id": [1, 2, 3],
                        "name": ["Alice", "Bob", "Charlie"],
                        "score": [95.0, 89.5, 78.2],
                    }
                )
                with self.assertRaises(DatabaseError):
                    sql_table_from_df(cursor, DEFAULT_SCHEMA, df_og)

                qualified_table_name = (
                    f"{DEFAULT_SCHEMA}.TEST_MYSQL_CONNECTOR_AAAAAAAAAAAAAAAA"
                )
                expected_calls = [
                    (
                        f"CREATE TABLE {qualified_table_name} (id BIGINT, name LONGTEXT, score DOUBLE, PRIMARY KEY (id))",
                        None,
                    ),
                    (f"DROP TABLE IF EXISTS {qualified_table_name}", None),
                ]

                for call_args, (sql_stmt, params) in zip(
                    mock_exec.call_args_list, expected_calls
                ):
                    self.assertEqual(call_args.args[1], sql_stmt)

                    if params is None:
                        self.assertEqual(0, len(call_args.kwargs))

    @patch("mysql.ai.utils.utils.extend_sql_table")
    @foreach_cnx(always_setup=True, connection_timeout=DEFAULT_CONNECTION_TIMEOUT)
    def test_sql_table_from_df_fail_bad_col(self, mock_extend):
        with (
            random_name_patcher(),
            patch(
                "mysql.ai.utils.utils.execute_sql", wraps=mysql.ai.utils.execute_sql
            ) as mock_exec,
        ):
            mock_extend.side_effect = DatabaseError("Mock Exception")

            with atomic_transaction(self.cnx) as cursor:
                df_og = pd.DataFrame(
                    {
                        ";,().=<>!+-*/%&|^~[]{}@#?$`'\"\\": [1],
                    }
                )
                with self.assertRaises(ValueError):
                    sql_table_from_df(cursor, DEFAULT_SCHEMA, df_og)

                self.assertEqual(len(mock_exec.call_args_list), 0)

    def test_validate_name(self):
        # check valid characters
        validate_name("Ab_0")

        with self.assertRaises(ValueError):
            validate_name(None)

        with self.assertRaises(ValueError):
            validate_name("")

        with self.assertRaises(ValueError):
            validate_name({})

    def test_convert_to_df(self):
        # Checks conversion edge cases: None, copy by value, Series/1D/2D array reshaping and column naming.
        # Should return None if input is None
        self.assertIsNone(convert_to_df(None))

        # Should return a DataFrame copy with the same content and columns
        df = pd.DataFrame({"a": [1, 2], "b": [3, 4]})
        result = convert_to_df(df)
        self.assertIsInstance(result, pd.DataFrame)
        pd.testing.assert_frame_equal(df, result)
        # Should not be the same object
        self.assertIsNot(result, df)

        # Should convert Series to a DataFrame
        s = pd.Series([5, 6, 7])
        result = convert_to_df(s)
        self.assertIsInstance(result, pd.DataFrame)
        self.assertEqual(list(result[0]), [5, 6, 7])

        # 1D array should be reshaped to (n, 1)
        arr = np.array([9, 8, 7])
        result = convert_to_df(arr)
        self.assertIsInstance(result, pd.DataFrame)
        self.assertEqual(result.shape, (3, 1))
        self.assertEqual(list(result.columns), ["feature_0"])

        # 2D array should keep its shape and receive named columns
        arr = np.array([[1, 2], [3, 4]])
        result = convert_to_df(arr, col_prefix="col")
        self.assertIsInstance(result, pd.DataFrame)
        self.assertEqual(result.shape, (2, 2))
        self.assertEqual(list(result.columns), ["col_0", "col_1"])
        self.assertTrue((result.values == arr).all())
