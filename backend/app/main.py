from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from .config import MEDIA_ROOT, SESSION_SECRET_KEY

APP_DIR = Path(__file__).resolve().parent
from .database import Base, SessionLocal, engine
from .routers import admin, extension_api
from .routers.admin import ensure_default_admin

Base.metadata.create_all(bind=engine)

app = FastAPI(title="RI-LPR backend")

app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET_KEY)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/media", StaticFiles(directory=str(MEDIA_ROOT)), name="media")
app.mount("/admin/static", StaticFiles(directory=str(APP_DIR / "static")), name="admin-static")

app.include_router(extension_api.router)
app.include_router(admin.router)


@app.on_event("startup")
def on_startup():
    db = SessionLocal()
    try:
        ensure_default_admin(db)
    finally:
        db.close()


@app.get("/")
def root():
    return {"status": "ok", "service": "ri-lpr backend"}
