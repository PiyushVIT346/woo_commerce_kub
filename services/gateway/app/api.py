import asyncio
import re
import time

import bcrypt
import jwt
from asyncpg import UniqueViolationError
from fastapi import APIRouter, Depends, HTTPException, Request, Response

from . import config, db
from .chat import run_chat
from .core import SEP
from .crypto import encrypt, random_token, sha256
from .upstream import refresh_all, refresh_server

router = APIRouter(prefix="/api")
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,30}$")


async def body_of(request: Request) -> dict:
    try:
        data = await request.json()
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


async def session_user(request: Request) -> dict:
    token = request.cookies.get("session")
    if not token:
        raise HTTPException(401, "Not signed in")
    try:
        uid = jwt.decode(token, config.SESSION_SECRET, algorithms=["HS256"])["uid"]
    except Exception:
        raise HTTPException(401, "Not signed in")
    user = await db.fetchrow("select id,email,name,role from users where id=$1 and active", uid)
    if not user:
        raise HTTPException(401, "Not signed in")
    return user


async def admin_user(user: dict = Depends(session_user)) -> dict:
    if user["role"] != "admin":
        raise HTTPException(403, "Admins only")
    return user


async def _hash(pw: str) -> str:
    return (await asyncio.to_thread(bcrypt.hashpw, pw.encode(), bcrypt.gensalt())).decode()


# ---------------- auth ----------------
@router.post("/auth/login")
async def login(request: Request, response: Response):
    b = await body_of(request)
    u = await db.fetchrow("select * from users where lower(email)=lower($1) and active", str(b.get("email", "")))
    ok = bool(u and u["password_hash"]) and await asyncio.to_thread(bcrypt.checkpw, str(b.get("password", "")).encode(), u["password_hash"].encode())
    if not ok:
        raise HTTPException(401, "Wrong email or password")
    token = jwt.encode({"uid": u["id"], "exp": int(time.time()) + 12 * 3600}, config.SESSION_SECRET, algorithm="HS256")
    response.set_cookie("session", token, httponly=True, samesite="lax", secure=config.COOKIE_SECURE, max_age=12 * 3600)
    return {"id": u["id"], "email": u["email"], "name": u["name"], "role": u["role"]}


@router.post("/auth/logout")
async def logout(response: Response):
    response.delete_cookie("session")
    return {"ok": True}


@router.post("/auth/accept-invite")
async def accept_invite(request: Request):
    b = await body_of(request)
    token, password = b.get("token"), str(b.get("password") or "")
    if not token or len(password) < 8:
        raise HTTPException(400, "Token and a password of at least 8 characters are required")
    inv = await db.fetchrow("select * from invites where token_hash=$1 and used_at is null and expires_at>now()", sha256(str(token)))
    if not inv:
        raise HTTPException(400, "Invite is invalid or expired")
    await db.execute(
        "insert into users(email,name,role,password_hash) values($1,$2,$3,$4) "
        "on conflict (email) do update set password_hash=$4, name=$2, role=$3, active=true",
        inv["email"], b.get("name") or inv["email"], inv["role"], await _hash(password))
    await db.execute("update invites set used_at=now() where id=$1", inv["id"])
    return {"ok": True}


@router.get("/me")
async def me(user: dict = Depends(session_user)):
    return user


# ---------------- servers ----------------
def server_view(r: dict, is_admin: bool) -> dict:
    v = {"id": r["id"], "slug": r["slug"], "name": r["name"], "enabled": r["enabled"], "status": r["status"],
         "last_error": r["last_error"], "last_checked_at": r["last_checked_at"],
         "tools": [{"name": t["name"], "gateway_name": f"{r['slug']}{SEP}{t['name']}", "description": t.get("description")} for t in r["tools"]]}
    if is_admin:  # the credential itself is never returned, only whether one is set
        v.update(url=r["url"], auth_type=r["auth_type"], header_name=r["header_name"], has_credential=bool(r["secret_enc"]))
    return v


def check_auth(auth_type, header_name):
    if auth_type not in ("none", "bearer", "header"):
        raise HTTPException(400, "auth_type must be none, bearer or header")
    if auth_type == "header" and not header_name:
        raise HTTPException(400, "header_name is required for header auth")


@router.get("/servers")
async def list_servers(user: dict = Depends(session_user)):
    rows = await db.fetch("select * from servers order by id")
    return [server_view(r, user["role"] == "admin") for r in rows]


@router.post("/servers", status_code=201)
async def add_server(request: Request, _: dict = Depends(admin_user)):
    b = await body_of(request)
    if not SLUG.match(str(b.get("slug", ""))):
        raise HTTPException(400, "slug must be lowercase letters, digits and dashes")
    if not re.match(r"^https?://", str(b.get("url", ""))) or not b.get("name"):
        raise HTTPException(400, "name and an http(s) url are required")
    check_auth(b.get("auth_type", "none"), b.get("header_name"))
    try:
        row = await db.fetchrow(
            "insert into servers(slug,name,url,auth_type,header_name,secret_enc) values($1,$2,$3,$4,$5,$6) returning id",
            b["slug"], b["name"], b["url"], b.get("auth_type", "none"), b.get("header_name") or None, encrypt(b["secret"]) if b.get("secret") else None)
    except UniqueViolationError:
        raise HTTPException(409, "slug already exists")
    await refresh_server(row["id"])
    return {"id": row["id"]}


@router.patch("/servers/{server_id}")
async def edit_server(server_id: int, request: Request, _: dict = Depends(admin_user)):
    b = await body_of(request)
    cur = await db.fetchrow("select * from servers where id=$1", server_id)
    if not cur:
        raise HTTPException(404, "Not found")
    auth_type = b.get("auth_type") or cur["auth_type"]
    header_name = b.get("header_name") or cur["header_name"]
    check_auth(auth_type, header_name)
    secret = None if b.get("clear_secret") else (encrypt(b["secret"]) if b.get("secret") else cur["secret_enc"])
    await db.execute("update servers set name=$2,url=$3,auth_type=$4,header_name=$5,secret_enc=$6,enabled=$7 where id=$1",
                     server_id, b.get("name") or cur["name"], b.get("url") or cur["url"], auth_type,
                     header_name if auth_type == "header" else None, secret, b["enabled"] if "enabled" in b else cur["enabled"])
    await refresh_server(server_id)
    return {"ok": True}


@router.delete("/servers/{server_id}")
async def remove_server(server_id: int, _: dict = Depends(admin_user)):
    await db.execute("delete from servers where id=$1", server_id)
    return {"ok": True}


@router.post("/servers-refresh")
async def refresh(_: dict = Depends(admin_user)):
    await refresh_all()
    return {"ok": True}


# ---------------- members & invites ----------------
@router.get("/users")
async def users(_: dict = Depends(admin_user)):
    return await db.fetch("select id,email,name,role,active,created_at from users order by id")


@router.patch("/users/{uid}")
async def edit_user(uid: int, request: Request, me_: dict = Depends(admin_user)):
    b = await body_of(request)
    active, role = b.get("active"), b.get("role")
    if uid == me_["id"] and (active is False or (role and role != "admin")):
        raise HTTPException(400, "You cannot deactivate or demote yourself")
    if role and role not in ("admin", "member"):
        raise HTTPException(400, "invalid role")
    await db.execute("update users set active=coalesce($2,active), role=coalesce($3,role) where id=$1", uid, active, role)
    return {"ok": True}


@router.post("/invites", status_code=201)
async def invite(request: Request, admin: dict = Depends(admin_user)):
    b = await body_of(request)
    email = str(b.get("email", ""))
    if not re.match(r"^\S+@\S+\.\S+$", email):
        raise HTTPException(400, "valid email required")
    token = random_token(24)
    await db.execute("insert into invites(token_hash,email,role,expires_at,created_by) values($1,$2,$3,now()+interval '7 days',$4)",
                     sha256(token), email, "admin" if b.get("role") == "admin" else "member", admin["id"])
    return {"token": token, "expires_in_days": 7}  # shown once; only the hash is stored


# ---------------- API keys ----------------
@router.get("/keys")
async def keys(all: str = "", user: dict = Depends(session_user)):
    base = "select k.id,k.name,k.prefix,k.created_at,k.last_used_at,k.revoked_at,u.email as user_email from api_keys k join users u on u.id=k.user_id"
    if all == "1" and user["role"] == "admin":
        return await db.fetch(base + " order by k.id desc")
    return await db.fetch(base + " where k.user_id=$1 order by k.id desc", user["id"])


@router.post("/keys", status_code=201)
async def create_key(request: Request, user: dict = Depends(session_user)):
    b = await body_of(request)
    key = f"gw_{random_token(32)}"
    row = await db.fetchrow("insert into api_keys(user_id,name,prefix,key_hash) values($1,$2,$3,$4) returning id",
                            user["id"], str(b.get("name") or "My key")[:60], key[:10], sha256(key))
    return {"id": row["id"], "key": key}  # returned exactly once; only the SHA-256 is stored


@router.delete("/keys/{key_id}")
async def revoke_key(key_id: int, user: dict = Depends(session_user)):
    if user["role"] == "admin":
        res = await db.execute("update api_keys set revoked_at=now() where id=$1 and revoked_at is null", key_id)
    else:
        res = await db.execute("update api_keys set revoked_at=now() where id=$1 and revoked_at is null and user_id=$2", key_id, user["id"])
    return {"revoked": int(res.split()[-1])}


# ---------------- audit ----------------
@router.get("/audit")
async def audit(limit: int = 200, user: dict = Depends(session_user)):
    limit = max(1, min(limit, 1000))
    cols = "id,ts,user_email,source,server_slug,tool,duration_ms,status,error"
    if user["role"] == "admin":
        return await db.fetch(f"select {cols} from audit_log order by id desc limit $1", limit)
    return await db.fetch(f"select {cols} from audit_log where user_id=$2 order by id desc limit $1", limit, user["id"])


# ---------------- chat ----------------
@router.post("/chat")
async def chat(request: Request, user: dict = Depends(session_user)):
    b = await body_of(request)
    msgs = b.get("messages") if isinstance(b.get("messages"), list) else []
    try:
        return await run_chat(user, msgs[-30:])
    except Exception as e:
        raise HTTPException(502, str(e))
