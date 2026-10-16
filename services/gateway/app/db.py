import asyncio
import json

import asyncpg

from . import config

pool: asyncpg.Pool = None  # type: ignore

SCHEMA = """
create table if not exists users(id serial primary key, email text unique not null, name text,
  role text not null check (role in ('admin','member')), password_hash text, active boolean not null default true,
  created_at timestamptz default now());
create table if not exists invites(id serial primary key, token_hash text unique not null, email text not null, role text not null,
  expires_at timestamptz not null, used_at timestamptz, created_by int references users(id), created_at timestamptz default now());
create table if not exists api_keys(id serial primary key, user_id int not null references users(id) on delete cascade, name text not null,
  prefix text not null, key_hash text unique not null, created_at timestamptz default now(), last_used_at timestamptz, revoked_at timestamptz);
create table if not exists servers(id serial primary key, slug text unique not null, name text not null, url text not null,
  auth_type text not null default 'none', header_name text, secret_enc text, enabled boolean not null default true,
  status text not null default 'unknown', last_error text, last_checked_at timestamptz, tools jsonb not null default '[]',
  created_at timestamptz default now());
create table if not exists audit_log(id bigserial primary key, ts timestamptz not null default now(), user_id int, user_email text,
  source text, server_slug text, tool text, duration_ms int, status text, error text);
create index if not exists audit_ts on audit_log(ts desc);
"""


async def _init_conn(conn):
    await conn.set_type_codec("jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog")


async def init_db():
    global pool
    for attempt in range(1, 31):
        try:
            pool = await asyncpg.create_pool(config.DATABASE_URL, min_size=1, max_size=10, init=_init_conn)
            await pool.execute(SCHEMA)
            return
        except Exception as e:  # database still starting
            print(f"db not ready ({e}), retry {attempt}", flush=True)
            await asyncio.sleep(2)
    raise RuntimeError("database unavailable")


async def fetch(q, *a):
    return [dict(r) for r in await pool.fetch(q, *a)]


async def fetchrow(q, *a):
    r = await pool.fetchrow(q, *a)
    return dict(r) if r else None


async def execute(q, *a):
    return await pool.execute(q, *a)
