"""
db/connection.py
----------------
Async PostgreSQL connection pool using asyncpg.
Supports both a single DATABASE_URL (Supabase / hosted) and individual
environment variables for local setups.

.env for Supabase (recommended)
--------------------------------
DATABASE_URL=postgresql://postgres:<password>@db.<ref>.supabase.co:5432/postgres

.env for local PostgreSQL (fallback)
-------------------------------------
DB_HOST      e.g. localhost
DB_PORT      e.g. 5432
DB_NAME      e.g. gtm_uae
DB_USER      e.g. postgres
DB_PASSWORD  (your password)

Supabase requires SSL — ssl="require" is set automatically when
DATABASE_URL is present.
statement_cache_size=0 is required for Supabase transaction pooler
(pgbouncer in transaction mode does not support prepared statements).
"""

import os

import asyncpg
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Module-level pool — initialised once via init_pool() and reused across nodes
# ---------------------------------------------------------------------------
_pool: asyncpg.Pool | None = None


async def init_pool() -> asyncpg.Pool:
    """
    Create (or return the existing) asyncpg connection pool.

    Call this once at application startup (e.g., in main.py lifespan).
    All nodes then call get_pool() to borrow a connection.
    """
    global _pool
    if _pool is None:
        database_url = os.getenv("DATABASE_URL", "")

        if database_url:
            # Supabase / hosted PostgreSQL
            # statement_cache_size=0 required — pgbouncer transaction mode
            # does not support prepared statements
            _pool = await asyncpg.create_pool(
                dsn=database_url,
                ssl="require",
                min_size=1,
                max_size=int(os.getenv("DB_POOL_MAX_SIZE", "20")),
                statement_cache_size=0,
            )
        else:
            # Local PostgreSQL fallback
            _pool = await asyncpg.create_pool(
                host=os.getenv("DB_HOST", "localhost"),
                port=int(os.getenv("DB_PORT", "5432")),
                database=os.getenv("DB_NAME", "gtm_uae"),
                user=os.getenv("DB_USER", "postgres"),
                password=os.getenv("DB_PASSWORD", ""),
                min_size=1,
                max_size=int(os.getenv("DB_POOL_MAX_SIZE", "20")),
            )

    return _pool


async def get_pool() -> asyncpg.Pool:
    """Return the active pool, initialising it if necessary."""
    return await init_pool()


async def close_pool() -> None:
    """Gracefully close the connection pool. Call at shutdown."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None