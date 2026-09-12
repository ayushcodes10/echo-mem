"""Schema setup from an installed package.

`pip install echo-mem` ships the migrations but not `alembic.ini`, which lives
at the repository root and is not package data. A pip-installed user therefore
had the migration scripts on disk and no supported way to run them. These tests
pin the two things that make the pip path work: Alembic is pointed at the
migrations inside the package, and a missing server extension is reported as a
setup step rather than a traceback."""

from pathlib import Path

from echo_memory.cli import initdb

URL = "postgresql://postgres:postgres@localhost:5433/echo_memory"


def test_alembic_is_pointed_at_the_installed_package():
    """Not at a repo-relative path - that is the whole reason this exists."""
    location = Path(initdb._config(URL).get_main_option("script_location"))

    assert location.is_absolute()
    assert (location / "versions").is_dir()
    assert (location / "env.py").is_file()


def test_every_migration_is_reachable_from_the_package():
    location = Path(initdb._config(URL).get_main_option("script_location"))

    revisions = sorted(p.name[:4] for p in (location / "versions").glob("*.py"))

    assert revisions[0] == "0001"
    assert "0007" in revisions, "the newest migration must ship, not just the old ones"


def test_the_database_url_names_the_driver():
    """A bare postgresql:// makes SQLAlchemy reach for psycopg2, which nothing
    here depends on, so Alembic fails with ModuleNotFoundError - a message that
    reads as a broken install rather than a URL missing four characters. The
    rewrite used to live only in migrations/env.py, behind an environment
    variable the CLI always set and no other caller did: quickstart could not
    complete a single migration."""
    rewritten = initdb._config(URL).get_main_option("sqlalchemy.url")

    assert rewritten == URL.replace("postgresql://", "postgresql+psycopg://")


def test_a_url_that_already_names_a_driver_is_left_alone():
    """Somebody who passes postgresql+psycopg2:// has chosen a driver; turning
    it into postgresql+psycopg+psycopg2:// would be a URL nothing can parse."""
    explicit = "postgresql+psycopg2://postgres:postgres@localhost:5433/echo_memory"

    assert initdb.psycopg3_url(explicit) == explicit


def test_a_missing_age_extension_explains_the_setup_step():
    """AGE is server-side; a client cannot install it, so a stack trace here
    tells the user nothing they can act on."""
    hint = initdb.explain(Exception('could not open extension control file: extension "age"'))

    assert hint is not None
    assert "docker compose up -d" in hint


def test_a_missing_pgvector_extension_is_named_too():
    hint = initdb.explain(Exception('extension "vector" is not available'))

    assert hint is not None and "pgvector" in hint


def test_an_unrelated_error_is_not_explained_away():
    """Swallowing a real failure behind a friendly setup message would hide it."""
    assert initdb.explain(Exception("connection refused")) is None
    assert initdb.explain(Exception("password authentication failed")) is None
