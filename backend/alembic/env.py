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

# Model MetaData object for 'autogenerate' support
target_metadata = Base.metadata


def compare_server_default(
    context,
    inspected_column,
    metadata_column,
    inspected_default,
    metadata_default,
    rendered_metadata_default,
):
    """Normalize and reconcile semantic equivalents for MySQL/TiDB server defaults.

    In MySQL 8 and TiDB Cloud, NOW() and CURRENT_TIMESTAMP are exact functional
    synonyms for datetime initializers. When MySQL reflects a column, it frequently
    normalizes now() to CURRENT_TIMESTAMP or wraps expression defaults. This
    callback treats confirmed equivalent timestamp defaults as matching (returning
    False) ONLY when both columns are confirmed to be DATETIME- or TIMESTAMP-compatible
    types. For all other column types (integer, string, enum, etc.) or unconfirmed
    differences, it returns None to preserve strict Alembic drift detection.
    """
    dialect_name = (
        getattr(context.dialect, "name", "").lower()
        if context and getattr(context, "dialect", None)
        else ""
    )
    is_mysql_compatible = any(d in dialect_name for d in ("mysql", "mariadb", "tidb"))
    if not is_mysql_compatible:
        return None

    from sqlalchemy import types as sqltypes

    def _is_datetime_or_timestamp(col_or_dict) -> bool:
        if col_or_dict is None:
            return False
        col_type = getattr(col_or_dict, "type", None) or (
            col_or_dict.get("type") if isinstance(col_or_dict, dict) else None
        )
        if col_type is None:
            return False
        return isinstance(col_type, (sqltypes.DateTime, sqltypes.TIMESTAMP)) or getattr(
            col_type, "_type_affinity", None
        ) is sqltypes.DateTime

    # Fail-closed: BOTH inspected_column and metadata_column must independently pass
    # datetime / timestamp compatibility. If either is missing (None) or not a
    # datetime/timestamp type, return None to fall back to standard Alembic comparison.
    if not _is_datetime_or_timestamp(inspected_column) or not _is_datetime_or_timestamp(metadata_column):
        return None

    if inspected_default is not None and rendered_metadata_default is not None:
        import re

        def clean_default(val: str) -> str:
            v = str(val).strip().lower()
            while v.startswith("(") and v.endswith(")"):
                v = v[1:-1].strip()
            return re.sub(r"\(\)$", "", v).strip()

        clean_inspected = clean_default(inspected_default)
        clean_metadata = clean_default(rendered_metadata_default)

        # In MySQL and TiDB, 'now' and 'current_timestamp' are exact functional synonyms
        timestamp_synonyms = {"now", "current_timestamp"}
        if clean_inspected in timestamp_synonyms and clean_metadata in timestamp_synonyms:
            return False

    return None


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
        compare_server_default=compare_server_default,
    )

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
            compare_server_default=compare_server_default,
        )

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
