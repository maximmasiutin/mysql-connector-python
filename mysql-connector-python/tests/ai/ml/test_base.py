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

    ELEMS_PER_CLASS = 5
    NUM_FEAT = 3
    NUM_CLASSES = 2
    NUM_ROWS = ELEMS_PER_CLASS * NUM_CLASSES


@unittest.skipIf(not tests.MYSQL_ML_ENABLED, AI_SKIP_MESSAGE)
class TestMyBaseMLModel(MyAITest):
    def setUp(self):
        super().setUp()
        # Use a classifier as concrete for the base API
        self.X = pd.DataFrame(
            np.random.randn(NUM_ROWS, NUM_FEAT),
            columns=[f"feature_{i}" for i in range(NUM_FEAT)],
        )
        self.y = pd.Series(
            [i for _ in range(ELEMS_PER_CLASS) for i in range(NUM_CLASSES)],
            name="target",
        )

    @foreach_cnx(always_setup=True, connection_timeout=DEFAULT_CONNECTION_TIMEOUT)
    def test_export_import_model(self):
        clf = MyClassifier(self.cnx)

        model_info = clf.get_model_info()
        self.assertEqual(model_info, None)

        clf.fit(self.X, self.y)

        model_info = clf.get_model_info()
        self.assertIsInstance(model_info, dict)

        model_name = model_info["model_handle"]

        clf2 = MyClassifier(self.cnx, model_name=model_name)

        self.assertTrue(np.all(clf.predict(self.X) == clf2.predict(self.X)))
        self.assertEqual(clf.get_model_info(), clf2.get_model_info())

        clf2._delete_model()

        with self.assertRaises(DatabaseError):
            clf.predict(self.X)

        with self.assertRaises(DatabaseError):
            clf2.predict(self.X)
