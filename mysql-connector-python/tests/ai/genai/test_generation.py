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

from typing import Optional
from unittest.mock import patch

import tests

from tests import foreach_cnx
from tests.ai.constants import AI_SKIP_MESSAGE, DEFAULT_CONNECTION_TIMEOUT
from tests.ai.utilities import MyAITest

from mysql.connector.abstracts import MySQLConnectionAbstract
from mysql.connector.errors import DatabaseError

if tests.MYSQL_ML_ENABLED:
    import mysql.ai.utils

    from mysql.ai.genai import MyLLM


@unittest.skipIf(not tests.MYSQL_ML_ENABLED, AI_SKIP_MESSAGE)
class TestMyLLM(MyAITest):
    def _llm_hello_world(
        self,
        conn: MySQLConnectionAbstract,
        prompt: str = "Hello world",
        options: Optional[dict] = None,
    ):
        # Utility to invoke LLM consistently for all tests, with configurable prompt and options.
        options = {} if options is None else options
        llm = MyLLM(conn)
        output = llm.invoke(prompt, **options)
        return output

    def check_call(
        self, response: Optional[str], call_args: "CallArgs", query: str, params: tuple
    ) -> None:
        # Validates response and checks full SQL call signature (args/kwargs) to match expected generation input.
        if response is not None:
            self.assertIsInstance(response, str)
            self.assertTrue(len(response) > 1)

        args, kwargs = call_args.args, call_args.kwargs
        self.assertEqual(len(args), 2)
        self.assertEqual(len(kwargs), 1)

        self.assertEqual(args[1], query)
        self.assertEqual(kwargs["params"], params)

    """
    Generation tests
    """

    @foreach_cnx(always_setup=True, connection_timeout=DEFAULT_CONNECTION_TIMEOUT)
    def test_llm_basic(self):
        with patch(
            "mysql.ai.genai.generation.execute_sql", wraps=mysql.ai.utils.execute_sql
        ) as mock_exec:
            # Use patching and mock-exec to ensure no real DB execution and to fully check query/param generation.
            response = self._llm_hello_world(self.cnx)
            self.assertEqual(len(mock_exec.call_args_list), 1)
            self.check_call(
                response,
                mock_exec.call_args_list[0],
                'SELECT sys.ML_GENERATE("%s", %s);',
                ("Hello world", None),
            )

    @foreach_cnx(always_setup=True, connection_timeout=DEFAULT_CONNECTION_TIMEOUT)
    def test_llm_valid_option(self):
        with patch(
            "mysql.ai.genai.generation.execute_sql", wraps=mysql.ai.utils.execute_sql
        ) as mock_exec:
            options = {"max_tokens": 1}
            response = self._llm_hello_world(self.cnx, options=options)
            self.assertEqual(len(mock_exec.call_args_list), 1)
            self.check_call(
                response,
                mock_exec.call_args_list[0],
                'SELECT sys.ML_GENERATE("%s", CAST(%s as JSON));',
                ("Hello world", json.dumps(options)),
            )

    @foreach_cnx(always_setup=True, connection_timeout=DEFAULT_CONNECTION_TIMEOUT)
    def test_llm_invalid_option(self):
        with patch(
            "mysql.ai.genai.generation.execute_sql", wraps=mysql.ai.utils.execute_sql
        ) as mock_exec:
            options = {"max_tokens": -1}
            with self.assertRaises(DatabaseError):
                self._llm_hello_world(self.cnx, options=options)

            self.assertEqual(len(mock_exec.call_args_list), 1)
            self.check_call(
                None,
                mock_exec.call_args_list[0],
                'SELECT sys.ML_GENERATE("%s", CAST(%s as JSON));',
                ("Hello world", json.dumps(options)),
            )

    @foreach_cnx(always_setup=True, connection_timeout=DEFAULT_CONNECTION_TIMEOUT)
    def test_llm_empty_input(self):
        with patch(
            "mysql.ai.genai.generation.execute_sql", wraps=mysql.ai.utils.execute_sql
        ) as mock_exec:
            response = self._llm_hello_world(self.cnx, prompt="")

            self.assertEqual(len(mock_exec.call_args_list), 1)
            self.check_call(
                response,
                mock_exec.call_args_list[0],
                'SELECT sys.ML_GENERATE("%s", %s);',
                ("", None),
            )

    @foreach_cnx(always_setup=True, connection_timeout=DEFAULT_CONNECTION_TIMEOUT)
    def test_llm_stop_option(self):
        with patch(
            "mysql.ai.genai.generation.execute_sql", wraps=mysql.ai.utils.execute_sql
        ) as mock_exec:
            llm = MyLLM(self.cnx)
            stop_words = ["stop1", "stop2"]
            response = llm.invoke("Hello world", stop=stop_words)
            self.assertEqual(len(mock_exec.call_args_list), 1)
            self.check_call(
                response,
                mock_exec.call_args_list[0],
                'SELECT sys.ML_GENERATE("%s", CAST(%s as JSON));',
                ("Hello world", json.dumps({"stop_sequences": stop_words})),
            )

    @foreach_cnx(always_setup=True, connection_timeout=DEFAULT_CONNECTION_TIMEOUT)
    def test_llm_multiple_calls(self):
        with patch(
            "mysql.ai.genai.generation.execute_sql", wraps=mysql.ai.utils.execute_sql
        ) as mock_exec:
            llm = MyLLM(self.cnx)

            response1 = llm.invoke("Hello1")
            self.check_call(
                response1,
                mock_exec.call_args_list[0],
                'SELECT sys.ML_GENERATE("%s", %s);',
                ("Hello1", None),
            )

            response2 = llm.invoke("Hello2")
            self.check_call(
                response2,
                mock_exec.call_args_list[1],
                'SELECT sys.ML_GENERATE("%s", %s);',
                ("Hello2", None),
            )

            self.assertEqual(len(mock_exec.call_args_list), 2)

    """
    Model fields tests
    """

    @foreach_cnx(always_setup=True, connection_timeout=DEFAULT_CONNECTION_TIMEOUT)
    def test__llm_type(self):
        llm = MyLLM(self.cnx)
        self.assertEqual(llm._llm_type, "mysql_heatwave_llm")
