# Copyright (c) 2024, 2025, Oracle and/or its affiliates.
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

"""VECTOR Type Tests."""

import datetime
import math
import os
import platform
import struct
import unittest

from array import array

import tests

import mysql.connector
import mysql.connector.aio

from mysql.connector.constants import MYSQL_VECTOR_TYPE_CODE, FieldType
from mysql.connector.errors import DatabaseError, InterfaceError, ProgrammingError


LOCAL_PLATFORM = platform.platform().lower() if hasattr(platform, "platform") else ""
PLATFORM_IS_SOLARIS = "sunos-" in LOCAL_PLATFORM


@unittest.skipIf(
    tests.MYSQL_VERSION < (9, 0, 0),
    "MySQL Server 8.4.0 and older don't support VECTOR types.",
)
def setUpModule() -> None:
    global VECTOR_PLUGIN_LOADED

    VECTOR_PLUGIN_LOADED = True
    with mysql.connector.connect(**tests.get_mysql_config()) as cnx:
        with cnx.cursor() as cur:
            cur.execute(
                "SELECT component_urn from mysql.component"
                + " where component_urn = 'file://component_vector'"
            )
            if not cur.fetchall():
                try:
                    cur.execute("INSTALL COMPONENT 'file://component_vector'")
                except (ProgrammingError, DatabaseError):
                    VECTOR_PLUGIN_LOADED = False


@unittest.skipIf(
    tests.MYSQL_VERSION < (9, 0, 0),
    "MySQL Server 8.4.0 and older don't support VECTOR types.",
)
def tearDownModule() -> None:
    with mysql.connector.connect(**tests.get_mysql_config()) as cnx:
        with cnx.cursor() as cur:
            if VECTOR_PLUGIN_LOADED:
                cur.execute("UNINSTALL COMPONENT 'file://component_vector'")


class _BaseCommon:
    """Common code."""

    table_name = "wl16164"
    insert = (
        f"""INSERT INTO {table_name}(
        Student_Id,
        Embedding,
        First_name,
        Date_Of_Birth
    )"""
        + " VALUES ({0})"
    )

    v1 = array(MYSQL_VECTOR_TYPE_CODE, [3.141516, 2.719065, -87.539401])
    v2 = array(MYSQL_VECTOR_TYPE_CODE, (-3.141516, 5.769005, -0.334013))
    v3 = array(MYSQL_VECTOR_TYPE_CODE, (9.147116, -76.769115, -5.354053))

    exp_vector_value = lambda obj, exp_type, i: (
        getattr(obj, f"v{i}").tobytes() if exp_type == bytes else getattr(obj, f"v{i}")
    )

    stmt_create_proc = """
    CREATE PROCEDURE {0}(IN record_id INT, OUT birth_date DATE,
                                                            OUT my_embedding VECTOR)
        BEGIN
            INSERT INTO {1}(Student_Id, Date_Of_Birth, Embedding)
                VALUES ({2}, '{3}', {4});
            SELECT Date_Of_Birth INTO birth_date FROM {5}
                WHERE Student_Id = record_id;
            SELECT Embedding INTO my_embedding FROM {6}
                WHERE Student_Id = record_id;
        END
    """

    vector_max_dim = 16384

    def setUp(self) -> None:
        with mysql.connector.connect(**tests.get_mysql_config()) as cnx:
            with cnx.cursor() as cur:
                cur.execute(f"DROP TABLE IF EXISTS {self.table_name}")
                cur.execute(
                    f"""
                    CREATE TABLE {self.table_name} (
                        Student_Id INT,
                        Embedding VECTOR(3),
                        First_name VARCHAR (100),
                        Date_Of_Birth DATE,
                    PRIMARY KEY(Student_Id )
                    )
                """
                )

    def tearDown(self) -> None:
        with mysql.connector.connect(**tests.get_mysql_config()) as cnx:
            with cnx.cursor() as cur:
                cur.execute(f"DROP TABLE IF EXISTS {self.table_name}")


class _BaseVectorTests(_BaseCommon):
    """Base class for VectorTests."""

    def _test_execute_kernel(self, cur_conf, fetch_method, record_id):
        """Execute statements **with** the `%s` parameter bounding style.

        Checkpoints:
            * Ingest VECTOR values as binary strings (HEX) when prepared=False.
            * Ingest VECTOR values as byte strings when prepared=True.
            * Check `cur.executemany` and  `cur.execute`.
            * Check `cur.{fetchmethod}`.
            * Check `NULL` VECTOR values are returned as `None`.
            * Check the previous points with sync and async connections.
        """
        data = [
            [
                1,
                self.prep_vector(self.v1, cur_conf),
                "Amit",
                datetime.date(2004, 12, 22),
            ],
            [
                2,
                self.prep_vector(self.v2, cur_conf),
                "Manik",
                datetime.date(2006, 7, 4),
            ],
            [
                3,
                self.prep_vector(self.v3, cur_conf),
                "Sabrina",
                datetime.date(1997, 11, 2),
            ],
            [4, None, None, None],
        ]
        v, field_type, null_value = None, None, None
        s_bind = self.s_bind(cur_conf)

        with self.cnx.cursor(**cur_conf) as cur:
            if cur_conf.get("prepared"):
                for row in data[:3]:
                    cur.execute(
                        self.insert.format(s_bind),
                        row,
                    )
            else:
                cur.executemany(self.insert.format(s_bind), data[:3])

            cur.execute(self.insert.format("%s, %s, %s, %s"), data[-1])
            cur.execute(f"SELECT * from {self.table_name} WHERE Student_Id={record_id}")
            if fetch_method == "fetchmany":
                res = cur.fetchmany(size=1)[0]
            elif fetch_method == "fetchall":
                res = cur.fetchall()[0]
            else:
                res = cur.fetchone()
            v = res["Embedding"] if cur_conf.get("dictionary") else res[1]
            field_type = cur.description[1][1]

            cur.execute(f"SELECT * from {self.table_name} WHERE Student_Id=4")
            res = cur.fetchone()
            null_value = res["Embedding"] if cur_conf.get("dictionary") else res[1]

        self.cnx.rollback()

        exp_instance = (
            bytes if cur_conf.get("raw") and not cur_conf.get("prepared") else array
        )

        if isinstance(v, bytearray):
            v = bytes(v)

        self.assertEqual(field_type, FieldType.VECTOR)
        self.assertIsInstance(v, exp_instance)
        self.assertEqual(v, self.exp_vector_value(exp_instance, record_id))
        self.assertEqual(null_value, None)

    def _test_callproc_kernel(self, cur_conf, record_id) -> None:
        """Call a stored procedure.

        TODO: The server returns a wrong `field type` for types such as DATE and
        VECTOR when getting results after calling a stored procedure. It's a server bug.

        In the meantime, C/Py will return VECTOR types as `bytes` strings.
        """
        # `callproc` is not supported in the prepared statement protocol yet
        if cur_conf.get("prepared"):
            return

        tbn = self.table_name
        stmt_proc = self.stmt_create_proc.format(
            tbn,
            tbn,
            record_id,
            datetime.date(2006, 7, 4),
            self.stmt_create_proc_arg_4(record_id),
            tbn,
            tbn,
        )
        v, field_type = None, None

        with self.cnx.cursor(**cur_conf) as cur:
            cur.execute(f"DROP PROCEDURE IF EXISTS {tbn}")
            cur.execute(stmt_proc)
            res = cur.callproc(f"{tbn}", (record_id, None, None))
            v = res[f"{tbn}_arg3"] if cur_conf.get("dictionary") else res[-1]
            field_type = cur.description[-1][1]
            cur.execute(f"TRUNCATE TABLE {tbn}")  # clear table content

        exp_instance = bytes

        if isinstance(v, bytearray):
            v = bytes(v)

        self.assertNotEqual(field_type, FieldType.VECTOR)
        self.assertIsInstance(v, exp_instance)
        self.assertEqual(v, self.exp_vector_value(exp_instance, record_id))

    def _test_cursor(self, cur_conf):
        for i in (1, 2, 3):
            for fetch_method in ("fetchone", "fetchmany", "fetchall"):
                self._test_execute_kernel(
                    cur_conf=cur_conf, fetch_method=fetch_method, record_id=i
                )
            self._test_callproc_kernel(cur_conf=cur_conf, record_id=i)

    @tests.foreach_cnx()
    def test_cursor_plain(self):
        cur_conf = {}
        self._test_cursor(cur_conf)

    @tests.foreach_cnx()
    def test_cursor_raw(self):
        cur_conf = {"raw": True}
        self._test_cursor(cur_conf)

    @tests.foreach_cnx()
    def test_cursor_dictionary(self):
        cur_conf = {"dictionary": True}
        self._test_cursor(cur_conf)

    @tests.foreach_cnx()
    def test_cursor_buffered(self):
        cur_conf = {"buffered": True}
        self._test_cursor(cur_conf)

    @tests.foreach_cnx()
    def test_cursor_buffered_raw(self):
        cur_conf = {"buffered": True, "raw": True}
        self._test_cursor(cur_conf)

    @tests.foreach_cnx()
    def test_cursor_buffered_dictionary(self):
        cur_conf = {"buffered": True, "dictionary": True}
        self._test_cursor(cur_conf)

    @tests.foreach_cnx()
    def test_cursor_prepared(self):
        cur_conf = {"prepared": True}
        self._test_cursor(cur_conf)

    def _test_cmd_query_kernel(self, raw, record_id):
        """Execute statements with `cmd_query`.

        Checkpoints:
            * Ingest VECTOR values as binary strings (HEX).
            * Check `cnx.cmd_query`.
            * Check `cnx.get_rows` with raw=False/True.
            * Check `NULL` VECTOR values are returned as `None`.
            * Check the previous points with sync and async connections.
        """
        data = [
            [
                1,
                self.prep_vector(self.v1, {}),
                "Amit",
                datetime.date(2004, 12, 22),
            ],
            [
                2,
                self.prep_vector(self.v2, {}),
                "Manik",
                datetime.date(2006, 7, 4),
            ],
            [
                3,
                self.prep_vector(self.v3, {}),
                "Sabrina",
                datetime.date(1997, 11, 2),
            ],
            [4, "NULL", "NULL", "NULL"],
        ]
        v, null_value = None, None

        for row in data[:3]:
            self.cnx.cmd_query(
                self.insert.format(self.with_no_s_bind).format(*row),
            )
        self.cnx.cmd_query(
            self.insert.format("{0}, {1}, {2}, {3}").format(*data[-1]),
        )
        self.cnx.cmd_query(
            f"SELECT * from {self.table_name} WHERE Student_Id={record_id}"
        )
        res = self.cnx.get_rows(raw=raw)
        v = res[0][0][1]

        self.cnx.cmd_query(f"SELECT * from {self.table_name} WHERE Student_Id=4")
        res = self.cnx.get_rows(raw=raw)
        null_value = res[0][0][1]

        self.cnx.rollback()

        exp_instance = bytes if raw else array

        if isinstance(v, bytearray):
            v = bytes(v)

        self.assertIsInstance(v, exp_instance)
        self.assertEqual(v, self.exp_vector_value(exp_instance, record_id))
        self.assertEqual(null_value, None)

    @tests.foreach_cnx()
    def test_cnx_cmd_query(self):
        for i in (1, 2, 3):
            for raw in (True, False):
                self._test_cmd_query_kernel(raw=raw, record_id=i)


class VectorTests(_BaseVectorTests, tests.MySQLConnectorTests):
    """Testing the new VECTOR type for sync connection.

    Operate with VECTOR values without relying on the built-in server VECTOR utilities.
    """

    prep_vector = lambda obj, v, conf: (
        v.tobytes() if conf.get("prepared") else v.tobytes().hex()
    )

    s_bind = lambda obj, conf: (
        "%s, {0}, %s, %s".format("%s" if conf.get("prepared") else "x%s")
    )
    with_no_s_bind = "'{0}', x'{1}', '{2}', '{3}'"

    stmt_create_proc_arg_4 = (
        lambda obj, i: f"x'{getattr(obj, f'v{i}').tobytes().hex()}'"
    )

    @tests.foreach_cnx()
    def test_ingest_wrong_type(self):
        """Ingest an invalid type for VECTOR values.

        Expect a `DatabaseError`/`InterfaceError`.
        """
        s_bind = "%s, %s, %s, %s"
        wrong_cases = [
            (DatabaseError, [4, 13.45, "Adam", datetime.date(1897, 1, 21)]),
            (
                DatabaseError,
                [5, datetime.date(1897, 1, 21), "Orlando", datetime.date(1997, 12, 3)],
            ),
        ]
        for err, row in wrong_cases:
            with self.assertRaises(err):
                with self.cnx.cursor() as cur:
                    # The c-ext raises an InterfaceError and pure-python a DatabaseError
                    try:
                        cur.execute(self.insert.format(s_bind), row)
                    except (
                        DatabaseError,
                        InterfaceError,
                    ):
                        raise DatabaseError

    @tests.foreach_cnx()
    def test_ingest_big_endian_encoding(self):
        """Ingest a sequence using a big-endian encoding.

        Expect no error but a mismatch between the original sequence and the returned one.
        """
        byte_order = ">"  # big-endian - true for most modern architectures
        err_msg = ""
        if PLATFORM_IS_SOLARIS:
            # for some legacy architectures "<" must be used to indicate big-endian
            _, _, _, _, arch = os.uname()
            if "sun4v" in arch.lower():
                byte_order = "<"
            err_msg = (
                f"Solaris with {arch} architecture using byte-order '{byte_order}'"
            )

        record_id = 6
        row = [
            record_id,
            struct.pack(
                f"{byte_order}{len(self.v1)}f", *(tuple(self.v1))
            ).hex(),  # BigEndian encoding
            "Mario",
            datetime.date(1967, 3, 17),
        ]
        s_bind = "%s, x%s, %s, %s"
        v, field_type = None, None

        with self.cnx.cursor() as cur:
            # When ingesting a big-endian encoded sequence, the server does not generate
            # an error. However, the returned array.array won't correspond to the original
            # sequence.
            # check execute
            cur.execute(self.insert.format(s_bind), row)
            cur.execute(f"SELECT * from {self.table_name} WHERE Student_Id={record_id}")
            res = cur.fetchall()
            v = res[0][1]
            field_type = cur.description[1][1]
        self.cnx.rollback()

        exp_instance = array

        if isinstance(v, bytearray):
            v = bytes(v)

        self.assertEqual(field_type, FieldType.VECTOR)
        self.assertIsInstance(v, exp_instance)
        self.assertNotEqual(v, self.v1, err_msg)

    @tests.foreach_cnx()
    def test_vector_max_dim(self):
        """Provide a very big number of dimensions for a VECTOR type.

        Expect `DatabaseError`.
        """
        with self.cnx.cursor() as cur:
            with self.assertRaises(DatabaseError):
                cur.execute(
                    f"""
                    CREATE TABLE {self.table_name} (
                        Student_Id INT,
                        First_name VARCHAR (100),
                        Last_name VARCHAR (100),
                        Date_Of_Birth DATE,
                        Class VARCHAR(10),
                        Contact_Details BIGINT,
                        Embedding VECTOR({self.vector_max_dim}),
                    PRIMARY KEY(Student_Id )
                    )
                """
                )


class VectorTestsPlusUtils(_BaseVectorTests, tests.MySQLConnectorTests):
    """Testing the new VECTOR type for sync connection.

    Operate with VECTOR values relying on the built-in server VECTOR utilities.
    """

    prep_vector = lambda obj, v, conf: (str(v) if isinstance(v, list) else str(list(v)))

    s_bind = lambda obj, conf: ("%s, STRING_TO_VECTOR(%s), %s, %s")
    with_no_s_bind = "'{0}', STRING_TO_VECTOR('{1}'), '{2}', '{3}'"

    stmt_create_proc_arg_4 = (
        lambda obj, i: f"STRING_TO_VECTOR('{list(getattr(obj, f'v{i}'))}')"
    )

    @tests.foreach_cnx()
    def test_server_util_string_to_vector(self) -> None:
        """Check `STRING_TO_VECTOR`.

        Check Connector/Python can receive the string representation of a `list` of
        floats, and returns an `array.array` value if the output isn't NULL,
        `None` otherwise.
        """
        with self.cnx.cursor() as cur:
            cur.execute(f"SELECT STRING_TO_VECTOR(%s)", [str(list(self.v1))])
            res = cur.fetchone()
            self.assertEqual(res[0], self.v1)

            cur.execute(f"SELECT STRING_TO_VECTOR(%s)", [None])
            res = cur.fetchone()
            self.assertEqual(res[0], None)

    @tests.foreach_cnx()
    def test_server_util_vector_to_string(self) -> None:
        """Check `VECTOR_TO_STRING`.

        Check Connector/Python can receive the encoding (as `bytes`) of a
        sequence of floats for a `VECTOR` argument, and returns a `str` value
        if the output isn't NULL, `None` otherwise.
        """
        with self.cnx.cursor() as cur:
            cur.execute("SELECT VECTOR_TO_STRING(x%s)", [self.v2.tobytes().hex()])
            res = cur.fetchone()
            self.assertIsInstance(res[0], str)

            cur.execute("SELECT VECTOR_TO_STRING(%s)", [None])
            res = cur.fetchone()
            self.assertEqual(res[0], None)

    @tests.foreach_cnx()
    def test_server_util_vector_dim(self) -> None:
        """Check `VECTOR_DIM`.

        Check Connector/Python can receive the encoding (as `bytes`) of a sequence
        of floats for a `VECTOR` argument, and returns an `int` value if the output
        isn't NULL, `None` otherwise.
        """
        with self.cnx.cursor(prepared=True) as cur:
            cur.execute("SELECT VECTOR_DIM(%s)", [self.v2.tobytes()])
            res = cur.fetchone()
            self.assertEqual(res[0], len(self.v2))

            cur.execute("SELECT VECTOR_DIM(%s)", [None])
            res = cur.fetchone()
            self.assertEqual(res[0], None)

    @tests.foreach_cnx()
    def test_server_util_distance(self) -> None:
        """Check `DISTANCE`.

        Check Connector/Python can receive the encoding (as `bytes`)
        of a sequence of floats for a `VECTOR` argument, and returns
        a `float` value if the output isn't NULL, `None` otherwise.

        Expect `ProgrammingError` when the "component_vector" plugin isn't installed.
        """
        dist = math.sqrt(sum([(x - y) ** 2 for x, y in zip(self.v1, self.v2)]))
        with self.cnx.cursor() as cur:
            with (
                self.assertRaises(ProgrammingError)
                if not VECTOR_PLUGIN_LOADED
                else nullcontext()
            ):
                cur.execute(
                    "SELECT DISTANCE(%s, %s, 'EUCLIDIAN')",
                    [self.v1.tobytes(), self.v2.tobytes()],
                )

                res = cur.fetchone()
                self.assertLessEqual(abs(res[0] - dist), 1e-5)

                cur.execute("SELECT DISTANCE(%s, %s, 'EUCLIDIAN')", [None, None])
                res = cur.fetchone()
                self.assertEqual(res[0], None)


class _BaseVectorTestsAio(_BaseCommon):
    """Base class for VectorTestsAio."""

    async def _test_execute_kernel(self, cur_conf, fetch_method, record_id):
        """Execute statements **with** the `%s` parameter bounding style.

        Checkpoints:
            * Ingest VECTOR values as binary strings (HEX) when prepared=False.
            * Ingest VECTOR values as byte strings when prepared=True.
            * Check `cur.executemany` and  `cur.execute`.
            * Check `cur.{fetchmethod}`.
            * Check `NULL` VECTOR values are returned as `None`.
            * Check the previous points with sync and async connections.
        """
        data = [
            [
                1,
                self.prep_vector(self.v1, cur_conf),
                "Amit",
                datetime.date(2004, 12, 22),
            ],
            [
                2,
                self.prep_vector(self.v2, cur_conf),
                "Manik",
                datetime.date(2006, 7, 4),
            ],
            [
                3,
                self.prep_vector(self.v3, cur_conf),
                "Sabrina",
                datetime.date(1997, 11, 2),
            ],
            [4, None, None, None],
        ]
        v, field_type, null_value = None, None, None
        s_bind = self.s_bind(cur_conf)

        async with await self.cnx.cursor(**cur_conf) as cur:
            if cur_conf.get("prepared"):
                for row in data[:3]:
                    await cur.execute(
                        self.insert.format(s_bind),
                        row,
                    )
            else:
                await cur.executemany(self.insert.format(s_bind), data[:3])

            await cur.execute(self.insert.format("%s, %s, %s, %s"), data[-1])
            await cur.execute(
                f"SELECT * from {self.table_name} WHERE Student_Id={record_id}"
            )
            if fetch_method == "fetchmany":
                res = (await cur.fetchmany(size=1))[0]
            elif fetch_method == "fetchall":
                res = (await cur.fetchall())[0]
            else:
                res = await cur.fetchone()
            v = res["Embedding"] if cur_conf.get("dictionary") else res[1]
            field_type = cur.description[1][1]

            await cur.execute(f"SELECT * from {self.table_name} WHERE Student_Id=4")
            res = await cur.fetchone()
            null_value = res["Embedding"] if cur_conf.get("dictionary") else res[1]

        await self.cnx.rollback()

        exp_instance = (
            bytes if cur_conf.get("raw") and not cur_conf.get("prepared") else array
        )

        if isinstance(v, bytearray):
            v = bytes(v)

        self.assertEqual(field_type, FieldType.VECTOR)
        self.assertIsInstance(v, exp_instance)
        self.assertEqual(v, self.exp_vector_value(exp_instance, record_id))
        self.assertEqual(null_value, None)

    async def _test_callproc_kernel(self, cur_conf, record_id) -> None:
        """Call a stored procedure.

        TODO: The server returns a wrong `field type` for types such as DATE and
        VECTOR when getting results after calling a stored procedure. It's a server bug.

        In the meantime, C/Py will return VECTOR types as `bytes` strings.
        """
        # `callproc` is not supported in the prepared statement protocol yet
        if cur_conf.get("prepared"):
            return

        tbn = self.table_name
        stmt_proc = self.stmt_create_proc.format(
            tbn,
            tbn,
            record_id,
            datetime.date(2006, 7, 4),
            self.stmt_create_proc_arg_4(record_id),
            tbn,
            tbn,
        )
        v, field_type = None, None

        async with await self.cnx.cursor(**cur_conf) as cur:
            await cur.execute(f"DROP PROCEDURE IF EXISTS {tbn}")
            await cur.execute(stmt_proc)
            res = await cur.callproc(f"{tbn}", (record_id, None, None))
            v = res[f"{tbn}_arg3"] if cur_conf.get("dictionary") else res[-1]
            field_type = cur.description[-1][1]
            await cur.execute(f"TRUNCATE TABLE {tbn}")  # clear table content

        exp_instance = bytes

        if isinstance(v, bytearray):
            v = bytes(v)

        self.assertNotEqual(field_type, FieldType.VECTOR)
        self.assertIsInstance(v, exp_instance)
        self.assertEqual(v, self.exp_vector_value(exp_instance, record_id))

    async def _test_cursor(self, cur_conf):
        for i in (1, 2, 3):
            for fetch_method in ("fetchone", "fetchmany", "fetchall"):
                await self._test_execute_kernel(
                    cur_conf=cur_conf, fetch_method=fetch_method, record_id=i
                )
            await self._test_callproc_kernel(cur_conf=cur_conf, record_id=i)

    @tests.foreach_cnx_aio()
    async def test_cursor_plain(self):
        cur_conf = {}
        await self._test_cursor(cur_conf)

    @tests.foreach_cnx_aio()
    async def test_cursor_raw(self):
        cur_conf = {"raw": True}
        await self._test_cursor(cur_conf)

    @tests.foreach_cnx_aio()
    async def test_cursor_dictionary(self):
        cur_conf = {"dictionary": True}
        await self._test_cursor(cur_conf)

    @tests.foreach_cnx_aio()
    async def test_cursor_buffered(self):
        cur_conf = {"buffered": True}
        await self._test_cursor(cur_conf)

    @tests.foreach_cnx_aio()
    async def test_cursor_buffered_raw(self):
        cur_conf = {"buffered": True, "raw": True}
        await self._test_cursor(cur_conf)

    @tests.foreach_cnx_aio()
    async def test_cursor_buffered_dictionary(self):
        cur_conf = {"buffered": True, "dictionary": True}
        await self._test_cursor(cur_conf)

    @tests.foreach_cnx_aio()
    async def test_cursor_prepared(self):
        cur_conf = {"prepared": True}
        await self._test_cursor(cur_conf)

    async def _test_cmd_query_kernel(self, raw, record_id):
        """Execute statements with `cmd_query`.

        Checkpoints:
            * Ingest VECTOR values as binary strings (HEX).
            * Check `cnx.cmd_query`.
            * Check `cnx.get_rows` with raw=False/True.
            * Check `NULL` VECTOR values are returned as `None`.
            * Check the previous points with sync and async connections.
        """
        data = [
            [
                1,
                self.prep_vector(self.v1, {}),
                "Amit",
                datetime.date(2004, 12, 22),
            ],
            [
                2,
                self.prep_vector(self.v2, {}),
                "Manik",
                datetime.date(2006, 7, 4),
            ],
            [
                3,
                self.prep_vector(self.v3, {}),
                "Sabrina",
                datetime.date(1997, 11, 2),
            ],
            [4, "NULL", "NULL", "NULL"],
        ]
        v, null_value = None, None

        for row in data[:3]:
            await self.cnx.cmd_query(
                self.insert.format(self.with_no_s_bind).format(*row),
            )
        await self.cnx.cmd_query(
            self.insert.format("{0}, {1}, {2}, {3}").format(*data[-1]),
        )
        await self.cnx.cmd_query(
            f"SELECT * from {self.table_name} WHERE Student_Id={record_id}"
        )
        res = await self.cnx.get_rows(raw=raw)
        v = res[0][0][1]

        await self.cnx.cmd_query(f"SELECT * from {self.table_name} WHERE Student_Id=4")
        res = await self.cnx.get_rows(raw=raw)
        null_value = res[0][0][1]

        await self.cnx.rollback()

        exp_instance = bytes if raw else array

        if isinstance(v, bytearray):
            v = bytes(v)

        self.assertIsInstance(v, exp_instance)
        self.assertEqual(v, self.exp_vector_value(exp_instance, record_id))
        self.assertEqual(null_value, None)

    @tests.foreach_cnx_aio()
    async def test_cnx_cmd_query(self):
        for i in (1, 2, 3):
            for raw in (True, False):
                await self._test_cmd_query_kernel(raw=raw, record_id=i)


class VectorTestsAio(_BaseVectorTestsAio, tests.MySQLConnectorAioTestCase):
    """Testing the new VECTOR type for async connection.

    Operate with VECTOR values without relying on the built-in server VECTOR utilities.
    """

    prep_vector = lambda obj, v, conf: (
        v.tobytes() if conf.get("prepared") else v.tobytes().hex()
    )

    s_bind = lambda obj, conf: (
        "%s, {0}, %s, %s".format("%s" if conf.get("prepared") else "x%s")
    )
    with_no_s_bind = "'{0}', x'{1}', '{2}', '{3}'"

    stmt_create_proc_arg_4 = (
        lambda obj, i: f"x'{getattr(obj, f'v{i}').tobytes().hex()}'"
    )

    @tests.foreach_cnx_aio()
    async def test_ingest_wrong_type(self):
        """Ingest an invalid type for VECTOR values.

        Expect a `DatabaseError`/`InterfaceError`.
        """
        s_bind = "%s, %s, %s, %s"
        wrong_cases = [
            (DatabaseError, [4, 13.45, "Adam", datetime.date(1897, 1, 21)]),
            (
                DatabaseError,
                [5, datetime.date(1897, 1, 21), "Orlando", datetime.date(1997, 12, 3)],
            ),
        ]
        for err, row in wrong_cases:
            with self.assertRaises(err):
                async with await self.cnx.cursor() as cur:
                    # The c-ext raises an InterfaceError and pure-python a DatabaseError
                    try:
                        await cur.execute(self.insert.format(s_bind), row)
                    except (
                        DatabaseError,
                        InterfaceError,
                    ):
                        raise DatabaseError

    @tests.foreach_cnx_aio()
    async def test_ingest_big_endian_encoding(self):
        """Ingest a sequence using a big-endian encoding.

        Expect no error but a mismatch between the original sequence and the returned one.
        """
        byte_order = ">"  # big-endian - true for most modern architectures
        err_msg = ""
        if PLATFORM_IS_SOLARIS:
            # for some legacy architectures "<" must be used to indicate big-endian
            _, _, _, _, arch = os.uname()
            if "sun4v" in arch.lower():
                byte_order = "<"
            err_msg = (
                f"Solaris with {arch} architecture using byte-order '{byte_order}'"
            )

        record_id = 6
        row = [
            record_id,
            struct.pack(
                f"{byte_order}{len(self.v1)}f", *(tuple(self.v1))
            ).hex(),  # BigEndian encoding
            "Mario",
            datetime.date(1967, 3, 17),
        ]
        s_bind = "%s, x%s, %s, %s"
        v, field_type = None, None

        async with await self.cnx.cursor() as cur:
            # When ingesting a big-endian encoded sequence, the server does not generate
            # an error. However, the returned array.array won't correspond to the original
            # sequence.
            # check execute
            await cur.execute(self.insert.format(s_bind), row)
            await cur.execute(
                f"SELECT * from {self.table_name} WHERE Student_Id={record_id}"
            )
            res = await cur.fetchall()
            v = res[0][1]
            field_type = cur.description[1][1]
        await self.cnx.rollback()

        exp_instance = array

        if isinstance(v, bytearray):
            v = bytes(v)

        self.assertEqual(field_type, FieldType.VECTOR)
        self.assertIsInstance(v, exp_instance)
        self.assertNotEqual(v, self.v1, err_msg)

    @tests.foreach_cnx()
    async def test_vector_max_dim(self):
        """Provide a very big number of dimensions for a VECTOR type.

        Expect `DatabaseError`.
        """
        async with await self.cnx.cursor() as cur:
            with self.assertRaises(DatabaseError):
                await cur.execute(
                    f"""
                    CREATE TABLE {self.table_name} (
                        Student_Id INT,
                        First_name VARCHAR (100),
                        Last_name VARCHAR (100),
                        Date_Of_Birth DATE,
                        Class VARCHAR(10),
                        Contact_Details BIGINT,
                        Embedding VECTOR({self.vector_max_dim}),
                    PRIMARY KEY(Student_Id )
                    )
                """
                )


class VectorTestsPlusUtilsAio(_BaseVectorTestsAio, tests.MySQLConnectorAioTestCase):
    """Testing the new VECTOR type for async connection.

    Operate with VECTOR values relying on the built-in server VECTOR utilities.
    """

    prep_vector = lambda obj, v, conf: (str(v) if isinstance(v, list) else str(list(v)))

    s_bind = lambda obj, conf: ("%s, STRING_TO_VECTOR(%s), %s, %s")
    with_no_s_bind = "'{0}', STRING_TO_VECTOR('{1}'), '{2}', '{3}'"

    stmt_create_proc_arg_4 = (
        lambda obj, i: f"STRING_TO_VECTOR('{list(getattr(obj, f'v{i}'))}')"
    )

    @tests.foreach_cnx_aio()
    async def test_server_util_string_to_vector(self) -> None:
        """Check `STRING_TO_VECTOR`.

        Check Connector/Python can receive the string representation of a `list` of
        floats, and returns an `array.array` value if the output isn't NULL,
        `None` otherwise.
        """
        async with await self.cnx.cursor() as cur:
            await cur.execute(f"SELECT STRING_TO_VECTOR(%s)", [str(list(self.v1))])
            res = await cur.fetchone()
            self.assertEqual(res[0], self.v1)

            await cur.execute(f"SELECT STRING_TO_VECTOR(%s)", [None])
            res = await cur.fetchone()
            self.assertEqual(res[0], None)

    @tests.foreach_cnx_aio()
    async def test_server_util_vector_to_string(self) -> None:
        """Check `VECTOR_TO_STRING`.

        Check Connector/Python can receive the encoding (as `bytes`) of a
        sequence of floats for a `VECTOR` argument, and returns a `str` value
        if the output isn't NULL, `None` otherwise.
        """
        async with await self.cnx.cursor() as cur:
            await cur.execute("SELECT VECTOR_TO_STRING(x%s)", [self.v2.tobytes().hex()])
            res = await cur.fetchone()
            self.assertIsInstance(res[0], str)

            await cur.execute("SELECT VECTOR_TO_STRING(%s)", [None])
            res = await cur.fetchone()
            self.assertEqual(res[0], None)

    @tests.foreach_cnx_aio()
    async def test_server_util_vector_dim(self) -> None:
        """Check `VECTOR_DIM`.

        Check Connector/Python can receive the encoding (as `bytes`) of a sequence
        of floats for a `VECTOR` argument, and returns an `int` value if the output
        isn't NULL, `None` otherwise.
        """
        async with await self.cnx.cursor(prepared=True) as cur:
            await cur.execute("SELECT VECTOR_DIM(%s)", [self.v2.tobytes()])
            res = await cur.fetchone()
            self.assertEqual(res[0], len(self.v2))

            await cur.execute("SELECT VECTOR_DIM(%s)", [None])
            res = await cur.fetchone()
            self.assertEqual(res[0], None)

    @tests.foreach_cnx_aio()
    async def test_server_util_distance(self) -> None:
        """Check `DISTANCE`.

        Check Connector/Python can receive the encoding (as `bytes`)
        of a sequence of floats for a `VECTOR` argument, and returns
        a `float` value if the output isn't NULL, `None` otherwise.

        Expect `ProgrammingError` when the "component_vector" plugin isn't installed.
        """
        dist = math.sqrt(sum([(x - y) ** 2 for x, y in zip(self.v1, self.v2)]))
        async with await self.cnx.cursor() as cur:
            with (
                self.assertRaises(ProgrammingError)
                if not VECTOR_PLUGIN_LOADED
                else nullcontext()
            ):
                await cur.execute(
                    "SELECT DISTANCE(%s, %s, 'EUCLIDIAN')",
                    [self.v1.tobytes(), self.v2.tobytes()],
                )

                res = await cur.fetchone()
                self.assertLessEqual(abs(res[0] - dist), 1e-5)

                await cur.execute("SELECT DISTANCE(%s, %s, 'EUCLIDIAN')", [None, None])
                res = await cur.fetchone()
                self.assertEqual(res[0], None)
