# Copyright (c) 2025, Oracle and/or its affiliates. All rights reserved.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License, version 2.0, as
# published by the Free Software Foundation.
#
# This program is also distributed with certain software (including
# but not limited to OpenSSL) that is licensed under separate terms,
# as designated in a particular file or component or in included license
# documentation.  The authors of MySQL hereby grant you an
# additional permission to link the program and your derivative works
# with the separately licensed software that they have included with
# MySQL.
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

"""Unittests for mysql.connector.aio.pooling"""

import asyncio
import os
import sys
import unittest
import uuid

from tests import (
    MYSQL_VERSION,
    MySQLConnectorAioTestCase,
    foreach_cnx_aio,
    get_mysql_config,
)

import mysql.connector.aio

from mysql.connector import errors
from mysql.connector.aio import connect, pooling
from mysql.connector.aio.connection import MySQLConnection
from mysql.connector.constants import ClientFlag

MYSQL_CNX_CLASS = (MySQLConnection,)
POOLED_CONNECTION_SUPPORTED = None
POOLED_CONNECTION_NOT_SUPPORTED_REASON_MSG = (
    "Pooled connection not supported for Python versions lower than 3.11 on Windows"
)


async def check_if_pooled_connection_is_supported() -> bool:
    """Returns True if feature is supported for the Python version being used."""
    if os.name == "nt":
        dbconfig = {**get_mysql_config(), **{"pool_size": 2}}
        try:
            async with await mysql.connector.aio.connect(**dbconfig) as cnx:
                pass
            pooling._CONNECTION_POOLS = {}
        except errors.NotSupportedError:
            return False
    return True


def setUpModule() -> None:
    global POOLED_CONNECTION_SUPPORTED
    POOLED_CONNECTION_SUPPORTED = asyncio.run(check_if_pooled_connection_is_supported())

    # Pooled connection not supported for Python versions lower than 3.11 on Windows
    py_version_info = sys.version_info
    if os.name == "nt" and py_version_info.major == 3 and py_version_info.minor <= 10:
        assert POOLED_CONNECTION_SUPPORTED == False

    # check the global variable was set
    assert POOLED_CONNECTION_SUPPORTED is not None


class PooledMySQLConnectionTests(MySQLConnectorAioTestCase):

    def setUp(self):
        if POOLED_CONNECTION_SUPPORTED is False:
            self.skipTest(POOLED_CONNECTION_NOT_SUPPORTED_REASON_MSG)

    @foreach_cnx_aio()
    async def test___init__(self):
        dbconfig = get_mysql_config()
        if MYSQL_VERSION < (5, 7):
            dbconfig["client_flags"] = [-ClientFlag.CONNECT_ARGS]
        cnxpool = pooling.MySQLConnectionPool(pool_size=4)
        self.assertRaises(TypeError, pooling.PooledMySQLConnection)
        cnx = MySQLConnection(**dbconfig)
        await cnx.connect()
        pcnx = pooling.PooledMySQLConnection(cnxpool, cnx)
        self.assertEqual(cnxpool, pcnx._cnx_pool)
        self.assertEqual(cnx, pcnx._cnx)

        self.assertRaises(AttributeError, pooling.PooledMySQLConnection, None, None)
        self.assertRaises(AttributeError, pooling.PooledMySQLConnection, cnxpool, None)

    @foreach_cnx_aio()
    async def test___getattr__(self):
        dbconfig = get_mysql_config()
        if MYSQL_VERSION < (5, 7):
            dbconfig["client_flags"] = [-ClientFlag.CONNECT_ARGS]
        cnxpool = pooling.MySQLConnectionPool(pool_size=1, pool_name="test")
        cnx = MySQLConnection(**dbconfig)
        pcnx = pooling.PooledMySQLConnection(cnxpool, cnx)

        exp_attrs = {
            "_connection_timeout": dbconfig["connection_timeout"],
            "_database": dbconfig["database"],
            "_host": dbconfig["host"],
            "_password": dbconfig["password"],
            "_port": dbconfig["port"],
            "_unix_socket": dbconfig["unix_socket"],
        }
        for attr, value in exp_attrs.items():
            self.assertEqual(
                value,
                getattr(pcnx, attr),
                "Attribute {0} of reference connection not correct".format(attr),
            )

        self.assertEqual(pcnx.connect, cnx.connect)

    @foreach_cnx_aio()
    async def test_close(self):
        dbconfig = get_mysql_config()
        if MYSQL_VERSION < (5, 7):
            dbconfig["client_flags"] = [-ClientFlag.CONNECT_ARGS]
        cnxpool = pooling.MySQLConnectionPool(pool_size=1)

        cnxpool._original_cnx = None

        async def dummy_add_connection(self, cnx=None):
            self._original_cnx = cnx

        cnxpool.add_connection = dummy_add_connection.__get__(
            cnxpool, pooling.MySQLConnectionPool
        )
        if MYSQL_VERSION < (5, 7):
            dbconfig["client_flags"] = [-ClientFlag.CONNECT_ARGS]

        cnx = MySQLConnection(**dbconfig)
        await cnx.connect()
        pcnx = pooling.PooledMySQLConnection(cnxpool, cnx)

        await pcnx.close()
        self.assertEqual(cnx, cnxpool._original_cnx)

    @foreach_cnx_aio()
    async def test_config(self):
        dbconfig = get_mysql_config()
        cnxpool = pooling.MySQLConnectionPool(pool_size=1, **dbconfig)
        await cnxpool.initialize_pool()
        cnx = await cnxpool.get_connection()

        self.assertRaises(errors.PoolError, cnx.config)


class MySQLConnectionPoolTests(MySQLConnectorAioTestCase):

    def setUp(self):
        if POOLED_CONNECTION_SUPPORTED is False:
            self.skipTest(POOLED_CONNECTION_NOT_SUPPORTED_REASON_MSG)

    @foreach_cnx_aio()
    async def test_initialize_pool(self):
        dbconfig = get_mysql_config()
        if MYSQL_VERSION < (5, 7):
            dbconfig["client_flags"] = [-ClientFlag.CONNECT_ARGS]

        with self.assertRaises(errors.PoolError):
            pool = pooling.MySQLConnectionPool()
            await pool.initialize_pool()

        self.assertRaises(
            AttributeError,
            pooling.MySQLConnectionPool,
            pool_name="test",
            pool_size=-1,
        )
        self.assertRaises(
            AttributeError,
            pooling.MySQLConnectionPool,
            pool_name="test",
            pool_size=0,
        )
        self.assertRaises(
            AttributeError,
            pooling.MySQLConnectionPool,
            pool_name="test",
            pool_size=(pooling.CNX_POOL_MAXSIZE + 1),
        )

        cnxpool = pooling.MySQLConnectionPool(pool_name="test", **dbconfig)
        await cnxpool.initialize_pool()
        self.assertEqual(5, cnxpool._pool_size)
        self.assertEqual("test", cnxpool._pool_name)
        self.assertTrue(isinstance(cnxpool._cnx_queue, asyncio.Queue))
        self.assertTrue(isinstance(cnxpool._config_version, uuid.UUID))
        self.assertTrue(True, cnxpool._reset_session)

        cnxpool = pooling.MySQLConnectionPool(pool_size=10, pool_name="test")
        self.assertEqual(10, cnxpool._pool_size)

        cnxpool = pooling.MySQLConnectionPool(pool_size=10, **dbconfig)
        await cnxpool.initialize_pool()
        self.assertEqual(
            dbconfig,
            cnxpool._cnx_config,
            "Connection configuration not saved correctly",
        )
        self.assertEqual(10, cnxpool._cnx_queue.qsize())
        self.assertTrue(isinstance(cnxpool._config_version, uuid.UUID))

        cnxpool = pooling.MySQLConnectionPool(
            pool_size=1, pool_name="test", pool_reset_session=False
        )
        self.assertFalse(cnxpool._reset_session)

    @foreach_cnx_aio()
    async def test_pool_name(self):
        """Test MySQLConnectionPool.pool_name property"""
        pool_name = "ham"
        cnxpool = pooling.MySQLConnectionPool(pool_name=pool_name)
        self.assertEqual(pool_name, cnxpool.pool_name)

    @foreach_cnx_aio()
    async def test_pool_size(self):
        """Test MySQLConnectionPool.pool_size property"""
        pool_size = 4
        cnxpool = pooling.MySQLConnectionPool(pool_name="test", pool_size=pool_size)
        self.assertEqual(pool_size, cnxpool.pool_size)

    @foreach_cnx_aio()
    async def test_reset_session(self):
        """Test MySQLConnectionPool.reset_session property"""
        cnxpool = pooling.MySQLConnectionPool(
            pool_name="test", pool_reset_session=False
        )
        self.assertFalse(cnxpool.can_reset_session)
        cnxpool._reset_session = True
        self.assertTrue(cnxpool.can_reset_session)

    @foreach_cnx_aio()
    async def test__set_pool_size(self):
        cnxpool = pooling.MySQLConnectionPool(pool_name="test")
        self.assertRaises(AttributeError, cnxpool._set_pool_size, -1)
        self.assertRaises(AttributeError, cnxpool._set_pool_size, 0)
        self.assertRaises(
            AttributeError,
            cnxpool._set_pool_size,
            pooling.CNX_POOL_MAXSIZE + 1,
        )

        cnxpool._set_pool_size(pooling.CNX_POOL_MAXSIZE - 1)
        self.assertEqual(pooling.CNX_POOL_MAXSIZE - 1, cnxpool._pool_size)

    @foreach_cnx_aio()
    async def test__set_pool_name(self):
        cnxpool = pooling.MySQLConnectionPool(pool_name="test")

        self.assertRaises(AttributeError, cnxpool._set_pool_name, "pool name")
        self.assertRaises(AttributeError, cnxpool._set_pool_name, "pool%%name")
        self.assertRaises(
            AttributeError,
            cnxpool._set_pool_name,
            "long_pool_name" * pooling.CNX_POOL_MAXNAMESIZE,
        )

    @foreach_cnx_aio()
    async def test_add_connection(self):
        cnxpool = pooling.MySQLConnectionPool(pool_name="test")
        with self.assertRaises(errors.PoolError):
            await cnxpool.add_connection()

        dbconfig = get_mysql_config()
        if MYSQL_VERSION < (5, 7):
            dbconfig["client_flags"] = [-ClientFlag.CONNECT_ARGS]
        cnxpool = pooling.MySQLConnectionPool(pool_size=2, pool_name="test")
        await cnxpool.set_config(**dbconfig)
        await cnxpool.add_connection()
        pcnx = pooling.PooledMySQLConnection(cnxpool, cnxpool._cnx_queue.get_nowait())
        self.assertTrue(isinstance(pcnx._cnx, MYSQL_CNX_CLASS))
        self.assertEqual(cnxpool, pcnx._cnx_pool)
        self.assertEqual(cnxpool._config_version, pcnx._cnx._pool_config_version)

        cnx = pcnx._cnx
        await pcnx.close()
        # We should get the same connection back
        self.assertEqual(cnx, cnxpool._cnx_queue.get_nowait())
        await cnxpool.add_connection(cnx)

        # reach max connections
        await cnxpool.add_connection()
        with self.assertRaises(errors.PoolError):
            await cnxpool.add_connection()

        # fail connecting
        await cnxpool._remove_connections()
        cnxpool._cnx_config["port"] = 9999999
        cnxpool._cnx_config["unix_socket"] = "/ham/spam/foobar.socket"
        with self.assertRaises(OSError):
            await cnxpool.add_connection()

        with self.assertRaises(errors.PoolError):
            await cnxpool.add_connection(cnx=str)

    @foreach_cnx_aio()
    async def test_set_config(self):
        dbconfig = get_mysql_config()
        if MYSQL_VERSION < (5, 7):
            dbconfig["client_flags"] = [-ClientFlag.CONNECT_ARGS]
        cnxpool = pooling.MySQLConnectionPool(pool_name="test")

        # No configuration changes
        config_version = cnxpool._config_version
        await cnxpool.set_config()
        self.assertEqual(config_version, cnxpool._config_version)
        self.assertEqual({}, cnxpool._cnx_config)

        # Valid configuration changes
        config_version = cnxpool._config_version
        await cnxpool.set_config(**dbconfig)
        self.assertEqual(dbconfig, cnxpool._cnx_config)
        self.assertNotEqual(config_version, cnxpool._config_version)

        # Invalid configuration changes
        config_version = cnxpool._config_version
        wrong_dbconfig = dbconfig.copy()
        wrong_dbconfig["spam"] = "ham"
        with self.assertRaises(errors.PoolError):
            await cnxpool.set_config(**wrong_dbconfig)
        self.assertEqual(dbconfig, cnxpool._cnx_config)
        self.assertEqual(config_version, cnxpool._config_version)

    @foreach_cnx_aio()
    async def test_get_connection(self):
        dbconfig = get_mysql_config()
        if MYSQL_VERSION < (5, 7):
            dbconfig["client_flags"] = [-ClientFlag.CONNECT_ARGS]
        cnxpool = pooling.MySQLConnectionPool(pool_size=2, pool_name="test")

        with self.assertRaises(errors.PoolError):
            await cnxpool.get_connection()

        cnxpool = pooling.MySQLConnectionPool(pool_size=1, **dbconfig)
        await cnxpool.initialize_pool()

        # Get connection from pool
        pcnx = await cnxpool.get_connection()
        self.assertTrue(isinstance(pcnx, pooling.PooledMySQLConnection))
        with self.assertRaises(errors.PoolError):
            await cnxpool.get_connection()
        self.assertEqual(pcnx._cnx._pool_config_version, cnxpool._config_version)
        prev_config_version = pcnx._pool_config_version
        prev_thread_id = pcnx.connection_id
        await pcnx.close()

        # Change configuration
        config_version = cnxpool._config_version
        dbconfig["autocommit"] = True
        await cnxpool.set_config(**dbconfig)
        self.assertNotEqual(config_version, cnxpool._config_version)

        pcnx = await cnxpool.get_connection()
        self.assertNotEqual(pcnx._cnx._pool_config_version, prev_config_version)
        self.assertNotEqual(prev_thread_id, pcnx.connection_id)
        self.assertEqual(1, await pcnx.get_autocommit())
        await pcnx.close()

        # Get connection from pool using a context manager
        async with await cnxpool.get_connection() as pcnx:
            self.assertTrue(isinstance(pcnx, pooling.PooledMySQLConnection))

    @foreach_cnx_aio()
    async def test_close_pool(self):
        dbconfig = get_mysql_config()
        if MYSQL_VERSION < (5, 7):
            dbconfig["client_flags"] = [-ClientFlag.CONNECT_ARGS]
        cnxpool = pooling.MySQLConnectionPool(pool_size=2, pool_name="test", **dbconfig)
        await cnxpool.initialize_pool()
        pcnx = await cnxpool.get_connection()
        self.assertEqual(1, await cnxpool.close_pool())
        await pcnx.close()
        self.assertEqual(1, await cnxpool.close_pool())
        self.assertEqual(0, await cnxpool.close_pool())

        with self.assertRaises(errors.PoolError):
            await cnxpool.get_connection()

    @foreach_cnx_aio()
    async def test_concurrently_access_pool_connections(self):
        dbconfig = get_mysql_config()
        server_version = None
        test_cmd = "SELECT @@version"
        async with await mysql.connector.aio.connect(**dbconfig) as cnx:
            await cnx.cmd_query(test_cmd)
            server_version = await cnx.get_rows()

        cnxpool = pooling.MySQLConnectionPool(
            pool_name="test_pool", pool_size=3, **dbconfig
        )
        await cnxpool.initialize_pool()

        async def test_pool_cnx(
            pool: pooling.MySQLConnectionPool, secs: int = 1
        ) -> None:
            try:
                await asyncio.sleep(secs)
                async with await pool.get_connection() as cnx:
                    await cnx.cmd_query(test_cmd)
                    self.assertEqual(await cnx.get_rows(), server_version)
                    async with await cnx.cursor() as cur:
                        await cur.execute(test_cmd)
                        self.assertEqual(await cur.fetchall(), server_version[0])
            except Exception:
                raise

        async def close_cnx_pool(pool: pooling.MySQLConnectionPool) -> int:
            await pool.close_pool()

        await asyncio.gather(
            test_pool_cnx(cnxpool),
            test_pool_cnx(cnxpool),
            test_pool_cnx(cnxpool),
        )
        # rechecking whether all of the cnxpools were properly closed and cnx
        # were sent back to the pool
        await asyncio.gather(
            test_pool_cnx(cnxpool),
            test_pool_cnx(cnxpool),
            test_pool_cnx(cnxpool),
        )
        # cnx demand more than pool size
        # this will fail as getting 4 connection objects from the pool (pool-size: 3)
        # at the same time is not possible
        with self.assertRaises(errors.PoolError):
            await asyncio.gather(
                test_pool_cnx(cnxpool),
                test_pool_cnx(cnxpool),
                test_pool_cnx(cnxpool),
                test_pool_cnx(cnxpool),
            )

        # but the below set of operations are possible
        # as with variable sleep times, the methods executed early are sending the used
        # cnx objects back to the pool and those are getting re-used later
        try:
            await asyncio.gather(
                test_pool_cnx(cnxpool, 1),
                test_pool_cnx(cnxpool, 2),
                test_pool_cnx(cnxpool, 3),
                test_pool_cnx(cnxpool, 4),
            )
        except Exception:
            self.fail(
                "Connection objects from the pool are not getting re-used properly."
            )

        # concurrently try to close the pool
        try:
            asyncio.gather(
                close_cnx_pool(cnxpool),
                close_cnx_pool(cnxpool),
                close_cnx_pool(cnxpool),
            )
        except Exception:
            self.fail(
                "Concurrent calls to `close_pool(...)` should not raise any exceptions."
            )


class ModuleConnectorPoolingTests(MySQLConnectorAioTestCase):
    """Testing MySQL Connector module pooling functionality"""

    def setUp(self):
        if POOLED_CONNECTION_SUPPORTED is False:
            self.skipTest(POOLED_CONNECTION_NOT_SUPPORTED_REASON_MSG)

    async def asyncTearDown(self):
        pooling._CONNECTION_POOLS = {}

    @foreach_cnx_aio()
    async def test__connection_pools(self):
        self.assertEqual(pooling._CONNECTION_POOLS, {})

    @foreach_cnx_aio()
    async def test__get_pooled_connection(self):
        dbconfig = get_mysql_config()
        pooling._CONNECTION_POOLS.update({"spam": "ham"})
        with self.assertRaises(errors.InterfaceError):
            await connect(pool_name="spam")

        pooling._CONNECTION_POOLS = {}

        await connect(pool_name="ham", **dbconfig)
        self.assertTrue("ham" in pooling._CONNECTION_POOLS)
        cnxpool = pooling._CONNECTION_POOLS["ham"]
        self.assertTrue(isinstance(cnxpool, pooling.MySQLConnectionPool))
        self.assertEqual("ham", cnxpool.pool_name)

        await connect(pool_size=5, **dbconfig)
        pool_name = pooling.generate_pool_name(**dbconfig)
        self.assertTrue(pool_name in pooling._CONNECTION_POOLS)

    @foreach_cnx_aio()
    async def test_connect_pure(self):
        dbconfig = get_mysql_config()
        dbconfig["use_pure"] = True
        cnx = await connect(pool_size=1, pool_name="ham", **dbconfig)
        self.assertIsInstance(
            cnx._cnx,
            MySQLConnection,
            "{} type was expected".format(MySQLConnection),
        )
        exp = cnx.connection_id
        await cnx.close()
        pooled_id = await pooling._get_pooled_connection(pool_name="ham")
        self.assertEqual(
            exp,
            pooled_id.connection_id,
        )
