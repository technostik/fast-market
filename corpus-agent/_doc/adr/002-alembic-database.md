great. Most of the test passes. A few more to correct : 

pytest 
===================================================================== test session starts ======================================================================
platform linux -- Python 3.11.9, pytest-9.0.2, pluggy-1.6.0
rootdir: /home/joriel/Code/fast-market/corpus-agent
configfile: pyproject.toml
plugins: anyio-4.12.1
collected 55 items                                                                                                                                             

tests/test_api.py .................                                                                                                                      [ 30%]
tests/test_cli.py ....................                                                                                                                   [ 67%]
tests/test_embedder.py .                                                                                                                                 [ 69%]
tests/test_obsidian.py .                                                                                                                                 [ 70%]
tests/test_paths_config.py ....FF...                                                                                                                     [ 87%]
tests/test_storage.py ..F..                                                                                                                              [ 96%]
tests/test_sync_engine.py .                                                                                                                              [ 98%]
tests/test_youtube.py .                                                                                                                                  [100%]

=========================================================================== FAILURES ===========================================================================
_________________________________________________________ test_sqlite_store_default_path_is_tool_data __________________________________________________________

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x73b4c43d38d0>
tmp_path = PosixPath('/tmp/pytest-of-joriel/pytest-13/test_sqlite_store_default_path0')

    def test_sqlite_store_default_path_is_tool_data(monkeypatch, tmp_path: Path):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg_data"))
        store = SQLiteStore()
>       row = store.conn.execute("PRAGMA database_list").fetchone()
              ^^^^^^^^^^
E       AttributeError: 'SQLiteStore' object has no attribute 'conn'

tests/test_paths_config.py:73: AttributeError
___________________________________________________________ test_sqlite_store_expands_tilde_db_path ____________________________________________________________

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x73b4c4196ad0>
tmp_path = PosixPath('/tmp/pytest-of-joriel/pytest-13/test_sqlite_store_expands_tild0')

    def test_sqlite_store_expands_tilde_db_path(monkeypatch, tmp_path: Path):
        home = tmp_path / "home"
        monkeypatch.setenv("HOME", str(home))
        store = SQLiteStore("~/.local/share/fast-market/data/corpus/corpus.db")
>       row = store.conn.execute("PRAGMA database_list").fetchone()
              ^^^^^^^^^^
E       AttributeError: 'SQLiteStore' object has no attribute 'conn'

tests/test_paths_config.py:84: AttributeError
___________________________________________________________ test_auto_migration_adds_privacy_status ____________________________________________________________

self = <sqlalchemy.engine.base.Connection object at 0x73b4bc3bead0>
dialect = <sqlalchemy.dialects.sqlite.pysqlite.SQLiteDialect_pysqlite object at 0x73b4bc3bc8d0>
context = <sqlalchemy.dialects.sqlite.base.SQLiteExecutionContext object at 0x73b4bc3a4790>
statement = <sqlalchemy.dialects.sqlite.base.SQLiteCompiler object at 0x73b4bc3a5590>, parameters = [()]

    def _exec_single_context(
        self,
        dialect: Dialect,
        context: ExecutionContext,
        statement: Union[str, Compiled],
        parameters: Optional[_AnyMultiExecuteParams],
    ) -> CursorResult[Any]:
        """continue the _execute_context() method for a single DBAPI
        cursor.execute() or cursor.executemany() call.
    
        """
        if dialect.bind_typing is BindTyping.SETINPUTSIZES:
            generic_setinputsizes = context._prepare_set_input_sizes()
    
            if generic_setinputsizes:
                try:
                    dialect.do_set_input_sizes(
                        context.cursor, generic_setinputsizes, context
                    )
                except BaseException as e:
                    self._handle_dbapi_exception(
                        e, str(statement), parameters, None, context
                    )
    
        cursor, str_statement, parameters = (
            context.cursor,
            context.statement,
            context.parameters,
        )
    
        effective_parameters: Optional[_AnyExecuteParams]
    
        if not context.executemany:
            effective_parameters = parameters[0]
        else:
            effective_parameters = parameters
    
        if self._has_events or self.engine._has_events:
            for fn in self.dispatch.before_cursor_execute:
                str_statement, effective_parameters = fn(
                    self,
                    cursor,
                    str_statement,
                    effective_parameters,
                    context,
                    context.executemany,
                )
    
        if self._echo:
            self._log_info(str_statement)
    
            stats = context._get_cache_stats()
    
            if not self.engine.hide_parameters:
                self._log_info(
                    "[%s] %r",
                    stats,
                    sql_util._repr_params(
                        effective_parameters,
                        batches=10,
                        ismulti=context.executemany,
                    ),
                )
            else:
                self._log_info(
                    "[%s] [SQL parameters hidden due to hide_parameters=True]",
                    stats,
                )
    
        evt_handled: bool = False
        try:
            if context.execute_style is ExecuteStyle.EXECUTEMANY:
                effective_parameters = cast(
                    "_CoreMultiExecuteParams", effective_parameters
                )
                if self.dialect._has_events:
                    for fn in self.dialect.dispatch.do_executemany:
                        if fn(
                            cursor,
                            str_statement,
                            effective_parameters,
                            context,
                        ):
                            evt_handled = True
                            break
                if not evt_handled:
                    self.dialect.do_executemany(
                        cursor,
                        str_statement,
                        effective_parameters,
                        context,
                    )
            elif not effective_parameters and context.no_parameters:
                if self.dialect._has_events:
                    for fn in self.dialect.dispatch.do_execute_no_params:
                        if fn(cursor, str_statement, context):
                            evt_handled = True
                            break
                if not evt_handled:
                    self.dialect.do_execute_no_params(
                        cursor, str_statement, context
                    )
            else:
                effective_parameters = cast(
                    "_CoreSingleExecuteParams", effective_parameters
                )
                if self.dialect._has_events:
                    for fn in self.dialect.dispatch.do_execute:
                        if fn(
                            cursor,
                            str_statement,
                            effective_parameters,
                            context,
                        ):
                            evt_handled = True
                            break
                if not evt_handled:
>                   self.dialect.do_execute(
                        cursor, str_statement, effective_parameters, context
                    )

../venv/lib/python3.11/site-packages/sqlalchemy/engine/base.py:1967: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

self = <sqlalchemy.dialects.sqlite.pysqlite.SQLiteDialect_pysqlite object at 0x73b4bc3bc8d0>, cursor = <sqlite3.Cursor object at 0x73b4c6417640>
statement = 'CREATE INDEX IF NOT EXISTS ix_documents_privacy_status ON documents(privacy_status)', parameters = ()
context = <sqlalchemy.dialects.sqlite.base.SQLiteExecutionContext object at 0x73b4bc3a4790>

    def do_execute(self, cursor, statement, parameters, context=None):
>       cursor.execute(statement, parameters)
E       sqlite3.OperationalError: no such column: privacy_status

../venv/lib/python3.11/site-packages/sqlalchemy/engine/default.py:952: OperationalError

The above exception was the direct cause of the following exception:

self = <storage.sqlite_store.SQLiteStore object at 0x73b4bd799090>

    def _run_migrations(self) -> None:
        if self._path == ":memory:":
            from storage.models import Base
    
            Base.metadata.create_all(self.engine)
            with self.engine.begin() as conn:
                conn.execute(
                    text(
                        """
                        CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
                            source_plugin, source_id, content
                        )
                        """
                    )
                )
            logger.info("db_migration_complete", backend="sqlalchemy", target="memory")
            return
    
        config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
        config.set_main_option("sqlalchemy.url", self._build_db_url(self._path))
        try:
>           command.upgrade(config, "head")

storage/sqlalchemy_store.py:113: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
../venv/lib/python3.11/site-packages/alembic/command.py:483: in upgrade
    script.run_env()
../venv/lib/python3.11/site-packages/alembic/script/base.py:545: in run_env
    util.load_python_file(self.dir, "env.py")
../venv/lib/python3.11/site-packages/alembic/util/pyfiles.py:116: in load_python_file
    module = load_module_py(module_id, path)
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
../venv/lib/python3.11/site-packages/alembic/util/pyfiles.py:136: in load_module_py
    spec.loader.exec_module(module)  # type: ignore
    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
migrations/env.py:35: in <module>
    run_migrations_online()
migrations/env.py:29: in run_migrations_online
    context.run_migrations()
../venv/lib/python3.11/site-packages/alembic/runtime/environment.py:969: in run_migrations
    self.get_context().run_migrations(**kw)
../venv/lib/python3.11/site-packages/alembic/runtime/migration.py:626: in run_migrations
    step.migration_fn(**kw)
migrations/versions/0001_initial_schema.py:64: in upgrade
    op.execute("CREATE INDEX IF NOT EXISTS ix_documents_privacy_status ON documents(privacy_status)")
../venv/lib/python3.11/site-packages/alembic/operations/ops.py:2667: in execute
    return operations.invoke(op)
           ^^^^^^^^^^^^^^^^^^^^^
../venv/lib/python3.11/site-packages/alembic/operations/base.py:452: in invoke
    return fn(self, operation)
           ^^^^^^^^^^^^^^^^^^^
../venv/lib/python3.11/site-packages/alembic/operations/toimpl.py:259: in execute_sql
    operations.migration_context.impl.execute(
../venv/lib/python3.11/site-packages/alembic/ddl/impl.py:263: in execute
    self._exec(sql, execution_options)
../venv/lib/python3.11/site-packages/alembic/ddl/impl.py:256: in _exec
    return conn.execute(construct, params)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
../venv/lib/python3.11/site-packages/sqlalchemy/engine/base.py:1419: in execute
    return meth(
../venv/lib/python3.11/site-packages/sqlalchemy/sql/elements.py:527: in _execute_on_connection
    return connection._execute_clauseelement(
../venv/lib/python3.11/site-packages/sqlalchemy/engine/base.py:1641: in _execute_clauseelement
    ret = self._execute_context(
../venv/lib/python3.11/site-packages/sqlalchemy/engine/base.py:1846: in _execute_context
    return self._exec_single_context(
../venv/lib/python3.11/site-packages/sqlalchemy/engine/base.py:1986: in _exec_single_context
    self._handle_dbapi_exception(
../venv/lib/python3.11/site-packages/sqlalchemy/engine/base.py:2363: in _handle_dbapi_exception
    raise sqlalchemy_exception.with_traceback(exc_info[2]) from e
../venv/lib/python3.11/site-packages/sqlalchemy/engine/base.py:1967: in _exec_single_context
    self.dialect.do_execute(
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

self = <sqlalchemy.dialects.sqlite.pysqlite.SQLiteDialect_pysqlite object at 0x73b4bc3bc8d0>, cursor = <sqlite3.Cursor object at 0x73b4c6417640>
statement = 'CREATE INDEX IF NOT EXISTS ix_documents_privacy_status ON documents(privacy_status)', parameters = ()
context = <sqlalchemy.dialects.sqlite.base.SQLiteExecutionContext object at 0x73b4bc3a4790>

    def do_execute(self, cursor, statement, parameters, context=None):
>       cursor.execute(statement, parameters)
E       sqlalchemy.exc.OperationalError: (sqlite3.OperationalError) no such column: privacy_status
E       [SQL: CREATE INDEX IF NOT EXISTS ix_documents_privacy_status ON documents(privacy_status)]
E       (Background on this error at: https://sqlalche.me/e/20/e3q8)

../venv/lib/python3.11/site-packages/sqlalchemy/engine/default.py:952: OperationalError

The above exception was the direct cause of the following exception:

tmp_path = PosixPath('/tmp/pytest-of-joriel/pytest-13/test_auto_migration_adds_priva0')

    def test_auto_migration_adds_privacy_status(tmp_path):
        db_path = tmp_path / "legacy.db"
        conn = sqlite3.connect(db_path)
        conn.executescript(
            """
            CREATE TABLE documents (
                id INTEGER PRIMARY KEY,
                handle TEXT NOT NULL,
                source_plugin TEXT NOT NULL,
                source_id TEXT NOT NULL,
                title TEXT NOT NULL,
                raw_text TEXT NOT NULL,
                url TEXT,
                updated_at TEXT,
                duration_seconds INTEGER,
                content_hash TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                UNIQUE(source_plugin, source_id),
                UNIQUE(handle)
            );
            CREATE TABLE chunks (
                id INTEGER PRIMARY KEY,
                source_plugin TEXT NOT NULL,
                source_id TEXT NOT NULL,
                chunk_index INTEGER NOT NULL,
                content TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                embedding_json TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                UNIQUE(source_plugin, source_id, chunk_index)
            );
            CREATE VIRTUAL TABLE chunks_fts USING fts5(source_plugin, source_id, content);
            """
        )
        conn.commit()
        conn.close()
    
>       SQLiteStore(str(db_path))

tests/test_storage.py:64: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
storage/sqlite_store.py:15: in __init__
    super().__init__(path)
storage/sqlalchemy_store.py:63: in __init__
    self._run_migrations()
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

self = <storage.sqlite_store.SQLiteStore object at 0x73b4bd799090>

    def _run_migrations(self) -> None:
        if self._path == ":memory:":
            from storage.models import Base
    
            Base.metadata.create_all(self.engine)
            with self.engine.begin() as conn:
                conn.execute(
                    text(
                        """
                        CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
                            source_plugin, source_id, content
                        )
                        """
                    )
                )
            logger.info("db_migration_complete", backend="sqlalchemy", target="memory")
            return
    
        config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
        config.set_main_option("sqlalchemy.url", self._build_db_url(self._path))
        try:
            command.upgrade(config, "head")
        except Exception as exc:  # fail loudly
            logger.error("db_migration_failed", error=str(exc), path=self._path)
>           raise RuntimeError(f"Database migration failed for {self._path}") from exc
E           RuntimeError: Database migration failed for /tmp/pytest-of-joriel/pytest-13/test_auto_migration_adds_priva0/legacy.db

storage/sqlalchemy_store.py:116: RuntimeError
======================================================================= warnings summary =======================================================================
tests/test_api.py::test_sync_obsidian
tests/test_api.py::test_items_after_sync
tests/test_api.py::test_search_keyword
tests/test_api.py::test_get_document
tests/test_api.py::test_delete_document
tests/test_api.py::test_reindex
  /home/joriel/Code/fast-market/corpus-agent/commands/sync/register.py:65: DeprecationWarning: SQLiteStore now uses SQLAlchemy + Alembic under the hood; use SQLAlchemyStore directly.
    store = SQLiteStore(config.get("db_path"))

tests/test_api.py::test_items_empty
tests/test_api.py::test_items_after_sync
tests/test_api.py::test_get_document
tests/test_api.py::test_delete_document
  /home/joriel/Code/fast-market/corpus-agent/commands/status/register.py:52: DeprecationWarning: SQLiteStore now uses SQLAlchemy + Alembic under the hood; use SQLAlchemyStore directly.
    store = SQLiteStore(config.get("db_path"))

tests/test_api.py::test_search_keyword
tests/test_api.py::test_search_bad_mode
  /home/joriel/Code/fast-market/corpus-agent/commands/search/register.py:82: DeprecationWarning: SQLiteStore now uses SQLAlchemy + Alembic under the hood; use SQLAlchemyStore directly.
    store = SQLiteStore(config.get("db_path"))

tests/test_api.py::test_get_document
tests/test_api.py::test_get_document_not_found
tests/test_api.py::test_delete_document
  /home/joriel/Code/fast-market/corpus-agent/commands/get/register.py:56: DeprecationWarning: SQLiteStore now uses SQLAlchemy + Alembic under the hood; use SQLAlchemyStore directly.
    store = SQLiteStore(config.get("db_path"))

tests/test_api.py::test_delete_document
tests/test_api.py::test_delete_document_not_found
  /home/joriel/Code/fast-market/corpus-agent/commands/delete/register.py:42: DeprecationWarning: SQLiteStore now uses SQLAlchemy + Alembic under the hood; use SQLAlchemyStore directly.
    store = SQLiteStore(config.get("db_path"))

tests/test_api.py::test_reindex
  /home/joriel/Code/fast-market/corpus-agent/commands/reindex/register.py:48: DeprecationWarning: SQLiteStore now uses SQLAlchemy + Alembic under the hood; use SQLAlchemyStore directly.
    store = SQLiteStore(config.get("db_path"))

tests/test_cli.py: 30 warnings
  /home/joriel/Code/fast-market/corpus-agent/commands/helpers.py:28: DeprecationWarning: SQLiteStore now uses SQLAlchemy + Alembic under the hood; use SQLAlchemyStore directly.
    store = SQLiteStore(config.get("db_path"))

tests/test_paths_config.py::test_sqlite_store_default_path_is_tool_data
  /home/joriel/Code/fast-market/corpus-agent/tests/test_paths_config.py:72: DeprecationWarning: SQLiteStore now uses SQLAlchemy + Alembic under the hood; use SQLAlchemyStore directly.
    store = SQLiteStore()

tests/test_paths_config.py::test_sqlite_store_expands_tilde_db_path
  /home/joriel/Code/fast-market/corpus-agent/tests/test_paths_config.py:83: DeprecationWarning: SQLiteStore now uses SQLAlchemy + Alembic under the hood; use SQLAlchemyStore directly.
    store = SQLiteStore("~/.local/share/fast-market/data/corpus/corpus.db")

tests/test_storage.py::test_upsert_idempotent
tests/test_storage.py::test_keyword_search
tests/test_storage.py::test_replace_chunks_rolls_back_on_error
tests/test_sync_engine.py::test_sync_engine_sync
  /home/joriel/Code/fast-market/corpus-agent/tests/conftest.py:67: DeprecationWarning: SQLiteStore now uses SQLAlchemy + Alembic under the hood; use SQLAlchemyStore directly.
    return SQLiteStore(":memory:")

tests/test_storage.py::test_auto_migration_adds_privacy_status
  /home/joriel/Code/fast-market/corpus-agent/tests/test_storage.py:64: DeprecationWarning: SQLiteStore now uses SQLAlchemy + Alembic under the hood; use SQLAlchemyStore directly.
    SQLiteStore(str(db_path))

tests/test_storage.py::test_migration_works_when_cwd_changes
  /home/joriel/Code/fast-market/corpus-agent/tests/test_storage.py:98: DeprecationWarning: SQLiteStore now uses SQLAlchemy + Alembic under the hood; use SQLAlchemyStore directly.
    SQLiteStore(str(db_path))

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
=================================================================== short test summary info ====================================================================
FAILED tests/test_paths_config.py::test_sqlite_store_default_path_is_tool_data - AttributeError: 'SQLiteStore' object has no attribute 'conn'
FAILED tests/test_paths_config.py::test_sqlite_store_expands_tilde_db_path - AttributeError: 'SQLiteStore' object has no attribute 'conn'
FAILED tests/test_storage.py::test_auto_migration_adds_privacy_status - RuntimeError: Database migration failed for /tmp/pytest-of-joriel/pytest-13/test_auto_migration_adds_priva0/legacy.db
========================================================== 3 failed, 52 passed, 56 warnings in 5.20s ===========================================================
