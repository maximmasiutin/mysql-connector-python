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
import unittest

from typing import List, Optional, Tuple
from unittest.mock import MagicMock, patch

import tests

from tests import foreach_cnx
from tests.ai.constants import (
    AI_SKIP_MESSAGE,
    DEFAULT_CONNECTION_TIMEOUT,
    DEFAULT_SCHEMA,
)
from tests.ai.utilities import MyAITest, random_name_patcher

from mysql.connector.errors import DatabaseError

if tests.MYSQL_ML_ENABLED:
    import mysql.ai.utils

    from mysql.ai.genai import MyEmbeddings


@unittest.skipIf(not tests.MYSQL_ML_ENABLED, AI_SKIP_MESSAGE)
class TestMyEmbedding(MyAITest):
    def setUp(self):
        super().setUp()

        # Patch both embedding/utils execute_sql and patch random name generation for deterministic testing.
        self.mock_exec = MagicMock(wraps=mysql.ai.utils.execute_sql)
        self.embed_execute_patcher = patch(
            "mysql.ai.genai.embedding.execute_sql", self.mock_exec
        )
        self.utils_execute_patcher = patch(
            "mysql.ai.utils.utils.execute_sql", self.mock_exec
        )

        self.name_patcher = random_name_patcher()

        self.embed_execute_patcher.start()
        self.utils_execute_patcher.start()
        self.name_patcher.start()

    def tearDown(self):
        self.embed_execute_patcher.stop()
        self.utils_execute_patcher.stop()
        self.name_patcher.stop()

        super().tearDown()

    def get_expected_sql_for_embed(
        self,
        qualified_table_name: str,
        texts: List[str],
        options: Optional[dict] = None,
    ) -> List[str]:
        # Programmatic construction of expected SQL interaction sequence for embedding.
        if options is None:
            options_value = "%s"
        else:
            options_value = "CAST(%s as JSON)"
            options = json.dumps(options)
        embed_params = [options]

        expected_calls = [
            # (SQL statement, params)
            (
                f"CREATE TABLE {qualified_table_name} (id BIGINT, text LONGTEXT, PRIMARY KEY (id))",
                None,
            ),
        ]

        for i, text in enumerate(texts):
            expected_calls.append(
                (
                    f"INSERT INTO {qualified_table_name} (id, text) VALUES (%s, %s)",
                    [i, text],
                )
            )

        expected_calls += [
            (
                f"CALL sys.ML_EMBED_TABLE('{qualified_table_name}.text', '{qualified_table_name}.embeddings', {options_value})",
                embed_params,
            ),
            (f"SELECT * FROM {qualified_table_name}", None),
            (f"DROP TABLE IF EXISTS {qualified_table_name}", None),
        ]
        return expected_calls

    def check_call(
        self,
        responses: List[List[float]],
        expected_calls: List[Tuple[str, list]],
    ) -> None:
        # Composite assertion for both output embedding shape/type and full SQL call trace (mock_exec).
        call_args_list = self.mock_exec.call_args_list

        # Validate consistent shape and type of responses
        if responses:
            response_length = len(responses[0])
            for response in responses:
                self.assertIsInstance(response, list)
                self.assertEqual(response_length, len(response))
                self.assertTrue(all(isinstance(x, float) for x in response))

        # Validate that the db queries/stmts are as expected
        self.assertEqual(len(call_args_list), len(expected_calls))
        for call, (expected_stmt, expected_params) in zip(
            call_args_list, expected_calls
        ):
            self.assertEqual(call.args[1], expected_stmt)
            if not expected_params:
                self.assertEqual(len(call.kwargs), 0)
            else:
                self.assertEqual(len(call.kwargs), 1)
                self.assertEqual(call.kwargs["params"], expected_params)

    """
    Embedding tests
    """

    @foreach_cnx(always_setup=True, connection_timeout=DEFAULT_CONNECTION_TIMEOUT)
    def test_embed_query_basic(self):
        embedder = MyEmbeddings(self.cnx)
        response = [embedder.embed_query("Text1")]

        expected_calls = [('SELECT sys.ML_EMBED_ROW("%s", %s)', ("Text1", None))]

        self.check_call(response, expected_calls)

    @foreach_cnx(always_setup=True, connection_timeout=DEFAULT_CONNECTION_TIMEOUT)
    def test_embed_document_basic(self):
        embedder = MyEmbeddings(self.cnx)
        response = embedder.embed_documents(["Text1"])
        self.assertEqual(len(response), 1)

        table_name = f"{DEFAULT_SCHEMA}.TEST_MYSQL_CONNECTOR_AAAAAAAAAAAAAAAA"
        expected_calls = self.get_expected_sql_for_embed(table_name, ["Text1"])

        self.check_call(response, expected_calls)

    @foreach_cnx(always_setup=True, connection_timeout=DEFAULT_CONNECTION_TIMEOUT)
    def test_embed_document_multi(self):
        embedder = MyEmbeddings(self.cnx)
        response = embedder.embed_documents(["Text1", "Text2"])
        self.assertEqual(len(response), 2)

        table_name = f"{DEFAULT_SCHEMA}.TEST_MYSQL_CONNECTOR_AAAAAAAAAAAAAAAA"
        expected_calls = self.get_expected_sql_for_embed(table_name, ["Text1", "Text2"])

        self.check_call(response, expected_calls)

    @foreach_cnx(always_setup=True, connection_timeout=DEFAULT_CONNECTION_TIMEOUT)
    def test_embed_document_empty(self):
        embedder = MyEmbeddings(self.cnx)
        response = embedder.embed_documents([])
        self.assertEqual(len(response), 0)

        expected_calls = []

        self.check_call(response, expected_calls)

    @foreach_cnx(always_setup=True, connection_timeout=DEFAULT_CONNECTION_TIMEOUT)
    def test_embed_document_valid_options(self):
        options = {"truncate": True}
        embedder = MyEmbeddings(self.cnx, options=options)
        response = embedder.embed_documents(["Text1"])
        self.assertEqual(len(response), 1)

        table_name = f"{DEFAULT_SCHEMA}.TEST_MYSQL_CONNECTOR_AAAAAAAAAAAAAAAA"
        expected_calls = self.get_expected_sql_for_embed(table_name, ["Text1"], options)

        self.check_call(response, expected_calls)

    @foreach_cnx(always_setup=True, connection_timeout=DEFAULT_CONNECTION_TIMEOUT)
    def test_embed_failure(self):
        options = {"truncate": False}
        embedder = MyEmbeddings(self.cnx, options=options)
        LONG_QUERY = 1024
        with self.assertRaises(ValueError):
            embedder.embed_documents(
                ["Text1", " ".join(["A" for _ in range(LONG_QUERY)])]
            )

    @foreach_cnx(always_setup=True, connection_timeout=DEFAULT_CONNECTION_TIMEOUT)
    def test_embed_document_invalid_options(self):
        options = {"fake_option": True}
        with self.assertRaises(DatabaseError):
            embedder = MyEmbeddings(self.cnx, options=options)
            embedder.embed_documents(["Text1"])

        table_name = f"{DEFAULT_SCHEMA}.TEST_MYSQL_CONNECTOR_AAAAAAAAAAAAAAAA"
        expected_calls = [
            # (SQL statement, params)
            (
                f"CREATE TABLE {table_name} (id BIGINT, text LONGTEXT, PRIMARY KEY (id))",
                None,
            ),
            (
                f"INSERT INTO {table_name} (id, text) VALUES (%s, %s)",
                [0, "Text1"],
            ),
            (
                f"CALL sys.ML_EMBED_TABLE('{table_name}.text', '{table_name}.embeddings', CAST(%s as JSON))",
                [json.dumps(options)],
            ),
            (f"DROP TABLE IF EXISTS {table_name}", None),
        ]
        self.check_call(None, expected_calls)
