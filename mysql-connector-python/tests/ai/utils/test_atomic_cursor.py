# Copyright (c) 2025 Oracle and/or its affiliates.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License, version 2.0, as
# published by the Free Software Foundation.
#
# See the file COPYING for license information.

import unittest

from unittest.mock import MagicMock

import tests

from tests.ai.constants import AI_SKIP_MESSAGE

if tests.MYSQL_ML_ENABLED:
    from mysql.ai.utils import atomic_transaction


@unittest.skipIf(not tests.MYSQL_ML_ENABLED, AI_SKIP_MESSAGE)
class TestAtomicCursor(unittest.TestCase):
    @classmethod
    def setUp(self):
        self.conn = MagicMock()
        self.cursor = MagicMock()
        self.conn.cursor.return_value = self.cursor

    def test_normal_exit_closes_cursor_no_rollback(self):
        with atomic_transaction(self.conn) as cursor:
            cursor.execute("SELECT 1")
        self.conn.rollback.assert_not_called()
        self.cursor.close.assert_called_once()

    def test_exception_triggers_rollback_and_closes_cursor(self):
        class MyException(Exception):
            pass

        with self.assertRaises(MyException):
            with atomic_transaction(self.conn):
                raise MyException("fail here")
        self.conn.rollback.assert_called_once()
        self.cursor.close.assert_called_once()

    def test_rollback_raises_inner_exception_is_swallowed(self):
        # If rollback itself raises, the context exception is still propagated, not masked.
        self.conn.rollback.side_effect = RuntimeError("fail rollback")

        class MyException(Exception):
            pass

        with self.assertRaises(MyException):
            with atomic_transaction(self.conn):
                raise MyException("fail ctx")
        self.conn.rollback.assert_called_once()
        self.cursor.close.assert_called_once()

    def test_both_rollback_and_close_raise__donot_mask_exit_exception(self):
        # Both rollback and close raise exceptions: test that the exception
        # from inside the context is still the one propagated.
        self.conn.rollback.side_effect = RuntimeError("fail rollback")
        self.cursor.close.side_effect = RuntimeError("fail close")

        class MyException(Exception):
            pass

        with self.assertRaises(MyException):
            with atomic_transaction(self.conn):
                raise MyException("fail both")
        self.conn.rollback.assert_called_once()
        self.cursor.close.assert_called_once()

    def test_close_cursor_raises_exception_raises(self):
        # test that an exception is raised if close() fails and there was no
        # exception raised in the context.
        self.cursor.close.side_effect = RuntimeError("fail close")

        with self.assertRaises(RuntimeError):
            with atomic_transaction(self.conn) as cursor:
                cursor.execute("SELECT 1")
        self.conn.rollback.assert_not_called()
        self.cursor.close.assert_called_once()
