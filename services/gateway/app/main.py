import asyncio
from contextlib import asynccontextmanager

import bcrypt
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.routing import Route

from . import config, db
from .api import router
from .crypto import encrypt
from .mcp_endpoint import McpASGI, session_manager
from .upstream import health_loop


async def bootstrap():
    if not await db.fetchrow("select 1 from users where lower(email)=lower($1)", config.ADMIN_EMAIL):
        pw = (await asyncio.to_thread(bcrypt.hashpw, config.ADMIN_PASSWORD.encode(), bcrypt.gensalt())).decode()
        await db.execute("insert into users(email,name,role,password_hash) values($1,'Admin','admin',$2)", config.ADMIN_EMAIL, pw)
        print(f"created admin {config.ADMIN_EMAIL}", flush=True)
    # Seed the first upstream servers; the shared upstream token is stored encrypted like any other credential.
    for s in config.SEED_SERVERS:
        await db.execute(
            "insert into servers(slug,name,url,auth_type,secret_enc) values($1,$2,$3,$4,$5) on conflict (slug) do nothing",
            s["slug"], s["name"], s["url"], "bearer" if config.UPSTREAM_TOKEN else "none",
            encrypt(config.UPSTREAM_TOKEN) if config.UPSTREAM_TOKEN else None)


@asynccontextmanager
async def lifespan(_: FastAPI):
    await db.init_db()
    await bootstrap()
    async with session_manager.run():
        task = asyncio.create_task(health_loop())
        yield
        task.cancel()


app = FastAPI(title="Team MCP Gateway", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.include_router(router)
app.router.routes.append(Route("/mcp", endpoint=McpASGI()))  # raw ASGI route: no trailing-slash redirect


@app.get("/healthz")
async def healthz():
    return {"ok": True}


@app.exception_handler(HTTPException)
async def http_error(_: Request, exc: HTTPException):
    return JSONResponse({"error": exc.detail}, status_code=exc.status_code)


@app.exception_handler(Exception)
async def unhandled(_: Request, exc: Exception):
    print("unhandled error:", repr(exc), flush=True)
    return JSONResponse({"error": "Internal error"}, status_code=500)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=config.PORT, log_level="info")
