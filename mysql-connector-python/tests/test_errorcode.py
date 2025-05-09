# Copyright (c) 2012, 2024, Oracle and/or its affiliates.
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

"""Unittests for mysql.connector.errorcode
"""

from datetime import datetime

import tests

from mysql.connector import errorcode


class ErrorCodeTests(tests.MySQLConnectorTests):
    def test__MYSQL_VERSION(self):
        minimum = (5, 6, 6)
        self.assertTrue(isinstance(errorcode._MYSQL_VERSION, tuple))
        self.assertTrue(len(errorcode._MYSQL_VERSION) == 3)
        self.assertTrue(errorcode._MYSQL_VERSION >= minimum)

    def _check_code(self, code, num):
        try:
            self.assertEqual(getattr(errorcode, code), num)
        except AttributeError as err:
            self.fail(err)

    def test_server_error_codes(self):
        cases = {
            "OBSOLETE_ER_HASHCHK": 1000,
            "ER_TRG_INVALID_CREATION_CTX": 1604,
            "ER_CANT_EXECUTE_IN_READ_ONLY_TRANSACTION": 1792,
        }

        for code, num in cases.items():
            self._check_code(code, num)

    def test_client_error_codes(self):
        cases = {
            "CR_UNKNOWN_ERROR": 2000,
            "CR_PROBE_SLAVE_STATUS": 2022,
            "CR_AUTH_PLUGIN_CANNOT_LOAD": 2059,
        }

        for code, num in cases.items():
            self._check_code(code, num)
