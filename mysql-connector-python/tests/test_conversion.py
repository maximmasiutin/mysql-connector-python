# -*- coding: utf-8 -*-

# Copyright (c) 2009, 2025, Oracle and/or its affiliates.
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

"""Unittests for mysql.connector.conversion
"""

import array
import datetime
import os
import platform
import struct
import sys
import time
import uuid

from decimal import Decimal

import tests

from mysql.connector import MySQLConnection, constants, conversion
from mysql.connector.constants import MYSQL_DEFAULT_CHARSET_ID_57
from mysql.connector.errors import InterfaceError, ProgrammingError

try:
    from _mysql_connector import MySQLInterfaceError
except ImportError:
    MySQLInterfaceError = InterfaceError

ARCH_64BIT = sys.maxsize > 2**32 and sys.platform != "win32"
LOCAL_PLATFORM = platform.platform().lower() if hasattr(platform, "platform") else ""
PLATFORM_IS_SOLARIS = "sunos-" in LOCAL_PLATFORM


class CustomType:
    """Example of a custom type."""

    def __str__(self):
        return "This is a custom type"


class CustomConverter(conversion.MySQLConverter):
    """A custom MySQL converter class with a CustomType converter."""

    def _customtype_to_mysql(self, value):
        return str(value).encode()


class DummyConverter(conversion.MySQLConverter):
    """A dummy MySQL converter class that doesn't implement any conversion."""

    ...

"""Data types inherited from the native ones supported by the default MySQLConverter.
These are used in the unittest and integration tests of MySQLConverter for every connector types.
"""
class MyInt(int): ...
class MyFloat(float): ...
class MyStr(str): ...
class MyBytes(bytes): ...
class MyByteArray(bytearray): ...
class MyDateTime(datetime.datetime):  ...
class MyDate(datetime.date):   ...
class MyTime(datetime.time):  ...
class MyTimeDelta(datetime.timedelta):    ...
class MyDecimal(Decimal): ...

inherited_datatypes = (
    MyInt(123),
    MyFloat(123.321),
    MyStr("abcd"),
    MyBytes([1,2,3]),
    MyByteArray([14,32,24,6]),
    MyDateTime(2025, 5, 28, 16, 36, 6),
    MyDate(day=16, month=6, year=1999),
    MyTime(hour=10, minute=35, second=6),
    MyTimeDelta(hours=12, minutes=13, seconds=14, days=1),
    MyDecimal('12.145'),
)


class MySQLConverterBaseTests(tests.MySQLConnectorTests):
    def test_init(self):
        cnv = conversion.MySQLConverterBase()

        self.assertEqual("utf8", cnv.charset)
        self.assertEqual(True, cnv.use_unicode)

    def test_init2(self):
        cnv = conversion.MySQLConverterBase(charset="latin1", use_unicode=False)

        self.assertEqual("latin1", cnv.charset)
        self.assertEqual(False, cnv.use_unicode)

    def test_set_charset(self):
        cnv = conversion.MySQLConverterBase()
        cnv.set_charset("latin2")

        self.assertEqual("latin2", cnv.charset)

    def test_set_useunicode(self):
        cnv = conversion.MySQLConverterBase()
        cnv.set_unicode(False)

        self.assertEqual(False, cnv.use_unicode)

    def test_to_mysql(self):
        cnv = conversion.MySQLConverterBase()

        self.assertEqual("a value", cnv.to_mysql("a value"))

    def test_to_python(self):
        cnv = conversion.MySQLConverterBase()

        self.assertEqual("a value", cnv.to_python("nevermind", "a value"))

    def test_escape(self):
        cnv = conversion.MySQLConverterBase()

        self.assertEqual("'a value'", cnv.escape("'a value'"))

    def test_quote(self):
        cnv = conversion.MySQLConverterBase()

        self.assertEqual("'a value'", cnv.escape("'a value'"))


class MySQLConverterTests(tests.MySQLConnectorTests):
    _to_python_data = [
        (b"3.14", ("float", constants.FieldType.FLOAT)),
        (b"128", ("int", constants.FieldType.TINY)),
        (b"1281288", ("long", constants.FieldType.LONG)),
        (b"3.14", ("decimal", constants.FieldType.DECIMAL)),
        (b"2008-05-07", ("date", constants.FieldType.DATE)),
        (b"45:34:10", ("time", constants.FieldType.TIME)),
        (b"2008-05-07 22:34:10", ("datetime", constants.FieldType.DATETIME)),
        (
            b"val1,val2",
            (
                "set",
                constants.FieldType.SET,
                None,
                None,
                None,
                None,
                True,
                constants.FieldFlag.SET,
                33,
            ),
        ),
        ("2008", ("year", constants.FieldType.YEAR)),
        (b"\x80\x00\x00\x00", ("bit", constants.FieldType.BIT)),
        (
            b"\xc3\xa4 utf8 string",
            (
                "utf8",
                constants.FieldType.STRING,
                None,
                None,
                None,
                None,
                True,
                0,
                33,
            ),
        ),
    ]
    _to_python_exp = (
        float(_to_python_data[0][0]),
        int(_to_python_data[1][0]),
        int(_to_python_data[2][0]),
        Decimal("3.14"),
        datetime.date(2008, 5, 7),
        datetime.timedelta(hours=45, minutes=34, seconds=10),
        datetime.datetime(2008, 5, 7, 22, 34, 10),
        set(["val1", "val2"]),
        int(_to_python_data[8][0]),
        2147483648,
        str(b"\xc3\xa4 utf8 string", "utf8"),
    )

    def setUp(self):
        self.cnv = conversion.MySQLConverter()

    def tearDown(self):
        pass

    def test_init(self):
        pass

    def test_escape(self):
        """Making strings ready for MySQL operations"""
        data = (
            None,  # should stay the same
            int(128),  # should stay the same
            int(1281288),  # should stay the same
            float(3.14),  # should stay the same
            Decimal("3.14"),  # should stay a Decimal
            datetime.date(2022, 11, 7),
            datetime.timedelta(hours=35, minutes=34, seconds=10),
            datetime.datetime(2022, 11, 4, 9, 11, 0),
            time.strptime("30 Nov 2022", "%d %b %Y"),
            r"back\slash",
            "newline\n",
            "return\r",
            "'single'",
            '"double"',
            "windows\032",
        )
        exp = (
            None,
            128,
            1281288,
            float(3.14),
            Decimal("3.14"),
            datetime.date(2022, 11, 7),
            datetime.timedelta(hours=35, minutes=34, seconds=10),
            datetime.datetime(2022, 11, 4, 9, 11, 0),
            time.strptime("30 Nov 2022", "%d %b %Y"),
            "back\\\\slash",
            "newline\\n",
            "return\\r",
            "\\'single\\'",
            '\\"double\\"',
            "windows\\\x1a",
        )

        res = tuple([self.cnv.escape(v) for v in data])
        self.assertTrue(res, exp)

    def test_quote(self):
        """Quote values making them ready for MySQL operations."""
        data = [
            None,
            int(128),
            int(1281288),
            float(3.14),
            Decimal("3.14"),
            b"string A",
            b"string B",
        ]
        exp = (
            b"NULL",
            b"128",
            b"1281288",
            b"3.14",
            b"3.14",
            b"'string A'",
            b"'string B'",
        )

        res = tuple([self.cnv.quote(value) for value in data])
        self.assertEqual(res, exp)

    def test_to_mysql(self):
        """Convert Python types to MySQL types using helper method"""
        st_now = time.localtime()
        data = (
            128,  # int
            1281288,  # long
            float(3.14),  # float
            "Strings are sexy",
            r"\u82b1",
            None,
            datetime.datetime(2008, 5, 7, 20, 0o1, 23),
            datetime.date(2008, 5, 7),
            datetime.time(20, 0o3, 23),
            st_now,
            datetime.timedelta(hours=40, minutes=30, seconds=12),
            Decimal("3.14"),
            *inherited_datatypes,
        )
        exp = (
            data[0],
            data[1],
            data[2],
            self.cnv._str_to_mysql(data[3]),
            self.cnv._str_to_mysql(data[4]),
            None,
            b"2008-05-07 20:01:23",
            b"2008-05-07",
            b"20:03:23",
            time.strftime("%Y-%m-%d %H:%M:%S", st_now).encode("ascii"),
            b"40:30:12",
            b"3.14",
            123,
            123.321,
            b"abcd",
            b"\x01\x02\x03",
            b"\x0e \x18\x06",
            b"2025-05-28 16:36:06",
            b"1999-06-16",
            b"10:35:06",
            b"36:13:14",
            b"12.145",
        )

        res = tuple([self.cnv.to_mysql(value) for value in data])
        self.assertEqual(res, exp)
        self.assertRaises(TypeError, self.cnv.to_mysql, uuid.uuid4())

    def test__str_to_mysql(self):
        """A Python string becomes bytes."""
        data = "This is a string"
        exp = data.encode()
        res = self.cnv._str_to_mysql(data)

        self.assertEqual(exp, res)

    def test__bytes_to_mysql(self):
        """A Python bytes stays bytes."""
        data = b"This is a bytes"
        exp = data
        res = self.cnv._bytes_to_mysql(data)

        self.assertEqual(exp, res)

    def test__bytearray_to_mysql(self):
        """A Python bytearray becomes bytes."""
        data = bytearray(
            b"This is a bytearray",
        )
        exp = bytes(data)
        res = self.cnv._bytearray_to_mysql(data)

        self.assertEqual(exp, res)

    def test__nonetype_to_mysql(self):
        """Python None stays None for MySQL."""
        data = None
        res = self.cnv._nonetype_to_mysql(data)

        self.assertEqual(data, res)

    def test__datetime_to_mysql(self):
        """A datetime.datetime becomes formatted like Y-m-d H:M:S[.f]"""
        cases = [
            (datetime.datetime(2008, 5, 7, 20, 1, 23), b"2008-05-07 20:01:23"),
            (
                datetime.datetime(2012, 5, 2, 20, 1, 23, 10101),
                b"2012-05-02 20:01:23.010101",
            ),
        ]
        for data, exp in cases:
            self.assertEqual(exp, self.cnv._datetime_to_mysql(data))

    def test__date_to_mysql(self):
        """A datetime.date becomes formatted like Y-m-d"""
        data = datetime.date(2008, 5, 7)
        res = self.cnv._date_to_mysql(data)
        exp = data.strftime("%Y-%m-%d").encode("ascii")

        self.assertEqual(exp, res)

    def test__time_to_mysql(self):
        """A datetime.time becomes formatted like Y-m-d H:M:S[.f]"""
        cases = [
            (datetime.time(20, 3, 23), b"20:03:23"),
            (datetime.time(20, 3, 23, 10101), b"20:03:23.010101"),
        ]
        for data, exp in cases:
            self.assertEqual(exp, self.cnv._time_to_mysql(data))

    def test__struct_time_to_mysql(self):
        """A time.struct_time becomes formatted like Y-m-d H:M:S"""
        data = time.localtime()
        res = self.cnv._struct_time_to_mysql(data)
        exp = time.strftime("%Y-%m-%d %H:%M:%S", data).encode("ascii")

        self.assertEqual(exp, res)

    def test__timedelta_to_mysql(self):
        """A datetime.timedelta becomes format like 'H:M:S[.f]'"""
        cases = [
            (
                datetime.timedelta(hours=40, minutes=30, seconds=12),
                b"40:30:12",
            ),
            (
                datetime.timedelta(hours=-40, minutes=30, seconds=12),
                b"-39:29:48",
            ),
            (
                datetime.timedelta(hours=40, minutes=-1, seconds=12),
                b"39:59:12",
            ),
            (
                datetime.timedelta(hours=-40, minutes=60, seconds=12),
                b"-38:59:48",
            ),
            (
                datetime.timedelta(
                    hours=40, minutes=30, seconds=12, microseconds=10101
                ),
                b"40:30:12.010101",
            ),
            (
                datetime.timedelta(
                    hours=-40, minutes=30, seconds=12, microseconds=10101
                ),
                b"-39:29:47.989899",
            ),
            (
                datetime.timedelta(
                    hours=40, minutes=-1, seconds=12, microseconds=10101
                ),
                b"39:59:12.010101",
            ),
            (
                datetime.timedelta(
                    hours=-40, minutes=60, seconds=12, microseconds=10101
                ),
                b"-38:59:47.989899",
            ),
        ]

        for i, case in enumerate(cases):
            data, exp = case
            self.assertEqual(
                exp,
                self.cnv._timedelta_to_mysql(data),
                "Case {0} failed: {1}; got {2}".format(
                    i + 1, repr(data), self.cnv._timedelta_to_mysql(data)
                ),
            )

    def test__decimal_to_mysql(self):
        """A decimal.Decimal becomes a string."""
        data = Decimal("3.14")
        self.assertEqual(b"3.14", self.cnv._decimal_to_mysql(data))

    def test_to_python(self):
        """Convert MySQL data to Python types using helper method"""

        res = tuple([self.cnv.to_python(v[1], v[0]) for v in self._to_python_data])
        self.assertEqual(res, tuple(self._to_python_exp))

    def test_row_to_python(self):
        data = [v[0] for v in self._to_python_data]
        description = [v[1] for v in self._to_python_data]

        res = self.cnv.row_to_python(data, description)
        self.assertEqual(res, self._to_python_exp)

    def test__float_to_python(self):
        """Convert a MySQL FLOAT/DOUBLE to a Python float type"""
        data = b"3.14"
        exp = float(data)
        res = self.cnv._float_to_python(data)

        self.assertEqual(exp, res)

        self.assertEqual(self.cnv._float_to_python, self.cnv._double_to_python)

    def test__int_to_python(self):
        """Convert a MySQL TINY/SHORT/INT24/INT to a Python int type"""
        data = b"128"
        exp = int(data)
        res = self.cnv._int_to_python(data)

        self.assertEqual(exp, res)

        self.assertEqual(self.cnv._int_to_python, self.cnv._tiny_to_python)
        self.assertEqual(self.cnv._int_to_python, self.cnv._short_to_python)
        self.assertEqual(self.cnv._int_to_python, self.cnv._int24_to_python)

    def test__long_to_python(self):
        """Convert a MySQL LONG/LONGLONG to a Python long type"""
        data = b"1281288"
        exp = int(data)
        res = self.cnv._long_to_python(data)

        self.assertEqual(exp, res)

        self.assertEqual(self.cnv._long_to_python, self.cnv._longlong_to_python)

    def test__decimal_to_python(self):
        """Convert a MySQL DECIMAL to a Python decimal.Decimal type"""
        data = b"3.14"
        exp = Decimal("3.14")
        res = self.cnv._decimal_to_python(data)

        self.assertEqual(exp, res)

        self.assertEqual(self.cnv._decimal_to_python, self.cnv._newdecimal_to_python)

    def test__bit_to_python(self):
        """Convert a MySQL BIT to Python int"""
        data = [
            b"\x80",
            b"\x80\x00",
            b"\x80\x00\x00",
            b"\x80\x00\x00\x00",
            b"\x80\x00\x00\x00\x00",
            b"\x80\x00\x00\x00\x00\x00",
            b"\x80\x00\x00\x00\x00\x00\x00",
            b"\x80\x00\x00\x00\x00\x00\x00\x00",
        ]
        exp = [
            128,
            32768,
            8388608,
            2147483648,
            549755813888,
            140737488355328,
            36028797018963968,
            9223372036854775808,
        ]

        for i, buf in enumerate(data):
            self.assertEqual(self.cnv._bit_to_python(buf), exp[i])

    def test__date_to_python(self):
        """Convert a MySQL DATE to a Python datetime.date type"""
        data = b"2008-05-07"
        exp = datetime.date(2008, 5, 7)
        res = self.cnv._date_to_python(data)

        self.assertEqual(exp, res)

        self.assertEqual(None, self.cnv._date_to_python(b"0000-00-00"))

        self.assertEqual(None, self.cnv._date_to_python(b"1000-00-00"))

    def test__time_to_python(self):
        """Convert a MySQL TIME to a Python datetime.time type"""
        cases = [
            (
                b"45:34:10",
                datetime.timedelta(hours=45, minutes=34, seconds=10),
            ),
            (b"-45:34:10", datetime.timedelta(-2, 8750)),
            (
                b"45:34:10.010101",
                datetime.timedelta(
                    hours=45, minutes=34, seconds=10, microseconds=10101
                ),
            ),
            (b"-45:34:10.010101", datetime.timedelta(-2, 8749, 989899)),
        ]

        for i, case in enumerate(cases):
            data, exp = case
            self.assertEqual(
                exp,
                self.cnv._time_to_python(data),
                "Case {0} failed: {1}; got {2}".format(
                    i + 1, repr(data), repr(self.cnv._time_to_python(data))
                ),
            )

    def test__datetime_to_python(self):
        """Convert a MySQL DATETIME to a Python datetime.datetime type"""
        cases = [
            (
                b"2008-05-07 22:34:10",
                datetime.datetime(2008, 5, 7, 22, 34, 10),
            ),
            (
                b"2008-05-07 22:34:10.010101",
                datetime.datetime(2008, 5, 7, 22, 34, 10, 10101),
            ),
            (b"0000-00-00 00:00:00", None),
            (b"1000-00-00 00:00:00", None),
        ]
        for data, exp in cases:
            self.assertEqual(exp, self.cnv._datetime_to_python(data))

    def test__year_to_python(self):
        """Convert a MySQL YEAR to Python int"""
        data = "2008"
        exp = 2008

        self.assertEqual(exp, self.cnv._year_to_python(data))
        data = "foobar"
        self.assertRaises(ValueError, self.cnv._year_to_python, data)

    def test__set_to_python(self):
        """Convert a MySQL SET type to a Python sequence

        This actually calls hte _string_to_python() method since a SET is
        returned as string by MySQL. However, the description of the field
        has in it's field flags that the string is a SET.
        """
        data = b"val1,val2"
        exp = set(["val1", "val2"])
        desc = (
            "foo",
            constants.FieldType.STRING,
            2,
            3,
            4,
            5,
            6,
            constants.FieldFlag.SET,
            MYSQL_DEFAULT_CHARSET_ID_57,
        )
        res = self.cnv._string_to_python(data, desc)

        self.assertEqual(exp, res)

    def test__string_to_python_utf8(self):
        """Convert a UTF-8 MySQL STRING/VAR_STRING to a Python Unicode type"""
        self.cnv.set_charset("utf8")  # default
        data = b"\xc3\xa4 utf8 string"
        exp = data.decode("utf-8")
        res = self.cnv._string_to_python(data)

        self.assertEqual(exp, res)

    def test__string_to_python_latin1(self):
        """Convert a ISO-8859-1 MySQL STRING/VAR_STRING to a Python str"""
        self.cnv.set_charset("latin1")
        self.cnv.set_unicode(False)
        data = b"\xe4 latin string"
        exp = data
        res = self.cnv._string_to_python(data)
        self.assertEqual(exp, res)

        exp = data.decode("latin1")
        self.cnv.set_unicode(True)
        res = self.cnv._string_to_python(data)
        self.assertEqual(exp, res)

        self.cnv.set_charset("utf8")
        self.cnv.set_unicode(True)

    def test__string_to_python_binary(self):
        """Convert a STRING BINARY to Python bytes type"""
        data = b"\x33\xfd\x34\xed"
        desc = (
            "foo",
            constants.FieldType.STRING,
            2,
            3,
            4,
            5,
            6,
            constants.FieldFlag.BINARY,
            63,
        )
        res = self.cnv._string_to_python(data, desc)

        self.assertEqual(data, res)

    def test__blob_to_python_binary(self):
        """Convert a BLOB BINARY to Python bytes type"""
        data = b"\x33\xfd\x34\xed"
        desc = (
            "foo",
            constants.FieldType.BLOB,
            2,
            3,
            4,
            5,
            6,
            constants.FieldFlag.BINARY,
            63,
        )
        res = self.cnv._blob_to_python(data, desc)

        self.assertEqual(data, res)

    def test__vector_to_python(self):
        """Convert MySQL VECTOR to Python array.array type."""
        exp = array.array(
            constants.MYSQL_VECTOR_TYPE_CODE, [3.14159, 2.71828, -7.20846]
        )

        byte_order = "<"  # little-endian - true for most modern architectures
        err_msg = ""
        if PLATFORM_IS_SOLARIS:
            _, _, _, _, arch = os.uname()
            if "sun4v" in arch.lower():
                byte_order = ">"  # big-endian - true for some legacy architectures
            err_msg = (
                f"Solaris with {arch} architecture using byte-order '{byte_order}'"
            )

        data = struct.pack(f"{byte_order}3f", *[3.14159, 2.71828, -7.20846])

        res = self.cnv._vector_to_python(data)
        self.assertEqual(exp, res, err_msg)

        self.assertEqual(None, self.cnv._vector_to_python(None))
        self.assertEqual(exp, self.cnv._vector_to_python(exp))

        # check invalid `bytes` string
        for val in ("Hello Kids", "Oracle"):
            with self.assertRaises(ValueError):
                self.cnv._vector_to_python(val.encode())

        # check invalid input type
        for val in (56, [56, 89], "Yoshi", datetime.date(1929, 8, 28)):
            with self.assertRaises(TypeError):
                self.cnv._vector_to_python(val)

    def test_str_fallback(self):
        """Test str fallback for unsupported types."""
        custom_type = CustomType()
        self.assertRaises(TypeError, self.cnv.to_mysql, custom_type)
        exp = b"This is a custom type"
        self.cnv.str_fallback = True
        self.assertEqual(exp, self.cnv.to_mysql(custom_type))
        self.cnv.str_fallback = False


class MySQLConverterIntegrationTests(tests.MySQLConnectorTests):
    """Test the class converter integration.

    Work Logs:
        -

    Bugs:
        - BUG#33409819: Fix failure when using a conversion class in CMySQLConnection
        - BUG#37774513: Inconsistent conversion to_sql for cext vs pure python
    """

    table_name = "converter_table_integration"


    @tests.foreach_cnx()
    def test_converter_class_integration(self):
        create_table_stmt = (
            "CREATE TABLE {} ("
            "id INT PRIMARY KEY, "
            "my_null INT, "
            "my_bit BIT(7), "
            "my_tinyint TINYINT, "
            "my_smallint SMALLINT, "
            "my_mediumint MEDIUMINT, "
            "my_int INT, "
            "my_bigint BIGINT, "
            "my_decimal DECIMAL(20,10), "
            "my_float FLOAT, "
            "my_float_nan FLOAT, "
            "my_double DOUBLE, "
            "my_date DATE, "
            "my_time TIME, "
            "my_datetime DATETIME, "
            "my_year YEAR, "
            "my_char CHAR(100), "
            "my_varchar VARCHAR(100), "
            "my_enum ENUM('x-small', 'small', 'medium', 'large', 'x-large'), "
            "my_geometry POINT, "
            "my_blob BLOB)"
        )

        insert_stmt = (
            "INSERT INTO {} ("
            "id, "
            "my_null, "
            "my_bit, "
            "my_tinyint, "
            "my_smallint, "
            "my_mediumint, "
            "my_int, "
            "my_bigint, "
            "my_decimal, "
            "my_float, "
            "my_float_nan, "
            "my_double, "
            "my_date, "
            "my_time, "
            "my_datetime, "
            "my_year, "
            "my_char, "
            "my_varchar, "
            "my_enum, "
            "my_geometry, "
            "my_blob) "
            "VALUES (%s, %s, B'1111100', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
            "%s, %s, %s, %s, %s, %s, "
            "POINT(21.2, 34.2), %s)"
        )

        data = (
            1,
            None,
            127,
            32767,
            8388607,
            2147483647,
            4294967295 if ARCH_64BIT else 2147483647,
            Decimal("1.2"),
            3.14,
            float("NaN"),
            4.28,
            datetime.date(2018, 12, 31),
            datetime.time(12, 13, 14),
            datetime.datetime(2019, 2, 4, 10, 36, 00),
            2019,
            "abc",
            "MySQL 🐬",
            "x-large",
            b"random blob data",
        )

        exp = (
            1,
            None,
            124,
            127,
            32767,
            8388607,
            2147483647,
            4294967295 if ARCH_64BIT else 2147483647,
            Decimal("1.2000000000"),
            3.14,
            None,
            4.28,
            datetime.date(2018, 12, 31),
            datetime.timedelta(0, 43994),
            datetime.datetime(2019, 2, 4, 10, 36),
            2019,
            "abc",
            "MySQL \U0001f42c",
            "x-large",
            bytearray(
                b"\x00\x00\x00\x00\x01\x01\x00\x00\x003333335"
                b"@\x9a\x99\x99\x99\x99\x19A@"
            ),
            bytearray(b"random blob data"),
        )

        self.cnx.converter_class = conversion.MySQLConverter
        with self.cnx.cursor() as cur:
            cur.execute(f"DROP TABLE IF EXISTS {self.table_name}")
            cur.execute(create_table_stmt.format(self.table_name))
            cur.execute(insert_stmt.format(self.table_name), data)
            cur.execute(f"SELECT * FROM {self.table_name}")
            rows = cur.fetchall()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0], exp)

    @tests.foreach_cnx()
    def test_bug37774513(self):
        """BUG#37774513: Inconsistent conversion to_sql for cext vs pure python

        Custom data types inheriting from the native built-in ones are not being
        supported by the default data converter of pure-python based connector.

        This patch fixes the issue by verifying if the value passed to the converter is
        an instance of the native supported type classes.
        """

        exp = (
            123,
            123.321,
            "abcd",
            b'\x01\x02\x03',
            b'\x0e \x18\x06',
            datetime.datetime(2025, 5, 28, 16, 36, 6),
            datetime.date(1999, 6, 16),
            datetime.timedelta(seconds=38106),
            datetime.timedelta(days=1, seconds=43994),
            Decimal('12.145'),
        )

        with self.cnx.cursor() as cur:
            cur.execute(f"DROP TABLE IF EXISTS {self.table_name}")
            cur.execute(
                f"CREATE TABLE IF NOT EXISTS {self.table_name}("
                "mock_int INTEGER, "
                "mock_float DOUBLE, "
                "mock_str VARCHAR(50), "
                "mock_bytes BINARY(3), "
                "mock_bytearr VARBINARY(10), "
                "mock_datetime DATETIME, "
                "mock_date DATE, "
                "mock_time TIME, "
                "mock_timedelta TIME, "
                "mock_decimal DECIMAL(5,3))"
            )
            cur.execute(
                f"INSERT INTO {self.table_name} VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                inherited_datatypes,
            )
            cur.execute(f"SELECT * FROM {self.table_name}")
            # even though the data types are not the same
            # the values should be equal
            self.assertEqual(cur.fetchone(), exp)


class MySQLConverterAioIntegrationTests(tests.MySQLConnectorAioTestCase):
    """Test the class converter integration.

    Work Logs:
        -

    Bugs:
        - BUG#37774513: Inconsistent conversion to_sql for cext vs pure python
    """

    table_name = "converter_table_integration_aio"


    @tests.foreach_cnx_aio()
    async def test_converter_class_integration(self):
        create_table_stmt = (
            "CREATE TABLE {} ("
            "id INT PRIMARY KEY, "
            "my_null INT, "
            "my_bit BIT(7), "
            "my_tinyint TINYINT, "
            "my_smallint SMALLINT, "
            "my_mediumint MEDIUMINT, "
            "my_int INT, "
            "my_bigint BIGINT, "
            "my_decimal DECIMAL(20,10), "
            "my_float FLOAT, "
            "my_float_nan FLOAT, "
            "my_double DOUBLE, "
            "my_date DATE, "
            "my_time TIME, "
            "my_datetime DATETIME, "
            "my_year YEAR, "
            "my_char CHAR(100), "
            "my_varchar VARCHAR(100), "
            "my_enum ENUM('x-small', 'small', 'medium', 'large', 'x-large'), "
            "my_geometry POINT, "
            "my_blob BLOB)"
        )

        insert_stmt = (
            "INSERT INTO {} ("
            "id, "
            "my_null, "
            "my_bit, "
            "my_tinyint, "
            "my_smallint, "
            "my_mediumint, "
            "my_int, "
            "my_bigint, "
            "my_decimal, "
            "my_float, "
            "my_float_nan, "
            "my_double, "
            "my_date, "
            "my_time, "
            "my_datetime, "
            "my_year, "
            "my_char, "
            "my_varchar, "
            "my_enum, "
            "my_geometry, "
            "my_blob) "
            "VALUES (%s, %s, B'1111100', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
            "%s, %s, %s, %s, %s, %s, "
            "POINT(21.2, 34.2), %s)"
        )

        data = (
            1,
            None,
            127,
            32767,
            8388607,
            2147483647,
            4294967295 if ARCH_64BIT else 2147483647,
            Decimal("1.2"),
            3.14,
            float("NaN"),
            4.28,
            datetime.date(2018, 12, 31),
            datetime.time(12, 13, 14),
            datetime.datetime(2019, 2, 4, 10, 36, 00),
            2019,
            "abc",
            "MySQL 🐬",
            "x-large",
            b"random blob data",
        )

        exp = (
            1,
            None,
            124,
            127,
            32767,
            8388607,
            2147483647,
            4294967295 if ARCH_64BIT else 2147483647,
            Decimal("1.2000000000"),
            3.14,
            None,
            4.28,
            datetime.date(2018, 12, 31),
            datetime.timedelta(0, 43994),
            datetime.datetime(2019, 2, 4, 10, 36),
            2019,
            "abc",
            "MySQL \U0001f42c",
            "x-large",
            bytearray(
                b"\x00\x00\x00\x00\x01\x01\x00\x00\x003333335"
                b"@\x9a\x99\x99\x99\x99\x19A@"
            ),
            bytearray(b"random blob data"),
        )

        self.cnx.converter_class = conversion.MySQLConverter
        async with await self.cnx.cursor() as cur:
            await cur.execute(f"DROP TABLE IF EXISTS {self.table_name}")
            await cur.execute(create_table_stmt.format(self.table_name))
            await cur.execute(insert_stmt.format(self.table_name), data)
            await cur.execute(f"SELECT * FROM {self.table_name}")
            rows = await cur.fetchall()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0], exp)

    @tests.foreach_cnx_aio()
    async def test_bug37774513(self):
        """BUG#37774513: Inconsistent conversion to_sql for cext vs pure python

        Custom data types inheriting from the native built-in ones are not being
        supported by the default data converter of pure-python based connector.

        This patch fixes the issue by verifying if the value passed to the converter is
        an instance of the native supported type classes.
        """

        exp = (
            123,
            123.321,
            "abcd",
            b'\x01\x02\x03',
            b'\x0e \x18\x06',
            datetime.datetime(2025, 5, 28, 16, 36, 6),
            datetime.date(1999, 6, 16),
            datetime.timedelta(seconds=38106),
            datetime.timedelta(days=1, seconds=43994),
            Decimal('12.145'),
        )

        async with await self.cnx.cursor() as cur:
            await cur.execute(f"DROP TABLE IF EXISTS {self.table_name}")
            await cur.execute(
                f"CREATE TABLE IF NOT EXISTS {self.table_name}("
                "mock_int INTEGER, "
                "mock_float DOUBLE, "
                "mock_str VARCHAR(50), "
                "mock_bytes BINARY(3), "
                "mock_bytearr VARBINARY(10), "
                "mock_datetime DATETIME, "
                "mock_date DATE, "
                "mock_time TIME, "
                "mock_timedelta TIME, "
                "mock_decimal DECIMAL(5,3))"
            )
            await cur.execute(
                f"INSERT INTO {self.table_name} VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                inherited_datatypes,
            )
            await cur.execute(f"SELECT * FROM {self.table_name}")
            # even though the data types are not the same
            # the values should be equal
            self.assertEqual(await cur.fetchone(), exp)


class MySQLConverterStrFallbackTests(tests.MySQLConnectorTests):
    table_name = "converter_table"

    @classmethod
    def setUpClass(cls):
        config = tests.get_mysql_config()
        with MySQLConnection(**config) as cnx:
            cnx.cmd_query(f"DROP TABLE IF EXISTS {cls.table_name}")
            cnx.cmd_query(
                f"""
                CREATE TABLE {cls.table_name} (
                    id int NOT NULL AUTO_INCREMENT,
                    name VARCHAR(255),
                    PRIMARY KEY(id)
                )
                """
            )
            cnx.commit()

    @classmethod
    def tearDownClass(cls):
        config = tests.get_mysql_config()
        with MySQLConnection(**config) as cnx:
            cnx.cmd_query(f"DROP TABLE IF EXISTS {cls.table_name}")

    @tests.foreach_cnx()
    def test_converter_str_fallback(self):
        """Test the `converter_str_fallback` connection option.

        Scenarios:

          - Using the default connection options.
          - Using the default connection options with prepared statements.
          - Using `converter_str_fallback=True`.
          - Using `converter_str_fallback=True` with prepared statements.
          - Using `converter_str_fallback=False`.
          - Using `converter_str_fallback=False` with prepared statements.
          - Using `converter_str_fallback=True` with a dummy converter class.
          - Using `converter_str_fallback=True` with prepared statements with
            a dummy converter class.
          - Using `converter_str_fallback=False` with a dummy converter class.
          - Using `converter_str_fallback=False` with prepared statements with
            a dummy converter class.
        """

        def _run_test(prepared=False, converter_class=None):
            custom_type = CustomType()
            config = tests.get_mysql_config()
            if converter_class:
                config["converter_class"] = converter_class
            with self.cnx.__class__(**config) as cnx:
                with cnx.cursor(prepared=prepared) as cur:
                    self.assertRaises(
                        (
                            TypeError,
                            InterfaceError,
                            ProgrammingError,
                            MySQLInterfaceError,
                        ),
                        cur.execute,
                        f"INSERT INTO {self.table_name} (name) VALUES (%s)",
                        (custom_type,),
                    )

            config["converter_str_fallback"] = True

            with self.cnx.__class__(**config) as cnx:
                with cnx.cursor(prepared=prepared) as cur:
                    cur.execute(
                        f"INSERT INTO {self.table_name} (name) VALUES (%s)",
                        (custom_type,),
                    )
                    cur.execute(f"SELECT name FROM {self.table_name}")
                    res = cur.fetchall()
                    exp = str(custom_type)
                    self.assertEqual(exp, res[0][0])

        _run_test(prepared=False)
        _run_test(prepared=True)
        _run_test(prepared=False, converter_class=DummyConverter)
        _run_test(prepared=True, converter_class=DummyConverter)

