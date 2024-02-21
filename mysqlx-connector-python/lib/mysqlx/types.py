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

"""
Type hint aliases hub
"""

import typing

from datetime import datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple, Type, Union

if hasattr(typing, "TypeAlias"):
    # pylint: disable=no-name-in-module
    from typing import TypeAlias  # type: ignore[attr-defined]
else:
    try:
        from typing_extensions import TypeAlias
    except ModuleNotFoundError:
        # pylint: disable=reimported
        from typing import Any as TypeAlias


if TYPE_CHECKING:
    from google.protobuf.message import Message as ProtoMessage

    # pylint: disable=redefined-builtin
    from .connection import Connection, Session, SocketStream
    from .crud import DatabaseObject, Schema
    from .dbdoc import DbDoc
    from .errors import (
        DatabaseError,
        DataError,
        Error,
        IntegrityError,
        InterfaceError,
        InternalError,
        NotSupportedError,
        OperationalError,
        PoolError,
        ProgrammingError,
        TimeoutError,
    )
    from .expr import ExprParser
    from .protobuf import Message as XdevMessage
    from .result import BaseResult, Column
    from .statement import Statement


StrOrBytes = Union[str, bytes]

BuildScalarTypes = Optional[Union[str, bytes, bool, int, float]]
BuildExprTypes = Union[
    "XdevMessage", "ExprParser", Dict[str, Any], "DbDoc", List, Tuple, BuildScalarTypes
]
ColumnType: TypeAlias = "Column"
ConnectionType: TypeAlias = "Connection"
DatabaseTargetType: TypeAlias = "DatabaseObject"
ErrorClassTypes = Union[
    Type["Error"],
    Type["InterfaceError"],
    Type["DatabaseError"],
    Type["InternalError"],
    Type["OperationalError"],
    Type["ProgrammingError"],
    Type["IntegrityError"],
    Type["DataError"],
    Type["NotSupportedError"],
    Type["PoolError"],
    Type["TimeoutError"],
]
ErrorTypes = Union[
    "Error",
    "InterfaceError",
    "DatabaseError",
    "InternalError",
    "OperationalError",
    "ProgrammingError",
    "IntegrityError",
    "DataError",
    "NotSupportedError",
    "PoolError",
    "TimeoutError",
]
EscapeTypes = Optional[Union[int, float, Decimal, StrOrBytes]]
FieldTypes = Optional[Union[int, float, str, bytes, Decimal, datetime, timedelta]]
MessageType: TypeAlias = "XdevMessage"
ProtobufMessageType: TypeAlias = "ProtoMessage"
ProtobufMessageCextType = Dict[str, Any]
ResultBaseType: TypeAlias = "BaseResult"
SchemaType: TypeAlias = "Schema"
SessionType: TypeAlias = "Session"
SocketType: TypeAlias = "SocketStream"
StatementType: TypeAlias = "Statement"
