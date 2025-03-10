MySQL Connector/Python
======================

.. image:: https://img.shields.io/pypi/v/mysql-connector-python.svg
   :target: https://pypi.org/project/mysql-connector-python/
.. image:: https://img.shields.io/pypi/pyversions/mysql-connector-python.svg
   :target: https://pypi.org/project/mysql-connector-python/
.. image:: https://img.shields.io/pypi/l/mysql-connector-python.svg
   :target: https://pypi.org/project/mysql-connector-python/

.. === <mysql> ====
MySQL Connector/Python enables Python programs to access MySQL databases, using
an API that is compliant with the `Python Database API Specification v2.0
(PEP 249) <https://www.python.org/dev/peps/pep-0249/>`_ - We refer to it as the
`Classic API <https://dev.mysql.com/doc/connector-python/en/connector-python-reference.html>`_.

.. === </mysql> ====

.. === <mysqlx> [repl("It also", "MySQL Connector/Python")] ===
It also contains an implementation of the `XDevAPI <https://dev.mysql.com/doc/x-devapi-userguide/en>`_
- An Application Programming Interface for working with the `MySQL Document Store
<https://dev.mysql.com/doc/refman/en/document-store.html>`_.

.. === </mysqlx> ===

.. === <mysql> [repl("* `XDevAPI <https://dev.mysql.com/doc/x-devapi-userguide/en>`_", "")] ====
Features
--------

* `Asynchronous Connectivity <https://dev.mysql.com/doc/connector-python/en/connector-python-asyncio.html>`_
* `C-extension <https://dev.mysql.com/doc/connector-python/en/connector-python-cext.html>`_
* `Telemetry <https://dev.mysql.com/doc/connector-python/en/connector-python-opentelemetry.html>`_
* `XDevAPI <https://dev.mysql.com/doc/x-devapi-userguide/en>`_

.. === </mysql> ====


Installation
------------

Connector/Python contains the classic and XDevAPI connector APIs, which are
installed separately. Any of these can be installed from a binary
or source distribution.

Binaries are distributed in the following package formats:

* `RPM <https://docs.redhat.com/en/documentation/red_hat_enterprise_linux/8/html/packaging_and_distributing_software/introduction-to-rpm_packaging-and-distributing-software>`_
* `WHEEL <https://packaging.python.org/en/latest/discussions/package-formats/#what-is-a-wheel>`_

On the other hand, the source code is distributed as a compressed file
from which a wheel package can be built.

The recommended way to install Connector/Python is via `pip <https://pip.pypa.io/>`_,
which relies on WHEEL packages. For such a reason, it is the installation procedure
that is going to be described moving forward.

Please, refer to the official MySQL documentation `Connector/Python Installation
<https://dev.mysql.com/doc/connector-python/en/connector-python-installation.html>`_ to
know more about installing from an RPM, or building and installing a WHEEL package from
a source distribution.

Before installing a package with `pip <https://pip.pypa.io/>`_, it is strongly suggested
to have the most recent ``pip`` version installed on your system.
If your system already has ``pip`` installed, you might need to update it. Or you can use
the `standalone pip installer <https://pip.pypa.io/en/latest/installation/>`_.

.. === <mysql> [repl("The *classic API* can be installed via pip as follows:", "")] ===
The *classic API* can be installed via pip as follows:

.. code-block:: bash

    $ pip install mysql-connector-python

.. === </mysql> ====

.. === <mysqlx> [repl("similarly, the *XDevAPI* can be installed with:", "")] ===
similarly, the *XDevAPI* can be installed with:

.. code-block:: bash

    $ pip install mysqlx-connector-python

Please refer to the `installation tutorial <https://dev.mysql.com/doc/dev/connector-python/installation.html>`_
for installation alternatives of the XDevAPI.

.. === </mysqlx> ===


++++++++++++++++++++
Installation Options
++++++++++++++++++++

Connector packages included in MySQL Connector/Python allow you to install
optional dependencies to unleash certain functionalities.

.. === <mysql> ===
.. code-block:: bash

    # 3rd party packages to unleash the telemetry functionality are installed
    $ pip install mysql-connector-python[telemetry]

.. === </mysql> ===

.. === <mysqlx> [repl("similarly, for the XDevAPI:", "")] ===
similarly, for the XDevAPI:

.. code-block:: bash

    # 3rd party packages to unleash the compression functionality are installed
    $ pip install mysqlx-connector-python[compression]

.. === </mysqlx> ===

This installation option can be seen as a shortcut to install all the
dependencies needed by a particular feature. Mind that this is optional
and you are free to install the required dependencies by yourself.

.. === <mysql> [repl("Options for the Classic connector:", "Available options:")] ===
Options for the Classic connector:

* dns-srv
* gssapi
* fido2
* telemetry

.. === </mysql> ===

.. === <mysqlx> [repl("Options for the XDevAPI connector:", "Available options:")] ===
Options for the XDevAPI connector:

* dns-srv
* compression

.. === </mysqlx> ===

.. === <mysql> [repl("Classic", "Sample Code"), repl("-------", "-----------")] ===
Classic
-------

.. code:: python

    import mysql.connector

    # Connect to server
    cnx = mysql.connector.connect(
        host="127.0.0.1",
        port=3306,
        user="mike",
        password="s3cre3t!")

    # Get a cursor
    cur = cnx.cursor()

    # Execute a query
    cur.execute("SELECT CURDATE()")

    # Fetch one result
    row = cur.fetchone()
    print("Current date is: {0}".format(row[0]))

    # Close connection
    cnx.close()

.. === </mysql> ===

.. === <mysqlx> [repl("XDevAPI", "Sample Code"), repl("-------", "-----------")] ===
XDevAPI
-------

.. code:: python

    import mysqlx

    # Connect to server
    session = mysqlx.get_session(
       host="127.0.0.1",
       port=33060,
       user="mike",
       password="s3cr3t!")
    schema = session.get_schema("test")

    # Use the collection "my_collection"
    collection = schema.get_collection("my_collection")

    # Specify which document to find with Collection.find()
    result = collection.find("name like :param") \
                       .bind("param", "S%") \
                       .limit(1) \
                       .execute()

    # Print document
    docs = result.fetch_all()
    print(r"Name: {0}".format(docs[0]["name"]))

    # Close session
    session.close()

.. === </mysqlx> ===

.. === <both> [repl-mysql("- `MySQL Connector/Python X DevAPI Reference <https://dev.mysql.com/doc/dev/connector-python/>`_", ""), repl-mysqlx("- `MySQL Connector/Python Developer Guide <https://dev.mysql.com/doc/connector-python/en/>`_", "")] ===
Additional Resources
--------------------

- `MySQL Connector/Python Developer Guide <https://dev.mysql.com/doc/connector-python/en/>`_
- `MySQL Connector/Python X DevAPI Reference <https://dev.mysql.com/doc/dev/connector-python/>`_
- `MySQL Connector/Python Forum <http://forums.mysql.com/list.php?50>`_
- `MySQL Public Bug Tracker <https://bugs.mysql.com>`_
- `Slack <https://mysqlcommunity.slack.com>`_ (`Sign-up <https://lefred.be/mysql-community-on-slack/>`_ required if you do not have an Oracle account)
- `Stack Overflow <https://stackoverflow.com/questions/tagged/mysql-connector-python>`_
- `Oracle Blogs <https://blogs.oracle.com/search.html?q=connector-python>`_

.. === </both> ===


Contributing
------------

There are a few ways to contribute to the Connector/Python code. Please refer
to the `contributing guidelines <CONTRIBUTING.md>`_ for additional information.


License
-------

Please refer to the `README.txt <README.txt>`_ and `LICENSE.txt <LICENSE.txt>`_
files, available in this repository, for further details.
