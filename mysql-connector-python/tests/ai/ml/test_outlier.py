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

from unittest.mock import MagicMock, patch

import tests

from tests import foreach_cnx
from tests.ai.constants import AI_SKIP_MESSAGE, DEFAULT_CONNECTION_TIMEOUT
from tests.ai.utilities import MyAITest

from mysql.connector.errors import DatabaseError

if tests.MYSQL_ML_ENABLED:
    import numpy as np
    import pandas as pd

    from mysql.ai.ml.outlier import EPS, MyAnomalyDetector
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    ELEMS_PER_CLASS = 5
    NUM_FEAT = 3
    NUM_ROWS = ELEMS_PER_CLASS * 2


@unittest.skipIf(not tests.MYSQL_ML_ENABLED, AI_SKIP_MESSAGE)
class TestMyAnomalyDetector(MyAITest):
    def setUp(self):
        super().setUp()
        self.X = pd.DataFrame(
            np.random.randn(NUM_ROWS, NUM_FEAT),
            columns=[f"feature_{i}" for i in range(NUM_FEAT)],
        )

    def _make_mock_detector(self, threshold=0.8):
        """
        Helper: construct MyAnomalyDetector with MyBaseMLModel.__init__ patched as a no-op (for pure unit test).
        """
        # Creates an anomaly detector with all real database functionality mocked out, usable for pure prediction/unit testing.
        with patch("mysql.ai.ml.base.MyBaseMLModel.__init__", return_value=None):
            det = MyAnomalyDetector(MagicMock())
            det._model = MagicMock()
            # Mock catalog model info to provide threshold used by decision_function
            if threshold is not None:
                det.get_model_info = MagicMock(
                    return_value={
                        "model_metadata": {
                            "training_params": {
                                "anomaly_detection_threshold": threshold
                            }
                        }
                    }
                )
            else:
                # Simulate missing threshold in trained model metadata
                det.get_model_info = MagicMock(
                    return_value={
                        "model_metadata": {
                            "training_params": {
                                # intentionally empty
                            }
                        }
                    }
                )
        return det

    @foreach_cnx(always_setup=True, connection_timeout=DEFAULT_CONNECTION_TIMEOUT)
    @unittest.skip("Test will fail until MySQL 9.5.0 release")
    def test_pipeline_and_output_shapes(self):
        """
        Test MyAnomalyDetector as head in sklearn Pipeline, with preprocessor, strict output shape and value checks.
        """
        detector = MyAnomalyDetector(self.cnx)
        pipe = Pipeline([("scaler", StandardScaler()), ("anomaly", detector)])
        pipe.fit(self.X)  # Outlier detection is typically unsupervised

        preds = pipe.predict(self.X)
        self.assertEqual(preds.ndim, 1)
        self.assertEqual(preds.shape, (len(self.X),))
        self.assertTrue(np.isin(preds, [-1, 1]).all())
        self.assertTrue(np.isfinite(preds).all())

        decision = pipe.named_steps["anomaly"].decision_function(self.X)
        self.assertEqual(decision.ndim, 1)
        self.assertEqual(decision.shape, (len(self.X),))
        self.assertTrue(np.isfinite(decision).all())

        scores = pipe.named_steps["anomaly"].score_samples(self.X)
        self.assertEqual(scores.ndim, 1)
        self.assertEqual(scores.shape, (len(self.X),))
        self.assertTrue(np.isfinite(scores).all())

    @foreach_cnx(always_setup=True, connection_timeout=DEFAULT_CONNECTION_TIMEOUT)
    def test_invalid_options_raise(self):
        """
        Test DatabaseError is raised if invalid options are provided via constructor to fit_extra_options,
        score_extra_options for their respective operations.
        """
        # Constructor no longer accepts outlier_threshold; validation moved to trained model metadata.

        # Invalid fit options
        det_fit_invalid = MyAnomalyDetector(
            self.cnx, fit_extra_options={"invalid_option": True}
        )
        with self.assertRaises(DatabaseError):
            det_fit_invalid.fit(self.X)

        # Invalid score options (used for score_samples/decision_function)
        det_score_invalid = MyAnomalyDetector(
            self.cnx, score_extra_options={"invalid_option": True}
        )
        det_score_invalid.fit(self.X)
        with self.assertRaises(DatabaseError):
            det_score_invalid.predict(self.X)
        with self.assertRaises(DatabaseError):
            det_score_invalid.decision_function(self.X)
        with self.assertRaises(DatabaseError):
            det_score_invalid.score_samples(self.X)

    def test_missing_threshold_raises_value_error(self):
        """Unit test: missing anomaly_detection_threshold in model info raises ValueError in decision_function."""
        X = pd.DataFrame(np.zeros((1, 1)))
        det = self._make_mock_detector(threshold=None)
        det._model.predict.return_value = {
            "ml_results": pd.Series([{"probabilities": {"normal": 0.5}}])
        }
        with self.assertRaises(ValueError):
            det.decision_function(X)

    def test_missing_model_info_raises_value_error(self):
        """Unit test: missing model catalog info raises ValueError in decision_function."""
        X = pd.DataFrame(np.zeros((1, 1)))
        det = self._make_mock_detector()
        # Force model catalog to return None to simulate non-existent model
        det.get_model_info = MagicMock(return_value=None)
        det._model.predict.return_value = {
            "ml_results": pd.Series([{"probabilities": {"normal": 0.5}}])
        }
        with self.assertRaises(ValueError):
            det.decision_function(X)

    def test_predict_logic_with_mock(self):
        """Unit test: verify label logic for various predicted probabilities using a mocked backend."""
        # This is a pure logic test: threshold and probability boundary checking—all predictions are fully mocked.
        X = pd.DataFrame(np.zeros((3, 2)))

        # Set up detector so that threshold = 0.9, so boundary = logits(0.1)
        det = self._make_mock_detector(threshold=0.9)
        # Prepare p = 0.05 (high anomaly), p = 0.5, p = 0.99 (not anomaly)
        backend_probs = np.array([0.05, 0.5, 0.99])
        # Properly mock the modern ml_results return format
        det._model.predict.return_value = {
            "ml_results": pd.Series(
                [{"probabilities": {"normal": p}} for p in backend_probs]
            )
        }

        pred = det.predict(X)
        np.testing.assert_array_equal(pred, [-1, 1, 1])

    def test_score_samples_shape_and_values(self):
        """Unit test: verify score_samples shape and value mapping using a mock backend."""
        # This test only verifies the mathematical mapping from probabilities to scores, not any DB code.
        X = pd.DataFrame(np.ones((2, 3)))
        det = self._make_mock_detector()
        det._model.predict.return_value = {
            "ml_results": pd.Series(
                [
                    {"probabilities": {"normal": 0.75}},
                    {"probabilities": {"normal": 0.25}},
                ]
            )
        }
        scores = det.score_samples(X)
        np.testing.assert_allclose(scores, [1.0986, -1.0986], rtol=1e-3)

    def test_decision_function_consistency(self):
        """Unit test: decision_function output is score_samples - boundary."""
        X = pd.DataFrame(np.zeros((1, 4)))
        det = self._make_mock_detector(threshold=0.7)
        det._model.predict.return_value = {
            "ml_results": pd.Series([{"probabilities": {"normal": 0.7}}])
        }
        scores = det.score_samples(X)
        decision = det.decision_function(X)
        boundary = det.boundary
        np.testing.assert_allclose(scores - boundary, decision, rtol=1e-10)

    def test_predict_handles_vectorized_and_scalar(self):
        """Unit test: predict works for scalar and vectorized outputs."""
        X = pd.DataFrame(np.zeros((2, 1)))
        det = self._make_mock_detector()
        det._model.predict.return_value = {
            "ml_results": pd.Series(
                [
                    {"probabilities": {"normal": 0.4}},
                    {"probabilities": {"normal": 0.2}},
                ]
            )
        }
        preds = det.predict(X)
        self.assertEqual(preds.shape, (2,))

    def test_score_samples_clips_extreme_probabilities(self):
        X = pd.DataFrame(np.zeros((2, 1)))
        det = self._make_mock_detector()
        det._model.predict.return_value = {
            "ml_results": pd.Series(
                [
                    {"probabilities": {"normal": 0.0}},
                    {"probabilities": {"normal": 1.0}},
                ]
            )
        }
        scores = det.score_samples(X)
        expected = np.array([np.log(EPS / (1.0 - EPS)), np.log((1.0 - EPS) / EPS)])
        np.testing.assert_allclose(scores, expected, rtol=1e-6, atol=1e-12)
        self.assertTrue(np.isfinite(scores).all())

    def test_decision_function_uses_cached_boundary(self):
        X = pd.DataFrame(np.zeros((2, 2)))
        det = self._make_mock_detector(threshold=0.6)
        # First call establishes boundary via get_model_info
        det._model.predict.return_value = {
            "ml_results": pd.Series(
                [
                    {"probabilities": {"normal": 0.6}},
                    {"probabilities": {"normal": 0.6}},
                ]
            )
        }
        _ = det.decision_function(X)
        old_boundary = det.boundary
        # Ensure no additional catalog access when boundary already cached
        det.get_model_info.reset_mock()
        # Second call with different scores should reuse cached boundary
        det._model.predict.return_value = {
            "ml_results": pd.Series(
                [
                    {"probabilities": {"normal": 0.4}},
                    {"probabilities": {"normal": 0.8}},
                ]
            )
        }
        _ = det.decision_function(X)
        self.assertEqual(det.get_model_info.call_count, 0)
        self.assertEqual(det.boundary, old_boundary)

    def test_predict_tie_at_boundary_is_inlier(self):
        """If decision_function equals 0, predict should return +1 (inlier)."""
        X = pd.DataFrame(np.zeros((1, 1)))
        # threshold = 0.6 -> boundary uses logits(1 - 0.6) = logits(0.4)
        det = self._make_mock_detector(threshold=0.6)
        # Provide normal prob exactly equal to 0.4 so score_samples equals boundary
        det._model.predict.return_value = {
            "ml_results": pd.Series([{"probabilities": {"normal": 0.4}}])
        }
        pred = det.predict(X)
        np.testing.assert_array_equal(pred, [1])
