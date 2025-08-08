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

    from mysql.ai.ml.classifier import MyClassifier
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    ELEMS_PER_CLASS = 5
    NUM_FEAT = 3
    NUM_CLASSES = 2
    NUM_ROWS = NUM_CLASSES * ELEMS_PER_CLASS


@unittest.skipIf(not tests.MYSQL_ML_ENABLED, AI_SKIP_MESSAGE)
class TestMyClassifier(MyAITest):
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
    def test_pipeline_and_output_shapes(self):
        """
        Test MyClassifier as the head in sklearn Pipeline (with preprocessor), with strict shape checks.
        """
        clf = MyClassifier(self.cnx)
        pipe = Pipeline([("scaler", StandardScaler()), ("mysql_clf", clf)])
        pipe.fit(self.X, self.y)

        preds = pipe.predict(self.X)
        # 1D output, (N,)
        self.assertEqual(preds.ndim, 1)
        self.assertEqual(preds.shape, (len(self.X),))

        # 2D proba output: (N, C), in [0,1], rows ~1
        proba = pipe.named_steps["mysql_clf"].predict_proba(self.X)
        n_classes = len(set(self.y))
        self.assertEqual(proba.ndim, 2)
        self.assertEqual(proba.shape, (len(self.X), n_classes))
        self.assertTrue((proba >= 0).all() and (proba <= 1).all())

    @foreach_cnx(always_setup=True, connection_timeout=DEFAULT_CONNECTION_TIMEOUT)
    def test_invalid_options_raise(self):
        """
        Test DatabaseError is raised if invalid options are provided via constructor to fit_extra_options and
        predict_extra_options for their respective operations.
        """
        # Invalid fit options
        clf_fit_invalid = MyClassifier(
            self.cnx, fit_extra_options={"invalid_option": True}
        )
        with self.assertRaises(DatabaseError):
            clf_fit_invalid.fit(self.X, self.y)

        # Invalid predict options
        clf_predict_invalid = MyClassifier(
            self.cnx, predict_extra_options={"invalid_option": True}
        )
        clf_predict_invalid.fit(self.X, self.y)
        with self.assertRaises(DatabaseError):
            clf_predict_invalid.predict(self.X)
        with self.assertRaises(DatabaseError):
            clf_predict_invalid.predict_proba(self.X)

    @foreach_cnx(always_setup=True, connection_timeout=DEFAULT_CONNECTION_TIMEOUT)
    def test_explain_predictions_with_fake_options(self):
        """Test explain with fake explain_extra_options, should raise DatabaseError."""
        # Intentionally pass invalid explain_extra_options to confirm error handling.
        model = MyClassifier(self.cnx, explain_extra_options={"fake_option": 123})
        model.fit(self.X, self.y)
        with self.assertRaises(DatabaseError):
            model.explain_predictions(self.X)
