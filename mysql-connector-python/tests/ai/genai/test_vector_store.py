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
import textwrap
import unittest

from typing import List, Tuple
from unittest.mock import MagicMock, patch

import tests

from tests import foreach_cnx
from tests.ai.constants import (
    AI_SKIP_MESSAGE,
    DEFAULT_CONNECTION_TIMEOUT,
    DEFAULT_SCHEMA,
)
from tests.ai.utilities import MyAITest, random_name_patcher

if tests.MYSQL_ML_ENABLED:
    import mysql.ai.utils

    from langchain_core.documents import Document
    from mysql.ai.genai import MyEmbeddings, MyVectorStore

    texts = ["A", "B", "C"]
    metadatas = [{}, {"key": 1}, {"key": []}, {"key": {}}]

    # Needs to be at least 2d for similarity search with cosine
    embeddings = {
        "A": [1.0, -1.0],
        "B": [1.0, 1.0],
        "C": [1.0, 1.01],
        "Hello world!": [0.0, 0.0],
    }


def get_dummy_embeddings():
    # Produces a MyEmbeddings stub where each string maps to a fixed embedding vector, used for similarity tests.
    def embed_query(text: str) -> List[float]:
        return embeddings[text]

    def embed_documents(texts: List[str]) -> List[List[float]]:
        return [embed_query(text) for text in texts]

    mock = MagicMock(spec=MyEmbeddings)
    mock.embed_query.side_effect = embed_query
    mock.embed_documents.side_effect = embed_documents

    return mock


@unittest.skipIf(not tests.MYSQL_ML_ENABLED, AI_SKIP_MESSAGE)
class TestVectorStore(MyAITest):
    def setUp(self):
        super().setUp()

        self.maxDiff = None

        # Patch both vector_store/utils execute_sql and patch random name generator for deterministic and verifiable testing.
        self.mock_exec = MagicMock(wraps=mysql.ai.utils.execute_sql)
        self.embed_execute_patcher = patch(
            "mysql.ai.genai.vector_store.execute_sql", self.mock_exec
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

    def check_call(self, expected_calls: List[Tuple[str, list]]) -> None:
        # Asserts the generated SQL (after removing whitespace differences) and params sequence for strict correctness.
        call_args_list = self.mock_exec.call_args_list
        self.assertEqual(len(call_args_list), len(expected_calls))
        for call, (expected_stmt, expected_params) in zip(
            call_args_list, expected_calls
        ):
            self.assertEqual(
                textwrap.dedent(call.args[1]).strip(),
                textwrap.dedent(expected_stmt).strip(),
            )
            if expected_params is None:
                self.assertEqual(call.kwargs, {})
            else:
                self.assertEqual(len(call.kwargs), 1)
                self.assertEqual(list(call.kwargs["params"]), expected_params)

    @foreach_cnx(always_setup=True, connection_timeout=DEFAULT_CONNECTION_TIMEOUT)
    def test_from_texts(self):
        embedder = get_dummy_embeddings()

        vector_store = MyVectorStore.from_texts(
            texts, embedder, metadatas=metadatas, db_connection=self.cnx
        )
        results = vector_store.similarity_search("B", k=2)
        vector_store.delete_all()

        qualified_table_name = f"{DEFAULT_SCHEMA}.TEST_MYSQL_CONNECTOR_AAAAAAAAAAAAAAAA"
        expected_calls = [
            (
                f"""
                CREATE TABLE {qualified_table_name} (
                    `id` VARCHAR(128) NOT NULL,
                    `content` TEXT,
                    `metadata` JSON DEFAULT NULL,
                    `embed` vector(%s),
                    PRIMARY KEY (`id`)
                ) ENGINE=InnoDB;
            """,
                [2],
            ),
            (
                f"INSERT INTO {qualified_table_name} (id, content, embed, metadata) VALUES (%s, %s, string_to_vector(%s), %s)",
                ["internal_ai_id_0", "A", "[1.0, -1.0]", None],
            ),
            (
                f"INSERT INTO {qualified_table_name} (id, content, embed, metadata) VALUES (%s, %s, string_to_vector(%s), CAST(%s as JSON))",
                ["internal_ai_id_1", "B", "[1.0, 1.0]", json.dumps(metadatas[1])],
            ),
            (
                f"INSERT INTO {qualified_table_name} (id, content, embed, metadata) VALUES (%s, %s, string_to_vector(%s), CAST(%s as JSON))",
                ["internal_ai_id_2", "C", "[1.0, 1.01]", json.dumps(metadatas[2])],
            ),
            ("SET @mysql_ai.embedding = string_to_vector(%s)", ["[1.0, 1.0]"]),
            (
                f"""
                CALL sys.ML_SIMILARITY_SEARCH(
                    @mysql_ai.embedding,
                    JSON_ARRAY(
                        '{qualified_table_name}'
                    ),
                    JSON_OBJECT(
                        "segment", "content",
                        "segment_embedding", "embed",
                        "document_name", "id"
                    ),
                    2,
                    %s,
                    NULL,
                    NULL,
                    CAST(%s as JSON),
                    @mysql_ai.context,
                    @mysql_ai.context_map,
                    @mysql_ai.retrieval_info
                )
            """,
                [
                    "COSINE",
                    json.dumps(
                        {
                            "max_distance": 0.6,
                            "percentage_distance": 20.0,
                            "segment_overlap": 0,
                        }
                    ),
                ],
            ),
            ("SELECT @mysql_ai.context_map", None),
            (
                f"SELECT id, content, metadata FROM {qualified_table_name} WHERE id = %s",
                ["internal_ai_id_1"],
            ),
            (
                f"SELECT id, content, metadata FROM {qualified_table_name} WHERE id = %s",
                ["internal_ai_id_2"],
            ),
            (f"DROP TABLE IF EXISTS {qualified_table_name}", None),
        ]
        self.check_call(expected_calls)

        expected_results = [
            Document(id="internal_ai_id_1", page_content="B", metadata={"key": 1}),
            Document(id="internal_ai_id_2", page_content="C", metadata={"key": []}),
        ]
        for result, expected_result in zip(results, expected_results):
            self.assertEqual(result, expected_result)

    @foreach_cnx(always_setup=True, connection_timeout=DEFAULT_CONNECTION_TIMEOUT)
    def test_from_texts_no_meta(self):
        embedder = get_dummy_embeddings()

        vector_store = MyVectorStore.from_texts(
            texts, embedder, metadatas=None, db_connection=self.cnx
        )
        results = vector_store.similarity_search("B", k=2)
        vector_store.delete_all()

        qualified_table_name = f"{DEFAULT_SCHEMA}.TEST_MYSQL_CONNECTOR_AAAAAAAAAAAAAAAA"
        expected_calls = [
            (
                f"""
                CREATE TABLE {qualified_table_name} (
                    `id` VARCHAR(128) NOT NULL,
                    `content` TEXT,
                    `metadata` JSON DEFAULT NULL,
                    `embed` vector(%s),
                    PRIMARY KEY (`id`)
                ) ENGINE=InnoDB;
            """,
                [2],
            ),
            (
                f"INSERT INTO {qualified_table_name} (id, content, embed, metadata) VALUES (%s, %s, string_to_vector(%s), %s)",
                ["internal_ai_id_0", "A", "[1.0, -1.0]", None],
            ),
            (
                f"INSERT INTO {qualified_table_name} (id, content, embed, metadata) VALUES (%s, %s, string_to_vector(%s), %s)",
                ["internal_ai_id_1", "B", "[1.0, 1.0]", None],
            ),
            (
                f"INSERT INTO {qualified_table_name} (id, content, embed, metadata) VALUES (%s, %s, string_to_vector(%s), %s)",
                ["internal_ai_id_2", "C", "[1.0, 1.01]", None],
            ),
            ("SET @mysql_ai.embedding = string_to_vector(%s)", ["[1.0, 1.0]"]),
            (
                f"""
                CALL sys.ML_SIMILARITY_SEARCH(
                    @mysql_ai.embedding,
                    JSON_ARRAY(
                        '{qualified_table_name}'
                    ),
                    JSON_OBJECT(
                        "segment", "content",
                        "segment_embedding", "embed",
                        "document_name", "id"
                    ),
                    2,
                    %s,
                    NULL,
                    NULL,
                    CAST(%s as JSON),
                    @mysql_ai.context,
                    @mysql_ai.context_map,
                    @mysql_ai.retrieval_info
                )
            """,
                [
                    "COSINE",
                    json.dumps(
                        {
                            "max_distance": 0.6,
                            "percentage_distance": 20.0,
                            "segment_overlap": 0,
                        }
                    ),
                ],
            ),
            ("SELECT @mysql_ai.context_map", None),
            (
                f"SELECT id, content, metadata FROM {qualified_table_name} WHERE id = %s",
                ["internal_ai_id_1"],
            ),
            (
                f"SELECT id, content, metadata FROM {qualified_table_name} WHERE id = %s",
                ["internal_ai_id_2"],
            ),
            (f"DROP TABLE IF EXISTS {qualified_table_name}", None),
        ]
        self.check_call(expected_calls)

        expected_results = [
            Document(id="internal_ai_id_1", page_content="B"),
            Document(id="internal_ai_id_2", page_content="C"),
        ]
        for result, expected_result in zip(results, expected_results):
            self.assertEqual(result, expected_result)

    @foreach_cnx(always_setup=True, connection_timeout=DEFAULT_CONNECTION_TIMEOUT)
    def test_add_documents(self):
        embedder = get_dummy_embeddings()

        vector_store = MyVectorStore(self.cnx, embedder)

        # check empty
        result = vector_store.add_documents([])
        self.assertEqual(result, [])

        ids, documents = [], []
        for i, (text, metadata) in enumerate(zip(texts, metadatas)):
            ids.append(f"external_id_{i}")
            documents.append(Document(page_content=text, metadata=metadata))

        # check that we validate ids same length as documents
        with self.assertRaises(ValueError):
            vector_store.add_documents(
                documents, ids=[i for i in range(len(documents) + 1)]
            )

        result_ids = vector_store.add_documents(documents, ids=ids)
        self.assertEqual(result_ids, ids)

        vector_store.delete(ids)
        ids = vector_store.add_documents(documents)
        vector_store.delete(ids)

        qualified_table_name1 = (
            f"{DEFAULT_SCHEMA}.TEST_MYSQL_CONNECTOR_AAAAAAAAAAAAAAAA"
        )
        qualified_table_name2 = (
            f"{DEFAULT_SCHEMA}.TEST_MYSQL_CONNECTOR_AAAAAAAAAAAAAAAB"
        )
        expected_calls = [
            (
                f"""
                CREATE TABLE {qualified_table_name1} (
                    `id` VARCHAR(128) NOT NULL,
                    `content` TEXT,
                    `metadata` JSON DEFAULT NULL,
                    `embed` vector(%s),
                    PRIMARY KEY (`id`)
                ) ENGINE=InnoDB;
            """,
                [2],
            ),
            (
                f"INSERT INTO {qualified_table_name1} (id, content, embed, metadata) VALUES (%s, %s, string_to_vector(%s), %s)",
                ["external_id_0", "A", "[1.0, -1.0]", None],
            ),
            (
                f"INSERT INTO {qualified_table_name1} (id, content, embed, metadata) VALUES (%s, %s, string_to_vector(%s), CAST(%s as JSON))",
                ["external_id_1", "B", "[1.0, 1.0]", json.dumps(metadatas[1])],
            ),
            (
                f"INSERT INTO {qualified_table_name1} (id, content, embed, metadata) VALUES (%s, %s, string_to_vector(%s), CAST(%s as JSON))",
                ["external_id_2", "C", "[1.0, 1.01]", json.dumps(metadatas[2])],
            ),
            (
                f"DELETE FROM {qualified_table_name1} WHERE id = %s",
                ["external_id_0"],
            ),
            (
                f"DELETE FROM {qualified_table_name1} WHERE id = %s",
                ["external_id_1"],
            ),
            (
                f"DELETE FROM {qualified_table_name1} WHERE id = %s",
                ["external_id_2"],
            ),
            (f"DROP TABLE IF EXISTS {qualified_table_name1}", None),
            (
                f"""
                CREATE TABLE {qualified_table_name2} (
                    `id` VARCHAR(128) NOT NULL,
                    `content` TEXT,
                    `metadata` JSON DEFAULT NULL,
                    `embed` vector(%s),
                    PRIMARY KEY (`id`)
                ) ENGINE=InnoDB;
            """,
                [2],
            ),
            (
                f"INSERT INTO {qualified_table_name2} (id, content, embed, metadata) VALUES (%s, %s, string_to_vector(%s), %s)",
                ["internal_ai_id_0", "A", "[1.0, -1.0]", None],
            ),
            (
                f"INSERT INTO {qualified_table_name2} (id, content, embed, metadata) VALUES (%s, %s, string_to_vector(%s), CAST(%s as JSON))",
                ["internal_ai_id_1", "B", "[1.0, 1.0]", json.dumps(metadatas[1])],
            ),
            (
                f"INSERT INTO {qualified_table_name2} (id, content, embed, metadata) VALUES (%s, %s, string_to_vector(%s), CAST(%s as JSON))",
                ["internal_ai_id_2", "C", "[1.0, 1.01]", json.dumps(metadatas[2])],
            ),
            (
                f"DELETE FROM {qualified_table_name2} WHERE id = %s",
                ["internal_ai_id_0"],
            ),
            (
                f"DELETE FROM {qualified_table_name2} WHERE id = %s",
                ["internal_ai_id_1"],
            ),
            (
                f"DELETE FROM {qualified_table_name2} WHERE id = %s",
                ["internal_ai_id_2"],
            ),
            (f"DROP TABLE IF EXISTS {qualified_table_name2}", None),
        ]
        self.check_call(expected_calls)

    @foreach_cnx(always_setup=True, connection_timeout=DEFAULT_CONNECTION_TIMEOUT)
    def test_empty_similarity_search(self):
        embedder = get_dummy_embeddings()

        vector_store = MyVectorStore(self.cnx, embedder)

        # check empty
        result = vector_store.add_documents([])
        self.assertEqual(result, [])

        # Check that the empty similarity search does not fail
        result = vector_store.similarity_search("test query")
        self.assertEqual(result, [])

        # No queries should have been executed for the empty similarity search
        expected_calls = []
        self.check_call(expected_calls)

    @foreach_cnx(always_setup=True, connection_timeout=DEFAULT_CONNECTION_TIMEOUT)
    def test_context_manager(self):
        qualified_table_name = f"{DEFAULT_SCHEMA}.TEST_MYSQL_CONNECTOR_AAAAAAAAAAAAAAAA"

        with MyVectorStore(self.cnx) as vector_store:
            vector_store.add_texts(["text1"])

        self.assertEqual(
            self.mock_exec.call_args_list[-1].args[1],
            f"DROP TABLE IF EXISTS {qualified_table_name}",
        )

    @foreach_cnx(always_setup=True, connection_timeout=DEFAULT_CONNECTION_TIMEOUT)
    def test_missing_connection(self):
        with self.assertRaises(ValueError):
            MyVectorStore.from_texts(["Text1", "Text2"], get_dummy_embeddings())
