"""echo-memory init-db: create or upgrade the schema from the installed package.

`pip install echo-mem` ships the code, the CLI and all six migration scripts,
but not `alembic.ini` - that file lives at the repository root and is not
package data. So a pip-installed user had the migrations on disk and no
supported way to run them: `alembic upgrade head` finds no config, and pointing
`-c` at a file they do not have is not an instruction anyone can follow. The
published package could not create its own database.

This drives Alembic through its Python API against the migrations inside the
installed package, so the pip path works without a git clone. Running it from a
clone is equivalent to `alembic upgrade head`; there is deliberately no second
code path for the two cases.

It does NOT create the database or install the extensions. Apache AGE and
pgvector are server-side extensions that a client cannot conjure, so a missing
one is reported as the setup step it is rather than as a stack trace."""

from importlib import resources

from alembic import command
from alembic.config import Config as AlembicConfig

# Reported as setup instructions rather than tracebacks: each is a thing the
# user must do to their server, not a bug in this command.
_EXTENSION_HINTS = {
    "age": (
        "Apache AGE is not installed on this server. Echo Memory stores the graph "
        "in AGE, so it cannot run without it. The docker-compose.yml in the repo "
        "builds a Postgres image with AGE and pgvector already present:\n"
        "  docker compose up -d"
    ),
    "vector": (
        "pgvector is not installed on this server. Echo Memory stores embeddings "
        "in it. See docker-compose.yml, or install the extension on your Postgres."
    ),
}


def _config(database_url: str) -> AlembicConfig:
    """Point Alembic at the migrations inside the installed package rather than
    at a repo-relative path, which is what makes this work after a pip install."""
    migrations = resources.files("echo_memory") / "migrations"
    cfg = AlembicConfig()
    cfg.set_main_option("script_location", str(migrations))
    cfg.set_main_option("sqlalchemy.url", database_url)
    return cfg


def explain(error: Exception) -> str | None:
    """A setup instruction for a missing extension, or None if this error is
    something else and should surface as itself."""
    text = str(error).lower()
    for name, hint in _EXTENSION_HINTS.items():
        if f'extension "{name}"' in text or f"extension {name}" in text:
            return hint
    return None


def upgrade(database_url: str, revision: str = "head") -> None:
    command.upgrade(_config(database_url), revision)


def current(database_url: str) -> None:
    command.current(_config(database_url), verbose=True)
