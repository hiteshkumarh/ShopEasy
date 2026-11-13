import os
import sys
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

# Ensure backend root directory is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Import Base, models, and connection helpers so metadata and TLS options are populated
from app.core.database import Base, DATABASE_URL, get_database_url, get_ssl_connect_args
import app.models  # noqa: F401 - ensures all 16 models are imported

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
try:
    config = context.config
except (AttributeError, NameError):
    config = None

if config is not None:
    # ConfigParser uses '%' for interpolation. SQLAlchemy URLs can contain
    # percent-encoded credentials (for example, %40 for '@'), so escape percent
    # signs only while storing the value in Alembic's ConfigParser. The online
    # configuration below receives the original URL directly.
    config.set_main_option("sqlalchemy.url", DATABASE_URL.replace("%", "%%"))

    # Interpret the config file for Python logging.
    if config.config_file_name is not None:
        fileConfig(config.config_file_name)

from contextlib import contextmanager
import re
import threading
from alembic.ddl.mysql import MySQLImpl
from sqlalchemy import types as sqltypes

# Model MetaData object for 'autogenerate' support
target_metadata = Base.metadata

_PATCH_LOCK = threading.RLock()
_PATCH_DEPTH = 0
_BASE_MYSQL_COMPARE_SERVER_DEFAULT = getattr(
    MySQLImpl, "_unwrapped_compare_server_default", MySQLImpl.compare_server_default
)
_ORIG_MYSQL_COMPARE_SERVER_DEFAULT = None


def _is_datetime_or_timestamp(col) -> bool:
    if col is None:
        return False
    col_type = getattr(col, "type", None) or (
        col.get("type") if isinstance(col, dict) else None
    )
    if col_type is None:
        return False
    return isinstance(col_type, (sqltypes.DateTime, sqltypes.TIMESTAMP)) or getattr(
        col_type, "_type_affinity", None
    ) is sqltypes.DateTime


def _clean_default(val: str) -> str:
    if val is None:
        return ""
    v = str(val).strip().lower()
    while v.startswith("(") and v.endswith(")"):
        v = v[1:-1].strip()
    return re.sub(r"\(\)$", "", v).strip()


def _mysql_compare_server_default(
    self,
    inspector_column,
    metadata_column,
    rendered_metadata_default,
    rendered_inspector_default,
):
    """Normalize and reconcile semantic equivalents for MySQL/TiDB timestamp defaults.

    In MySQL 8 and TiDB Cloud, NOW() and CURRENT_TIMESTAMP are exact functional
    synonyms for datetime initializers. When MySQL reflects a column, it frequently
    normalizes now() to CURRENT_TIMESTAMP or wraps expression defaults. This
    wrapper treats confirmed equivalent timestamp defaults as matching (returning
    False) ONLY when both columns are confirmed to be DATETIME- or TIMESTAMP-compatible
    types and no ON UPDATE differences exist. For all other column types or unconfirmed
    differences, it delegates to the original MySQL comparator to preserve strict
    Alembic drift detection.
    """
    orig_compare = getattr(
        MySQLImpl,
        "_unwrapped_compare_server_default",
        _ORIG_MYSQL_COMPARE_SERVER_DEFAULT or _BASE_MYSQL_COMPARE_SERVER_DEFAULT,
    )

    if _is_datetime_or_timestamp(inspector_column) and _is_datetime_or_timestamp(metadata_column):
        clean_ins = _clean_default(rendered_inspector_default)
        clean_met = _clean_default(rendered_metadata_default)
        timestamp_synonyms = {"now", "current_timestamp"}
        if clean_ins in timestamp_synonyms and clean_met in timestamp_synonyms:
            ins_lower = str(rendered_inspector_default or "").lower()
            met_lower = str(rendered_metadata_default or "").lower()
            has_ins_onupdate = "on update" in ins_lower
            has_met_onupdate = "on update" in met_lower
            if has_ins_onupdate == has_met_onupdate:
                return False

    return orig_compare(
        self,
        inspector_column,
        metadata_column,
        rendered_metadata_default,
        rendered_inspector_default,
    )


@contextmanager
def scoped_mysql_compare_server_default():
    """Temporarily scope the timestamp normalization wrapper to migration execution.

    Why this approach is necessary:
    In Alembic (including 1.20.1), passing `compare_server_default` to `context.configure()`
    causes Alembic's `_user_compare_server_default` comparator to execute on every column
    with priority FIRST. For reflected computed columns (e.g. `beneficiary_queue.active_flag`),
    MySQL reflection produces a `Computed` object which lacks `.arg`, triggering
    `AttributeError: 'Computed' object has no attribute 'arg'` on line 197 of
    `alembic/autogenerate/compare/server_defaults.py`.

    By NOT passing `compare_server_default` to `context.configure()`, Alembic's built-in
    `_compare_computed_default` handles computed columns natively without error.
    This context manager wraps `MySQLImpl.compare_server_default` strictly during migration
    and schema-comparison execution, reconciling MySQL/TiDB timestamp synonyms
    (`now()` vs `CURRENT_TIMESTAMP`) at the dialect level, and restores the original
    unwrapped comparator in a finally block.

    Concurrency & Scope Behavior:
    `MySQLImpl.compare_server_default` is a class-level method on `alembic.ddl.mysql.MySQLImpl`.
    Class attributes in Python are process-global across all threads.
    1. Callers of `scoped_mysql_compare_server_default()` are serialized safely using an
       internal re-entrant lock (`_PATCH_LOCK`). Nested invocations on the same thread are
       tracked with depth counter `_PATCH_DEPTH`.
    2. Concurrent observation: If another thread executes Alembic autogenerate comparisons or
       migrations concurrently WITHOUT acquiring `scoped_mysql_compare_server_default()`, that
       thread could observe the patched `_mysql_compare_server_default` comparator while this
       scope is active.
    3. Limitation: `_PATCH_LOCK` serializes callers of this context manager, but cannot protect
       unrelated code or concurrent threads that invoke Alembic directly without acquiring this
       lock. Complete thread isolation for class-level patches is not possible in CPython
       without modifying Alembic internals. In standard Alembic CLI and CI migration workflows,
       migrations execute sequentially in a single process.
    4. Clean cleanup: When the outermost scope exits (`_PATCH_DEPTH == 0`), the original comparator
       is restored and temporary attribute `_unwrapped_compare_server_default` is deleted from
       `MySQLImpl`, leaving no stale wrapper or leftover attributes on the class.
    """
    global _PATCH_DEPTH, _ORIG_MYSQL_COMPARE_SERVER_DEFAULT
    with _PATCH_LOCK:
        if _PATCH_DEPTH == 0:
            _ORIG_MYSQL_COMPARE_SERVER_DEFAULT = getattr(
                MySQLImpl,
                "_unwrapped_compare_server_default",
                MySQLImpl.compare_server_default,
            )
            MySQLImpl._unwrapped_compare_server_default = _ORIG_MYSQL_COMPARE_SERVER_DEFAULT
            MySQLImpl.compare_server_default = _mysql_compare_server_default
        _PATCH_DEPTH += 1
        try:
            yield
        finally:
            _PATCH_DEPTH -= 1
            if _PATCH_DEPTH == 0:
                MySQLImpl.compare_server_default = _ORIG_MYSQL_COMPARE_SERVER_DEFAULT
                _ORIG_MYSQL_COMPARE_SERVER_DEFAULT = None
                if hasattr(MySQLImpl, "_unwrapped_compare_server_default"):
                    delattr(MySQLImpl, "_unwrapped_compare_server_default")


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well. By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.
    """
    url = config.get_main_option("sqlalchemy.url") if config else None
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with scoped_mysql_compare_server_default():
        with context.begin_transaction():
            context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.
    """
    configuration = config.get_section(config.config_ini_section, {}) if config else {}
    target_url = get_database_url()
    configuration["sqlalchemy.url"] = target_url

    ssl_args = get_ssl_connect_args(target_url)
    connect_args = dict(ssl_args) if ssl_args else {}
    if target_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        connect_args=connect_args,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )

        with scoped_mysql_compare_server_default():
            with context.begin_transaction():
                context.run_migrations()


try:
    is_offline = context.is_offline_mode()
except (AttributeError, NameError):
    is_offline = None

if is_offline is not None:
    if is_offline:
        run_migrations_offline()
    else:
        run_migrations_online()
