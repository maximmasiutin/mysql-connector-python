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

import unittest

import tests

from tests import foreach_cnx
from tests.ai.constants import AI_SKIP_MESSAGE, DEFAULT_CONNECTION_TIMEOUT
from tests.ai.utilities import MyAITest

from mysql.connector.errors import DatabaseError

if tests.MYSQL_ML_ENABLED:
    import numpy as np
    import pandas as pd

    from mysql.ai.ml.transformer import MyGenericTransformer
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    ELEMS_PER_CLASS = 5
    NUM_FEAT = 3
    NUM_CLASSES = 2
    NUM_ROWS = NUM_CLASSES * ELEMS_PER_CLASS


@unittest.skipIf(not tests.MYSQL_ML_ENABLED, AI_SKIP_MESSAGE)
class TestMyGenericTransformer(MyAITest):
    def setUp(self):
        super().setUp()
        self.X = pd.DataFrame(
            np.random.randn(NUM_ROWS, NUM_FEAT),
            columns=[f"feature_{i}" for i in range(NUM_FEAT)],
        )
        self.y = pd.Series(
            [i for _ in range(ELEMS_PER_CLASS) for i in range(NUM_CLASSES)],
            name="target",
        )

    @foreach_cnx(always_setup=True, connection_timeout=DEFAULT_CONNECTION_TIMEOUT)
    def test_pipeline_fit_transform_and_score(self):
        """Test transformer in pipeline and score method."""
        transformer = MyGenericTransformer(self.cnx)
        pipe = Pipeline(
            [("scaler", StandardScaler()), ("mysql_transform", transformer)]
        )
        pipe.fit(self.X, self.y)
        Xt = pipe.transform(self.X)
        self.assertTrue(hasattr(Xt, "shape"))
        self.assertEqual(Xt.shape[0], self.X.shape[0])

        expected_columns = [
            "feature_0",
            "feature_1",
            "feature_2",
            "Prediction",
            "ml_results",
        ]
        self.assertTrue(all([col_name in Xt.columns for col_name in expected_columns]))
        self.assertEqual(Xt.shape[1], len(expected_columns) + 1)

        # Score
        result = pipe.named_steps["mysql_transform"].score(self.X, self.y)
        self.assertTrue(0.0 <= result <= 1.0)

    @foreach_cnx(always_setup=True, connection_timeout=DEFAULT_CONNECTION_TIMEOUT)
    def test_invalid_options_raise(self):
        """Test invalid options for fit, transform, explain, and score each raise DatabaseError."""
        # Fit
        transformer_fit_invalid = MyGenericTransformer(
            self.cnx, fit_extra_options={"bad_option": 42}
        )
        with self.assertRaises(DatabaseError):
            transformer_fit_invalid.fit(self.X, self.y)

        # Transform
        transformer_invalid_options = MyGenericTransformer(
            self.cnx,
            transform_extra_options={"bad_option": 43},
            score_extra_options={"bad_option": 45},
        )
        transformer_invalid_options.fit(self.X, self.y)
        with self.assertRaises(DatabaseError):
            transformer_invalid_options.transform(self.X)
        # Score
        with self.assertRaises(DatabaseError):
            transformer_invalid_options.score(self.X, self.y)
