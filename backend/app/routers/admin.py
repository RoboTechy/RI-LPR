from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, Response, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from .. import models, relay_client
from ..config import DEFAULT_ADMIN_PASSWORD, DEFAULT_ADMIN_USERNAME, WORKER_INTERNAL_URL
from ..database import get_db
from ..jalali import to_jalali_str
from ..security import (
    ensure_camera_access,
    get_current_admin,
    hash_password,
    require_superuser,
    verify_password,
)
from ..settings import (
    LIGHT_MODES, get_auto_green_seconds, get_light_mode, set_auto_green_seconds, set_light_mode,
)
from .extension_api import plate_digits

router = APIRouter(prefix="/admin", tags=["admin"])

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.globals["jalali"] = to_jalali_str


def ensure_default_admin(db: Session):
    if db.query(models.AdminUser).count() == 0:
        db.add(
            models.AdminUser(
                username=DEFAULT_ADMIN_USERNAME,
                password_hash=hash_password(DEFAULT_ADMIN_PASSWORD),
                is_superuser=True,
            )
        )
        db.commit()


# ---------------------------------------------------------------- login ---

@router.get("/login")
def login_form(request: Request):
    return templates.TemplateResponse(request, "login.html", {"error": None})


@router.post("/login")
def login_submit(request: Request, username: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    user = db.query(models.AdminUser).filter(models.AdminUser.username == username).first()
    if not user or not verify_password(password, user.password_hash):
        return templates.TemplateResponse(
            request, "login.html", {"error": "نام کاربری یا رمز عبور اشتباه است"}
        )
    request.session["admin_user_id"] = user.id
    return RedirectResponse("/admin", status_code=303)


@router.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/admin/login", status_code=303)


# ------------------------------------------------------------ dashboard ---

@router.get("")
def dashboard(request: Request, db: Session = Depends(get_db), admin: models.AdminUser = Depends(get_current_admin)):
    camera_count = db.query(models.Camera).count()
    log_count = db.query(models.PermitLog).count()
    recent_logs = db.query(models.PermitLog).order_by(models.PermitLog.created_at.desc()).limit(10).all()
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "admin": admin,
            "camera_count": camera_count,
            "log_count": log_count,
            "recent_logs": recent_logs,
        },
    )


# --------------------------------------------------------------- cameras ---

def visible_cameras(db: Session, admin: models.AdminUser):
    if admin.is_superuser:
        return db.query(models.Camera).order_by(models.Camera.line_number).all()
    return sorted(admin.cameras, key=lambda c: c.line_number)


@router.get("/cameras")
def cameras_list(request: Request, db: Session = Depends(get_db), admin: models.AdminUser = Depends(get_current_admin)):
    # Light status is fetched by the page itself afterwards (see
    # cameras.html's own script, calling /admin/cameras/lights-status) -
    # NOT here. This route must render instantly regardless of whether
    # the Pi relay service is even reachable yet; blocking the whole
    # page load on it was exactly the few-seconds-every-time slowness
    # reported when the Pi wasn't set up.
    cameras = visible_cameras(db, admin)
    auto_green_seconds = get_auto_green_seconds(db)
    light_modes = {cam.line_number: get_light_mode(db, cam.line_number) for cam in cameras}
    return templates.TemplateResponse(
        request,
        "cameras.html",
        {"admin": admin, "cameras": cameras, "auto_green_seconds": auto_green_seconds, "light_modes": light_modes},
    )


@router.get("/cameras/lights-status")
def cameras_lights_status(admin: models.AdminUser = Depends(get_current_admin)):
    """Fetched asynchronously by cameras.html after the page has already
    rendered - see cameras_list() above for why this is separate."""
    return relay_client.get_all_lights()


@router.post("/settings/auto-green-seconds")
def update_auto_green_seconds(
    seconds: float = Form(...),
    db: Session = Depends(get_db),
    admin: models.AdminUser = Depends(require_superuser),
):
    """How long (seconds) a line's light stays green in AUTOMATIC mode,
    i.e. after a permit is saved for a truck on that line. The Pi turns
    it red again by itself when the time is up. Lines in MANUAL mode
    ignore this - their light is set by hand."""
    if seconds <= 0 or seconds > 3600:
        raise HTTPException(status_code=400, detail="مدت زمان باید بین ۱ تا ۳۶۰۰ ثانیه باشد")
    set_auto_green_seconds(db, seconds)
    return RedirectResponse("/admin/cameras", status_code=303)


@router.get("/cameras/new")
def camera_new_form(request: Request, admin: models.AdminUser = Depends(require_superuser)):
    return templates.TemplateResponse(
        request, "camera_form.html", {"admin": admin, "camera": None, "error": None}
    )


@router.post("/cameras/new")
def camera_new_submit(
    request: Request,
    name: str = Form(...),
    line_number: int = Form(...),
    rtsp_ip: str = Form(...),
    rtsp_port: int = Form(554),
    rtsp_username: str = Form(""),
    rtsp_password: str = Form(""),
    rtsp_path: str = Form("/Streaming/Channels/101"),
    rtsp_url_override: str = Form(""),
    is_active: str = Form(None),
    db: Session = Depends(get_db),
    admin: models.AdminUser = Depends(require_superuser),
):
    camera = models.Camera(
        name=name,
        line_number=line_number,
        rtsp_ip=rtsp_ip,
        rtsp_port=rtsp_port,
        rtsp_username=rtsp_username,
        rtsp_password=rtsp_password,
        rtsp_path=rtsp_path,
        rtsp_url_override=rtsp_url_override or None,
        is_active=bool(is_active),
    )
    db.add(camera)
    db.commit()
    return RedirectResponse("/admin/cameras", status_code=303)


@router.get("/cameras/{camera_id}/edit")
def camera_edit_form(
    camera_id: int, request: Request, db: Session = Depends(get_db), admin: models.AdminUser = Depends(require_superuser)
):
    camera = db.query(models.Camera).get(camera_id)
    return templates.TemplateResponse(
        request, "camera_form.html", {"admin": admin, "camera": camera, "error": None}
    )


@router.post("/cameras/{camera_id}/edit")
def camera_edit_submit(
    camera_id: int,
    name: str = Form(...),
    line_number: int = Form(...),
    rtsp_ip: str = Form(...),
    rtsp_port: int = Form(554),
    rtsp_username: str = Form(""),
    rtsp_password: str = Form(""),
    rtsp_path: str = Form("/Streaming/Channels/101"),
    rtsp_url_override: str = Form(""),
    is_active: str = Form(None),
    db: Session = Depends(get_db),
    admin: models.AdminUser = Depends(require_superuser),
):
    camera = db.query(models.Camera).get(camera_id)
    camera.name = name
    camera.line_number = line_number
    camera.rtsp_ip = rtsp_ip
    camera.rtsp_port = rtsp_port
    camera.rtsp_username = rtsp_username
    camera.rtsp_password = rtsp_password
    camera.rtsp_path = rtsp_path
    camera.rtsp_url_override = rtsp_url_override or None
    camera.is_active = bool(is_active)
    db.commit()
    return RedirectResponse("/admin/cameras", status_code=303)


@router.post("/cameras/{camera_id}/delete")
def camera_delete(
    camera_id: int, db: Session = Depends(get_db), admin: models.AdminUser = Depends(require_superuser)
):
    camera = db.query(models.Camera).get(camera_id)
    if camera:
        db.delete(camera)
        db.commit()
    return RedirectResponse("/admin/cameras", status_code=303)


@router.get("/cameras/{camera_id}/test")
def camera_test_view(
    camera_id: int, request: Request, db: Session = Depends(get_db), admin: models.AdminUser = Depends(get_current_admin)
):
    """Just the live stream + whatever the last test happened to show -
    no new detection test run (that's the POST below, triggered by the
    page's own button). Lets "پخش زنده" link straight here without
    forcing a detection run first."""
    camera = db.query(models.Camera).get(camera_id)
    ensure_camera_access(camera, admin)
    return templates.TemplateResponse(
        request, "camera_test.html", {"admin": admin, "camera": camera, "result": None}
    )


@router.post("/cameras/{camera_id}/test")
def camera_test(
    camera_id: int, request: Request, db: Session = Depends(get_db), admin: models.AdminUser = Depends(get_current_admin)
):
    camera = db.query(models.Camera).get(camera_id)
    ensure_camera_access(camera, admin)
    result = {"success": False, "error": "دوربین پیدا نشد"}
    if camera is not None:
        try:
            # the api container has none of the ML dependencies on
            # purpose (see backend/Dockerfile vs Dockerfile.worker) -
            # the worker container, which already has them, does the
            # actual connect + inference and we just call it.
            resp = httpx.post(f"{WORKER_INTERNAL_URL}/test-camera/{camera_id}", timeout=30)
            resp.raise_for_status()
            result = resp.json()
        except httpx.HTTPError as exc:
            result = {"success": False, "error": f"سرویس پردازش تصویر در دسترس نیست: {exc}"}

    return templates.TemplateResponse(
        request, "camera_test.html", {"admin": admin, "camera": camera, "result": result}
    )


@router.get("/cameras/{camera_id}/preview.jpg")
def camera_preview(camera_id: int, db: Session = Depends(get_db), admin: models.AdminUser = Depends(get_current_admin)):
    """One current frame of the live view. The page polls this a few times
    a second: short requests, so any number of open camera tabs fit within
    the browser's connection limit, and the picture comes from the
    connection the worker already holds for plate reading. 503 means that
    camera has no such connection - the page then uses /stream instead."""
    camera = db.query(models.Camera).get(camera_id)
    ensure_camera_access(camera, admin)
    db.close()
    try:
        resp = httpx.get(f"{WORKER_INTERNAL_URL}/preview/{camera_id}", timeout=3)
    except httpx.HTTPError:
        raise HTTPException(status_code=503, detail="worker unavailable")
    if resp.status_code != 200:
        raise HTTPException(status_code=503, detail="no live frame for this camera")
    return Response(content=resp.content, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@router.get("/cameras/{camera_id}/stream")
def camera_stream(camera_id: int, db: Session = Depends(get_db), admin: models.AdminUser = Depends(get_current_admin)):
    """Proxies the worker's raw MJPEG feed (see worker/test_server.py's
    stream_camera()) so the browser - which can't reach the worker
    container directly, only the Compose network can - gets a live
    <img> preview instead of the one-snapshot-per-click test result."""
    camera = db.query(models.Camera).get(camera_id)
    ensure_camera_access(camera, admin)
    # FastAPI keeps a request's DB session open until the response has
    # finished - for a stream that is as long as the tab stays open, one
    # pooled connection per open live view. Nothing below needs the DB.
    db.close()

    def proxy():
        with httpx.stream("GET", f"{WORKER_INTERNAL_URL}/stream-camera/{camera_id}", timeout=None) as resp:
            for chunk in resp.iter_bytes():
                yield chunk

    return StreamingResponse(proxy(), media_type="multipart/x-mixed-replace; boundary=frame")


@router.post("/cameras/{camera_id}/light-mode/{mode}")
def camera_light_mode_set(
    camera_id: int,
    mode: str,
    db: Session = Depends(get_db),
    admin: models.AdminUser = Depends(get_current_admin),
):
    """Puts a line's light in AUTOMATIC ("auto": a saved permit turns it
    green for the admin-set time) or MANUAL ("manual": only the green/red
    buttons below change it). Any account with access to this camera may
    switch it, like the buttons themselves. Going back to automatic turns
    the light red first, so a light left green by hand can't stay green
    forever."""
    camera = db.query(models.Camera).get(camera_id)
    ensure_camera_access(camera, admin)
    if mode not in LIGHT_MODES:
        raise HTTPException(status_code=400, detail="حالت نامعتبر است")
    if camera is not None:
        previous = get_light_mode(db, camera.line_number)
        set_light_mode(db, camera.line_number, mode)
        if mode == "auto" and previous != "auto":
            relay_client.set_light(camera.line_number, "red")
    return RedirectResponse("/admin/cameras", status_code=303)


@router.post("/cameras/{camera_id}/light/{color}")
def camera_light_set(
    camera_id: int,
    color: str,
    db: Session = Depends(get_db),
    admin: models.AdminUser = Depends(get_current_admin),
):
    """Manual control of a line's traffic light - for any logged-in
    account (admin or اوپراتور) with access to this camera. Only while the
    line is in MANUAL mode; green then stays on until red is pressed (no
    timer). In automatic mode the light follows saved permits and the
    configured time, and these buttons are refused."""
    camera = db.query(models.Camera).get(camera_id)
    ensure_camera_access(camera, admin)
    if color not in ("green", "red"):
        raise HTTPException(status_code=400, detail="رنگ نامعتبر است")
    if camera is not None:
        if get_light_mode(db, camera.line_number) != "manual":
            raise HTTPException(status_code=400, detail="این لاین روی حالت خودکار است - ابتدا آن را روی «دستی» بگذارید")
        if color == "green":
            relay_client.set_light(camera.line_number, "green", seconds=0)
        else:
            relay_client.set_light(camera.line_number, "red")
    return RedirectResponse("/admin/cameras", status_code=303)


# ----------------------------------------------------------------- users ---

@router.get("/users")
def users_list(request: Request, db: Session = Depends(get_db), admin: models.AdminUser = Depends(require_superuser)):
    users = db.query(models.AdminUser).order_by(models.AdminUser.username).all()
    return templates.TemplateResponse(request, "users.html", {"admin": admin, "users": users})


@router.get("/users/new")
def user_new_form(request: Request, db: Session = Depends(get_db), admin: models.AdminUser = Depends(require_superuser)):
    cameras = db.query(models.Camera).order_by(models.Camera.line_number).all()
    return templates.TemplateResponse(
        request, "user_form.html", {"admin": admin, "user": None, "cameras": cameras, "error": None}
    )


@router.post("/users/new")
def user_new_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    is_superuser: str = Form(None),
    camera_ids: list[int] = Form([]),
    db: Session = Depends(get_db),
    admin: models.AdminUser = Depends(require_superuser),
):
    user = models.AdminUser(username=username, password_hash=hash_password(password), is_superuser=bool(is_superuser))
    if camera_ids:
        user.cameras = db.query(models.Camera).filter(models.Camera.id.in_(camera_ids)).all()
    db.add(user)
    db.commit()
    return RedirectResponse("/admin/users", status_code=303)


@router.get("/users/{user_id}/edit")
def user_edit_form(
    user_id: int, request: Request, db: Session = Depends(get_db), admin: models.AdminUser = Depends(require_superuser)
):
    user = db.query(models.AdminUser).get(user_id)
    cameras = db.query(models.Camera).order_by(models.Camera.line_number).all()
    return templates.TemplateResponse(
        request, "user_form.html", {"admin": admin, "user": user, "cameras": cameras, "error": None}
    )


@router.post("/users/{user_id}/edit")
def user_edit_submit(
    user_id: int,
    username: str = Form(...),
    password: str = Form(""),
    is_superuser: str = Form(None),
    camera_ids: list[int] = Form([]),
    db: Session = Depends(get_db),
    admin: models.AdminUser = Depends(require_superuser),
):
    user = db.query(models.AdminUser).get(user_id)
    user.username = username
    if password:
        user.password_hash = hash_password(password)
    user.is_superuser = bool(is_superuser)
    user.cameras = db.query(models.Camera).filter(models.Camera.id.in_(camera_ids)).all() if camera_ids else []
    db.commit()
    return RedirectResponse("/admin/users", status_code=303)


@router.post("/users/{user_id}/delete")
def user_delete(user_id: int, db: Session = Depends(get_db), admin: models.AdminUser = Depends(require_superuser)):
    user = db.query(models.AdminUser).get(user_id)
    if user and user.id != admin.id:
        db.delete(user)
        db.commit()
    return RedirectResponse("/admin/users", status_code=303)


# ------------------------------------------------------------------ logs ---

@router.get("/logs")
def logs_list(
    request: Request,
    plate: str = "",
    page: int = 1,
    db: Session = Depends(get_db),
    admin: models.AdminUser = Depends(get_current_admin),
):
    page_size = 50
    query = db.query(models.PermitLog).order_by(models.PermitLog.created_at.desc())
    if plate:
        query = query.filter(models.PermitLog.plate.ilike(f"%{plate}%"))
    total = query.count()
    logs = query.offset((page - 1) * page_size).limit(page_size).all()
    return templates.TemplateResponse(
        request,
        "logs.html",
        {
            "admin": admin,
            "logs": logs,
            "plate_digits": plate_digits,
            "plate": plate,
            "page": page,
            "has_next": page * page_size < total,
            "has_prev": page > 1,
        },
    )
