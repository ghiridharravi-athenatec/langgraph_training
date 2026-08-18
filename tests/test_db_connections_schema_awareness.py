from app.core import db_connections


class _FakeInspector:
    '''Stands in for sqlalchemy.inspect(engine) - only the two methods
    _sql_list_tables/_sql_describe_table actually call.'''

    def __init__(self, schemas=None, tables_by_schema=None, columns=None):
        self._schemas = schemas or []
        self._tables_by_schema = tables_by_schema or {}
        self._columns = columns if columns is not None else [{"name": "id", "type": "INTEGER"}]
        self.get_columns_calls = []

    def get_schema_names(self):
        return self._schemas

    def get_table_names(self, schema=None):
        return self._tables_by_schema.get(schema, [])

    def get_columns(self, table_name, schema=None):
        self.get_columns_calls.append((table_name, schema))
        return self._columns


def _patch_inspector(monkeypatch, inspector):
    monkeypatch.setattr(db_connections, "_sql_engine", lambda details: object())
    monkeypatch.setattr(db_connections.sqlalchemy, "inspect", lambda engine: inspector)


def test_list_tables_returns_bare_names_when_only_one_user_schema(monkeypatch):
    inspector = _FakeInspector(schemas=["public"], tables_by_schema={"public": ["users", "orders"]})
    _patch_inspector(monkeypatch, inspector)

    tables = db_connections._sql_list_tables({"engine": "postgresql"})
    assert tables == ["users", "orders"]


def test_list_tables_qualifies_names_across_multiple_user_schemas(monkeypatch):
    inspector = _FakeInspector(
        schemas=["public", "finance", "pg_catalog", "information_schema", "pg_toast"],
        tables_by_schema={"public": ["users"], "finance": ["transactions"]},
    )
    _patch_inspector(monkeypatch, inspector)

    tables = db_connections._sql_list_tables({"engine": "postgresql"})
    assert set(tables) == {"public.users", "finance.transactions"}


def test_list_tables_filters_out_system_schemas_for_mssql(monkeypatch):
    inspector = _FakeInspector(
        schemas=["dbo", "reporting", "sys", "guest"],
        tables_by_schema={"dbo": ["accounts"], "reporting": ["monthly_summary"]},
    )
    _patch_inspector(monkeypatch, inspector)

    tables = db_connections._sql_list_tables({"engine": "mssql"})
    assert set(tables) == {"dbo.accounts", "reporting.monthly_summary"}


def test_list_tables_never_schema_qualifies_mysql(monkeypatch):
    # MySQL conflates "schema" with "database" - get_schema_names() there would
    # leak other databases outside this connection's own scope, so it's never
    # even called; get_table_names() runs with no schema argument.
    inspector = _FakeInspector(schemas=["some_other_database"], tables_by_schema={None: ["users"]})
    _patch_inspector(monkeypatch, inspector)

    tables = db_connections._sql_list_tables({"engine": "mysql"})
    assert tables == ["users"]


def test_split_schema_splits_qualified_names_for_schema_aware_engines():
    assert db_connections._split_schema("postgresql", "finance.transactions") == ("finance", "transactions")
    assert db_connections._split_schema("mssql", "reporting.monthly_summary") == ("reporting", "monthly_summary")


def test_split_schema_leaves_unqualified_names_alone():
    assert db_connections._split_schema("postgresql", "users") == (None, "users")


def test_split_schema_never_splits_mysql_names_even_with_a_dot():
    assert db_connections._split_schema("mysql", "finance.transactions") == (None, "finance.transactions")


def test_describe_table_passes_the_split_schema_to_get_columns(monkeypatch):
    inspector = _FakeInspector()
    _patch_inspector(monkeypatch, inspector)

    columns = db_connections._sql_describe_table({"engine": "postgresql"}, "finance.transactions")

    assert inspector.get_columns_calls == [("transactions", "finance")]
    assert columns == [{"name": "id", "type": "INTEGER"}]


def test_describe_table_passes_no_schema_for_an_unqualified_name(monkeypatch):
    inspector = _FakeInspector()
    _patch_inspector(monkeypatch, inspector)

    db_connections._sql_describe_table({"engine": "postgresql"}, "users")

    assert inspector.get_columns_calls == [("users", None)]
