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

import copy
import unittest

from typing import List, Tuple
from unittest.mock import MagicMock, patch

import tests

from tests import foreach_cnx
from tests.ai.constants import (
    AI_SKIP_MESSAGE,
    DEFAULT_CONNECTION_TIMEOUT,
    DEFAULT_SCHEMA,
    MYSQL_CONNECTOR_RANDOM_NAME_SPACE,
)
from tests.ai.utilities import MyAITest, random_name_patcher

from mysql.connector.errors import DatabaseError

if tests.MYSQL_ML_ENABLED:
    import mysql.ai.utils
    import numpy as np
    import pandas as pd

    from mysql.ai.ml.model import MyModel

ELEMS_PER_CLASS = 5
NUM_FEAT = 2
NUM_CLASSES = 2
NUM_ROWS = NUM_CLASSES * ELEMS_PER_CLASS


@unittest.skipIf(not tests.MYSQL_ML_ENABLED, AI_SKIP_MESSAGE)
class TestMyModel(MyAITest):
    def setUp(self):
        self.maxDiff = None
        super().setUp()

        # Patch all execute_sql usage & random name generator for deterministic validation and SQL call capture.
        self.mock_exec = MagicMock(wraps=mysql.ai.utils.execute_sql)
        self.embed_execute_patcher = patch(
            "mysql.ai.ml.model.execute_sql", self.mock_exec
        )
        self.utils_execute_patcher = patch(
            "mysql.ai.utils.utils.execute_sql", self.mock_exec
        )

        self.name_patcher = random_name_patcher()

        self.embed_execute_patcher.start()
        self.utils_execute_patcher.start()
        self.name_patcher.start()

        self.X = pd.DataFrame(
            np.random.randn(NUM_ROWS, NUM_FEAT),
            columns=[f"feature_{i}" for i in range(NUM_FEAT)],
        )

        self.y = pd.DataFrame(
            [i for _ in range(ELEMS_PER_CLASS) for i in range(NUM_CLASSES)],
            columns=[f"target" for _ in range(1)],
        )

    def tearDown(self):
        # Undo all patching for clean test isolation.
        self.embed_execute_patcher.stop()
        self.utils_execute_patcher.stop()
        self.name_patcher.stop()

        super().tearDown()

    def check_call(
        self,
        call_args_list: List,
        expected_calls: List[Tuple[str, list]],
    ) -> None:
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

    @foreach_cnx(always_setup=True, connection_timeout=DEFAULT_CONNECTION_TIMEOUT)
    def test_classification(self):
        X, y = self.X, self.y

        model_name = f"{MYSQL_CONNECTOR_RANDOM_NAME_SPACE}_test_model"
        model_var = f"mysql_ai.{model_name}"

        ml_model = MyModel(self.cnx, model_name=model_name)
        # Verify the initial SQL preamble for model instantiation.
        expected_calls = [
            ("CALL sys.ML_CREATE_OR_UPGRADE_CATALOG();", None),
            (f"SET @mysql_ai.{model_name} = %s;", (model_name,)),
        ]
        self.check_call(self.mock_exec.call_args_list, expected_calls)
        self.assertEqual(len(self.mock_exec.call_args_list), len(expected_calls))
        self.mock_exec.reset_mock()

        ml_model.fit(X, y)
        table_name = f"{MYSQL_CONNECTOR_RANDOM_NAME_SPACE}_AAAAAAAAAAAAAAAA"
        target_row = f"target"
        # The following verifies the full ML training SQL sequence produced by .fit().
        expected_calls = [
            (
                f"CREATE TABLE {DEFAULT_SCHEMA}.{table_name} (feature_0 DOUBLE, feature_1 DOUBLE, {target_row} BIGINT)",
                None,
            ),
            (
                f"DELETE FROM ML_SCHEMA_root.MODEL_CATALOG WHERE model_handle = @{model_var}",
                None,
            ),
            (
                f"CALL sys.ML_TRAIN('{DEFAULT_SCHEMA}.{table_name}', '{target_row}', CAST(%s as JSON), @{model_var})",
                ['{"task": "classification"}'],
            ),
            (f"DROP TABLE IF EXISTS {DEFAULT_SCHEMA}.{table_name}", None),
        ]
        self.check_call(
            [*self.mock_exec.call_args_list[:1], *self.mock_exec.call_args_list[-3:]],
            expected_calls,
        )
        self.assertEqual(
            len(self.mock_exec.call_args_list), len(expected_calls) + len(X)
        )
        self.mock_exec.reset_mock()

        """
        Check model info
        """
        ml_model.get_model_info()
        self.mock_exec.reset_mock()

        """
        Get values
        """
        explanations = ml_model.explain_model()
        expected_calls = [
            (f"CALL sys.ML_MODEL_LOAD(@{model_var}, NULL);", None),
            (
                f"SELECT model_explanation FROM ML_SCHEMA_root.MODEL_CATALOG WHERE model_handle = @{model_var}",
                None,
            ),
        ]
        self.check_call(self.mock_exec.call_args_list, expected_calls)
        self.assertEqual(len(self.mock_exec.call_args_list), len(expected_calls))
        self.mock_exec.reset_mock()

        predictions = ml_model.predict(X)
        table_name = f"{MYSQL_CONNECTOR_RANDOM_NAME_SPACE}_AAAAAAAAAAAAAAAB"
        target_table_name = f"{MYSQL_CONNECTOR_RANDOM_NAME_SPACE}_AAAAAAAAAAAAAAAC"
        expected_calls = [
            (
                f"CREATE TABLE {DEFAULT_SCHEMA}.{table_name} (feature_0 DOUBLE, feature_1 DOUBLE)",
                None,
            ),
            (f"CALL sys.ML_MODEL_LOAD(@{model_var}, NULL);", None),
            (
                f"CALL sys.ML_PREDICT_TABLE('{DEFAULT_SCHEMA}.{table_name}', @{model_var}, '{DEFAULT_SCHEMA}.{target_table_name}', %s)",
                [None],
            ),
            (f"SELECT * FROM {DEFAULT_SCHEMA}.{target_table_name}", None),
            (f"DROP TABLE IF EXISTS {DEFAULT_SCHEMA}.{table_name}", None),
            (f"DROP TABLE IF EXISTS {DEFAULT_SCHEMA}.{target_table_name}", None),
        ]
        self.check_call(
            [*self.mock_exec.call_args_list[:1], *self.mock_exec.call_args_list[-5:]],
            expected_calls,
        )
        self.assertEqual(
            len(self.mock_exec.call_args_list), len(expected_calls) + len(X)
        )
        self.mock_exec.reset_mock()

        score = ml_model.score(X, y, "balanced_accuracy")
        table_name = f"{MYSQL_CONNECTOR_RANDOM_NAME_SPACE}_AAAAAAAAAAAAAAAE"
        target_row = f"{MYSQL_CONNECTOR_RANDOM_NAME_SPACE}_AAAAAAAAAAAAAAAD"
        expected_calls = [
            (
                f"CREATE TABLE {DEFAULT_SCHEMA}.{table_name} (feature_0 DOUBLE, feature_1 DOUBLE, {target_row} BIGINT)",
                None,
            ),
            (f"CALL sys.ML_MODEL_LOAD(@{model_var}, NULL);", None),
            (
                f"CALL sys.ML_SCORE('{DEFAULT_SCHEMA}.{table_name}', '{target_row}', @{model_var}, %s, @{model_var}.score, %s)",
                ["balanced_accuracy", None],
            ),
            (f"SELECT @{model_var}.score", None),
            (f"DROP TABLE IF EXISTS {DEFAULT_SCHEMA}.{table_name}", None),
        ]
        self.check_call(
            [*self.mock_exec.call_args_list[:1], *self.mock_exec.call_args_list[-4:]],
            expected_calls,
        )
        self.assertEqual(
            len(self.mock_exec.call_args_list), len(expected_calls) + len(X)
        )
        self.mock_exec.reset_mock()

        pred_explanations = ml_model.explain_predictions(X)
        table_name = f"{MYSQL_CONNECTOR_RANDOM_NAME_SPACE}_AAAAAAAAAAAAAAAF"
        target_table_name = f"{MYSQL_CONNECTOR_RANDOM_NAME_SPACE}_AAAAAAAAAAAAAAAG"
        expected_calls = [
            (
                f"CREATE TABLE {DEFAULT_SCHEMA}.{table_name} (feature_0 DOUBLE, feature_1 DOUBLE)",
                None,
            ),
            (f"CALL sys.ML_MODEL_LOAD(@{model_var}, NULL);", None),
            (
                f"CALL sys.ML_EXPLAIN_TABLE('myconnpy.{table_name}', @{model_var}, 'myconnpy.{target_table_name}', CAST(%s as JSON))",
                ['{"prediction_explainer": "permutation_importance"}'],
            ),
            (f"SELECT * FROM {DEFAULT_SCHEMA}.{target_table_name}", None),
            (f"DROP TABLE IF EXISTS {DEFAULT_SCHEMA}.{table_name}", None),
            (f"DROP TABLE IF EXISTS {DEFAULT_SCHEMA}.{target_table_name}", None),
        ]
        self.check_call(
            [*self.mock_exec.call_args_list[:1], *self.mock_exec.call_args_list[-5:]],
            expected_calls,
        )
        self.assertEqual(
            len(self.mock_exec.call_args_list), len(expected_calls) + len(X)
        )
        self.mock_exec.reset_mock()

        """
        Check explanations
        """
        explanations_cleaned = copy.deepcopy(explanations)
        explanations_cleaned["permutation_importance"]["feature_0"] = None
        explanations_cleaned["permutation_importance"]["feature_1"] = None
        explanations_expected = {
            "permutation_importance": {"feature_0": None, "feature_1": None}
        }
        self.assertEqual(explanations_expected, explanations_cleaned)

        """
        Check predictions
        """
        processed_columns = list(predictions.columns)
        processed_columns[0] = "ID"
        col_info = list(zip(processed_columns, predictions.dtypes))
        expected_col_info = [
            ("ID", np.dtype("int64")),
            ("feature_0", np.dtype("float64")),
            ("feature_1", np.dtype("float64")),
            ("Prediction", np.dtype("int64")),
            ("ml_results", np.dtype("O")),
        ]
        col_info.sort(), expected_col_info.sort()
        self.assertEqual(col_info, expected_col_info)
        self.assertEqual(list(predictions.shape), [y.shape[0], len(expected_col_info)])

        """
        Check score
        """
        self.assertTrue(0.0 <= score <= 1.0)

        """
        Check pred_explanations
        """
        processed_columns = list(pred_explanations.columns)
        processed_columns[0] = "ID"
        expected_info = {
            "ID": np.dtype("int64"),
            "feature_0": np.dtype("float64"),
            "feature_1": np.dtype("float64"),
            "Prediction": np.dtype("int64"),
            "Notes": np.dtype("O"),
            "ml_results": np.dtype("O"),
        }
        for col_name, col_type in zip(processed_columns, pred_explanations.dtypes):
            if col_name in expected_info:
                self.assertEqual(expected_info.pop(col_name), col_type)
            else:
                self.assertTrue(
                    col_name in ["feature_0_attribution", "feature_1_attribution"]
                )
        self.assertEqual(expected_info, {})
        self.assertEqual(list(predictions.shape), [y.shape[0], predictions.shape[1]])

        """
        Check repeatability
        """
        self.assertEqual(explanations, ml_model.explain_model())
        self.assertTrue(predictions.equals(ml_model.predict(X)))
        self.assertEqual(score, ml_model.score(X, y, "balanced_accuracy"))
        self.assertTrue(pred_explanations.equals(ml_model.explain_predictions(X)))

        """
        Check making new model with same alias
        """
        ml_model_copy = MyModel(self.cnx, model_name=model_name)

        self.assertEqual(explanations, ml_model_copy.explain_model())
        self.assertTrue(predictions.equals(ml_model_copy.predict(X)))
        self.assertEqual(score, ml_model_copy.score(X, y, "balanced_accuracy"))
        self.assertTrue(pred_explanations.equals(ml_model_copy.explain_predictions(X)))

        ml_model._delete_model()

    @foreach_cnx(always_setup=True, connection_timeout=DEFAULT_CONNECTION_TIMEOUT)
    def test_anomaly(self):
        """
        Basic test primarily to check that anomaly detection does not throw any unexpected errors
        """
        X, y = self.X, self.y

        ml_model = MyModel(self.cnx, task="anomaly_detection")
        ml_model._delete_model()

        ml_model.fit(X, None)

        ml_model.explain_model()
        ml_model.predict(X)
        ml_model.score(X, y, "balanced_accuracy")
        with self.assertRaises(DatabaseError):
            ml_model.explain_predictions(X)
        ml_model._delete_model()

    @foreach_cnx(always_setup=True, connection_timeout=DEFAULT_CONNECTION_TIMEOUT)
    def test_invalid_operation_order(self):
        """
        We never train a model, so we should not be able to run downstream tasks
        """
        X, y = self.X, self.y

        ml_model = MyModel(self.cnx)

        with self.assertRaises(DatabaseError):
            ml_model.explain_model()
        with self.assertRaises(DatabaseError):
            ml_model.predict(X)
        with self.assertRaises(DatabaseError):
            ml_model.score(X, y, "balanced_accuracy")
        with self.assertRaises(DatabaseError):
            ml_model.explain_predictions(X)

    @foreach_cnx(always_setup=True, connection_timeout=DEFAULT_CONNECTION_TIMEOUT)
    def test_invalid_option_key(self):
        """
        Check that we properly validate and provide option keys

        NOTE: We do our most robust checks here instead of with valid options
        as explain_predictions's underlying SQL procedure does not currently
        support any options that are compatible with mysql-connector-python
        - 2025-08-08
        """
        X, y = self.X, self.y

        fake_options = {"fake_option": 1}

        # "Randomly" assigned name
        model_name = f"{MYSQL_CONNECTOR_RANDOM_NAME_SPACE}_AAAAAAAAAAAAAAAA"
        model_var = f"mysql_ai.{model_name}"

        ml_model = MyModel(self.cnx)
        ml_model._delete_model()

        expected_calls = [
            ("CALL sys.ML_CREATE_OR_UPGRADE_CATALOG();", None),
            (
                f"SELECT * FROM ML_SCHEMA_root.MODEL_CATALOG WHERE model_handle = %s",
                (model_name,),
            ),
            (f"SET @{model_var} = %s;", (model_name,)),
            (
                f"DELETE FROM ML_SCHEMA_root.MODEL_CATALOG WHERE model_handle = @{model_var}",
                None,
            ),
        ]
        # raise Exception(self.mock_exec.call_args_list)
        self.check_call(self.mock_exec.call_args_list, expected_calls)
        self.assertEqual(len(self.mock_exec.call_args_list), len(expected_calls))
        self.mock_exec.reset_mock()

        with self.assertRaises(DatabaseError):
            ml_model.fit(X, y, options=fake_options)
        table_name = f"{MYSQL_CONNECTOR_RANDOM_NAME_SPACE}_AAAAAAAAAAAAAAAB"
        target_row = f"target"
        expected_calls = [
            (
                f"CREATE TABLE {DEFAULT_SCHEMA}.{table_name} (feature_0 DOUBLE, feature_1 DOUBLE, {target_row} BIGINT)",
                None,
            ),
            (
                f"DELETE FROM ML_SCHEMA_root.MODEL_CATALOG WHERE model_handle = @{model_var}",
                None,
            ),
            (
                f"CALL sys.ML_TRAIN('{DEFAULT_SCHEMA}.{table_name}', '{target_row}', CAST(%s as JSON), @{model_var})",
                ['{"fake_option": 1, "task": "classification"}'],
            ),
            (f"DROP TABLE IF EXISTS {DEFAULT_SCHEMA}.{table_name}", None),
        ]
        self.check_call(
            [*self.mock_exec.call_args_list[:1], *self.mock_exec.call_args_list[-3:]],
            expected_calls,
        )
        self.assertEqual(
            len(self.mock_exec.call_args_list), len(expected_calls) + len(X)
        )
        self.mock_exec.reset_mock()

        ml_model.fit(X, y)
        table_name = f"{MYSQL_CONNECTOR_RANDOM_NAME_SPACE}_AAAAAAAAAAAAAAAC"
        target_row = f"target"
        expected_calls = [
            (
                f"CREATE TABLE {DEFAULT_SCHEMA}.{table_name} (feature_0 DOUBLE, feature_1 DOUBLE, {target_row} BIGINT)",
                None,
            ),
            (
                f"DELETE FROM ML_SCHEMA_root.MODEL_CATALOG WHERE model_handle = @{model_var}",
                None,
            ),
            (
                f"CALL sys.ML_TRAIN('{DEFAULT_SCHEMA}.{table_name}', '{target_row}', CAST(%s as JSON), @{model_var})",
                ['{"task": "classification"}'],
            ),
            (f"DROP TABLE IF EXISTS {DEFAULT_SCHEMA}.{table_name}", None),
        ]
        self.check_call(
            [*self.mock_exec.call_args_list[:1], *self.mock_exec.call_args_list[-3:]],
            expected_calls,
        )
        self.assertEqual(
            len(self.mock_exec.call_args_list), len(expected_calls) + len(X)
        )
        self.mock_exec.reset_mock()

        with self.assertRaises(DatabaseError):
            ml_model.predict(X, options=fake_options)
        table_name = f"{MYSQL_CONNECTOR_RANDOM_NAME_SPACE}_AAAAAAAAAAAAAAAD"
        target_table_name = f"{MYSQL_CONNECTOR_RANDOM_NAME_SPACE}_AAAAAAAAAAAAAAAE"
        expected_calls = [
            (
                f"CREATE TABLE {DEFAULT_SCHEMA}.{table_name} (feature_0 DOUBLE, feature_1 DOUBLE)",
                None,
            ),
            (f"CALL sys.ML_MODEL_LOAD(@{model_var}, NULL);", None),
            (
                f"CALL sys.ML_PREDICT_TABLE('{DEFAULT_SCHEMA}.{table_name}', @{model_var}, '{DEFAULT_SCHEMA}.{target_table_name}', CAST(%s as JSON))",
                ['{"fake_option": 1}'],
            ),
            (f"DROP TABLE IF EXISTS {DEFAULT_SCHEMA}.{table_name}", None),
            (f"DROP TABLE IF EXISTS {DEFAULT_SCHEMA}.{target_table_name}", None),
        ]
        self.check_call(
            [*self.mock_exec.call_args_list[:1], *self.mock_exec.call_args_list[-4:]],
            expected_calls,
        )
        self.assertEqual(
            len(self.mock_exec.call_args_list), len(expected_calls) + len(X)
        )
        self.mock_exec.reset_mock()

        with self.assertRaises(DatabaseError):
            ml_model.score(X, y, "balanced_accuracy", options=fake_options)
        table_name = f"{MYSQL_CONNECTOR_RANDOM_NAME_SPACE}_AAAAAAAAAAAAAAAG"
        target_row = f"{MYSQL_CONNECTOR_RANDOM_NAME_SPACE}_AAAAAAAAAAAAAAAF"
        expected_calls = [
            (
                f"CREATE TABLE {DEFAULT_SCHEMA}.{table_name} (feature_0 DOUBLE, feature_1 DOUBLE, {target_row} BIGINT)",
                None,
            ),
            (f"CALL sys.ML_MODEL_LOAD(@{model_var}, NULL);", None),
            (
                f"CALL sys.ML_SCORE('{DEFAULT_SCHEMA}.{table_name}', '{target_row}', @{model_var}, %s, @{model_var}.score, CAST(%s as JSON))",
                ["balanced_accuracy", '{"fake_option": 1}'],
            ),
            (f"DROP TABLE IF EXISTS {DEFAULT_SCHEMA}.{table_name}", None),
        ]
        self.check_call(
            [*self.mock_exec.call_args_list[:1], *self.mock_exec.call_args_list[-3:]],
            expected_calls,
        )
        self.assertEqual(
            len(self.mock_exec.call_args_list), len(expected_calls) + len(X)
        )
        self.mock_exec.reset_mock()

        with self.assertRaises(DatabaseError):
            ml_model.explain_predictions(X, options=fake_options)
        table_name = f"{MYSQL_CONNECTOR_RANDOM_NAME_SPACE}_AAAAAAAAAAAAAAAH"
        target_table_name = f"{MYSQL_CONNECTOR_RANDOM_NAME_SPACE}_AAAAAAAAAAAAAAAI"
        expected_calls = [
            (
                f"CREATE TABLE {DEFAULT_SCHEMA}.{table_name} (feature_0 DOUBLE, feature_1 DOUBLE)",
                None,
            ),
            (f"CALL sys.ML_MODEL_LOAD(@{model_var}, NULL);", None),
            (
                f"CALL sys.ML_EXPLAIN_TABLE('myconnpy.{table_name}', @{model_var}, 'myconnpy.{target_table_name}', CAST(%s as JSON))",
                ['{"fake_option": 1}'],
            ),
            (f"DROP TABLE IF EXISTS {DEFAULT_SCHEMA}.{table_name}", None),
            (f"DROP TABLE IF EXISTS {DEFAULT_SCHEMA}.{target_table_name}", None),
        ]
        self.check_call(
            [*self.mock_exec.call_args_list[:1], *self.mock_exec.call_args_list[-4:]],
            expected_calls,
        )
        self.assertEqual(
            len(self.mock_exec.call_args_list), len(expected_calls) + len(X)
        )
        self.mock_exec.reset_mock()

        ml_model._delete_model()

    @foreach_cnx(always_setup=True, connection_timeout=DEFAULT_CONNECTION_TIMEOUT)
    def test_valid_option_key(self):
        """
        Check that we properly forward along options. We can do this by checking that invalid values throw errors and valid values work without issue.
        """
        X, y = self.X, self.y

        ml_model = MyModel(self.cnx, task="anomaly_detection")

        with self.assertRaises(DatabaseError):
            ml_model.fit(X, None, options={"exclude_column_list": ["ids"]})
        ml_model.fit(X, None, options={"exclude_column_list": ["feature_0"]})

        with self.assertRaises(DatabaseError):
            ml_model.predict(X, options={"threshold": -1.0})
        ml_model.predict(X, options={"threshold": 0.0})

        with self.assertRaises(DatabaseError):
            ml_model.score(X, y, "precision_at_k", options={"topk": -1})
        ml_model.score(X, y, "precision_at_k", options={"topk": 10})

        ml_model._delete_model()

    @foreach_cnx(always_setup=True, connection_timeout=DEFAULT_CONNECTION_TIMEOUT)
    def test_forecasting(self):
        data = {
            "C0": [
                2016,
                2017,
                2018,
                2019,
                2020,
                2021,
                2022,
                2023,
                2024,
                2025,
                2026,
                2027,
                2028,
                2029,
                2030,
                2031,
                2032,
                2033,
            ],
            "C1": [
                5141280,
                4169320,
                -6117510,
                4240520,
                -765548,
                -2419130,
                6113810,
                2843360,
                -3605160,
                5526540,
                2457080,
                1680460,
                3544160,
                -3083790,
                -7132180,
                2919490,
                7507210,
                -4632270,
            ],
            "C2": [
                -2005884417,
                -2016618842,
                466787207,
                -146322759,
                -1937283532,
                -1223832992,
                -664275221,
                -2144935961,
                -227541896,
                1222380629,
                1360642676,
                -3850890,
                737213162,
                -2114547172,
                -2113917636,
                -325129819,
                -1579914004,
                -1782430355,
            ],
            "C3": [
                -95648400000000,
                5197890000000,
                9637310000000,
                -58668400000000,
                17690700000000,
                -5368850000000,
                13145700000000,
                121560000000000,
                -79559000000000,
                -74323200000000,
                136942000000000,
                -86288600000000,
                30627000000000,
                14566100000000,
                76392300000000,
                -46361100000000,
                37199300000000,
                -73774600000000,
            ],
        }

        df = pd.DataFrame(data)

        y = df["C1"].copy()
        X = df.drop(columns=["C1"])
        X["C0"] = pd.to_datetime(X["C0"].astype(str) + "-01-01")

        # Add datetime column
        self.X["ddate"] = pd.date_range(
            start="2022-01-01", periods=NUM_ROWS, freq="D"
        ).astype("datetime64[ns]")

        task = "forecasting"
        ml_model = MyModel(self.cnx, task=task)

        ml_model.fit(
            X, y, options={"datetime_index": "C0", "endogenous_variables": ["C1"]}
        )

        ml_model.predict(X)

        ml_model._delete_model()

    @foreach_cnx(always_setup=True, connection_timeout=DEFAULT_CONNECTION_TIMEOUT)
    def test_log_anomaly_detection(self):
        sample_sentences = [
            "The quick brown fox jumps over the lazy dog.",
            "Data science is transforming business decisions.",
            "Cloud computing offers on-demand scalability.",
            "Machine learning models require quality data.",
            "Python is a popular language for analytics.",
            "Natural language processing enables chatbots.",
            "Security and compliance are top enterprise concerns.",
            "Visualization helps make complex data accessible.",
            "Continuous integration improves software delivery.",
            "Customer experience is key to business success.",
        ]

        X = pd.DataFrame(
            {
                "id": range(1, len(sample_sentences) + 1),  # auto-increment from 1
                "log": sample_sentences,
            }
        )

        task = "log_anomaly_detection"

        ml_model = MyModel(self.cnx, task=task)

        ml_model.fit(X, None, options={"exclude_column_list": ["id"]})

        ml_model.predict(X)

        ml_model._delete_model()

    @foreach_cnx(always_setup=True, connection_timeout=DEFAULT_CONNECTION_TIMEOUT)
    def test_anomaly_detection(self):
        X = self.X

        task = "anomaly_detection"

        ml_model = MyModel(self.cnx, task=task)

        ml_model.fit(X, None)

        ml_model.predict(X)

        ml_model._delete_model()

    @foreach_cnx(always_setup=True, connection_timeout=DEFAULT_CONNECTION_TIMEOUT)
    def test_recommendation(self):
        X = pd.DataFrame(
            {
                "C0": ["AAAA", "B", "C", "D", "EEE", "ABC", "CEG", "DE", "AB", "BC"],
                "C1": ["tv"] * 10,
                "C2": [
                    "test",
                    "random",
                    "tea",
                    "coffee",
                    "test1",
                    "random1",
                    "tea2",
                    "coffee2",
                    "test3",
                    "random3",
                ],
                "C3": [10, -10, 0, 4, 5, -5, 0, 4, 10, -10],
                "C4": ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J"],
                "C5": [0, 1, 2, 4, 2, 1, 3, 4.2, 2.1, 3],
                "C6": pd.to_datetime(
                    [
                        f"{year}-01-01"
                        for year in [
                            2018,
                            2019,
                            2017,
                            2016,
                            2015,
                            2014,
                            2013,
                            2012,
                            2022,
                            2023,
                        ]
                    ]
                ),
            }
        )

        # Target DataFrame (y)
        y = pd.DataFrame({"target": [0, 3, 1, 2, 5, 4, 1, 2, 4, 0]})

        task = "recommendation"
        ml_model = MyModel(self.cnx, task=task)

        ml_model.fit(X, y, options={"users": "C1", "items": "C2"})

        ml_model.predict(X)

        ml_model._delete_model()

    @foreach_cnx(always_setup=True, connection_timeout=DEFAULT_CONNECTION_TIMEOUT)
    def test_topic_modeling(self):
        sample_sentences = [
            "The quick brown fox jumps over the lazy dog.",
            "Data science is transforming business decisions.",
            "Cloud computing offers on-demand scalability.",
            "Machine learning models require quality data.",
            "Python is a popular language for analytics.",
            "Natural language processing enables chatbots.",
            "Security and compliance are top enterprise concerns.",
            "Visualization helps make complex data accessible.",
            "Continuous integration improves software delivery.",
            "Customer experience is key to business success.",
        ]

        X = pd.DataFrame(
            {
                "target": list(range(len(sample_sentences))),
                "text_feature": sample_sentences,
            }
        )

        task = "topic_modeling"
        ml_model = MyModel(self.cnx, task=task)

        ml_model.fit(X, None, options={"document_column": "text_feature"})

        ml_model.predict(X)

        ml_model._delete_model()

    @foreach_cnx(always_setup=True, connection_timeout=DEFAULT_CONNECTION_TIMEOUT)
    def test_standard_tasks(self):
        X, y = self.X, self.y

        standard_tasks = [
            "classification",
            "regression",
        ]
        for task in standard_tasks:
            ml_model = MyModel(self.cnx, task=task)

            ml_model.fit(X, y)

            ml_model.predict(X)

            ml_model._delete_model()
