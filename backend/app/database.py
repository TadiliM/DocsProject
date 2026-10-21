import psycopg
from psycopg.rows import dict_row

from app.config import Settings


def get_connection(settings: Settings) -> psycopg.Connection:
    """Open a connection. Use it in a with block to commit or roll back and close."""
    try:
        return psycopg.connect(
            host=settings.postgres_host,
            port=settings.postgres_port,
            dbname=settings.postgres_db,
            user=settings.postgres_user,
            password=settings.postgres_password.get_secret_value(),
            connect_timeout=3,
            options="-c statement_timeout=5000",
            row_factory=dict_row,
        )
    except psycopg.OperationalError:
        # Hide driver traceback frames, which can include the plaintext password.
        raise psycopg.OperationalError(
            "Could not connect to PostgreSQL. Check database availability and settings."
        ) from None


def check_database(settings: Settings) -> bool:
    """Check connectivity, pgvector, and the two required tables."""
    with get_connection(settings) as connection:
        row = connection.execute(
            """
            SELECT
                EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')
                AND to_regclass('public.documents') IS NOT NULL
                AND to_regclass('public.chunks') IS NOT NULL AS ready
            """
        ).fetchone()
        return row["ready"]
