# Copyright (c) 2023, 2024, Oracle and/or its affiliates.
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

"""Concurrency script.

This module checks traces are exported correctly when having one
or more connections at the same time.

Trace context propagation is carried on via query attributes.
MySQL client/server protocol commands supporting query attributes
are `cmd_query` and `cmd_stmt_execute`.

In order to execute this script you need:

1. An OTEL Collector listening to port `COLLECTOR_PORT` at `COLLECTOR_URL`.
2. A MySQL Server with OTEL configured and enabled.
3. mysql-connector-python >= 8.1.0
4. Python packages opentelemetry-api, opentelemetry-sdk and \
    opentelemetry-exporter-otlp-proto-http

This isn't an automated test, it is meant to be executed manually. To confirm
success you must verify trace continuity (linkage between connector and server
spans) by looking at the Collector's UI.

Default configuration is assumed for MySQL Server and OTEL Collector.

```
MySQL Server
------------
port: 3306
host: localhost
user: root
password: ""  # empty string
use_pure: True

OTEL Collector
--------------
port: 4318
url (host): localhost

Context Propagation
-------------------
test_cmd_query: True
```

However you can override any of these defaults according to the following flags:
--mysql-port: int
--mysql-host: str
--mysql-user: str
--mysql-password: str
--cpy-use-pure: bool
--collector-port: int
--collector-host: str
--test-cmd_query: bool
--debug: bool

Example: default config for mysql server and collector, using the c-ext
implementation of connector-python and just running the check
for prepared statements:

`$ python concurrency_check.py --cpy-use-pure=False --test-cmd-query=False`
"""

import logging

from sanity_check import BaseContextPropagationTests, setup_cmd_parser

import mysql.connector

from mysql.connector.opentelemetry.instrumentation import MySQLInstrumentor

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("mysql.connector.connection")
logger.setLevel(logging.DEBUG)
handler = logging.StreamHandler()
logger.addHandler(handler)


instrumentor = MySQLInstrumentor()
BOOL_ARGS = {"cpy_use_pure", "test_cmd_query", "test_cmd_stmt_execute"}


class TestsConcurrentConnections(BaseContextPropagationTests):
    """Concurrency checks."""

    def test_two_concurrent_cnxs(self, prepared=False, app_span_name="concurrent_cnxs"):
        print("\tRunning two concurrent connections...")

        instrumentor.instrument()
        with self._tracer.start_as_current_span(app_span_name):
            cnx1 = mysql.connector.connect(**self._mysql_config)
            cnx2 = mysql.connector.connect(**self._mysql_config)

            cur1, cur2 = cnx1.cursor(prepared=prepared), cnx2.cursor(prepared=prepared)

            cur1.execute("SELECT @@version")
            cur2.execute("SET @x = '2'")

            _ = cur1.fetchall()

            cur2.execute("SELECT @x")
            cur1.execute("SELECT '1'")

            _, _ = cur2.fetchall(), cur1.fetchall()

            cur1.close()
            cur2.close()

            cnx1.close()
            cnx2.close()

        instrumentor.uninstrument()


if __name__ == "__main__":
    config = vars(setup_cmd_parser())

    print("Script configuration")
    print("--------------------")
    for key in config.keys():
        if key in BOOL_ARGS and isinstance(config[key], str):
            if config[key].lower() == "false":
                config[key] = False
            elif config[key].lower() == "true":
                config[key] = True
            else:
                raise ValueError(f"{key} must be a bool")
        print(f"\t{key}: {config[key]}")
    print()

    runner = TestsConcurrentConnections(**config)

    runner.test_two_concurrent_cnxs(prepared=False)
