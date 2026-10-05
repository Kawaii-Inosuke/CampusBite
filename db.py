"""The single database helper (TRD 4.2).

A small ThreadedConnectionPool (max 5 connections) is created lazily, once per
process, so it also works after Gunicorn forks its workers. `get_db()` is a
context manager: it commits on success, rolls back on error, and always hands
the connection back to the pool.
"""
import threading
from contextlib import contextmanager

import psycopg2
import psycopg2.extras
import psycopg2.pool

import config

MAX_CONN = 5

_pool = None
_pool_lock = threading.Lock()
# ThreadedConnectionPool raises an error when it is empty instead of waiting,
# so this semaphore makes extra threads wait for a free connection.
_slots = threading.BoundedSemaphore(MAX_CONN)


def _connect_kwargs():
    kwargs = {
        "dsn": config.DATABASE_URL,
        "connect_timeout": 10,
        # Keepalives stop the Supabase pooler from silently dropping idle connections.
        "keepalives": 1,
        "keepalives_idle": 30,
        "keepalives_interval": 10,
        "keepalives_count": 3,
    }
    # TRD: connect with sslmode=require. If the URL already sets sslmode
    # explicitly we respect it (e.g. sslmode=disable for a local test database).
    if "sslmode=" not in config.DATABASE_URL:
        kwargs["sslmode"] = "require"
    return kwargs


def _get_pool():
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                _pool = psycopg2.pool.ThreadedConnectionPool(1, MAX_CONN, **_connect_kwargs())
    return _pool


@contextmanager
def get_db():
    """Yield a connection inside one transaction; commit or roll back, then release it."""
    _slots.acquire()
    pool = None
    conn = None
    try:
        pool = _get_pool()
        conn = pool.getconn()
        if conn.closed:  # dropped by the server while idle: replace it
            pool.putconn(conn, close=True)
            conn = pool.getconn()
        try:
            yield conn
            conn.commit()
        except Exception:
            if not conn.closed:
                conn.rollback()
            raise
    finally:
        if conn is not None:
            # Close broken connections instead of returning them to the pool.
            pool.putconn(conn, close=bool(conn.closed))
        _slots.release()


def dict_cursor(conn):
    """Cursor that returns rows as dicts (row["name"] instead of row[1])."""
    return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
