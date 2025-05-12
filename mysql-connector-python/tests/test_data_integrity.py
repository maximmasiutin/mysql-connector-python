# -*- coding: utf-8 -*-

# Copyright (c) 2025, Oracle and/or its affiliates.
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

"""Unittest to verify data integrity between connector and the database"""

from tests import (
    get_mysql_config,
    foreach_cnx,
    foreach_cnx_aio,
    MySQLConnectorTests,
    MySQLConnectorAioTestCase,
)

import mysql.connector

class CursorDataIntegrity(MySQLConnectorTests):
    """Test data integrity of Connector/Python pure-python and c-extension based cursors"""

    table_name = "data_integrity"

    query_with_no_params = (
        "SELECT 'mypass%%s'", "SELECT '%smypass%s'",
    )
    fetchone_q_no_params = (('mypass%%s',), ('%smypass%s',),)
    fetchall_q_no_params = ([('mypass%%s',),], [('%smypass%s',),],)

    query_with_params = (
        ("SELECT %s", (1,)), ("SELECT %s+%s", (1,2,)),
        ("SELECT %s", ("abc%%ssbca",)), ("SELECT %s", ("%s",)),
        ("SELECT DATE_FORMAT(%s, '%Y-%m-%d %H:%i:%S')", ("2017-06-15 12:20:23",)),
    )
    fetchone_q_params = (
        (1,), (3,), ("abc%%ssbca",),
        ("%s",), ("2017-06-15 12:20:23",),
    )
    fetchall_q_params = (
        [(1,),], [(3,),], [("abc%%ssbca",),],
        [("%s",),], [("2017-06-15 12:20:23",),],
        [("abcdef",),],
    )

    insert_q = f"INSERT INTO {table_name} VALUES"
    insert_query_with_no_params = f"""
        {insert_q} (1, 'abc%s'), (2, '1a2b3c%s%dzzz%%s'), (3, '%d%f%srandomurl:::331d0.##45%')
    """
    insert_query_with_params = f"{insert_q} (%s, %s)"
    fetchall_insert_q = [
        (1, 'abc%s'),
        (2, '1a2b3c%s%dzzz%%s'),
        (3, '%d%f%srandomurl:::331d0.##45%'),
    ]

    function_query = (
        "CREATE FUNCTION IF NOT EXISTS hello_func(`name%%ss` CHAR(20))"
        "   RETURNS CHAR(50) DETERMINISTIC"
        "   RETURN CONCAT('Hello, ',`name%%ss`,'!')"
    )

    spcl_table_name = "my_table%%ss"
    create_spcl_table_q = (
        f"CREATE TABLE IF NOT EXISTS `{spcl_table_name}` (`bar%%s` INTEGER, `%%sfoo` VARCHAR(50), "
        "`val_%s` BOOL)"
    )
    spcl_insert_q = f"INSERT INTO `{spcl_table_name}` VALUES"
    spcl_insert_q_no_params = f"""
        {spcl_insert_q} (1, 'encoded_stuff#%s%d%%sfd', false), (2, '%s_bbb_%%s', true)
    """
    spcl_insert_q_params = f"{spcl_insert_q} (%s, %s, %s)"
    spcl_fetchall_q = [
        (1, 'encoded_stuff#%s%d%%sfd', 0),
        (2, '%s_bbb_%%s', 1),
    ]
    del_spcl_table_q = f"DROP TABLE IF EXISTS `{spcl_table_name}`"

    create_table_q = f"CREATE TABLE IF NOT EXISTS {table_name} (id INTEGER, val VARCHAR(30))"
    del_table_q = f"DROP TABLE IF EXISTS {table_name}"

    @classmethod
    def setUpClass(cls):
        with mysql.connector.connect(**get_mysql_config()) as cnx:
            cnx.cmd_query(cls.create_table_q)
            cnx.commit()

    @classmethod
    def tearDownClass(cls):
        with mysql.connector.connect(**get_mysql_config()) as cnx:
            cnx.cmd_query(cls.del_table_q)

    @foreach_cnx()
    def test_select_query_with_no_params(self):
        for idx in range(len(self.query_with_no_params)):
            for prepared in (True, False):
                with self.cnx.cursor(prepared=prepared) as cur:
                    cur.execute(self.query_with_no_params[idx])
                    self.assertEqual(cur.fetchone(), self.fetchone_q_no_params[idx])
                    cur.execute(self.query_with_no_params[idx])
                    self.assertEqual(cur.fetchall(), self.fetchall_q_no_params[idx])

    @foreach_cnx()
    def test_select_query_with_params(self):
        for idx in range(len(self.query_with_params)):
            query, params = self.query_with_params[idx]
            for prepared in (True, False):
                with self.cnx.cursor(prepared=prepared) as cur:
                    cur.execute(query, params)
                    self.assertEqual(cur.fetchone(), self.fetchone_q_params[idx])
                    cur.execute(query, params)
                    self.assertEqual(cur.fetchall(), self.fetchall_q_params[idx])

    @foreach_cnx()
    def test_insert_query_with_no_params(self):
        for prepared in (True, False):
                with self.cnx.cursor(prepared=prepared) as cur:
                    cur.execute(self.insert_query_with_no_params)
                    cur.execute(f"SELECT * FROM {self.table_name}")
                    self.assertEqual(cur.fetchall(), self.fetchall_insert_q)
                    cur.execute(f"DELETE FROM {self.table_name}")

    @foreach_cnx()
    def test_insert_query_with_params(self):
        for prepared in (True, False):
                with self.cnx.cursor(prepared=prepared) as cur:
                    cur.executemany(self.insert_query_with_params, tuple(self.fetchall_insert_q))
                    cur.execute(f"SELECT * FROM {self.table_name}")
                    self.assertEqual(cur.fetchall(), self.fetchall_insert_q)
                    cur.execute(f"DELETE FROM {self.table_name}")

    @foreach_cnx()
    def test_insert_query_data_persistence(self):
        for prepared in (True, False):
            with self.cnx.cursor(prepared=prepared) as cur:
                cur.execute(
                    f"INSERT INTO {self.table_name} VALUES (%s, %s)",
                    # without raw string passed here, `\a` will be sent as `\x07`
                    (5, r"%sabcd%%sbcd\a:.com")
                )
                cur.execute(f"SELECT val FROM {self.table_name}")
                self.assertEqual(cur.fetchone(), (r"%sabcd%%sbcd\a:.com",))
                cur.execute(f"SELECT val FROM {self.table_name}")
                self.assertEqual(cur.fetchall(), [(r"%sabcd%%sbcd\a:.com",)])
                cur.execute(f"DELETE FROM {self.table_name}")

    @foreach_cnx()
    def test_function(self):
        with self.cnx.cursor() as cur:
            cur.execute(self.function_query)
            cur.execute("SELECT hello_func('abc')")
            self.assertEqual(cur.fetchone(), ('Hello, abc!',))

    @foreach_cnx()
    def test_spcl_table_col_names(self):
        for prepared in (True, False):
            with self.cnx.cursor(prepared=prepared) as cur:
                # create table with %s and %%s in table and column names
                cur.execute(self.create_spcl_table_q)
                # execute insert query with no params
                cur.execute(self.spcl_insert_q_no_params)
                cur.execute(f"SELECT * FROM `{self.spcl_table_name}`")
                self.assertEqual(cur.fetchall(), self.spcl_fetchall_q)
                # fetch a particular column data
                cur.execute(f"SELECT `%%sfoo` FROM `{self.spcl_table_name}`")
                self.assertEqual(cur.fetchall(), [(data[1],) for data in self.spcl_fetchall_q])
                # erase table data
                cur.execute(self.del_spcl_table_q)

    @foreach_cnx()
    def test_spcl_table_col_insert_with_params(self):
        for prepared in (True, False):
            with self.cnx.cursor(prepared=prepared) as cur:
                # create table with %s and %%s in table and column names
                cur.execute(self.create_spcl_table_q)
                # execute insert query with params
                cur.executemany(self.spcl_insert_q_params, tuple(self.spcl_fetchall_q))
                cur.execute(f"SELECT * FROM `{self.spcl_table_name}`")
                self.assertEqual(cur.fetchall(), self.spcl_fetchall_q)
                # erase table data
                cur.execute(self.del_spcl_table_q)



class CursorAioDataIntegrity(MySQLConnectorAioTestCase):

    table_name = CursorDataIntegrity.table_name

    query_with_no_params = CursorDataIntegrity.query_with_no_params
    fetchone_q_no_params = CursorDataIntegrity.fetchone_q_no_params
    fetchall_q_no_params = CursorDataIntegrity.fetchall_q_no_params

    query_with_params = CursorDataIntegrity.query_with_params
    fetchone_q_params = CursorDataIntegrity.fetchone_q_params
    fetchall_q_params = CursorDataIntegrity.fetchall_q_params

    insert_query_with_no_params = CursorDataIntegrity.insert_query_with_no_params
    insert_query_with_params = CursorDataIntegrity.insert_query_with_params
    fetchall_insert_q = CursorDataIntegrity.fetchall_insert_q

    function_query = CursorDataIntegrity.function_query

    spcl_table_name = CursorDataIntegrity.spcl_table_name
    create_spcl_table_q = CursorDataIntegrity.create_spcl_table_q
    spcl_insert_q = CursorDataIntegrity.spcl_insert_q
    spcl_insert_q_no_params = CursorDataIntegrity.spcl_insert_q_no_params
    spcl_insert_q_params = CursorDataIntegrity.spcl_insert_q_params
    spcl_fetchall_q = CursorDataIntegrity.spcl_fetchall_q
    del_spcl_table_q = CursorDataIntegrity.del_spcl_table_q

    create_table_q = CursorDataIntegrity.create_table_q
    del_table_q = CursorDataIntegrity.del_table_q

    @classmethod
    def setUpClass(cls):
        with mysql.connector.connect(**get_mysql_config()) as cnx:
            cnx.cmd_query(cls.create_table_q)
            cnx.commit()

    @classmethod
    def tearDownClass(cls):
        with mysql.connector.connect(**get_mysql_config()) as cnx:
            cnx.cmd_query(cls.del_table_q)

    @foreach_cnx_aio()
    async def test_aio_select_query_with_no_params(self):
        for idx in range(len(self.query_with_no_params)):
            for prepared in (True, False):
                async with await self.cnx.cursor(prepared=prepared) as cur:
                    await cur.execute(self.query_with_no_params[idx])
                    self.assertEqual(await cur.fetchone(), self.fetchone_q_no_params[idx])
                    await cur.execute(self.query_with_no_params[idx])
                    self.assertEqual(await cur.fetchall(), self.fetchall_q_no_params[idx])

    @foreach_cnx_aio()
    async def test_aio_select_query_with_params(self):
        for idx in range(len(self.query_with_params)):
            query, params = self.query_with_params[idx]
            for prepared in (True, False):
                async with await self.cnx.cursor(prepared=prepared) as cur:
                    await cur.execute(query, params)
                    self.assertEqual(await cur.fetchone(), self.fetchone_q_params[idx])
                    await cur.execute(query, params)
                    self.assertEqual(await cur.fetchall(), self.fetchall_q_params[idx])

    @foreach_cnx_aio()
    async def test_aio_insert_query_with_no_params(self):
        for prepared in (True, False):
                async with await self.cnx.cursor(prepared=prepared) as cur:
                    await cur.execute(self.insert_query_with_no_params)
                    await cur.execute(f"SELECT * FROM {self.table_name}")
                    self.assertEqual(await cur.fetchall(), self.fetchall_insert_q)
                    await cur.execute(f"DELETE FROM {self.table_name}")

    @foreach_cnx_aio()
    async def test_aio_insert_query_with_params(self):
        for prepared in (True, False):
                async with await self.cnx.cursor(prepared=prepared) as cur:
                    await cur.executemany(self.insert_query_with_params, tuple(self.fetchall_insert_q))
                    await cur.execute(f"SELECT * FROM {self.table_name}")
                    self.assertEqual(await cur.fetchall(), self.fetchall_insert_q)
                    await cur.execute(f"DELETE FROM {self.table_name}")

    @foreach_cnx_aio()
    async def test_aio_insert_query_data_persistence(self):
        for prepared in (True, False):
            async with await self.cnx.cursor(prepared=prepared) as cur:
                await cur.execute(
                    f"INSERT INTO {self.table_name} VALUES (%s, %s)",
                    # without raw string passed here, `\a` will be sent as `\x07`
                    (5, r"%sabcd%%sbcd\a:.com")
                )
                await cur.execute(f"SELECT val FROM {self.table_name}")
                self.assertEqual(await cur.fetchone(), (r"%sabcd%%sbcd\a:.com",))
                await cur.execute(f"SELECT val FROM {self.table_name}")
                self.assertEqual(await cur.fetchall(), [(r"%sabcd%%sbcd\a:.com",)])
                await cur.execute(f"DELETE FROM {self.table_name}")

    @foreach_cnx_aio()
    async def test_aio_function(self):
        async with await self.cnx.cursor() as cur:
            await cur.execute(self.function_query)
            await cur.execute("SELECT hello_func('abc')")
            self.assertEqual(await cur.fetchone(), ('Hello, abc!',))

    @foreach_cnx_aio()
    async def test_aio_spcl_table_col_names(self):
        for prepared in (True, False):
            async with await self.cnx.cursor(prepared=prepared) as cur:
                # create table with %s and %%s in table and column names
                await cur.execute(self.create_spcl_table_q)
                # execute insert query with no params
                await cur.execute(self.spcl_insert_q_no_params)
                await cur.execute(f"SELECT * FROM `{self.spcl_table_name}`")
                self.assertEqual(await cur.fetchall(), self.spcl_fetchall_q)
                # fetch a particular column data
                await cur.execute(f"SELECT `%%sfoo` FROM `{self.spcl_table_name}`")
                self.assertEqual(await cur.fetchall(), [(data[1],) for data in self.spcl_fetchall_q])
                # erase table data
                await cur.execute(self.del_spcl_table_q)

    @foreach_cnx_aio()
    async def test_aio_spcl_table_col_insert_with_params(self):
        for prepared in (True, False):
            async with await self.cnx.cursor(prepared=prepared) as cur:
                # create table with %s and %%s in table and column names
                await cur.execute(self.create_spcl_table_q)
                # execute insert query with params
                await cur.executemany(self.spcl_insert_q_params, tuple(self.spcl_fetchall_q))
                await cur.execute(f"SELECT * FROM `{self.spcl_table_name}`")
                self.assertEqual(await cur.fetchall(), self.spcl_fetchall_q)
                # erase table data
                await cur.execute(self.del_spcl_table_q)
