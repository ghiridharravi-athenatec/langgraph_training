'''External database connections for "Database Ingestion" - encrypted credential
storage plus the actual per-engine connect/introspect/query logic the DB chat
agent's tools (list_tables/describe_table/run_query, see db_agent.py) dispatch
into. Kept separate from db_agent.py: this module has no idea an LLM exists,
it just knows how to safely talk to Postgres/MySQL/SQL Server/MongoDB.

Read-only is enforced in two independent layers (see run_query):
1. Tool-design level (the real defense) - the agent is only ever given this
   one query-shaped tool, never anything write-shaped.
2. Query-level (defense in depth) - _assert_read_only_sql rejects write
   keywords and multi-statement input before anything reaches the driver;
   SQL connections are also opened read-only where the dialect supports it.
For MongoDB there's no free-text query language to keyword-filter - read-only
is enforced structurally instead: the Mongo tool only ever calls find()/
aggregate(), there is no delete_one/update_one/insert_one path to reach at all.
'''

import json
import re
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote_plus

import sqlalchemy
from cryptography.fernet import Fernet, InvalidToken
from pymongo import MongoClient
from pymongo.errors import PyMongoError
from sqlalchemy.exc import SQLAlchemyError

from app.core import config
from app.core.logger import get_logger
from app.core.messages import msg

logger = get_logger(__name__)

ENGINES = ("postgresql", "mysql", "mssql", "mongodb")

def _build_fernet() -> Fernet:
    key = config.DB_CREDENTIAL_ENCRYPTION_KEY
    if key:
        try:
            return Fernet(key.encode())
        except ValueError:
            # Malformed key (wrong length/padding, not real base64, etc.) - degrade to
            # the same ephemeral-key fallback as "unset" rather than crashing the whole
            # app at import time over a typo in one env var, UNLESS the operator has opted
            # into strict startup via REQUIRE_PERSISTENT_ENCRYPTION_KEYS.
            if config.REQUIRE_PERSISTENT_ENCRYPTION_KEYS:
                raise RuntimeError(
                    "DB_CREDENTIAL_ENCRYPTION_KEY is set but isn't a valid Fernet key (expected 32 "
                    "url-safe base64-encoded bytes), and REQUIRE_PERSISTENT_ENCRYPTION_KEYS is set - "
                    "refusing to start with an ephemeral key. Generate a real one with `python -c "
                    "\"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"` "
                    "and fix it in your .env."
                )
            logger.warning(
                "DB_CREDENTIAL_ENCRYPTION_KEY is set but isn't a valid Fernet key (expected 32 "
                "url-safe base64-encoded bytes) - using an ephemeral key for this process instead. "
                "Generate a real one with `python -c \"from cryptography.fernet import Fernet; "
                "print(Fernet.generate_key().decode())\"` and fix it in your .env."
            )
    else:
        if config.REQUIRE_PERSISTENT_ENCRYPTION_KEYS:
            raise RuntimeError(
                "DB_CREDENTIAL_ENCRYPTION_KEY not set, and REQUIRE_PERSISTENT_ENCRYPTION_KEYS is set - "
                "refusing to start with an ephemeral key. Generate one with `python -c \"from cryptography."
                "fernet import Fernet; print(Fernet.generate_key().decode())\"` and set it via your secrets manager."
            )
        logger.warning(
            "DB_CREDENTIAL_ENCRYPTION_KEY not set - using an ephemeral key for this process. "
            "Saved database connections will be UNRECOVERABLE after restart. Generate one with "
            "`python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"` "
            "and set it via your secrets manager for any deployment meant to keep connections across restarts."
        )
    return Fernet(Fernet.generate_key())


_fernet = _build_fernet()

_query_executor = ThreadPoolExecutor(max_workers=8)

_WRITE_KEYWORDS_RE = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|CREATE|GRANT|REVOKE|REPLACE|MERGE|EXEC|EXECUTE|CALL)\b",
    re.IGNORECASE,
)

_SQL_DIALECT_DRIVERS = {
    "postgresql": "postgresql+psycopg2",
    "mysql": "mysql+pymysql",
    "mssql": "mssql+pyodbc",
}


class ConnectionError_(Exception):
    '''Raised for any failure connecting to or querying an external database -
    kept as one exception type so callers (the /database/connections endpoint,
    the agent's tool loop) don't need to know about driver-specific exceptions.'''


# ---------------------------------------------------------------------------
# Encryption at rest
# ---------------------------------------------------------------------------

def encrypt_connection_details(details: Dict[str, Any]) -> str:
    return _fernet.encrypt(json.dumps(details).encode()).decode()


def decrypt_connection_details(token: str) -> Dict[str, Any]:
    try:
        return json.loads(_fernet.decrypt(token.encode()).decode())
    except InvalidToken as e:
        raise ConnectionError_("Stored connection credentials could not be decrypted.") from e


# ---------------------------------------------------------------------------
# Connection spec normalization - accepts EITHER a raw connection string OR
# structured fields (host/port/username/password/database), whichever the
# caller filled in.
# ---------------------------------------------------------------------------

def build_connection_details(
    engine: str,
    connection_string: Optional[str] = None,
    host: Optional[str] = None,
    port: Optional[int] = None,
    username: Optional[str] = None,
    password: Optional[str] = None,
    database: Optional[str] = None,
) -> Dict[str, Any]:
    if engine not in ENGINES:
        raise ValueError(f"Unknown engine '{engine}'. Must be one of: {', '.join(ENGINES)}")

    if connection_string:
        return {"engine": engine, "connection_string": connection_string, "database": database or ""}

    if not all([host, username, database]):
        raise ValueError("Provide either a connection string, or at least host/username/database.")

    return {
        "engine": engine,
        "host": host,
        "port": port,
        "username": username,
        "password": password or "",
        "database": database,
    }


def _sqlalchemy_url(details: Dict[str, Any]) -> str:
    if details.get("connection_string"):
        return details["connection_string"]

    driver = _SQL_DIALECT_DRIVERS[details["engine"]]
    user = quote_plus(details["username"])
    pwd = quote_plus(details.get("password") or "")
    host = details["host"]
    port = details.get("port")
    port_part = f":{port}" if port else ""
    database = details["database"]
    return f"{driver}://{user}:{pwd}@{host}{port_part}/{database}"


def _mongo_uri(details: Dict[str, Any]) -> str:
    if details.get("connection_string"):
        return details["connection_string"]

    user = quote_plus(details["username"])
    pwd = quote_plus(details.get("password") or "")
    host = details["host"]
    port = details.get("port") or 27017
    return f"mongodb://{user}:{pwd}@{host}:{port}/{details['database']}"


def _run_with_timeout(fn, timeout_seconds: int):
    future = _query_executor.submit(fn)
    try:
        return future.result(timeout=timeout_seconds)
    except FutureTimeoutError:
        raise ConnectionError_(msg("db_query.timeout", seconds=timeout_seconds))


# ---------------------------------------------------------------------------
# SQL engines (Postgres / MySQL / SQL Server) via SQLAlchemy
#
# Schema-awareness (Postgres/SQL Server only): a schema there is a real
# sub-division *within* the one database this connection is scoped to, so it's
# safe to enumerate and expose. MySQL conflates "schema" with "database" -
# get_schema_names() on MySQL would return the names of other databases
# entirely outside this connection's own `database` field, which would leak
# past the scoping every other engine respects here. MySQL tables are
# therefore never schema-qualified; Postgres/SQL Server tables are, whenever
# more than one user-facing schema actually exists.
# ---------------------------------------------------------------------------

def _sql_engine(details: Dict[str, Any]):
    url = _sqlalchemy_url(details)
    return sqlalchemy.create_engine(url, pool_pre_ping=True, pool_recycle=300)


_SCHEMA_AWARE_ENGINES = {"postgresql", "mssql"}

_SYSTEM_SCHEMAS = {
    "postgresql": {"pg_catalog", "information_schema", "pg_toast"},
    "mssql": {
        "sys", "information_schema", "guest",
        "db_accessadmin", "db_backupoperator", "db_datareader", "db_datawriter",
        "db_ddladmin", "db_denydatareader", "db_denydatawriter", "db_owner", "db_securityadmin",
    },
}


def _sql_user_schemas(engine_name: str, inspector: "sqlalchemy.engine.reflection.Inspector") -> List[str]:
    system = _SYSTEM_SCHEMAS.get(engine_name, set())
    return [s for s in inspector.get_schema_names() if s not in system]


def _split_schema(engine_name: str, table_name: str) -> Tuple[Optional[str], str]:
    '''Splits a "schema.table" name (as returned by _sql_list_tables) back into its
    parts for describe_table/get_columns. MySQL table names are never
    schema-qualified in the first place, so a dot there is just part of an
    (unusual but legal) table name, not a schema separator.'''
    if engine_name in _SCHEMA_AWARE_ENGINES and "." in table_name:
        schema, _, name = table_name.partition(".")
        return schema, name
    return None, table_name


def _sql_list_tables(details: Dict[str, Any]) -> List[str]:
    try:
        engine = _sql_engine(details)
        inspector = sqlalchemy.inspect(engine)
        engine_name = details["engine"]

        if engine_name not in _SCHEMA_AWARE_ENGINES:
            return inspector.get_table_names()

        schemas = _sql_user_schemas(engine_name, inspector)
        if len(schemas) <= 1:
            # Only one user-facing schema (the common case) - bare names, same
            # output shape as before schema-awareness existed.
            return inspector.get_table_names(schema=schemas[0] if schemas else None)

        return [
            f"{schema}.{table}"
            for schema in schemas
            for table in inspector.get_table_names(schema=schema)
        ]
    except SQLAlchemyError as e:
        raise ConnectionError_(f"Could not list tables: {e}") from e


def _sql_describe_table(details: Dict[str, Any], table_name: str) -> List[Dict[str, str]]:
    try:
        engine_name = details["engine"]
        schema, name = _split_schema(engine_name, table_name)
        engine = _sql_engine(details)
        columns = sqlalchemy.inspect(engine).get_columns(name, schema=schema)
        return [{"name": c["name"], "type": str(c["type"])} for c in columns]
    except SQLAlchemyError as e:
        raise ConnectionError_(f"Could not describe table '{table_name}': {e}") from e


def _assert_read_only_sql(sql: str) -> None:
    stripped = sql.strip().rstrip(";")
    if ";" in stripped:
        raise ConnectionError_(msg("db_query.multi_statement"))
    if not re.match(r"^\s*(SELECT|WITH)\b", stripped, re.IGNORECASE):
        raise ConnectionError_(msg("db_query.not_select"))
    if _WRITE_KEYWORDS_RE.search(stripped):
        raise ConnectionError_(msg("db_query.write_keyword"))


def _sql_run_query(details: Dict[str, Any], sql: str) -> Dict[str, Any]:
    _assert_read_only_sql(sql)
    row_limit = config.DB_QUERY_ROW_LIMIT

    def _execute():
        engine = _sql_engine(details)
        with engine.connect() as connection:
            # Belt-and-suspenders beyond the keyword check above, where the
            # dialect supports it - Postgres rejects any write inside a
            # READ ONLY transaction at the database level, not just app-level
            # string matching.
            if details["engine"] == "postgresql":
                connection = connection.execution_options(postgresql_readonly=True)
            result = connection.exec_driver_sql(sql)
            columns = list(result.keys())
            rows = []
            for i, row in enumerate(result):
                if i >= row_limit:
                    return {"columns": columns, "rows": rows, "truncated": True}
                rows.append([str(v) if v is not None else None for v in row])
            return {"columns": columns, "rows": rows, "truncated": False}

    try:
        return _run_with_timeout(_execute, config.DB_QUERY_TIMEOUT_SECONDS)
    except SQLAlchemyError as e:
        raise ConnectionError_(f"Query failed: {e}") from e


# ---------------------------------------------------------------------------
# MongoDB - structurally read-only (find/aggregate/count only, no write
# methods are ever called from this module).
# ---------------------------------------------------------------------------

def _mongo_client(details: Dict[str, Any]) -> MongoClient:
    return MongoClient(_mongo_uri(details), serverSelectionTimeoutMS=5000)


def _mongo_database_name(details: Dict[str, Any]) -> str:
    if details.get("database"):
        return details["database"]
    # Fall back to whatever database the connection string itself names.
    return MongoClient(_mongo_uri(details)).get_default_database().name


def _mongo_list_tables(details: Dict[str, Any]) -> List[str]:
    try:
        client = _mongo_client(details)
        return client[_mongo_database_name(details)].list_collection_names()
    except PyMongoError as e:
        raise ConnectionError_(f"Could not list collections: {e}") from e


def _mongo_describe_table(details: Dict[str, Any], collection_name: str) -> List[Dict[str, str]]:
    try:
        client = _mongo_client(details)
        sample = client[_mongo_database_name(details)][collection_name].find_one()
        if sample is None:
            return []
        return [{"name": k, "type": type(v).__name__} for k, v in sample.items()]
    except PyMongoError as e:
        raise ConnectionError_(f"Could not describe collection '{collection_name}': {e}") from e


def _mongo_run_query(details: Dict[str, Any], collection: str, filter: Optional[Dict] = None, projection: Optional[Dict] = None) -> Dict[str, Any]:
    row_limit = config.DB_QUERY_ROW_LIMIT

    def _execute():
        client = _mongo_client(details)
        cursor = client[_mongo_database_name(details)][collection].find(filter or {}, projection).limit(row_limit + 1)
        docs = [json.loads(json.dumps(doc, default=str)) for doc in cursor]
        truncated = len(docs) > row_limit
        return {"documents": docs[:row_limit], "truncated": truncated}

    try:
        return _run_with_timeout(_execute, config.DB_QUERY_TIMEOUT_SECONDS)
    except PyMongoError as e:
        raise ConnectionError_(f"Query failed: {e}") from e


# ---------------------------------------------------------------------------
# Engine-dispatching public API
# ---------------------------------------------------------------------------

def test_connection(details: Dict[str, Any]) -> List[str]:
    '''Connects and lists tables/collections - used both to validate a connection
    before saving it and as the agent's list_tables tool. Raises ConnectionError_
    on any failure.'''
    return list_tables(details)


def list_tables(details: Dict[str, Any]) -> List[str]:
    if details["engine"] == "mongodb":
        return _mongo_list_tables(details)
    return _sql_list_tables(details)


def describe_table(details: Dict[str, Any], table_name: str) -> List[Dict[str, str]]:
    if details["engine"] == "mongodb":
        return _mongo_describe_table(details, table_name)
    return _sql_describe_table(details, table_name)


def run_query(details: Dict[str, Any], **kwargs) -> Dict[str, Any]:
    '''kwargs shape differs by engine - {"sql": "..."} for the 3 SQL engines,
    {"collection": ..., "filter": ..., "projection": ...} for MongoDB. See
    db_agent.py's per-engine tool schema for what the model is actually asked
    to supply.'''
    if details["engine"] == "mongodb":
        return _mongo_run_query(details, kwargs.get("collection"), kwargs.get("filter"), kwargs.get("projection"))
    return _sql_run_query(details, kwargs.get("sql", ""))
