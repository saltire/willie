"""
*Availability: 3.1+*

*Note:* This supersedes the ``SettingsDB`` object of 3.0. Within Willie modules,
simmilar functionallity can be found using ``db.preferences``.

This class defines an interface for a semi-arbitrary database type. It is meant
to allow module writers to operate without regard to how the end user has
decided to set up the database.
"""
"""
Copyright 2012, Edward D. Powell, embolalia.net
Licensed under the Eiffel Forum License 2.

http://willie.dftba.net
"""

from collections import Iterable
from tools import deprecated

supported_types = set()
#Attempt to import possible db modules
try:
    import MySQLdb
    import MySQLdb.cursors
    supported_types.add('mysql')
except ImportError:
    pass

try:
    import sqlite3
    supported_types.add('sqlite')
except ImportError:
    pass


class WillieDB(object):
    """
    Return a WillieDB object configured with the options in the given Config
    object. The exact settgins used vary depending on the type of database
    chosen to back the SettingsDB, as determined by the ``userdb_type``
    attribute of *config*.

    Currently, two values for ``userdb_type`` are supported: ``sqlite`` and
    ``mysql``. The ``sqlite`` type requires that ``userdb_file`` be set in the
    ``db`` section of ``config`` (that is, under the ``[db]`` heading in the
    config file), and refer to a writeable sqlite database. The ``mysql`` type
    requires ``userdb_host``, ``userdb_user``, ``userdb_pass``, and
    ``userdb_name`` to be set, and provide the host and name of a MySQL database,
    as well as a username and password for a user able to write to said database.

    Upon creation of the object, the tables currently existing in the given
    database will be registered, as though added through ``add_table``.
    """

    def __init__(self, config):
        self._none = Table(self, '_none', [], '_none')
        self.tables = set()
        if not config.parser.has_section('db'):
            self.type = None
            print 'No user settings database specified. Ignoring.'
            return

        self.type = config.db.userdb_type.lower()
        if self.type not in supported_types:
            self.type = None
            print 'User settings database type is not supported. You may be missing the module for it. Ignoring.'
            return

        if self.type == 'mysql':
            self.substitution = '%s'
            self.sub = '%s'
            self._mySQL(config)
        elif self.type == 'sqlite':
            self.substitution = '?'
            self.sub = '?'
            self._sqlite(config)

    def __getattr__(self, attr):
        """
        Handle non-existant tables gracefully by returning a pseudo-table.
        """
        return self._none

    def __nonzero__(self):
        """Allow for testing if a db is set up through `if willie.db`."""
        return bool(self.type)

    def _mySQL(self, config):
        try:
            self._host = config.db.userdb_host
            self._user = config.db.userdb_user
            self._passwd = config.db.userdb_pass
            self._dbname = config.db.userdb_name
        except AttributeError as e:
            print 'Some options are missing for your MySQL DB. The database will not be set up.'
            return

        try:
            db = MySQLdb.connect(host=self._host,
                         user=self._user,
                         passwd=self._passwd,
                         db=self._dbname)
        except:
            print 'Error: Unable to connect to user settings DB.'
            return

        #Set up existing tables and columns
        cur = MySQLdb.cursors.DictCursor(db)
        cur.execute("SHOW tables;")
        tables = cur.fetchall()
        for table in tables:
            name = table['Tables_in_%s' % self._dbname]
            cur.execute("SHOW columns FROM %s;" % name)
            result = cur.fetchall()
            columns = []
            key = []
            for column in result:
                columns.append(column['Field'])
                if column['Key'].startswith('PRI'):
                    key.append(column['Field'])
            setattr(self, name, Table(self, name, columns, key))
            self.tables.add(name)
        db.close()

    def _sqlite(self, config):
        try:
            self._file = config.db.userdb_file
        except AttributeError:
            print 'No file specified for SQLite DB. The database will not be set up.'
            return

        try:
            db = sqlite3.connect(self._file)
        except:
            print 'Error: Unable to connect to DB.'
            return

        #Set up existing tables and columns
        cur = db.cursor()
        cur.execute("SELECT * FROM sqlite_master;")
        tables = cur.fetchall()
        for table in tables:
            name = table[1]
            if name.startswith('sqlite_'):
                continue

            cur.execute("PRAGMA table_info(%s);" % name)
            result = cur.fetchall()
            columns = []
            key = []
            for column in result:
                columns.append(column[1])
                if column[3]:
                    key.append(column[1])
            setattr(self, name, Table(self, name, columns, key))
        db.close()

    def check_table(self, name, columns, key):
        """
        Return ``True`` if the WillieDB contains a table with the same ``name``
        and ``key``, and which contains a column with the same name as each element
        in the given list ``columns``.
        """
        table = getattr(self, name)
        return (isinstance(table, Table) and table.key == key and
                all(c in table.columns for c in columns))

    def _get_column_creation_text(self, columns, key=None):
        cols = '('
        for column in columns:
            if isinstance(column, basestring):
                if self.type == 'mysql':
                    cols = cols + column + ' VARCHAR(255)'
                elif self.type == 'sqlite':
                    cols = cols + column + ' string'
            elif isinstance(column, tuple):
                cols += '%s %s' % column

            if key and column in key:
                cols += ' NOT NULL'
            cols += ', '

        if key:
            if isinstance(key, basestring):
                cols += 'PRIMARY KEY (%s)' % key
            else:
                cols += 'PRIMARY KEY (%s)' % ', '.join(key)
        else:
            cols = cols[:-2]
        return cols + ')'

    def add_table(self, name, columns, key):
        """
        Add a column with the given ``name`` and ``key``, which has the given
        ``columns``. Each element in ``columns`` may be either a string giving
        the name of the column, or a tuple containing the name of the column and
        its type (using SQL type names). If the former, the type will be assumed
        as string.

        This will attempt to create the table within the database. If an error
        is encountered while adding the table, it will not be added to the
        WillieDB object. If a table with the same name and key already exists,
        the given columns will be added (if they don't already exist).

        The given ``name`` can not be the same as any function or attribute
        (with the exception of other tables) of the ``WillieDB`` object, nor may
        it start with ``'_'``. If it does not meet this requirement, or if the
        ``name`` matches that of an existing table with a different ``key``, a
        ``ValueError`` will be thrown.

        When a table is created, the column ``key`` will be declared as the
        primary key of the table. If it is desired that there be no primary key,
        this can be achieved by creating the table manually, or with a custom
        query, and then creating the WillieDB object.
        """
        # First, get the attribute with that name. It'll probably be a pseudo-
        # table, but we want to know if the table already exists or if it's
        # some other db attribute.
        extant_table = getattr(self, name)
        if name.startswith('_'):  # exclude special names
            raise ValueError('Invalid table name %s.' % name)
        elif not isinstance(extant_table, Table):
            #Conflict with a non-table value, probably a function
            raise ValueError('Invalid table name %s.' % name)
        elif not name in self.tables:
            # We got a table, but it's not registered in the table list, so we
            # create it.
            cols = self._get_column_creation_text(columns, key)
            db = self.connect()
            cursor = db.cursor()
            cursor.execute("CREATE TABLE %s %s;" % (name, cols))
            db.close()
            extant_table = Table(self, name, columns, key)
            setattr(self, name, extant_table)
            self.tables.add(name)
        elif extant_table.key == key:
            # We got an actual table. If the key on the table being created
            # has the same key, it's safe to assume it's the one the user
            # wanted, so if there are columns not already there, we add them.
            if not all(c in extant_table.columns for c in columns):
                db = self.connect()
                cursor = db.cursor()
                cursor.execute("ALTER TABLE %s ADD COLUMN %s;")
                extant_table.colums.add(columns)
                db.close()
        else:
            # There's already a different table with that name, which we can't
            # fix, so raise an error.
            raise ValueError('Table %s already exists with different key.'
                             % name)

    def connect(self):
        """
        Create a database connection object. This functions essentially the same
        as the ``connect`` function of the appropriate database type, allowing
        for custom queries to be executed.
        """
        if self.type == 'mysql':
            return MySQLdb.connect(host=self._host,
                     user=self._user,
                     passwd=self._passwd,
                     db=self._dbname)
        elif self.type == 'sqlite':
            return sqlite3.connect(self._file)


class Table(object):
    """
    Return an object which represents a table in the given WillieDB, with the
    given attributes. This will not check if ``db`` already has a table with the
    given ``name``; the ``db``'s ``add_table`` provides that functionality.

    ``key`` must be a string, which is in the list of strings ``columns``, or an
    Exception will be thrown.
    """

    def __init__(self, db, name, columns, key):
        #This lets us have a pseudo-table to handle a non-existant table
        if name is '_none':
            self.db = db
            self.columns = set()
            self.name = name
            self.key = '_none'
            return
        if not key:
            key = columns[0]
        if len(key) == 1:
            key = key[0]  # This catches strings, too, but without consequence.

        self.db = db
        self.columns = set(columns)
        self.name = name
        if isinstance(key, basestring):
            if key not in columns:
                raise Exception  # TODO
            self.key = key
        else:
            for k in key:
                if k not in columns:
                    raise Exception  # TODO
            self.key = key

    def __nonzero__(self):
        return bool(self.columns)

    def users(self):
        """
        Returns the number of users (entries not starting with # or &) in the
        table's ``key`` column.
        """
        if not self.columns:  # handle a non-existant table
            return 0

        db = self.db.connect()
        cur = db.cursor()
        cur.execute("SELECT COUNT(*) FROM " + self.name +
                " WHERE " + self.key + " LIKE \"[^#&]%;")
        result = int(cur.fetchone()[0])
        db.close()
        return result

    def channels(self):
        """
        Returns the number of users (entries starting with # or &) in the
        table's ``key`` column.
        """
        if not self.columns: # handle a non-existent table
            return 0

        db = self.db.connect()
        cur = db.cursor()
        cur.execute("SELECT COUNT(*) FROM " + self.name +
                " WHERE " + self.key + " LIKE \"[#&]%;")
        result = int(cur.fetchone()[0])
        db.close()
        return result


    def size(self):
        """Returns the total number of rows in the table."""
        if not self.columns: # handle a non-existent table
            return 0
        
        db = self.db.connect()
        cur = db.cursor()
        
        cur.execute('SELECT COUNT(*) FROM {0};'.format(self.name))
        result = int(cur.fetchone()[0])
        db.close()
        return result
    
    
    def _make_where_statement(self, cols):
        return ' AND '.join('{0} = {1}'.format(c, self.db.sub) for c in cols)
    
    
    def _select(self, cur, columns=[], where={}):
        """Select one or more rows from the table.
        'columns' must be a list and 'where' must be a dict."""
        if where:
            curkeys, curvalues = zip(*where.items())
            where_sql = ' WHERE ' + self._make_where_statement(curkeys)
        else:
            where_sql = ''
            
        command = 'SELECT {0} FROM {1}{2};'.format(
            ', '.join(columns) if columns else '*',
            self.name,
            where_sql)
        cur.execute(command, curvalues)
        return cur.fetchall()
        
        
    def _insert(self, cur, values):
        """Insert a row into the table.
        'values' can be either a list or a dict."""
        try:
            columns, values = zip(*values.items())
            columns_sql = ' ({1})'.format(', '.join(columns))
        except AttributeError:
            columns_sql = ''
            
        command = 'INSERT INTO {0}{1} VALUES ({2});'.format(
            self.name,
            columns_sql,
            ', '.join((self.db.sub,) * len(values)))
        cur.execute(command, values)
        
        
    def _update(self, cur, values, where):
        """Update a row in the table.
        'values' and 'where' must be dicts."""
        newcolumns, newvalues = zip(*values.items())
        curcolumns, curvalues = zip(*where.items())
        
        command = 'UPDATE {0} SET {1} WHERE {2};'.format(
            self.name,
            ', '.join('{0} = {1}'.format(c, self.db.sub) for c in newcolumns),
            self._make_where_statement(curcolumns))
        cur.execute(command, newvalues + curvalues)
        
        
    def _delete(self, cur, where):
        """Delete a row from the table.
        'where' must be a dict."""
        columns, values = zip(*where.items())
        
        command = 'DELETE FROM {0} WHERE {1};'.format(
            self.name,
            self._make_where_statement(columns))
        cur.execute(command, values)      
        

    def get(self, columns, where={}):
        """
        Retrieve the value(s) in one or more 'columns' in the row matching the
        columns and values in the 'where' dict.
        
        'columns' can be either a single column name, or a list of column names.
        If one name is passed, a single string will be returned; otherwise a
        list of values will be returned in the same order.
        """
        if not self.columns: # handle a non-existent table
            raise ValueError('Table is empty.')
        
        db = self.db.connect()
        
        if isinstance(columns, basestring):
            result = [row[0] for row in
                      self._select(db.cursor(), [columns], where)]
        else:
            result = self._select(db.cursor(), columns, where)
        
        db.close()
        if not result:
            raise KeyError('Row does not exist in table.')

        return result
        
        
    def update(self, values, where={}):
        """
        Update the row matching the columns and values in the 'where' dict,
        with the columns and new values in the 'values' dict.
        If the row does not exist, it will be created.
        """
        if not self.columns: # handle a non-existent table
            raise ValueError('Table is empty.')
        
        db = self.db.connect()
        cur = db.cursor()

        if not self._select(cur, where):
            self._insert(cur, values)
        else:
            self._update(cur, values, where)
            
        db.commit()
        db.close()


    def delete(self, where={}):
        """Deletes the row for ``row`` in the database, removing its values in
        all columns."""
        if not self.columns: # handle a non-existent table
            raise ValueError('Table is empty.')

        db = self.db.connect()
        cur = db.cursor()
        
        if not self._select(cur, where=where):
            db.close()
            raise KeyError('Row does not exist in table.')

        self._delete(cur, where)
        
        db.commit()
        db.close()
        

    def keys(self, key=None):
        """
        Return an iterator over the keys and values in the table.

        In a for each loop, you can use ``for key in table:``, where key will be
        the value of the ``key`` column(s), which defaults to the primary key,
        and table is the Table. This may be deprecated in future versions.
        """
        if not self.columns: # handle a non-existent table
            raise ValueError('Table is empty.')

        if not key:
            key = self.key

        db = self.db.connect()

        result = self._select(db.cursor(), key)
        
        db.close()
        return result
    

    def __iter__(self):
        return self.keys()

    def contains(self, row, key=None):
        """
        Return ``True`` if this table has a row where the key value is equal to
        ``key``, else ``False``.

        ``key in db`` will also work, where db is your SettingsDB object.
        """
        if not self.columns:  # handle a non-existant table
            return False

        if not key:
            key = self.key
        db = self.db.connect()
        cur = db.cursor()
        where = self._make_where_statement(key, row)
        cur.execute('SELECT * FROM ' + self.name + ' WHERE ' + where, [row])
        result = cur.fetchone()
        db.close()
        if result:
            return True
        else:
            return False

    def __contains__(self, item):
        return self.contains(item)

    @deprecated
    def hascolumn(self, column):
        return self.has_columns(column)

    @deprecated
    def hascolumns(self, column):
        return self.has_columns(column)

    def has_columns(self, column):
        """
        Each Table contains a cached list of its columns. ``hascolumn(column)``
        checks this list, and returns True if it contains ``column``. If
        ``column`` is an iterable, this returns true if all of the values in
        ``column`` are in the column cache. Note that this will not check the
        database itself; it's meant for speed, not accuracy. However, unless
        you have multiple bots using the same database, or are adding columns
        while the bot is running, you are unlikely to encounter errors.
        """
        if not self.columns:  # handle a non-existant table
            return False

        if isinstance(column, basestring):
            return column in self.columns
        elif isinstance(column, Iterable):
            has = True
            for col in column:
                has = col in self.columns and has
            return has

    @deprecated
    def addcolumns(self, columns):
        return self.add_columns(columns)

    def add_columns(self, columns):
        """
        Insert a new column into the table, and add it to the column cache.
        This is the preferred way to add new columns to the database.
        """
        if not self.columns:  # handle a non-existant table
            raise ValueError('Table is empty.')

        #I feel like adding one at a time is weird, but it works.
        db = self.db.connect()
        for column in columns:
            cmd = 'ALTER TABLE ' + self.name + ' ADD '
            if isinstance(column, tuple):
                cmd = cmd + column[0] + ' ' + column[1] + ';'
            else:
                cmd = cmd + column + ' text;'
            cur = db.cursor()
            cur.execute(cmd)
        db.commit()
        db.close()

        #Why a second loop? because I don't want clomuns to be added to self.columns if executing the SQL command fails
        for column in columns:
            self.columns.add(column)


def configure(config):
    """
    Interactively create configuration options and add the attributes to
    the Config object ``config``.
    """
    config.add_section('db')

    config.interactive_add('db', 'userdb_type',
        'What type of database would you like to use? (mysql/sqlite)', 'mysql')

    if config.db.userdb_type == 'sqlite':
        config.interactive_add('db', 'userdb_file', 'Location for the database file')

    elif config.db.userdb_type == 'mysql':
        config.interactive_add('db', 'userdb_host', "Enter the MySQL hostname", 'localhost')
        config.interactive_add('db', 'userdb_user', "Enter the MySQL username")
        config.interactive_add('db', 'userdb_pass', "Enter the user's password", 'none')
        config.interactive_add('db', 'userdb_name', "Enter the name of the database to use")

    else:
        print "This isn't currently supported. Aborting."
