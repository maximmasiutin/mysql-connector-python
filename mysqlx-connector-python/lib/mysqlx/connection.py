# Copyright (c) 2016, 2025, Oracle and/or its affiliates.
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

# mypy: disable-error-code="index,attr-defined"

"""Implementation of communication for MySQL X servers."""

from __future__ import annotations

from types import TracebackType

try:
    import ssl

    SSL_AVAILABLE = True
    TLS_VERSIONS = {
        "TLSv1.2": ssl.PROTOCOL_TLSv1_2,
    }
    # TLSv1.3 included in PROTOCOL_TLS, but PROTOCOL_TLS is not included on 3.4
    TLS_VERSIONS["TLSv1.3"] = (
        ssl.PROTOCOL_TLS
        if hasattr(ssl, "PROTOCOL_TLS")
        else ssl.PROTOCOL_SSLv23  # Alias of PROTOCOL_TLS
    )
    TLS_V1_3_SUPPORTED = hasattr(ssl, "HAS_TLSv1_3") and ssl.HAS_TLSv1_3
except ImportError:
    SSL_AVAILABLE = False
    TLS_V1_3_SUPPORTED = False
    TLS_VERSIONS = {}

import json
import os
import platform
import queue
import random
import re
import socket
import sys
import threading
import uuid

from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple, Type, Union

try:
    import dns.exception
    import dns.resolver
except ImportError:
    HAVE_DNSPYTHON = False
else:
    HAVE_DNSPYTHON = True

from datetime import datetime, timedelta
from functools import wraps
from json.decoder import JSONDecodeError
from urllib.parse import parse_qsl, unquote, urlparse

from .authentication import MySQL41AuthPlugin, PlainAuthPlugin, Sha256MemoryAuthPlugin
from .constants import (
    COMPRESSION_ALGORITHMS,
    OPENSSL_CS_NAMES,
    SUPPORTED_TLS_VERSIONS,
    TLS_CIPHER_SUITES,
    Auth,
    Compression,
    SSLMode,
)
from .crud import Schema

# pylint: disable=redefined-builtin
from .errors import (
    InterfaceError,
    NotSupportedError,
    OperationalError,
    PoolError,
    ProgrammingError,
    TimeoutError,
)
from .helpers import escape, get_item_or_attr, iani_to_openssl_cs_name
from .logger import logger
from .protobuf import Protobuf
from .protocol import HAVE_LZ4, HAVE_ZSTD, MessageReader, MessageWriter, Protocol
from .result import BaseResult, DocResult, Result, RowResult, SqlResult
from .statement import (
    AddStatement,
    DeleteStatement,
    FindStatement,
    InsertStatement,
    ModifyStatement,
    ReadStatement,
    RemoveStatement,
    SelectStatement,
    SqlStatement,
    UpdateStatement,
    quote_identifier,
)
from .types import ColumnType, MessageType, ResultBaseType, StatementType

sys.path.append("..")

from .tls_ciphers import UNACCEPTABLE_TLS_CIPHERSUITES, UNACCEPTABLE_TLS_VERSIONS
from .utils import (
    linux_distribution,
    warn_ciphersuites_deprecated,
    warn_tls_version_deprecated,
)
from .version import LICENSE, VERSION

DUPLICATED_IN_LIST_ERROR = (
    "The '{list}' list must not contain repeated values, the value "
    "'{value}' is duplicated."
)

TLS_VERSION_ERROR = (
    "The given tls_version: '{}' is not recognized as a valid "
    "TLS protocol version (should be one of {})."
)

TLS_VERSION_UNACCEPTABLE_ERROR = (
    "The given tls_version: '{}' are no longer allowed (should be one of {})."
)

TLS_VER_NO_SUPPORTED = (
    "No supported TLS protocol version found in the 'tls-versions' list '{}'. "
)

CONNECTION_CLOSED_ERROR = {
    1810: "This session was closed because the connection has been idle for "
    "too long. Use 'mysqlx.getSession()' or 'mysqlx.getClient()' to create a "
    "new one.",
    1053: "This session was closed because the server is shutting down.",
    3169: "This session was closed because the connection has been killed in "
    "a different session. Use 'mysqlx.getSession()' or 'mysqlx.getClient()' "
    "to create a new one.",
}

_CONNECT_TIMEOUT = 10000  # Default connect timeout in milliseconds
_DROP_DATABASE_QUERY = "DROP DATABASE IF EXISTS {}"
_CREATE_DATABASE_QUERY = "CREATE DATABASE IF NOT EXISTS {}"
_SELECT_SCHEMA_NAME_QUERY = (
    "SELECT SCHEMA_NAME FROM INFORMATION_SCHEMA.SCHEMATA WHERE SCHEMA_NAME = '{}'"
)
_SELECT_VERSION_QUERY = "SELECT @@version"

_CNX_POOL_MAXSIZE = 99
_CNX_POOL_MAX_NAME_SIZE = 120
_CNX_POOL_NAME_REGEX = re.compile(r"[^a-zA-Z0-9._:\-*$#]")
_CNX_POOL_MAX_IDLE_TIME = 2147483
_CNX_POOL_QUEUE_TIMEOUT = 2147483

# Time is on seconds
_PENALTY_SERVER_OFFLINE = 1000000
_PENALTY_MAXED_OUT = 60
_PENALTY_NO_ADD_INFO = 60 * 60
_PENALTY_CONN_TIMEOUT = 60 * 60
_PENALTY_WRONG_PASSW = 60 * 60 * 24
_PENALTY_RESTARTING = 60
_TIMEOUT_PENALTIES = {
    # Server denays service e.g Max connections reached
    "[WinError 10053]": _PENALTY_MAXED_OUT,  # Established connection was aborted
    "[Errno 32]": _PENALTY_MAXED_OUT,  # Broken pipe
    # Server is Offline
    "[WinError 10061]": _PENALTY_SERVER_OFFLINE,  # Target machine actively refused it
    "[Errno 111]": _PENALTY_SERVER_OFFLINE,  # Connection refused
    # Host is offline:
    "[WinError 10060]": _PENALTY_CONN_TIMEOUT,  # Not respond after a period of time
    # No route to Host:
    "[Errno 11001]": _PENALTY_NO_ADD_INFO,  # getaddrinfo failed
    "[Errno -2]": _PENALTY_NO_ADD_INFO,  # Name or service not known
    # Wrong Password
    "Access denied": _PENALTY_WRONG_PASSW,
}
_TIMEOUT_PENALTIES_BY_ERR_NO = {1053: _PENALTY_RESTARTING}
_SPLIT_RE = re.compile(r",(?![^\(\)]*\))")
_PRIORITY_RE = re.compile(r"^\(address=(.+),priority=(\d+)\)$", re.VERBOSE)
_ROUTER_RE = re.compile(r"^\(address=(.+)[,]*\)$", re.VERBOSE)
_URI_SCHEME_RE = re.compile(r"^([a-zA-Z][a-zA-Z0-9+\-.]+)://(.*)")
_SSL_OPTS = [
    "ssl-cert",
    "ssl-ca",
    "ssl-key",
    "ssl-crl",
    "tls-versions",
    "tls-ciphersuites",
]
_SESS_OPTS = _SSL_OPTS + [
    "user",
    "password",
    "schema",
    "host",
    "port",
    "routers",
    "socket",
    "ssl-mode",
    "auth",
    "use-pure",
    "connect-timeout",
    "connection-attributes",
    "compression",
    "compression-algorithms",
    "dns-srv",
]


def generate_pool_name(**kwargs: Any) -> str:
    """Generate a pool name.

    This function takes keyword arguments, usually the connection arguments and
    tries to generate a name for the pool.

    Args:
        **kwargs: Arbitrary keyword arguments with the connection arguments.

    Raises:
        PoolError: If the name can't be generated.

    Returns:
        str: The generated pool name.
    """
    parts = []
    for key in ("host", "port", "user", "database", "client_id"):
        try:
            parts.append(str(kwargs[key]))
        except KeyError:
            pass

    if not parts:
        raise PoolError("Failed generating pool name; specify pool_name")

    return "_".join(parts)


def update_timeout_penalties_by_error(penalty_dict: Mapping[str, Any]) -> None:
    """Update the timeout penalties directory.

    Update the timeout penalties by error dictionary used to deactivate a pool.
    Args:
        penalty_dict (dict): The dictionary with the new timeouts.
    """
    if penalty_dict and isinstance(penalty_dict, dict):
        _TIMEOUT_PENALTIES_BY_ERR_NO.update(penalty_dict)


class SocketStream:
    """Implements a socket stream."""

    def __init__(self) -> None:
        self._socket: Optional[socket.socket] = None
        self._is_ssl: bool = False
        self._is_socket: bool = False
        self._host: Optional[str] = None

    def connect(self, params: Tuple, connect_timeout: float = _CONNECT_TIMEOUT) -> None:
        """Connects to a TCP service.

        Args:
            params (tuple): The connection parameters.

        Raises:
            :class:`mysqlx.InterfaceError`: If Unix socket is not supported.
        """
        if connect_timeout is not None:
            connect_timeout = connect_timeout / 1000  # Convert to seconds
        try:
            self._socket = socket.create_connection(params, connect_timeout)
            self._host = params[0]
        except ValueError:
            try:
                self._socket = socket.socket(socket.AF_UNIX)
                self._socket.settimeout(connect_timeout)
                self._socket.connect(params)
                self._is_socket = True
            except AttributeError:
                raise InterfaceError("Unix socket unsupported") from None
        self._socket.settimeout(None)

    def read(self, count: int) -> bytes:
        """Receive data from the socket.

        Args:
            count (int): Buffer size.

        Returns:
            bytes: The data received.
        """
        if self._socket is None:
            raise OperationalError("MySQLx Connection not available")
        buf = []
        while count > 0:
            data = self._socket.recv(count)
            if data == b"":
                raise RuntimeError("Unexpected connection close")
            buf.append(data)
            count -= len(data)
        return b"".join(buf)

    def sendall(self, data: bytes) -> None:
        """Send data to the socket.

        Args:
            data (bytes): The data to be sent.
        """
        if self._socket is None:
            raise OperationalError("MySQLx Connection not available")
        try:
            self._socket.sendall(data)
        except OSError as err:
            raise OperationalError(f"Unexpected socket error: {err}") from err

    def close(self) -> None:
        """Close the socket."""
        if not self._socket:
            return
        try:
            self._socket.shutdown(socket.SHUT_RDWR)
            self._socket.close()
        except OSError:
            # On [Errno 107] Transport endpoint is not connected
            pass
        self._socket = None

    def __del__(self) -> None:
        self.close()

    def set_ssl(
        self,
        ssl_protos: List[str],
        ssl_mode: str,
        ssl_ca: str,
        ssl_crl: str,
        ssl_cert: str,
        ssl_key: str,
        ssl_ciphers: List[str],
    ) -> None:
        """Set SSL parameters.

        Args:
            ssl_protos (list): SSL protocol to use.
            ssl_mode (str): SSL mode.
            ssl_ca (str): The certification authority certificate.
            ssl_crl (str): The certification revocation lists.
            ssl_cert (str): The certificate.
            ssl_key (str): The certificate key.
            ssl_ciphers (list): SSL ciphersuites to use.

        Raises:
            :class:`mysqlx.RuntimeError`: If Python installation has no SSL
                                          support.
            :class:`mysqlx.InterfaceError`: If the parameters are invalid.
        """
        if not SSL_AVAILABLE:
            self.close()
            raise RuntimeError("Python installation has no SSL support")

        if ssl_protos is None or not ssl_protos:
            # `check_hostname` is True by default
            context = ssl.create_default_context()
            if ssl_mode != SSLMode.VERIFY_IDENTITY:
                context.check_hostname = False
                if ssl_mode == SSLMode.REQUIRED:
                    context.verify_mode = ssl.CERT_NONE
        else:
            ssl_protos.sort(reverse=True)
            tls_version = ssl_protos[0]
            if (
                not TLS_V1_3_SUPPORTED
                and tls_version == "TLSv1.3"
                and len(ssl_protos) > 1
            ):
                tls_version = ssl_protos[1]
            ssl_protocol = TLS_VERSIONS[tls_version]
            context = ssl.SSLContext(ssl_protocol)

            if tls_version == "TLSv1.3":
                if "TLSv1.2" not in ssl_protos:
                    context.options |= ssl.OP_NO_TLSv1_2
                if "TLSv1.1" not in ssl_protos:
                    context.options |= ssl.OP_NO_TLSv1_1
                if "TLSv1" not in ssl_protos:
                    context.options |= ssl.OP_NO_TLSv1

            context.check_hostname = ssl_mode == SSLMode.VERIFY_IDENTITY

        if ssl_ca:
            try:
                context.load_verify_locations(ssl_ca)
                context.verify_mode = ssl.CERT_REQUIRED
            except (IOError, ssl.SSLError) as err:
                self.close()
                raise InterfaceError(f"Invalid CA Certificate: {err}") from err

        if ssl_crl:
            try:
                context.load_verify_locations(ssl_crl)
                context.verify_flags = ssl.VERIFY_CRL_CHECK_LEAF
            except (IOError, ssl.SSLError) as err:
                self.close()
                raise InterfaceError(f"Invalid CRL: {err}") from err

        if ssl_cert:
            try:
                context.load_cert_chain(ssl_cert, ssl_key)
            except (IOError, ssl.SSLError) as err:
                self.close()
                raise InterfaceError(f"Invalid Certificate/Key: {err}") from err

        if ssl_ciphers:
            context.set_ciphers(
                ":".join(iani_to_openssl_cs_name(ssl_protos[0], ssl_ciphers))
            )
        try:
            self._socket = context.wrap_socket(self._socket, server_hostname=self._host)
        except ssl.CertificateError as err:
            raise InterfaceError(f"{err}") from err

        self._is_ssl = True

        # Raise a deprecation warning if a deprecated TLS cipher or
        # version is being used.
        cipher, tls_version, _ = self._socket.cipher()
        warn_tls_version_deprecated(tls_version)
        warn_ciphersuites_deprecated(cipher, tls_version)

    def is_ssl(self) -> bool:
        """Verifies if SSL is being used.

        Returns:
            bool: Returns `True` if SSL is being used.
        """
        return self._is_ssl

    def is_socket(self) -> bool:
        """Verifies if socket connection is being used.

        Returns:
            bool: Returns `True` if socket connection is being used.
        """
        return self._is_socket

    def is_secure(self) -> bool:
        """Verifies if connection is secure.

        Returns:
            bool: Returns `True` if connection is secure.
        """
        return self._is_ssl or self._is_socket

    def is_open(self) -> bool:
        """Verifies if connection is open.

        Returns:
            bool: Returns `True` if connection is open.
        """
        return self._socket is not None


def catch_network_exception(func: Callable) -> Callable:
    """Decorator used to catch OSError or RuntimeError.

    Raises:
        :class:`mysqlx.InterfaceError`: If `OSError` or `RuntimeError`
                                        is raised.
    """

    @wraps(func)
    def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
        """Wrapper function."""
        try:
            if (
                isinstance(self, (Connection, PooledConnection))
                and self.is_server_disconnected()
            ):
                raise InterfaceError(*self.get_disconnected_reason())
            result = func(self, *args, **kwargs)
            if isinstance(result, BaseResult):
                warns: Any = result.get_warnings()
                for warn in warns:
                    if warn["code"] in CONNECTION_CLOSED_ERROR:
                        error_msg = CONNECTION_CLOSED_ERROR[warn["code"]]
                        reason = (
                            f"Connection close: {warn['msg']}: {error_msg}",
                            warn["code"],
                        )
                        if isinstance(self, (Connection, PooledConnection)):
                            self.set_server_disconnected(reason)
                        break
            return result
        except (InterfaceError, OSError, RuntimeError, TimeoutError) as err:
            if (
                func.__name__ == "get_column_metadata"
                and args
                and isinstance(args[0], SqlResult)
            ):
                warns = args[0].get_warnings()
                if warns:
                    warn = warns[0]
                    error_msg = CONNECTION_CLOSED_ERROR[warn["code"]]
                    reason = (
                        f"Connection close: {warn['msg']}: {error_msg}",
                        warn["code"],
                    )
                    if isinstance(self, PooledConnection):
                        self.pool.remove_connections()
                        # pool must be listed as faulty if server is shutting down
                        if warn["code"] == 1053:
                            PoolsManager().set_pool_unavailable(
                                self.pool, InterfaceError(*reason)
                            )
                    if isinstance(self, (Connection, PooledConnection)):
                        self.set_server_disconnected(reason)
                    self.disconnect()
                    raise InterfaceError(*reason) from err
            self.disconnect()
            raise

    return wrapper


class Router(dict):
    """Represents a set of connection parameters.

    Args:
       settings (dict): Dictionary with connection settings
    .. versionadded:: 8.0.20
    """

    def __init__(self, connection_params: Mapping[str, Any]) -> None:
        super().__init__()
        self.update(connection_params)
        self["available"] = self.get("available", True)

    def available(self) -> bool:
        """Verifies if the Router is available to open connections.

        Returns:
            bool: True if this Router is available else False.
        """
        return self["available"]

    def set_unavailable(self) -> None:
        """Sets this Router unavailable to open connections."""
        self["available"] = False

    def get_connection_params(self) -> Union[str, Tuple[str, Optional[int]]]:
        """Verifies if the Router is available to open connections.

        Returns:
            tuple: host and port or socket information tuple.
        """
        if "socket" in self:
            return self["socket"]
        return (self["host"], self["port"])


class RouterManager:
    """Manages the connection parameters of all the routers.

    Args:
        Routers (list): A list of Router objects.
        settings (dict): Dictionary with connection settings.
    .. versionadded:: 8.0.20
    """

    def __init__(self, routers: List[Router], settings: Dict[str, Any]) -> None:
        self._routers = routers
        self._settings = settings
        self._cur_priority_idx: int = 0
        self._can_failover: bool = True
        # Reuters status
        self._routers_directory: Dict[int, List[Router]] = {}
        self.routers_priority_list: List[int] = []
        self._ensure_priorities()

    def _ensure_priorities(self) -> None:
        """Ensure priorities.

        Raises:
            :class:`mysqlx.ProgrammingError`: If priorities are invalid.
        """
        priority_count = 0

        for router in self._routers:
            priority = router.get("priority", None)
            if priority is None:
                priority_count += 1
                router["priority"] = 100
            elif priority > 100:
                raise ProgrammingError("The priorities must be between 0 and 100", 4007)

        if 0 < priority_count < len(self._routers):
            raise ProgrammingError(
                "You must either assign no priority to any "
                "of the routers or give a priority for "
                "every router",
                4000,
            )

        self._routers.sort(key=lambda x: x["priority"], reverse=True)

        # Group servers with the same priority
        for router in self._routers:
            priority = router["priority"]
            if priority not in self._routers_directory:
                self._routers_directory[priority] = [Router(router)]
                self.routers_priority_list.append(priority)
            else:
                self._routers_directory[priority].append(Router(router))

    def _get_available_routers(self, priority: int) -> List[Router]:
        """Get a list of the current available routers that shares the given priority.

        Returns:
            list: A list of the current available routers.
        """
        router_list = self._routers_directory[priority]
        router_list = [router for router in router_list if router.available()]
        return router_list

    def _get_random_connection_params(self, priority: int) -> Router:
        """Get a random router from the group with the given priority.

        Returns:
            Router: A random router.
        """
        router_list = self._get_available_routers(priority)
        if not router_list:
            return None
        if len(router_list) == 1:
            return router_list[0]

        last = len(router_list) - 1
        index = random.randint(0, last)
        return router_list[index]

    def can_failover(self) -> bool:
        """Returns the next connection parameters.

        Returns:
            bool: True if there is more server to failover to else False.
        """
        return self._can_failover

    def get_next_router(self) -> Router:
        """Returns the next connection parameters.

        Returns:
            Router: with the connection parameters.
        """
        if not self._routers:
            self._can_failover = False
            router_settings = self._settings.copy()
            router_settings["host"] = self._settings.get("host", "localhost")
            router_settings["port"] = self._settings.get("port", 33060)
            return Router(router_settings)

        cur_priority = self.routers_priority_list[self._cur_priority_idx]
        routers_priority_len = len(self.routers_priority_list)

        search = True
        while search:
            router = self._get_random_connection_params(cur_priority)

            if router is not None or self._cur_priority_idx >= routers_priority_len:
                if (
                    self._cur_priority_idx == routers_priority_len - 1
                    and len(self._get_available_routers(cur_priority)) < 2
                ):
                    self._can_failover = False
                break

            # Search on next group
            self._cur_priority_idx += 1
            if self._cur_priority_idx < routers_priority_len:
                cur_priority = self.routers_priority_list[self._cur_priority_idx]

        return router

    def get_routers_directory(self) -> Dict[int, List[Router]]:
        """Returns the directory containing all the routers managed.

        Returns:
            dict: Dictionary with priorities as connection settings.
        """
        return self._routers_directory


class Connection:
    """Connection to a MySQL Server.

    Args:
        settings (dict): Dictionary with connection settings.
    """

    def __init__(self, settings: Dict[str, Any]) -> None:
        self.settings: Dict[str, Any] = settings
        self.stream: SocketStream = SocketStream()
        self.protocol: Optional[Protocol] = None
        self.keep_open: Optional[bool] = None
        self._user: Optional[str] = settings.get("user")
        self._password: Optional[str] = settings.get("password")
        self._schema: Optional[str] = settings.get("schema")
        self._active_result: Optional[ResultBaseType] = None
        self._routers: List[Router] = settings.get("routers", [])

        if "host" in settings and settings["host"]:
            self._routers.append(
                {
                    "host": settings.get("host"),
                    "port": settings.get("port", None),
                }
            )

        self.router_manager: RouterManager = RouterManager(self._routers, settings)
        self._connect_timeout: Optional[int] = settings.get(
            "connect-timeout", _CONNECT_TIMEOUT
        )
        if self._connect_timeout == 0:
            # None is assigned if connect timeout is 0, which disables timeouts
            # on socket operations
            self._connect_timeout = None

        self._stmt_counter: int = 0
        self._prepared_stmt_ids: List[int] = []
        self._prepared_stmt_supported: bool = True
        self._server_disconnected: bool = False
        self._server_disconnected_reason: Optional[Union[str, Tuple[str, int]]] = None

    def fetch_active_result(self) -> None:
        """Fetch active result."""
        if self._active_result is not None:
            self._active_result.fetch_all()
            self._active_result = None

    def set_active_result(self, result: ResultBaseType) -> None:
        """Set active result.

        Args:
            `Result`: It can be :class:`mysqlx.Result`,
                      :class:`mysqlx.BufferingResult`,
                      :class:`mysqlx.RowResult`, :class:`mysqlx.SqlResult` or
                      :class:`mysqlx.DocResult`.
        """
        self._active_result = result

    def connect(self) -> None:
        """Attempt to connect to the MySQL server.

        Raises:
            :class:`mysqlx.InterfaceError`: If fails to connect to the MySQL
                                            server.
            :class:`mysqlx.TimeoutError`: If connect timeout was exceeded.
        """
        # Loop and check
        error = None
        while self.router_manager.can_failover():
            try:
                router = self.router_manager.get_next_router()
                self.stream.connect(
                    router.get_connection_params(), self._connect_timeout  # type: ignore[arg-type]
                )
                reader = MessageReader(self.stream)
                writer = MessageWriter(self.stream)
                self.protocol = Protocol(reader, writer)

                caps_data = self.protocol.get_capabilites().capabilities
                caps = (
                    {get_item_or_attr(cap, "name").lower(): cap for cap in caps_data}
                    if caps_data
                    else {}
                )

                # Set TLS capabilities
                self._set_tls_capabilities(caps)

                # Set connection attributes capabilities
                if "attributes" in self.settings:
                    conn_attrs = self.settings["attributes"]
                    self.protocol.set_capabilities(session_connect_attrs=conn_attrs)

                # Set compression capabilities
                compression = self.settings.get("compression", Compression.PREFERRED)
                algorithms = self.settings.get("compression-algorithms")
                algorithm = (
                    None
                    if compression == Compression.DISABLED
                    else self._set_compression_capabilities(
                        caps, compression, algorithms
                    )
                )
                self._authenticate()
                self.protocol.set_compression(algorithm)
                return
            except (OSError, RuntimeError) as err:
                error = err
                router.set_unavailable()

        # Python 2.7 does not raise a socket.timeout exception when using
        # settimeout(), but it raises a socket.error with errno.EAGAIN (11)
        # or errno.EINPROGRESS (115) if connect-timeout value is too low
        if error is not None and isinstance(error, socket.timeout):
            if len(self._routers) <= 1:
                raise TimeoutError(
                    "Connection attempt to the server was aborted. "
                    f"Timeout of {self._connect_timeout} ms was exceeded"
                )
            raise TimeoutError(
                "All server connection attempts were aborted. "
                f"Timeout of {self._connect_timeout} ms was exceeded for each "
                "selected server"
            )
        if len(self._routers) <= 1:
            raise InterfaceError(f"Cannot connect to host: {error}")
        raise InterfaceError("Unable to connect to any of the target hosts", 4001)

    def _set_tls_capabilities(self, caps: Dict[str, Any]) -> None:
        """Set the TLS capabilities.

        Args:
            caps (dict): Dictionary with the server capabilities.

        Raises:
            :class:`mysqlx.OperationalError`: If SSL is not enabled at the
                                             server.
            :class:`mysqlx.RuntimeError`: If support for SSL is not available
                                          in Python.

        .. versionadded:: 8.0.21
        """
        if self.settings.get("ssl-mode") == SSLMode.DISABLED:
            return

        if self.stream.is_socket():
            if self.settings.get("ssl-mode"):
                logger.warning("SSL not required when using Unix socket.")
            return

        if "tls" not in caps:
            self.close_connection()
            raise OperationalError("SSL not enabled at server")

        is_ol7 = False
        if platform.system() == "Linux":
            distname, version, _ = linux_distribution()
            try:
                is_ol7 = "Oracle Linux" in distname and version.split(".")[0] == "7"
            except IndexError:
                is_ol7 = False

        if sys.version_info < (2, 7, 9) and not is_ol7:
            self.close_connection()
            raise RuntimeError(
                "The support for SSL is not available for this Python version"
            )

        self.protocol.set_capabilities(tls=True)
        self.stream.set_ssl(
            self.settings.get("tls-versions", None),
            self.settings.get("ssl-mode", SSLMode.REQUIRED),
            self.settings.get("ssl-ca"),
            self.settings.get("ssl-crl"),
            self.settings.get("ssl-cert"),
            self.settings.get("ssl-key"),
            self.settings.get("tls-ciphersuites"),
        )
        if "attributes" in self.settings:
            conn_attrs = self.settings["attributes"]
            self.protocol.set_capabilities(session_connect_attrs=conn_attrs)

    def _set_compression_capabilities(
        self,
        caps: Dict[str, Any],
        compression: str,
        algorithms: Optional[List[str]] = None,
    ) -> Optional[str]:
        """Set the compression capabilities.

        If compression is available, negociates client and server algorithms.
        By trying to find an algorithm from the requested compression
        algorithms list, which is supported by the server.

        If no compression algorithms list is provided, the following priority
        is used:

        1) zstd_stream
        2) lz4_message
        3) deflate_stream

        Args:
            caps (dict): Dictionary with the server capabilities.
            compression (str): The compression connection setting.
            algorithms (list): List of requested compression algorithms.

        Returns:
            str: The compression algorithm.

        .. versionadded:: 8.0.21
        .. versionchanged:: 8.0.22
        """
        compression_data = caps.get("compression")
        if compression_data is None:
            msg = "Compression requested but the server does not support it"
            if compression == Compression.REQUIRED:
                raise NotSupportedError(msg)
            logger.warning(msg)
            return None

        compression_dict = {}
        if isinstance(compression_data, dict):  # C extension is being used
            for fld in compression_data["value"]["obj"]["fld"]:
                compression_dict[fld["key"]] = [
                    value["scalar"]["v_string"]["value"].decode("utf-8")
                    for value in fld["value"]["array"]["value"]
                ]
        else:
            for fld in compression_data.value.obj.fld:
                compression_dict[fld.key] = [
                    value.scalar.v_string.value.decode("utf-8")
                    for value in fld.value.array.value
                ]

        server_algorithms = compression_dict.get("algorithm", [])
        algorithm = None

        # Try to find an algorithm from the requested compression algorithms
        # list, which is supported by the server
        if algorithms:
            # Resolve compression algorithms aliases and ignore unsupported
            client_algorithms = [
                COMPRESSION_ALGORITHMS[item]
                for item in algorithms
                if item in COMPRESSION_ALGORITHMS
            ]
            matched = [item for item in client_algorithms if item in server_algorithms]
            if matched:
                algorithm = COMPRESSION_ALGORITHMS.get(matched[0])
            elif compression == Compression.REQUIRED:
                raise InterfaceError(
                    "The connection compression is set as "
                    "required, but none of the provided "
                    "compression algorithms are supported."
                )
            else:
                return None  # Disable compression

        # No compression algorithms list was provided or couldn't found one
        # supported by the server
        if algorithm is None:
            if HAVE_ZSTD and "zstd_stream" in server_algorithms:
                algorithm = "zstd_stream"
            elif HAVE_LZ4 and "lz4_message" in server_algorithms:
                algorithm = "lz4_message"
            else:
                algorithm = "deflate_stream"

        if algorithm not in server_algorithms:
            msg = (
                "Compression requested but the compression algorithm "
                "negotiation failed"
            )
            if compression == Compression.REQUIRED:
                raise InterfaceError(msg)
            logger.warning(msg)
            return None

        self.protocol.set_capabilities(compression={"algorithm": algorithm})
        return algorithm

    def _authenticate(self) -> None:
        """Authenticate with the MySQL server."""
        auth = self.settings.get("auth")
        if auth:
            if auth == Auth.PLAIN:
                self._authenticate_plain()
            elif auth == Auth.SHA256_MEMORY:
                self._authenticate_sha256_memory()
            elif auth == Auth.MYSQL41:
                self._authenticate_mysql41()
        elif self.stream.is_secure():
            # Use PLAIN if no auth provided and connection is secure
            self._authenticate_plain()
        else:
            # Use MYSQL41 if connection is not secure
            try:
                self._authenticate_mysql41()
            except InterfaceError:
                pass
            else:
                return
            # Try SHA256_MEMORY if MYSQL41 fails
            try:
                self._authenticate_sha256_memory()
            except InterfaceError as err:
                raise InterfaceError(
                    "Authentication failed using MYSQL41 and "
                    "SHA256_MEMORY, check username and "
                    f"password or try a secure connection err:{err}"
                ) from err

    def _authenticate_mysql41(self) -> None:
        """Authenticate with the MySQL server using `MySQL41AuthPlugin`."""
        plugin = MySQL41AuthPlugin(self._user, self._password)
        self.protocol.send_auth_start(plugin.auth_name())
        extra_data = self.protocol.read_auth_continue()
        self.protocol.send_auth_continue(plugin.auth_data(extra_data))
        self.protocol.read_auth_ok()

    def _authenticate_plain(self) -> None:
        """Authenticate with the MySQL server using `PlainAuthPlugin`."""
        if not self.stream.is_secure():
            raise InterfaceError(
                "PLAIN authentication is not allowed via unencrypted connection"
            )
        plugin = PlainAuthPlugin(self._user, self._password)
        self.protocol.send_auth_start(plugin.auth_name(), auth_data=plugin.auth_data())
        self.protocol.read_auth_ok()

    def _authenticate_sha256_memory(self) -> None:
        """Authenticate with the MySQL server using `Sha256MemoryAuthPlugin`."""
        plugin = Sha256MemoryAuthPlugin(self._user, self._password)
        self.protocol.send_auth_start(plugin.auth_name())
        extra_data = self.protocol.read_auth_continue()
        self.protocol.send_auth_continue(plugin.auth_data(extra_data))
        self.protocol.read_auth_ok()

    def _deallocate_statement(self, statement: StatementType) -> None:
        """Deallocates statement.

        Args:
            statement (Statement): A `Statement` based type object.
        """
        if statement.prepared:
            self.protocol.send_prepare_deallocate(statement.stmt_id)
            self._prepared_stmt_ids.remove(statement.stmt_id)
            statement.prepared = False

    def _prepare_statement(
        self,
        msg_type: str,
        msg: MessageType,
        statement: Union[
            FindStatement,
            DeleteStatement,
            ModifyStatement,
            ReadStatement,
            RemoveStatement,
            UpdateStatement,
        ],
    ) -> None:
        """Prepares a statement.

        Args:
            msg_type (str): Message ID string.
            msg (mysqlx.protobuf.Message): MySQL X Protobuf Message.
            statement (Statement): A `Statement` based type object.
        """
        try:
            self.fetch_active_result()
            self.protocol.send_prepare_prepare(msg_type, msg, statement)
        except NotSupportedError:
            self._prepared_stmt_supported = False
            return
        self._prepared_stmt_ids.append(statement.stmt_id)
        statement.prepared = True

    def _execute_prepared_pipeline(
        self,
        msg_type: str,
        msg: MessageType,
        statement: Union[
            FindStatement,
            DeleteStatement,
            ModifyStatement,
            ReadStatement,
            RemoveStatement,
            UpdateStatement,
        ],
    ) -> None:
        """Executes the prepared statement pipeline.

        Args:
            msg_type (str): Message ID string.
            msg (mysqlx.protobuf.Message): MySQL X Protobuf Message.
            statement (Statement): A `Statement` based type object.
        """
        # For old servers without prepared statement support
        if not self._prepared_stmt_supported:
            # Crud::<Operation>
            self.protocol.send_msg_without_ps(msg_type, msg, statement)
            return

        if statement.deallocate_prepare_execute:
            # Prepare::Deallocate + Prepare::Prepare + Prepare::Execute
            self._deallocate_statement(statement)
            self._prepare_statement(msg_type, msg, statement)
            if not self._prepared_stmt_supported:
                self.protocol.send_msg_without_ps(msg_type, msg, statement)
                return
            self.protocol.send_prepare_execute(msg_type, msg, statement)
            statement.deallocate_prepare_execute = False
            statement.reset_exec_counter()
        elif statement.prepared and not statement.changed:
            # Prepare::Execute
            self.protocol.send_prepare_execute(msg_type, msg, statement)
        elif statement.changed and not statement.repeated:
            # Crud::<Operation>
            self._deallocate_statement(statement)
            self.protocol.send_msg_without_ps(msg_type, msg, statement)
            statement.changed = False
            statement.reset_exec_counter()
        elif not statement.changed and not statement.repeated:
            # Prepare::Prepare + Prepare::Execute
            if not statement.prepared:
                self._prepare_statement(msg_type, msg, statement)
            if not self._prepared_stmt_supported:
                self.protocol.send_msg_without_ps(msg_type, msg, statement)
                return
            self.protocol.send_prepare_execute(msg_type, msg, statement)
        elif statement.changed and statement.repeated:
            # Prepare::Deallocate + Crud::<Operation>
            self._deallocate_statement(statement)
            self.protocol.send_msg_without_ps(msg_type, msg, statement)
            statement.changed = False
            statement.reset_exec_counter()

        statement.increment_exec_counter()

    @catch_network_exception
    def send_sql(self, statement: SqlStatement) -> SqlResult:
        """Execute a SQL statement.

        Args:
            sql (str): The SQL statement.

        Raises:
            :class:`mysqlx.ProgrammingError`: If the SQL statement is not a
                                              valid string.
        """
        sql = statement.sql
        if self.protocol is None:
            raise OperationalError("MySQLx Connection not available")
        if not isinstance(sql, str):
            raise ProgrammingError("The SQL statement is not a valid string")
        msg_type, msg = self.protocol.build_execute_statement("sql", sql)
        self.protocol.send_msg_without_ps(msg_type, msg, statement)
        return SqlResult(self)

    @catch_network_exception
    def send_insert(self, statement: Union[AddStatement, InsertStatement]) -> Result:
        """Send an insert statement.

        Args:
            statement (`Statement`): It can be :class:`mysqlx.InsertStatement`
                                     or :class:`mysqlx.AddStatement`.

        Returns:
            :class:`mysqlx.Result`: A result object.
        """
        if self.protocol is None:
            raise OperationalError("MySQLx Connection not available")
        msg_type, msg = self.protocol.build_insert(statement)
        self.protocol.send_msg(msg_type, msg)
        ids = None
        if isinstance(statement, AddStatement):
            ids = statement.ids
        return Result(self, ids)

    @catch_network_exception
    def send_find(
        self, statement: Union[FindStatement, SelectStatement]
    ) -> Union[DocResult, RowResult]:
        """Send an find statement.

        Args:
            statement (`Statement`): It can be :class:`mysqlx.SelectStatement`
                                     or :class:`mysqlx.FindStatement`.

        Returns:
            `Result`: It can be class:`mysqlx.DocResult` or
                      :class:`mysqlx.RowResult`.
        """
        msg_type, msg = self.protocol.build_find(statement)
        self._execute_prepared_pipeline(msg_type, msg, statement)
        return DocResult(self) if statement.is_doc_based() else RowResult(self)

    @catch_network_exception
    def send_delete(self, statement: Union[DeleteStatement, RemoveStatement]) -> Result:
        """Send an delete statement.

        Args:
            statement (`Statement`): It can be :class:`mysqlx.RemoveStatement`
                                     or :class:`mysqlx.DeleteStatement`.

        Returns:
            :class:`mysqlx.Result`: The result object.
        """
        msg_type, msg = self.protocol.build_delete(statement)
        self._execute_prepared_pipeline(msg_type, msg, statement)
        return Result(self)

    @catch_network_exception
    def send_update(self, statement: Union[ModifyStatement, UpdateStatement]) -> Result:
        """Send an delete statement.

        Args:
            statement (`Statement`): It can be :class:`mysqlx.ModifyStatement`
                                     or :class:`mysqlx.UpdateStatement`.

        Returns:
            :class:`mysqlx.Result`: The result object.
        """
        msg_type, msg = self.protocol.build_update(statement)
        self._execute_prepared_pipeline(msg_type, msg, statement)
        return Result(self)

    @catch_network_exception
    def execute_nonquery(
        self,
        namespace: str,
        cmd: str,
        raise_on_fail: bool,
        fields: Optional[Dict[str, Any]] = None,
    ) -> Optional[Result]:
        """Execute a non query command.

        Args:
            namespace (str): The namespace.
            cmd (str): The command.
            raise_on_fail (bool): `True` to raise on fail.
            fields (Optional[dict]): The message fields.

        Raises:
            :class:`mysqlx.OperationalError`: On errors.

        Returns:
            :class:`mysqlx.Result`: The result object.
        """
        try:
            msg_type, msg = self.protocol.build_execute_statement(
                namespace, cmd, fields
            )
            self.protocol.send_msg(msg_type, msg)
            return Result(self)
        except OperationalError:
            if raise_on_fail:
                raise
        return None

    @catch_network_exception
    def execute_sql_scalar(self, sql: StatementType) -> int:
        """Execute a SQL scalar.

        Args:
            sql (str): The SQL statement.

        Raises:
            :class:`mysqlx.InterfaceError`: If no data found.

        Returns:
            :class:`mysqlx.Result`: The result.
        """
        msg_type, msg = self.protocol.build_execute_statement("sql", sql)
        self.protocol.send_msg(msg_type, msg)
        result = RowResult(self)
        result.fetch_all()
        if result.count == 0:
            raise InterfaceError("No data found")
        return result[0][0]

    @catch_network_exception
    def get_row_result(self, cmd: str, fields: Dict[str, Any]) -> RowResult:
        """Returns the row result.

        Args:
            cmd (str): The command.
            fields (dict): The message fields.

        Returns:
            :class:`mysqlx.RowResult`: The result object.
        """
        msg_type, msg = self.protocol.build_execute_statement("mysqlx", cmd, fields)
        self.protocol.send_msg(msg_type, msg)
        return RowResult(self)

    @catch_network_exception
    def read_row(self, result: RowResult) -> Optional[MessageType]:
        """Read row.

        Args:
            result (:class:`mysqlx.RowResult`): The result object.
        """
        return self.protocol.read_row(result)

    @catch_network_exception
    def close_result(self, result: Result) -> None:
        """Close result.

        Args:
            result (:class:`mysqlx.Result`): The result object.
        """
        self.protocol.close_result(result)

    @catch_network_exception
    def get_column_metadata(self, result: Result) -> List[ColumnType]:
        """Get column metadata.

        Args:
            result (:class:`mysqlx.Result`): The result object.
        """
        return self.protocol.get_column_metadata(result)

    def get_next_statement_id(self) -> int:
        """Returns the next statement ID.

        Returns:
            int: A statement ID.

        .. versionadded:: 8.0.16
        """
        self._stmt_counter += 1
        return self._stmt_counter

    def is_open(self) -> bool:
        """Check if connection is open.

        Returns:
            bool: `True` if connection is open.
        """
        return self.stream.is_open()

    def set_server_disconnected(self, reason: Union[str, Tuple[str, int]]) -> None:
        """Set the disconnection message from the server.

        Args:
            reason (str): disconnection reason from the server.
        """
        self._server_disconnected = True
        self._server_disconnected_reason = reason

    def is_server_disconnected(self) -> bool:
        """Verify if the session has been disconnect from the server.

        Returns:
            bool: `True` if the connection has been closed from the server
                  otherwise `False`.
        """
        return self._server_disconnected

    def get_disconnected_reason(self) -> Optional[Union[str, Tuple[str, int]]]:
        """Get the disconnection message sent by the server.

        Returns:
            string: disconnection reason from the server.
        """
        return self._server_disconnected_reason

    def disconnect(self) -> None:
        """Disconnect from server."""
        if not self.is_open():
            return
        self.stream.close()

    def close_session(self) -> None:
        """Close a sucessfully authenticated session."""
        if not self.is_open():
            return

        try:
            # Fetch any active result
            self.fetch_active_result()
            # Deallocate all prepared statements
            if self._prepared_stmt_supported:
                for stmt_id in self._prepared_stmt_ids:
                    self.protocol.send_prepare_deallocate(stmt_id)
                self._stmt_counter = 0
            # Send session close
            self.protocol.send_close()
            self.protocol.read_ok()
        except (InterfaceError, OperationalError, OSError) as err:
            logger.warning(
                "Warning: An error occurred while attempting to close the "
                "connection: %s",
                err,
            )
        finally:
            # The remote connection with the server has been lost,
            # close the connection locally.
            self.stream.close()

    def reset_session(self) -> None:
        """Reset a sucessfully authenticated session."""
        if not self.is_open():
            return
        if self._active_result is not None:
            self._active_result.fetch_all()
        try:
            self.keep_open = self.protocol.send_reset(self.keep_open)
        except (InterfaceError, OperationalError) as err:
            logger.warning(
                "Warning: An error occurred while attempting to reset the "
                "session: %s",
                err,
            )

    def close_connection(self) -> None:
        """Announce to the server that the client wants to close the
        connection. Discards any session state of the server.
        """
        if not self.is_open():
            return
        if self._active_result is not None:
            self._active_result.fetch_all()
        self.protocol.send_connection_close()
        self.protocol.read_ok()
        self.stream.close()


class PooledConnection(Connection):
    """Class to hold :class:`Connection` instances in a pool.

    PooledConnection is used by :class:`ConnectionPool` to facilitate the
    connection to return to the pool once is not required, more specifically
    once the close_session() method is invoked. It works like a normal
    Connection except for methods like close() and sql().

    The close_session() method will add the connection back to the pool rather
    than disconnecting from the MySQL server.

    The sql() method is used to execute sql statements.

    Args:
        pool (ConnectionPool): The pool where this connection must return.

    .. versionadded:: 8.0.13
    """

    def __init__(self, pool: ConnectionPool) -> None:
        if not isinstance(pool, ConnectionPool):
            raise AttributeError("pool should be a ConnectionPool object")
        super().__init__(pool.cnx_config)
        self.pool: ConnectionPool = pool
        self.host: str = pool.cnx_config["host"]
        self.port: int = pool.cnx_config["port"]

    def close_connection(self) -> None:
        """Closes the connection.

        This method closes the socket.
        """
        super().close_session()

    def close_session(self) -> None:
        """Do not close, but add connection back to pool.

        The close_session() method does not close the connection with the
        MySQL server. The connection is added back to the pool so it
        can be reused.

        When the pool is configured to reset the session, the session
        state will be cleared by re-authenticating the user once the connection
        is get from the pool.
        """
        self.pool.add_connection(self)

    def reconnect(self) -> None:
        """Reconnect this connection."""
        if self._active_result is not None:
            self._active_result.fetch_all()
        self._authenticate()

    def reset(self) -> None:
        """Reset the connection.

        Resets the connection by re-authenticate.
        """
        self.reconnect()

    def sql(self, sql: str) -> SqlStatement:
        """Creates a :class:`mysqlx.SqlStatement` object to allow running the
        SQL statement on the target MySQL Server.

        Args:
            sql (string): The SQL statement to be executed.

        Returns:
            mysqlx.SqlStatement: SqlStatement object.
        """
        return SqlStatement(self, sql)


class ConnectionPool(queue.Queue):
    """This class represents a pool of connections.

    Initializes the Pool with the given name and settings.

    Args:
        name (str): The name of the pool, used to track a single pool per
                    combination of host and user.
        **kwargs:
            max_size (int): The maximun number of connections to hold in
                            the pool.
            reset_session (bool): If the connection should be reseted when
                                  is taken from the pool.
            max_idle_time (int): The maximum number of milliseconds to allow
                                 a connection to be idle in the queue before
                                 being closed. Zero value means infinite.
            queue_timeout (int): The maximum number of milliseconds a
                                 request will wait for a connection to
                                 become available. A zero value means
                                 infinite.
            priority (int): The router priority, to choose this pool over
                            other with lower priority.

    Raises:
        :class:`mysqlx.PoolError` on errors.

    .. versionadded:: 8.0.13
    """

    def __init__(self, name: str, **kwargs: Any) -> None:
        self.name: Optional[str] = None
        self._set_pool_name(name)
        self._open_sessions: int = 0
        self._connections_openned: List[PooledConnection] = []
        self._available: bool = True
        self._timeout: int = 0
        self._timeout_stamp: datetime = datetime.now()
        self.pool_max_size: int = kwargs.get("max_size", 25)
        # Can't invoke super due to Queue not is a new-style class
        queue.Queue.__init__(self, self.pool_max_size)
        self.reset_session: bool = kwargs.get("reset_session", True)
        self.max_idle_time: int = kwargs.get("max_idle_time", 25)
        self.settings: Dict[str, Any] = kwargs
        self.queue_timeout: int = kwargs.get("queue_timeout", 25)
        self.priority: int = kwargs.get("priority", 0)
        self.cnx_config: Dict[str, Any] = kwargs
        self.host: str = kwargs["host"]
        self.port: int = kwargs["port"]

    def _set_pool_name(self, pool_name: str) -> None:
        r"""Set the name of the pool.

        This method checks the validity and sets the name of the pool.

        Args:
            pool_name (str): The pool name.

        Raises:
            AttributeError: If the pool_name contains illegal characters
                            ([^a-zA-Z0-9._\-*$#]) or is longer than
                            connection._CNX_POOL_MAX_NAME_SIZE.
        """
        if _CNX_POOL_NAME_REGEX.search(pool_name):
            raise AttributeError(f"Pool name '{pool_name}' contains illegal characters")
        if len(pool_name) > _CNX_POOL_MAX_NAME_SIZE:
            raise AttributeError(f"Pool name '{pool_name}' is too long")
        self.name = pool_name

    @property
    def open_connections(self) -> int:
        """Returns the number of open connections that can return to this pool."""
        return len(self._connections_openned)

    def remove_connection(self, cnx: Optional[PooledConnection] = None) -> None:
        """Removes a connection from this pool.

        Args:
            cnx (PooledConnection): The connection object.
        """
        self._connections_openned.remove(cnx)

    def remove_connections(self) -> None:
        """Removes all the connections from the pool."""
        while self.qsize() > 0:
            try:
                cnx = self.get(block=True, timeout=self.queue_timeout)
            except queue.Empty:
                pass
            else:
                try:
                    cnx.close_connection()
                except (RuntimeError, OSError, InterfaceError):
                    pass
                finally:
                    self.remove_connection(cnx)

    def add_connection(self, cnx: Optional[PooledConnection] = None) -> None:
        """Adds a connection to this pool.

        This method instantiates a Connection using the configuration passed
        when initializing the ConnectionPool instance or using the set_config()
        method.
        If cnx is a Connection instance, it will be added to the queue.

        Args:
            cnx (PooledConnection): The connection object.

        Raises:
            PoolError: If no configuration is set, if no more connection can
                       be added (maximum reached) or if the connection can not
                       be instantiated.
        """
        if not self.cnx_config:
            raise PoolError("Connection configuration not available")

        if self.full():
            raise PoolError("Failed adding connection; queue is full")

        if not cnx:
            cnx = PooledConnection(self)
            # mysqlx_wait_timeout is only available on MySQL 8
            ver = cnx.sql(_SELECT_VERSION_QUERY).execute().fetch_all()[0][0]
            if tuple(int(n) for n in ver.split("-")[0].split(".")) > (
                8,
                0,
                10,
            ):
                cnx.sql(f"set mysqlx_wait_timeout = {self.max_idle_time}").execute()
            self._connections_openned.append(cnx)
        else:
            if not isinstance(cnx, PooledConnection):
                raise PoolError("Connection instance not subclass of PooledSession")
            if cnx.is_server_disconnected():
                self.remove_connections()
                cnx.close()

        self.queue_connection(cnx)

    def queue_connection(self, cnx: PooledConnection) -> None:
        """Put connection back in the queue:

        This method is putting a connection back in the queue.
        It will not acquire a lock as the methods using _queue_connection() will
        have it set.

        Args:
            PooledConnection: The connection object.

        Raises:
            PoolError: On errors.
        """
        if not isinstance(cnx, PooledConnection):
            raise PoolError("Connection instance not subclass of PooledSession.")

        # Reset the connection
        if self.reset_session:
            cnx.reset_session()
        try:
            self.put(cnx, block=False)
        except queue.Full as err:
            raise PoolError("Failed adding connection; queue is full") from err

    def track_connection(self, connection: PooledConnection) -> None:
        """Tracks connection in order of close it when client.close() is invoke."""
        self._connections_openned.append(connection)

    def __str__(self) -> str:
        return self.name

    def available(self) -> bool:
        """Returns if this pool is available for pool connections from it.

        Returns:
            bool: True if this pool is available else False.
        .. versionadded:: 8.0.20
        """
        return self._available

    def set_unavailable(self, time_out: int = -1) -> None:
        """Sets this pool unavailable for a period of time (in seconds).

        .. versionadded:: 8.0.20
        """
        if self._available:
            logger.warning(
                "ConnectionPool.set_unavailable pool: %s time_out: %s",
                self,
                time_out,
            )
            self._available = False
            self._timeout_stamp = datetime.now()
            self._timeout = time_out

    def set_available(self) -> None:
        """Sets this pool available for pool connections from it.

        .. versionadded:: 8.0.20
        """
        self._available = True
        self._timeout_stamp = datetime.now()

    def get_timeout_stamp(self) -> Tuple[int, datetime]:
        """Returns the penalized time (timeout) and the time at the penalty.

        Returns:
            tuple: penalty seconds (int), timestamp at penalty (datetime object)
        .. versionadded:: 8.0.20
        """
        return (self._timeout, self._timeout_stamp)

    def close(self) -> None:
        """Empty this ConnectionPool."""
        for cnx in self._connections_openned:
            cnx.close_connection()


class PoolsManager:
    """Manages a pool of connections for a host or hosts in routers.

    This class handles all the pools of Connections.

    .. versionadded:: 8.0.13
    """

    __instance: PoolsManager = None
    __pools: Dict[str, Any] = {}

    def __new__(cls) -> PoolsManager:
        if PoolsManager.__instance is None:
            PoolsManager.__instance = object.__new__(cls)
            PoolsManager.__pools = {}
        return PoolsManager.__instance

    def _pool_exists(self, client_id: str, pool_name: str) -> bool:
        """Verifies if a pool exists with the given name.

        Args:
            client_id (str): The client id.
            pool_name (str): The name of the pool.

        Returns:
            bool: Returns `True` if the pool exists otherwise `False`.
        """
        pools = self.__pools.get(client_id, [])
        for pool in pools:
            if pool.name == pool_name:
                return True
        return False

    def _get_pools(self, settings: Dict[str, Any]) -> List:
        """Retrieves a list of pools that shares the given settings.

        Args:
            settings (dict): the configuration of the pool.

        Returns:
            list: A list of pools that shares the given settings.
        """
        available_pools = []
        pool_names = []
        connections_settings = self._get_connections_settings(settings)

        # Generate the names of the pools this settings can connect to
        for router_name, _ in connections_settings:
            pool_names.append(router_name)

        # Generate the names of the pools this settings can connect to
        for pool in self.__pools.get(settings.get("client_id", "No id"), []):
            if pool.name in pool_names:
                available_pools.append(pool)
        return available_pools

    @staticmethod
    def _get_connections_settings(
        settings: Dict[str, Any],
    ) -> List[Tuple[str, Dict[str, Any]]]:
        """Generates a list of separated connection settings for each host.

        Gets a list of connection settings for each host or router found in the
        given settings.

        Args:
            settings (dict): The configuration for the connections.

        Returns:
            list: A list of connections settings
        """
        pool_settings = settings.copy()
        routers = pool_settings.get("routers", [])
        connections_settings = []
        if "routers" in pool_settings:
            pool_settings.pop("routers")
        if "host" in pool_settings and "port" in pool_settings:
            routers.append(
                {
                    "priority": 100,
                    "weight": 0,
                    "host": pool_settings["host"],
                    "port": pool_settings["port"],
                }
            )
        # Order routers
        routers.sort(key=lambda x: (x["priority"], -x.get("weight", 0)))
        for router in routers:
            connection_settings = pool_settings.copy()
            connection_settings["host"] = router["host"]
            connection_settings["port"] = router["port"]
            connection_settings["priority"] = router["priority"]
            connection_settings["weight"] = router.get("weight", 0)
            connections_settings.append(
                (
                    generate_pool_name(**connection_settings),
                    connection_settings,
                )
            )
        return connections_settings

    def create_pool(self, cnx_settings: Dict[str, Any]) -> None:
        """Creates a `ConnectionPool` instance to hold the connections.

        Creates a `ConnectionPool` instance to hold the connections only if
        no other pool exists with the same configuration.

        Args:
            cnx_settings (dict): The configuration for the connections.
        """
        connections_settings = self._get_connections_settings(cnx_settings)

        # Subscribe client if it does not exists
        if cnx_settings.get("client_id", "No id") not in self.__pools:
            self.__pools[cnx_settings.get("client_id", "No id")] = []

        # Create a pool for each router
        for router_name, settings in connections_settings:
            if self._pool_exists(cnx_settings.get("client_id", "No id"), router_name):
                continue
            pool = self.__pools.get(cnx_settings.get("client_id", "No id"), [])
            pool.append(ConnectionPool(router_name, **settings))

    @staticmethod
    def _get_random_pool(pool_list: List[ConnectionPool]) -> ConnectionPool:
        """Get a random router from the group with the given priority.

        Returns:
            Router: a random router.

        .. versionadded:: 8.0.20
        """
        if not pool_list:
            return None
        if len(pool_list) == 1:
            return pool_list[0]

        last = len(pool_list) - 1
        index = random.randint(0, last)
        return pool_list[index]

    @staticmethod
    def _get_sublist(
        pools: List[ConnectionPool], index: int, cur_priority: int
    ) -> List[ConnectionPool]:
        sublist = []
        next_priority = None
        while index < len(pools):
            next_priority = pools[index].priority
            if cur_priority == next_priority and pools[index].available():
                sublist.append(pools[index])
            elif cur_priority != next_priority:
                break
            index += 1
        return sublist

    def _get_next_pool(
        self, pools: List[ConnectionPool], cur_priority: int
    ) -> ConnectionPool:
        index = 0
        for pool in pools:
            if pool.available() and cur_priority == pool.priority:
                break
            index += 1
        subpool: List = []
        while not subpool and index < len(pools):
            subpool = self._get_sublist(pools, index, cur_priority)
            index += 1
        return self._get_random_pool(subpool)

    @staticmethod
    def _get_next_priority(
        pools: List[ConnectionPool], cur_priority: Optional[int] = None
    ) -> int:
        if cur_priority is None and pools:
            return pools[0].priority
        # find the first pool that does not share the same priority
        for t_pool in pools:
            if t_pool.available():
                cur_priority = t_pool.priority
                return cur_priority
        return pools[0].priority

    def _check_unavailable_pools(
        self, settings: Dict[str, Any], revive: Optional[bool] = None
    ) -> None:
        pools = self._get_pools(settings)
        for pool in pools:
            if pool.available():
                continue
            timeout, timeout_stamp = pool.get_timeout_stamp()
            if revive:
                timeout = revive
            if datetime.now() > (timeout_stamp + timedelta(seconds=timeout)):
                pool.set_available()

    def get_connection(self, settings: Dict[str, Any]) -> PooledConnection:
        """Get a connection from the pool.

        This method returns an `PooledConnection` instance which has a reference
        to the pool that created it, and can be used as a normal Connection.

        When the MySQL connection is not connected, a reconnect is attempted.

        Raises:
            :class:`PoolError`: On errors.

        Returns:
            PooledConnection: A pooled connection object.
        """

        def set_mysqlx_wait_timeout(cnx: PooledConnection) -> None:
            ver = cnx.sql(_SELECT_VERSION_QUERY).execute().fetch_all()[0][0]
            # mysqlx_wait_timeout is only available on MySQL 8
            if tuple(int(n) for n in ver.split("-")[0].split(".")) > (
                8,
                0,
                10,
            ):
                cnx.sql(f"set mysqlx_wait_timeout = {pool.max_idle_time}").execute()

        pools = self._get_pools(settings)
        cur_priority = settings.get("cur_priority", None)
        error_list = []
        self._check_unavailable_pools(settings)
        cur_priority = self._get_next_priority(pools, cur_priority)
        if cur_priority is None:
            raise PoolError(
                "Unable to connect to any of the target hosts. No pool is available"
            )
        settings["cur_priority"] = cur_priority
        pool = self._get_next_pool(pools, cur_priority)
        lock = threading.RLock()
        while pool is not None:
            try:
                # Check connections aviability in this pool
                if pool.qsize() > 0:
                    # We have connections in pool, try to return a working one
                    with lock:
                        try:
                            cnx = pool.get(block=True, timeout=pool.queue_timeout)
                        except queue.Empty:
                            raise PoolError(
                                "Failed getting connection; pool exhausted"
                            ) from None
                        try:
                            if cnx.is_server_disconnected():
                                pool.remove_connections()
                            # Only reset the connection by re-authentification
                            # if the connection was unable to keep open by the
                            # server
                            if not cnx.keep_open:
                                cnx.reset()
                            set_mysqlx_wait_timeout(cnx)
                        except (RuntimeError, OSError, InterfaceError):
                            # Unable to reset connection, close and remove
                            try:
                                cnx.close_connection()
                            except (RuntimeError, OSError, InterfaceError):
                                pass
                            finally:
                                pool.remove_connection(cnx)
                            # By WL#13222 all idle sessions that connect to the
                            # same endpoint should be removed from the pool.
                            while pool.qsize() > 0:
                                try:
                                    cnx = pool.get(
                                        block=True, timeout=pool.queue_timeout
                                    )
                                except queue.Empty:
                                    pass
                                else:
                                    try:
                                        cnx.close_connection()
                                    except (RuntimeError, OSError, InterfaceError):
                                        pass
                                    finally:
                                        pool.remove_connection(cnx)
                            # Connection was closed by the server, create new
                            try:
                                cnx = PooledConnection(pool)
                                pool.track_connection(cnx)
                                cnx.connect()
                                set_mysqlx_wait_timeout(cnx)
                            except (RuntimeError, OSError, InterfaceError):
                                pass
                            finally:
                                # Server must be down, take down idle
                                # connections from this pool
                                while pool.qsize() > 0:
                                    try:
                                        cnx = pool.get(
                                            block=True,
                                            timeout=pool.queue_timeout,
                                        )
                                        cnx.close_connection()
                                        pool.remove_connection(cnx)
                                    except (RuntimeError, OSError, InterfaceError):
                                        pass
                        return cnx
                elif pool.open_connections < pool.pool_max_size:
                    # No connections in pool, but we can open a new one
                    cnx = PooledConnection(pool)
                    pool.track_connection(cnx)
                    cnx.connect()
                    set_mysqlx_wait_timeout(cnx)
                    return cnx
                else:
                    # Pool is exaust so the client needs to wait
                    with lock:
                        try:
                            cnx = pool.get(block=True, timeout=pool.queue_timeout)
                            cnx.reset()
                            set_mysqlx_wait_timeout(cnx)
                            return cnx
                        except queue.Empty:
                            raise PoolError("pool max size has been reached") from None
            except (InterfaceError, TimeoutError, PoolError) as err:
                error_list.append(f"pool: {pool} error: {err}")
                if isinstance(err, PoolError):
                    # Pool can be exhaust now but can be ready again in no time,
                    # e.g a connection is returned to the pool.
                    pool.set_unavailable(2)
                else:
                    self.set_pool_unavailable(pool, err)

                self._check_unavailable_pools(settings)
                # Try next pool with the same priority
                pool = self._get_next_pool(pools, cur_priority)

                if pool is None:
                    cur_priority = self._get_next_priority(pools, cur_priority)
                    settings["cur_priority"] = cur_priority
                    pool = self._get_next_pool(pools, cur_priority)
                    if pool is None:
                        msg = "\n  ".join(error_list)
                        raise PoolError(
                            "Unable to connect to any of the target hosts: "
                            f"[\n  {msg}\n]"
                        ) from err
                continue

        raise PoolError("Unable to connect to any of the target hosts")

    def close_pool(self, cnx_settings: Dict[str, Any]) -> int:
        """Closes the connections in the pools

        Returns:
            int: The number of closed pools
        """
        pools = self._get_pools(cnx_settings)
        for pool in pools:
            pool.close()
            # Remove the pool
            if cnx_settings.get("client_id", None) is not None:
                client_pools = self.__pools.get(cnx_settings.get("client_id"))
                if pool in client_pools:
                    client_pools.remove(pool)
        return len(pools)

    @staticmethod
    def set_pool_unavailable(
        pool: ConnectionPool, err: Union[InterfaceError, TimeoutError]
    ) -> None:
        """Sets a pool as unavailable.

        The time a pool is set unavailable depends on the given error message
        or the error number.

        Args:
            pool (ConnectionPool): The pool to set unavailable.
            err (Exception): The raised exception raised by a connection belonging
                             to the pool.
        """
        penalty = None
        try:
            err_no = err.errno
            penalty = _TIMEOUT_PENALTIES_BY_ERR_NO[err_no]
        except (AttributeError, KeyError):
            pass
        if not penalty:
            err_msg = err.msg
            for key, value in _TIMEOUT_PENALTIES.items():
                if key in err_msg:
                    penalty = value
        if penalty:
            pool.set_unavailable(penalty)
        else:
            # Other errors are severe punished
            pool.set_unavailable(100000)


class Session:
    """Enables interaction with a X Protocol enabled MySQL Product.

    The functionality includes:

    - Accessing available schemas.
    - Schema management operations.
    - Retrieval of connection information.

    Args:
        settings (dict): Connection data used to connect to the database.
    """

    def __init__(self, settings: Dict[str, Any]) -> None:
        self.use_pure: bool = settings.get("use-pure", Protobuf.use_pure)
        self._settings: Dict[str, Any] = settings

        # Check for DNS SRV
        if settings.get("host") and settings.get("dns-srv"):
            if not HAVE_DNSPYTHON:
                raise InterfaceError(
                    "MySQL host configuration requested DNS "
                    "SRV. This requires the Python dnspython "
                    "module. Please refer to documentation"
                )
            try:
                srv_records = dns.resolver.query(settings["host"], "SRV")
            except dns.exception.DNSException as err:
                raise InterfaceError(
                    f"Unable to locate any hosts for '{settings['host']}'"
                ) from err
            self._settings["routers"] = []
            for srv in srv_records:
                self._settings["routers"].append(
                    {
                        "host": srv.target.to_text(omit_final_dot=True),
                        "port": srv.port,
                        "priority": srv.priority,
                        "weight": srv.weight,
                    }
                )

        if (
            "connection-attributes" not in self._settings
            or self._settings["connection-attributes"] is not False
        ):
            self._settings["attributes"] = {}
            self._init_attributes()

        if "pooling" in settings and settings["pooling"]:
            # Create pool and retrieve a Connection instance
            PoolsManager().create_pool(settings)
            self._connection: Connection = PoolsManager().get_connection(settings)
            if self._connection is None:
                raise PoolError("Connection could not be retrieved from pool")
        else:
            self._connection = Connection(self._settings)
            self._connection.connect()
        # Set default schema
        schema = self._settings.get("schema")
        if schema:
            try:
                self.sql(f"USE {quote_identifier(schema)}").execute()
            except OperationalError as err:
                # Access denied for user will raise err.errno = 1044
                errmsg = (
                    err.msg
                    if err.errno == 1044
                    else f"Default schema '{schema}' does not exists"
                )
                raise InterfaceError(errmsg, err.errno) from err

    def __enter__(self) -> Session:
        return self

    def __exit__(
        self,
        exc_type: Type[BaseException],
        exc_value: BaseException,
        traceback: TracebackType,
    ) -> None:
        self.close()

    def _init_attributes(self) -> None:
        """Setup default and user defined connection-attributes."""
        if os.name == "nt":
            if "64" in platform.architecture()[0]:
                platform_arch: Union[str, Tuple[str, str]] = "x86_64"
            elif "32" in platform.architecture()[0]:
                platform_arch = "i386"
            else:
                platform_arch = platform.architecture()
            os_ver = f"Windows-{platform.win32_ver()[1]}"
        else:
            platform_arch = platform.machine()
            if platform.system() == "Darwin":
                os_ver = f"macOS-{platform.mac_ver()[0]}"
            else:
                os_ver = "-".join(linux_distribution()[0:2])

        license_chunks = LICENSE.split(" ")
        if license_chunks[0] == "GPLv2":
            client_license = "GPL-2.0"
        else:
            client_license = "Commercial"

        default_attributes = {
            # Process id
            "_pid": str(os.getpid()),
            # Platform architecture
            "_platform": platform_arch,
            # OS version
            "_os": os_ver,
            # Hostname of the local machine
            "_source_host": socket.gethostname(),
            # Client's name
            "_client_name": "mysql-connector-python",
            # Client's version
            "_client_version": ".".join([str(x) for x in VERSION[0:3]]),
            # Client's License identifier
            "_client_license": client_license,
        }
        self._settings["attributes"].update(default_attributes)

        if "connection-attributes" in self._settings:
            for attr_name in self._settings["connection-attributes"]:
                attr_value = self._settings["connection-attributes"][attr_name]
                # Validate name type
                if not isinstance(attr_name, str):
                    raise InterfaceError(
                        f"Attribute name '{attr_name}' must be a string type"
                    )
                # Validate attribute name limit 32 characters
                if len(attr_name) > 32:
                    raise InterfaceError(
                        f"Attribute name '{attr_name}' exceeds 32 characters "
                        "limit size"
                    )
                # Validate names in connection-attributes cannot start with "_"
                if attr_name.startswith("_"):
                    raise InterfaceError(
                        "Key names in 'session-connect-attributes' cannot "
                        f"start with '_', found: {attr_name}"
                    )
                # Validate value type
                if not isinstance(attr_value, str):
                    raise InterfaceError(
                        f"Attribute name '{attr_name}' value '{attr_value}' "
                        " must be a string type"
                    )

                # Validate attribute value limit 1024 characters
                if len(attr_value) > 1024:
                    raise InterfaceError(
                        f"Attribute name '{attr_name}' value: '{attr_value}' "
                        "exceeds 1024 characters limit size"
                    )

                self._settings["attributes"][attr_name] = attr_value

    @property
    def use_pure(self) -> bool:
        """bool: `True` to use pure Python Protobuf implementation."""
        return Protobuf.use_pure

    @use_pure.setter
    def use_pure(self, value: bool) -> None:
        if not isinstance(value, bool):
            raise ProgrammingError("'use_pure' option should be True or False")
        Protobuf.set_use_pure(value)

    def is_open(self) -> bool:
        """Returns `True` if the session is open.

        Returns:
            bool: Returns `True` if the session is open.
        """
        return self._connection.stream.is_open()

    def sql(self, sql: str) -> SqlStatement:
        """Creates a :class:`mysqlx.SqlStatement` object to allow running the
        SQL statement on the target MySQL Server.

        Args:
            sql (string): The SQL statement to be executed.

        Returns:
            mysqlx.SqlStatement: SqlStatement object.
        """
        return SqlStatement(self._connection, sql)

    def get_connection(self) -> Connection:
        """Returns the underlying connection.

        Returns:
            mysqlx.connection.Connection: The connection object.
        """
        return self._connection

    def get_schemas(self) -> List[str]:
        """Returns the list of schemas in the current session.

        Returns:
            `list`: The list of schemas in the current session.

        .. versionadded:: 8.0.12
        """
        result = self.sql("SHOW DATABASES").execute()
        return [row[0] for row in result.fetch_all()]

    def get_schema(self, name: str) -> Schema:
        """Retrieves a Schema object from the current session by it's name.

        Args:
            name (string): The name of the Schema object to be retrieved.

        Returns:
            mysqlx.Schema: The Schema object with the given name.
        """
        return Schema(self, name)

    def get_default_schema(self) -> Optional[Schema]:
        """Retrieves a Schema object from the current session by the schema
        name configured in the connection settings.

        Returns:
            mysqlx.Schema: The Schema object with the given name at connect
                           time.
            None: In case the default schema was not provided with the
                  initialization data.

        Raises:
            :class:`mysqlx.ProgrammingError`: If the provided default schema
                                              does not exists.
        """
        schema = self._connection.settings.get("schema")
        if schema:
            res = (
                self.sql(_SELECT_SCHEMA_NAME_QUERY.format(escape(schema)))
                .execute()
                .fetch_all()
            )
            try:
                if res[0][0] == schema:
                    return Schema(self, schema)
            except IndexError:
                raise ProgrammingError(
                    f"Default schema '{schema}' does not exists"
                ) from None
        return None

    def drop_schema(self, name: str) -> None:
        """Drops the schema with the specified name.

        Args:
            name (string): The name of the Schema object to be retrieved.
        """
        self._connection.execute_nonquery(
            "sql", _DROP_DATABASE_QUERY.format(quote_identifier(name)), True
        )

    def create_schema(self, name: str) -> Schema:
        """Creates a schema on the database and returns the corresponding
        object.

        Args:
            name (string): A string value indicating the schema name.
        """
        self._connection.execute_nonquery(
            "sql", _CREATE_DATABASE_QUERY.format(quote_identifier(name)), True
        )
        return Schema(self, name)

    def start_transaction(self) -> None:
        """Starts a transaction context on the server."""
        self._connection.execute_nonquery("sql", "START TRANSACTION", True)

    def commit(self) -> None:
        """Commits all the operations executed after a call to
        startTransaction().
        """
        self._connection.execute_nonquery("sql", "COMMIT", True)

    def rollback(self) -> None:
        """Discards all the operations executed after a call to
        startTransaction().
        """
        self._connection.execute_nonquery("sql", "ROLLBACK", True)

    def set_savepoint(self, name: Optional[str] = None) -> str:
        """Creates a transaction savepoint.

        If a name is not provided, one will be generated using the uuid.uuid1()
        function.

        Args:
            name (Optional[string]): The savepoint name.

        Returns:
            string: The savepoint name.
        """
        if name is None:
            name = f"{uuid.uuid1()}"
        elif not isinstance(name, str) or len(name.strip()) == 0:
            raise ProgrammingError("Invalid SAVEPOINT name")
        self._connection.execute_nonquery(
            "sql", f"SAVEPOINT {quote_identifier(name)}", True
        )
        return name

    def rollback_to(self, name: str) -> None:
        """Rollback to a transaction savepoint with the given name.

        Args:
            name (string): The savepoint name.
        """
        if not isinstance(name, str) or len(name.strip()) == 0:
            raise ProgrammingError("Invalid SAVEPOINT name")
        self._connection.execute_nonquery(
            "sql",
            f"ROLLBACK TO SAVEPOINT {quote_identifier(name)}",
            True,
        )

    def release_savepoint(self, name: str) -> None:
        """Release a transaction savepoint with the given name.

        Args:
            name (string): The savepoint name.
        """
        if not isinstance(name, str) or len(name.strip()) == 0:
            raise ProgrammingError("Invalid SAVEPOINT name")
        self._connection.execute_nonquery(
            "sql",
            f"RELEASE SAVEPOINT {quote_identifier(name)}",
            True,
        )

    def close(self) -> None:
        """Closes the session."""
        self._connection.close_session()
        # Set an unconnected connection
        self._connection = Connection(self._settings)

    def close_connections(self) -> None:
        """Closes all underliying connections as pooled connections"""
        self._connection.close_connection()


class Client:
    """Class defining a client, it stores a connection configuration.

    Args:
        connection_dict (dict): The connection information to connect to a
                                MySQL server.
        options_dict (dict): The options to configure this client.

    .. versionadded:: 8.0.13
    """

    def __init__(
        self,
        connection_dict: Dict[str, Any],
        options_dict: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.settings: Dict[str, Any] = connection_dict
        if options_dict is None:
            options_dict = {}

        self.sessions: List[Session] = []
        self.client_id: uuid.UUID = uuid.uuid4()

        self._set_pool_size(options_dict.get("max_size", 25))
        self._set_max_idle_time(options_dict.get("max_idle_time", 0))
        self._set_queue_timeout(options_dict.get("queue_timeout", 0))
        self._set_pool_enabled(options_dict.get("enabled", True))

        self.settings["pooling"] = self.pooling_enabled
        self.settings["max_size"] = self.max_size
        self.settings["client_id"] = self.client_id

    def __enter__(self) -> Client:
        return self

    def __exit__(
        self,
        exc_type: Type[BaseException],
        exc_value: BaseException,
        traceback: TracebackType,
    ) -> None:
        self.close()

    def _set_pool_size(self, pool_size: int) -> None:
        """Set the size of the pool.

        This method sets the size of the pool but it will not resize the pool.

        Args:
            pool_size (int): An integer equal or greater than 0 indicating
                             the pool size.

        Raises:
            :class:`AttributeError`: If the pool_size value is not an integer
                                     greater or equal to 0.
        """
        if (
            isinstance(pool_size, bool)
            or not isinstance(pool_size, int)
            or not pool_size > 0
        ):
            raise AttributeError(
                "Pool max_size value must be an integer greater than 0, the "
                f"given value {pool_size} is not valid"
            )

        self.max_size = _CNX_POOL_MAXSIZE if pool_size == 0 else pool_size

    def _set_max_idle_time(self, max_idle_time: int) -> None:
        """Set the max idle time.

        This method sets the max idle time.

        Args:
            max_idle_time (int): An integer equal or greater than 0 indicating
                                 the max idle time.

        Raises:
            :class:`AttributeError`: If the max_idle_time value is not an
                                     integer greater or equal to 0.
        """
        if (
            isinstance(max_idle_time, bool)
            or not isinstance(max_idle_time, int)
            or not max_idle_time > -1
        ):
            raise AttributeError(
                "Connection max_idle_time value must be an integer greater or "
                f"equal to 0, the given value {max_idle_time} is not valid"
            )

        self.max_idle_time = max_idle_time
        self.settings["max_idle_time"] = (
            _CNX_POOL_MAX_IDLE_TIME if max_idle_time == 0 else int(max_idle_time / 1000)
        )

    def _set_pool_enabled(self, enabled: bool) -> None:
        """Set if the pool is enabled.

        This method sets if the pool is enabled.

        Args:
            enabled (bool): True if to enabling the pool.

        Raises:
            :class:`AttributeError`: If the value of enabled is not a bool type.
        """
        if not isinstance(enabled, bool):
            raise AttributeError("The enabled value should be True or False.")
        self.pooling_enabled = enabled

    def _set_queue_timeout(self, queue_timeout: int) -> None:
        """Set the queue timeout.

        This method sets the queue timeout.

        Args:
            queue_timeout (int): An integer equal or greater than 0 indicating
                                 the queue timeout.

        Raises:
            :class:`AttributeError`: If the queue_timeout value is not an
                                     integer greater or equal to 0.
        """
        if (
            isinstance(queue_timeout, bool)
            or not isinstance(queue_timeout, int)
            or not queue_timeout > -1
        ):
            raise AttributeError(
                "Connection queue_timeout value must be an integer greater or "
                f"equal to 0, the given value {queue_timeout} is not valid"
            )

        self.queue_timeout = queue_timeout
        self.settings["queue_timeout"] = (
            _CNX_POOL_QUEUE_TIMEOUT if queue_timeout == 0 else int(queue_timeout / 1000)
        )
        # To avoid a connection stall waiting for the server, if the
        # connect-timeout is not given, use the queue_timeout
        if "connect-timeout" not in self.settings:
            self.settings["connect-timeout"] = self.queue_timeout

    def get_session(self) -> Session:
        """Creates a Session instance using the provided connection data.

        Returns:
            Session: Session object.
        """
        session = Session(self.settings)
        self.sessions.append(session)
        return session

    def close(self) -> None:
        """Closes the sessions opened by this client."""
        PoolsManager().close_pool(self.settings)
        for session in self.sessions:
            session.close_connections()


def _parse_address_list(path: str) -> Union[Dict[str, List[Dict]], Dict]:
    """Parses a list of host, port pairs.

    Args:
        path: String containing a list of routers or just router

    Returns:
        Returns a dict with parsed values of host, port and priority if
        specified.
    """
    path = path.replace(" ", "")
    array = (
        not ("," not in path and path.count(":") > 1 and path.count("[") == 1)
        and path.startswith("[")
        and path.endswith("]")
    )

    routers = []
    address_list = _SPLIT_RE.split(path[1:-1] if array else path)
    priority_count = 0
    for address in address_list:
        router: Dict = {}

        match = _PRIORITY_RE.match(address)
        if match:
            address = match.group(1)
            router["priority"] = int(match.group(2))
            priority_count += 1
        else:
            match = _ROUTER_RE.match(address)
            if match:
                address = match.group(1)
                router["priority"] = 100

        match = urlparse(f"//{address}")
        if not match.hostname:
            raise InterfaceError(f"Invalid address: {address}")

        try:
            router.update(host=match.hostname, port=match.port)
        except ValueError as err:
            raise ProgrammingError(f"Invalid URI: {err}", 4002) from err

        routers.append(router)

    if 0 < priority_count < len(address_list):
        raise ProgrammingError(
            "You must either assign no priority to any of the routers or give "
            "a priority for every router",
            4000,
        )

    return {"routers": routers} if array else routers[0]


def _parse_connection_uri(uri: str) -> Dict[str, Any]:
    """Parses the connection string and returns a dictionary with the
    connection settings.

    Args:
        uri: mysqlx URI scheme to connect to a MySQL server/farm.

    Returns:
        Returns a dict with parsed values of credentials and address of the
        MySQL server/farm.

    Raises:
        :class:`mysqlx.InterfaceError`: If contains a invalid option.
    """
    settings: Dict[str, Any] = {"schema": ""}

    match = _URI_SCHEME_RE.match(uri)
    scheme, uri = match.groups() if match else ("mysqlx", uri)

    if scheme not in ("mysqlx", "mysqlx+srv"):
        raise InterfaceError(f"Scheme '{scheme}' is not valid")

    if scheme == "mysqlx+srv":
        settings["dns-srv"] = True

    userinfo, tmp = uri.partition("@")[::2]
    host, query_str = tmp.partition("?")[::2]

    pos = host.rfind("/")
    if host[pos:].find(")") == -1 and pos > 0:
        host, settings["schema"] = host.rsplit("/", 1)
    host = host.strip("()")

    if not host or not userinfo or ":" not in userinfo:
        raise InterfaceError(f"Malformed URI '{uri}'")
    user, password = userinfo.split(":", 1)
    settings["user"], settings["password"] = unquote(user), unquote(password)

    if host.startswith(("/", "..", ".")):
        settings["socket"] = unquote(host)
    elif host.startswith("\\."):
        raise InterfaceError("Windows Pipe is not supported")
    else:
        settings.update(_parse_address_list(host))

    invalid_options = ("user", "password", "dns-srv")
    for key, val in parse_qsl(query_str, True):
        opt = key.replace("_", "-").lower()
        if opt in invalid_options:
            raise InterfaceError(f"Invalid option: '{key}'")
        if opt in _SSL_OPTS:
            settings[opt] = unquote(val.strip("()"))
        else:
            val_str = val.lower()
            if val_str in ("1", "true"):
                settings[opt] = True
            elif val_str in ("0", "false"):
                settings[opt] = False
            else:
                settings[opt] = val_str
    return settings


def _validate_settings(settings: Dict[str, Any]) -> None:
    """Validates the settings to be passed to a Session object
    the port values are converted to int if specified or set to 33060
    otherwise. The priority values for each router is converted to int
    if specified.

    Args:
        settings: dict containing connection settings.

    Raises:
        :class:`mysqlx.InterfaceError`: On any configuration issue.
    """
    invalid_opts = set(settings.keys()).difference(_SESS_OPTS)
    if invalid_opts:
        invalid_opts_list = "', '".join(invalid_opts)
        raise InterfaceError(f"Invalid option(s): '{invalid_opts_list}'")

    if "routers" in settings:
        for router in settings["routers"]:
            _validate_hosts(router, 33060)
    elif "host" in settings:
        _validate_hosts(settings)

    if "ssl-mode" in settings:
        ssl_mode = settings["ssl-mode"]
        try:
            settings["ssl-mode"] = SSLMode(
                ssl_mode.lower().strip() if isinstance(ssl_mode, str) else ssl_mode
            )
        except (AttributeError, ValueError) as err:
            raise InterfaceError(f"Invalid SSL Mode '{settings['ssl-mode']}'") from err
        if "ssl-ca" not in settings and settings["ssl-mode"] in [
            SSLMode.VERIFY_IDENTITY,
            SSLMode.VERIFY_CA,
        ]:
            raise InterfaceError("Cannot verify Server without CA")

    if "ssl-crl" in settings and "ssl-ca" not in settings:
        raise InterfaceError("CA Certificate not provided")

    if "ssl-key" in settings and "ssl-cert" not in settings:
        raise InterfaceError("Client Certificate not provided")

    if "ssl-ca" in settings and settings.get("ssl-mode") not in [
        SSLMode.VERIFY_IDENTITY,
        SSLMode.VERIFY_CA,
        SSLMode.DISABLED,
    ]:
        raise InterfaceError("Must verify Server if CA is provided")

    if "auth" in settings:
        auth = settings["auth"]
        try:
            settings["auth"] = Auth(
                auth.lower().strip() if isinstance(auth, str) else auth
            )
        except (AttributeError, ValueError) as err:
            raise InterfaceError(f"Invalid Auth '{settings['auth']}'") from err

    if "compression" in settings:
        compression = settings["compression"]
        try:
            settings["compression"] = Compression(
                compression.lower().strip()
                if isinstance(compression, str)
                else compression
            )
        except (AttributeError, ValueError) as err:
            raise InterfaceError(
                "The connection property 'compression' acceptable values are: "
                "'preferred', 'required', or 'disabled'. The value "
                f"'{settings['compression']}' is not acceptable"
            ) from err

    if "compression-algorithms" in settings:
        if isinstance(settings["compression-algorithms"], str):
            compression_algorithms = (
                settings["compression-algorithms"].strip().strip("[]")
            )
            if compression_algorithms:
                settings["compression-algorithms"] = compression_algorithms.split(",")
            else:
                settings["compression-algorithms"] = None
        elif not isinstance(settings["compression-algorithms"], (list, tuple)):
            raise InterfaceError(
                "Invalid type of the connection property 'compression-algorithms'"
            )
        if settings.get("compression") == Compression.DISABLED:
            settings["compression-algorithms"] = None

    if "connection-attributes" in settings:
        _validate_connection_attributes(settings)

    if "connect-timeout" in settings:
        try:
            if isinstance(settings["connect-timeout"], str):
                settings["connect-timeout"] = int(settings["connect-timeout"])
            if (
                not isinstance(settings["connect-timeout"], int)
                or settings["connect-timeout"] < 0
            ):
                raise ValueError
        except ValueError:
            raise TypeError(
                "The connection timeout value must be a positive "
                "integer (including 0)"
            ) from None

    if "dns-srv" in settings:
        if not isinstance(settings["dns-srv"], bool):
            raise InterfaceError("The value of 'dns-srv' must be a boolean")
        if settings.get("socket"):
            raise InterfaceError(
                "Using Unix domain sockets with DNS SRV lookup is not allowed"
            )
        if settings.get("port"):
            raise InterfaceError(
                "Specifying a port number with DNS SRV lookup is not allowed"
            )
        if settings.get("routers"):
            raise InterfaceError(
                "Specifying multiple hostnames with DNS SRV look up is not allowed"
            )
    elif "host" in settings and not settings.get("port"):
        settings["port"] = 33060

    if "tls-versions" in settings:
        _validate_tls_versions(settings)

    if "tls-ciphersuites" in settings:
        _validate_tls_ciphersuites(settings)


def _validate_hosts(
    settings: Dict[str, Any], default_port: Optional[int] = None
) -> None:
    """Validate hosts.

    Args:
        settings (dict): Settings dictionary.
        default_port (int): Default connection port.

    Raises:
        :class:`mysqlx.InterfaceError`: If priority or port are invalid.
    """
    if "priority" in settings and settings["priority"]:
        try:
            settings["priority"] = int(settings["priority"])
            if settings["priority"] < 0 or settings["priority"] > 100:
                raise ProgrammingError(
                    "Invalid priority value, must be between 0 and 100",
                    4007,
                )
        except NameError:
            raise ProgrammingError("Invalid priority", 4007) from None
        except ValueError:
            raise ProgrammingError(
                f"Invalid priority: {settings['priority']}", 4007
            ) from None

    if "port" in settings and settings["port"]:
        try:
            settings["port"] = int(settings["port"])
        except NameError:
            raise InterfaceError("Invalid port") from None
    elif "host" in settings and default_port:
        settings["port"] = default_port


def _validate_connection_attributes(settings: Dict[str, Any]) -> None:
    """Validate connection-attributes.

    Args:
        settings (dict): Settings dictionary.

    Raises:
        :class:`mysqlx.InterfaceError`: If attribute name or value exceeds size.
    """
    attributes = {}
    if "connection-attributes" not in settings:
        return

    conn_attrs = settings["connection-attributes"]

    if isinstance(conn_attrs, str):
        if conn_attrs == "":
            settings["connection-attributes"] = {}
            return
        if not (
            conn_attrs.startswith("[") and conn_attrs.endswith("]")
        ) and conn_attrs not in ["False", "false", "True", "true"]:
            raise InterfaceError(
                "The value of 'connection-attributes' must be a boolean or a "
                f"list of key-value pairs, found: '{conn_attrs}'"
            )
        if conn_attrs in ["False", "false", "True", "true"]:
            if conn_attrs in ["False", "false"]:
                settings["connection-attributes"] = False
            else:
                settings["connection-attributes"] = {}
            return
        conn_attributes = conn_attrs[1:-1].split(",")
        for attr in conn_attributes:
            if attr == "":
                continue
            attr_name_val = attr.split("=")
            attr_name = attr_name_val[0]
            attr_val = attr_name_val[1] if len(attr_name_val) > 1 else ""
            if attr_name in attributes:
                raise InterfaceError(
                    f"Duplicate key '{attr_name}' used in connection-attributes"
                )
            attributes[attr_name] = attr_val
    elif isinstance(conn_attrs, dict):
        for attr_name in conn_attrs:
            attr_value = conn_attrs[attr_name]
            if not isinstance(attr_value, str):
                attr_value = repr(attr_value)
            attributes[attr_name] = attr_value
    elif isinstance(conn_attrs, bool) or conn_attrs in [0, 1]:
        if conn_attrs:
            settings["connection-attributes"] = {}
        else:
            settings["connection-attributes"] = False
        return
    elif isinstance(conn_attrs, set):
        for attr_name in conn_attrs:
            attributes[attr_name] = ""
    elif isinstance(conn_attrs, list):
        for attr in conn_attrs:
            if attr == "":
                continue
            attr_name_val = attr.split("=")
            attr_name = attr_name_val[0]
            attr_val = attr_name_val[1] if len(attr_name_val) > 1 else ""
            if attr_name in attributes:
                raise InterfaceError(
                    f"Duplicate key '{attr_name}' used in connection-attributes"
                )
            attributes[attr_name] = attr_val
    elif not isinstance(conn_attrs, bool):
        raise InterfaceError(
            "connection-attributes must be Boolean or a list of key-value "
            f"pairs, found: '{conn_attrs}'"
        )

    if attributes:
        for attr_name, attr_value in attributes.items():
            # Validate name type
            if not isinstance(attr_name, str):
                raise InterfaceError(
                    f"Attribute name '{attr_name}' must be a string type"
                )
            # Validate attribute name limit 32 characters
            if len(attr_name) > 32:
                raise InterfaceError(
                    f"Attribute name '{attr_name}' exceeds 32 characters limit size"
                )
            # Validate names in connection-attributes cannot start with "_"
            if attr_name.startswith("_"):
                raise InterfaceError(
                    "Key names in connection-attributes cannot start with "
                    f"'_', found: '{attr_name}'"
                )

            # Validate value type
            if not isinstance(attr_value, str):
                raise InterfaceError(
                    f"Attribute '{attr_name}' value: '{attr_value}' must be "
                    "a string type"
                )
            # Validate attribute value limit 1024 characters
            if len(attr_value) > 1024:
                raise InterfaceError(
                    f"Attribute '{attr_name}' value: '{attr_value}' exceeds "
                    "1024 characters limit size"
                )

    settings["connection-attributes"] = attributes


def _validate_tls_versions(settings: Dict[str, Any]) -> None:
    """Validate tls-versions.

    Args:
        settings (dict): Settings dictionary.

    Raises:
        :class:`mysqlx.InterfaceError`: If tls-versions name is not valid.
    """
    tls_versions = []
    if "tls-versions" not in settings:
        return

    tls_versions_settings = settings["tls-versions"]

    if isinstance(tls_versions_settings, str):
        if not (
            tls_versions_settings.startswith("[")
            and tls_versions_settings.endswith("]")
        ):
            raise InterfaceError(
                f"tls-versions must be a list, found: '{tls_versions_settings}'"
            )
        tls_vers = tls_versions_settings[1:-1].split(",")
        for tls_ver in tls_vers:
            tls_version = tls_ver.strip()
            if tls_version == "":
                continue
            if tls_version in tls_versions:
                raise InterfaceError(
                    DUPLICATED_IN_LIST_ERROR.format(
                        list="tls_versions", value=tls_version
                    )
                )
            tls_versions.append(tls_version)
    elif isinstance(tls_versions_settings, list):
        if not tls_versions_settings:
            raise InterfaceError(
                "At least one TLS protocol version must be "
                "specified in 'tls-versions' list."
            )
        for tls_ver in tls_versions_settings:
            if tls_ver in tls_versions:
                raise InterfaceError(
                    DUPLICATED_IN_LIST_ERROR.format(list="tls_versions", value=tls_ver)
                )
            tls_versions.append(tls_ver)

    elif isinstance(tls_versions_settings, set):
        for tls_ver in tls_versions_settings:
            tls_versions.append(tls_ver)
    else:
        raise InterfaceError(
            "tls-versions should be a list with one or more of versions in "
            f"{', '.join(SUPPORTED_TLS_VERSIONS)}. found: '{tls_versions}'"
        )

    if not tls_versions:
        raise InterfaceError(
            "At least one TLS protocol version must be specified in "
            "'tls-versions' list."
        )

    use_tls_versions = []
    unacceptable_tls_versions = []
    not_tls_versions = []
    for tls_ver in tls_versions:
        if tls_ver in SUPPORTED_TLS_VERSIONS:
            use_tls_versions.append(tls_ver)
        if tls_ver in UNACCEPTABLE_TLS_VERSIONS:
            unacceptable_tls_versions.append(tls_ver)
        else:
            not_tls_versions.append(tls_ver)

    if use_tls_versions:
        if use_tls_versions == ["TLSv1.3"] and not TLS_V1_3_SUPPORTED:
            raise NotSupportedError(
                TLS_VER_NO_SUPPORTED.format(tls_versions, SUPPORTED_TLS_VERSIONS)
            )
        settings["tls-versions"] = use_tls_versions
    elif unacceptable_tls_versions:
        raise NotSupportedError(
            TLS_VERSION_UNACCEPTABLE_ERROR.format(
                unacceptable_tls_versions, SUPPORTED_TLS_VERSIONS
            )
        )
    elif not_tls_versions:
        raise InterfaceError(TLS_VERSION_ERROR.format(tls_ver, SUPPORTED_TLS_VERSIONS))


def _validate_tls_ciphersuites(settings: Dict[str, Any]) -> None:
    """Validate tls-ciphersuites.

    Args:
        settings (dict): Settings dictionary.

    Raises:
        :class:`mysqlx.InterfaceError`: If tls-ciphersuites name is not valid.
    """
    tls_ciphersuites = []
    if "tls-ciphersuites" not in settings:
        return

    tls_ciphersuites_settings = settings["tls-ciphersuites"]

    if isinstance(tls_ciphersuites_settings, str):
        if not (
            tls_ciphersuites_settings.startswith("[")
            and tls_ciphersuites_settings.endswith("]")
        ):
            raise InterfaceError(
                "tls-ciphersuites must be a list, found: "
                f"'{tls_ciphersuites_settings}'"
            )
        tls_css = tls_ciphersuites_settings[1:-1].split(",")
        if not tls_css:
            raise InterfaceError(
                "No valid cipher suite found in the 'tls-ciphersuites' list"
            )
        for tls_cs in tls_css:
            tls_cs = tls_cs.strip().upper()
            if tls_cs:
                tls_ciphersuites.append(tls_cs)
    elif isinstance(tls_ciphersuites_settings, (list, set)):
        tls_ciphersuites = [tls_cs for tls_cs in tls_ciphersuites_settings if tls_cs]
    else:
        raise InterfaceError(
            "tls-ciphersuites should be a list with one or more ciphersuites. "
            f"Found: '{tls_ciphersuites_settings}'"
        )

    tls_versions = (
        SUPPORTED_TLS_VERSIONS[:]
        if settings.get("tls-versions", None) is None
        else settings["tls-versions"][:]
    )

    # A newer TLS version can use a cipher introduced on
    # an older version.
    tls_versions.sort(reverse=True)
    newer_tls_ver = tls_versions[0]

    translated_names = []
    iani_cipher_suites_names = {}
    ossl_cipher_suites_names: List[str] = []

    # Old ciphers can work with new TLS versions.
    # Find all the ciphers introduced on previous TLS versions
    for tls_ver in SUPPORTED_TLS_VERSIONS[
        : SUPPORTED_TLS_VERSIONS.index(newer_tls_ver) + 1
    ]:
        iani_cipher_suites_names.update(TLS_CIPHER_SUITES[tls_ver])
        ossl_cipher_suites_names.extend(OPENSSL_CS_NAMES[tls_ver])

    for name in tls_ciphersuites:
        if "-" in name and name in ossl_cipher_suites_names:
            translated_names.append(name)
        elif name in iani_cipher_suites_names:
            translated_name = iani_cipher_suites_names[name]
            if translated_name in translated_names:
                raise AttributeError(
                    DUPLICATED_IN_LIST_ERROR.format(
                        list="tls_ciphersuites", value=translated_name
                    )
                )
            translated_names.append(translated_name)
        else:
            raise InterfaceError(
                f"The value '{name}' in cipher suites is not a valid cipher suite"
            )

    if not translated_names:
        raise InterfaceError(
            "No valid cipher suite found in the 'tls-ciphersuites' list"
        )

    # raise an error when using an unacceptable cipher
    for cipher_as_ossl in translated_names:
        for tls_ver in SUPPORTED_TLS_VERSIONS[
            : SUPPORTED_TLS_VERSIONS.index(newer_tls_ver) + 1
        ]:
            if (
                cipher_as_ossl
                in UNACCEPTABLE_TLS_CIPHERSUITES.get(tls_ver, {}).values()
            ):
                raise NotSupportedError(
                    f"Cipher {cipher_as_ossl} when used with {tls_ver} is unacceptable."
                )

    settings["tls-ciphersuites"] = translated_names


def _get_connection_settings(*args: Any, **kwargs: Any) -> Dict[str, Any]:
    """Parses the connection string and returns a dictionary with the
    connection settings.

    Args:
        *args: Variable length argument list with the connection data used
               to connect to the database. It can be a dictionary or a
               connection string.
        **kwargs: Arbitrary keyword arguments with connection data used to
                  connect to the database.

    Returns:
        mysqlx.Session: Session object.

    Raises:
        TypeError: If connection timeout is not a positive integer.
        :class:`mysqlx.InterfaceError`: If settings not provided.
    """
    settings = {}
    if args:
        if isinstance(args[0], str):
            settings = _parse_connection_uri(args[0])
        elif isinstance(args[0], dict):
            for key, val in args[0].items():
                settings[key.replace("_", "-")] = val
    elif kwargs:
        for key, val in kwargs.items():
            settings[key.replace("_", "-")] = val

    if not settings:
        raise InterfaceError("Settings not provided")

    _validate_settings(settings)
    return settings


def get_session(*args: Any, **kwargs: Any) -> Session:
    """Creates a Session instance using the provided connection data.

    Args:
        *args: Variable length argument list with the connection data used
               to connect to a MySQL server. It can be a dictionary or a
               connection string.
        **kwargs: Arbitrary keyword arguments with connection data used to
                  connect to the database.

    Returns:
        mysqlx.Session: Session object.
    """
    settings = _get_connection_settings(*args, **kwargs)
    return Session(settings)


def get_client(
    connection_string: Union[str, Dict[str, Any]],
    options_string: Union[str, Dict[str, Any]],
) -> Client:
    """Creates a Client instance with the provided connection data and settings.

    Args:
        connection_string: A string or a dict type object to indicate the \
            connection data used to connect to a MySQL server.

            The string must have the following uri format::

                cnx_str = 'mysqlx://{user}:{pwd}@{host}:{port}'
                cnx_str = ('mysqlx://{user}:{pwd}@['
                           '    (address={host}:{port}, priority=n),'
                           '    (address={host}:{port}, priority=n), ...]'
                           '       ?[option=value]')

            And the dictionary::

                cnx_dict = {
                    'host': 'The host where the MySQL product is running',
                    'port': '(int) the port number configured for X protocol',
                    'user': 'The user name account',
                    'password': 'The password for the given user account',
                    'ssl-mode': 'The flags for ssl mode in mysqlx.SSLMode.FLAG',
                    'ssl-ca': 'The path to the ca.cert'
                    "connect-timeout": '(int) milliseconds to wait on timeout'
                }

        options_string: A string in the form of a document or a dictionary \
            type with configuration for the client.

            Current options include::

                options = {
                    'pooling': {
                        'enabled': (bool), # [True | False], True by default
                        'max_size': (int), # Maximum connections per pool
                        "max_idle_time": (int), # milliseconds that a
                            # connection will remain active while not in use.
                            # By default 0, means infinite.
                        "queue_timeout": (int), # milliseconds a request will
                            # wait for a connection to become available.
                            # By default 0, means infinite.
                    }
                }

    Returns:
        mysqlx.Client: Client object.

    .. versionadded:: 8.0.13
    """
    if not isinstance(connection_string, (str, dict)):
        raise InterfaceError("connection_data must be a string or dict")

    settings_dict = _get_connection_settings(connection_string)

    if not isinstance(options_string, (str, dict)):
        raise InterfaceError("connection_options must be a string or dict")

    if isinstance(options_string, str):
        try:
            options_dict = json.loads(options_string)
        except JSONDecodeError as err:
            raise InterfaceError(
                "'pooling' options must be given in the form of a document or dict"
            ) from err
    else:
        options_dict = {}
        for key, value in options_string.items():
            options_dict[key.replace("-", "_")] = value

    if not isinstance(options_dict, dict):
        raise InterfaceError(
            "'pooling' options must be given in the form of a document or dict"
        )
    pooling_options_dict = {}
    if "pooling" in options_dict:
        pooling_options = options_dict.pop("pooling")
        if not isinstance(pooling_options, (dict)):
            raise InterfaceError(
                "'pooling' options must be given in the form document or dict"
            )
        # Fill default pooling settings
        pooling_options_dict["enabled"] = pooling_options.pop("enabled", True)
        pooling_options_dict["max_size"] = pooling_options.pop("max_size", 25)
        pooling_options_dict["max_idle_time"] = pooling_options.pop("max_idle_time", 0)
        pooling_options_dict["queue_timeout"] = pooling_options.pop("queue_timeout", 0)

        # No other options besides pooling are supported
        if len(pooling_options) > 0:
            raise InterfaceError(f"Unrecognized pooling options: {pooling_options}")
        # No other options besides pooling are supported
        if len(options_dict) > 0:
            raise InterfaceError(
                f"Unrecognized connection options: {options_dict.keys()}"
            )

    return Client(settings_dict, pooling_options_dict)
