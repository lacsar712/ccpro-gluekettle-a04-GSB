from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload
from sqlmodel import SQLModel, select

from app.db import engine, get_session
from app.domain import (
    RuleError,
    assert_can_occupy,
    assert_can_release,
    assert_can_set_status,
    latest_peak,
    open_occupancy,
    parse_slot_no,
)
from app.models import CoolingRack, CookLog, Kettle, User, Workshop, utcnow
from app.security import make_token, parse_token, verify_password
from app.seed import seed_demo


async def current_user(request: Request) -> User | None:
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        return None
    username = parse_token(header.split(" ", 1)[1])
    if not username:
        return None
    with get_session() as session:
        return session.exec(select(User).where(User.username == username)).first()


def load_kettle(session, kettle_id: int) -> Kettle | None:
    return session.exec(
        select(Kettle)
        .where(Kettle.id == kettle_id)
        .options(selectinload(Kettle.cooks), selectinload(Kettle.rack_occupancies))
    ).first()


def kettle_json(kettle: Kettle) -> dict:
    open_rack = open_occupancy(kettle)
    return {
        "id": kettle.id,
        "code": kettle.code,
        "status": kettle.status,
        "bench": kettle.bench,
        "latestPeakC": latest_peak(kettle),
        "cookCount": len(kettle.cooks or []),
        "rackSlotNo": open_rack.slot_no if open_rack else None,
    }


def rack_json(rack: CoolingRack, code: str | None = None) -> dict:
    return {
        "id": rack.id,
        "kettleId": rack.kettle_id,
        "kettleCode": code,
        "slotNo": rack.slot_no,
        "occupiedAt": rack.occupied_at.isoformat() if rack.occupied_at else None,
        "occupiedBy": rack.occupied_by,
        "releasedAt": rack.released_at.isoformat() if rack.released_at else None,
    }


async def health(request: Request):
    return JSONResponse({"status": "ok", "service": "GlueKettle"})


async def login(request: Request):
    body = await request.json()
    with get_session() as session:
        user = session.exec(select(User).where(User.username == body.get("username", ""))).first()
        if user is None or not verify_password(body.get("password", ""), user.password_hash):
            return JSONResponse({"detail": "用户名或密码错误"}, status_code=401)
        return JSONResponse(
            {"access_token": make_token(user.username), "user": {"username": user.username, "role": user.role}}
        )


async def me(request: Request):
    user = await current_user(request)
    if user is None:
        return JSONResponse({"detail": "未登录"}, status_code=401)
    return JSONResponse({"username": user.username, "role": user.role})


async def board(request: Request):
    user = await current_user(request)
    if user is None:
        return JSONResponse({"detail": "未登录"}, status_code=401)
    with get_session() as session:
        shop = session.exec(select(Workshop)).first()
        if shop is None:
            return JSONResponse({"detail": "尚无熬胶坊"}, status_code=404)
        kettles = session.exec(
            select(Kettle)
            .where(Kettle.workshop_id == shop.id)
            .options(selectinload(Kettle.cooks), selectinload(Kettle.rack_occupancies))
        ).all()
        loaded = sorted(kettles, key=lambda k: k.bench)
        return JSONResponse(
            {"workshop": shop.name, "alley": shop.alley, "kettles": [kettle_json(k) for k in loaded]}
        )


async def add_cook(request: Request):
    user = await current_user(request)
    if user is None:
        return JSONResponse({"detail": "未登录"}, status_code=401)
    kettle_id = int(request.path_params["kettle_id"])
    body = await request.json()
    try:
        peak = float(body.get("peakTempC"))
    except (TypeError, ValueError):
        return JSONResponse({"detail": "峰值温度必须是数字"}, status_code=400)
    with get_session() as session:
        kettle = load_kettle(session, kettle_id)
        if kettle is None:
            return JSONResponse({"detail": "锅不存在"}, status_code=404)
        session.add(CookLog(kettle_id=kettle.id, peak_temp_c=peak, operator=user.username))
        session.commit()
        kettle = load_kettle(session, kettle_id)
        return JSONResponse(kettle_json(kettle))


async def set_status(request: Request):
    user = await current_user(request)
    if user is None:
        return JSONResponse({"detail": "未登录"}, status_code=401)
    kettle_id = int(request.path_params["kettle_id"])
    body = await request.json()
    with get_session() as session:
        kettle = load_kettle(session, kettle_id)
        if kettle is None:
            return JSONResponse({"detail": "锅不存在"}, status_code=404)
        try:
            assert_can_set_status(kettle, body.get("status", ""))
        except RuleError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=400)
        kettle.status = body.get("status")
        session.add(kettle)
        session.commit()
        kettle = load_kettle(session, kettle_id)
        return JSONResponse(kettle_json(kettle))


async def list_rack(request: Request):
    user = await current_user(request)
    if user is None:
        return JSONResponse({"detail": "未登录"}, status_code=401)
    stmt = (
        select(CoolingRack, Kettle.code)
        .join(Kettle, CoolingRack.kettle_id == Kettle.id)
        .where(CoolingRack.released_at.is_(None))
        .order_by(CoolingRack.slot_no)
    )
    kettle_id = request.query_params.get("kettle_id")
    if kettle_id:
        try:
            stmt = stmt.where(CoolingRack.kettle_id == int(kettle_id))
        except ValueError:
            return JSONResponse({"detail": "锅编号无效"}, status_code=400)
    with get_session() as session:
        rows = session.exec(stmt).all()
        return JSONResponse({"racks": [rack_json(rack, code) for rack, code in rows]})


async def occupy_rack(request: Request):
    user = await current_user(request)
    if user is None:
        return JSONResponse({"detail": "未登录"}, status_code=401)
    body = await request.json()
    try:
        kettle_id = int(body.get("kettleId"))
    except (TypeError, ValueError):
        return JSONResponse({"detail": "锅编号无效"}, status_code=400)
    try:
        slot_no = parse_slot_no(body.get("slotNo"))
    except RuleError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    with get_session() as session:
        kettle = load_kettle(session, kettle_id)
        if kettle is None:
            return JSONResponse({"detail": "锅不存在"}, status_code=404)
        try:
            assert_can_occupy(kettle, slot_no)
        except RuleError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=400)
        rack = CoolingRack(kettle_id=kettle.id, slot_no=slot_no, occupied_by=user.username)
        session.add(rack)
        try:
            session.commit()
        except IntegrityError:
            # 并发抢号 / 同锅重复占位：唯一部分索引兜底，只许一条入库。
            session.rollback()
            other = session.exec(
                select(CoolingRack).where(
                    CoolingRack.slot_no == slot_no, CoolingRack.released_at.is_(None)
                )
            ).first()
            if other is not None and other.kettle_id != kettle_id:
                detail = f"架位号 {slot_no} 已被别的锅占用，换一个架位号"
            else:
                detail = "该锅已有未释放的架位占用，不能重复占位"
            return JSONResponse({"detail": detail}, status_code=409)
        session.refresh(rack)
        return JSONResponse(rack_json(rack, kettle.code), status_code=201)


async def release_rack(request: Request):
    user = await current_user(request)
    if user is None:
        return JSONResponse({"detail": "未登录"}, status_code=401)
    if user.role != "admin":
        return JSONResponse({"detail": "只有管理员能释放架位"}, status_code=403)
    rack_id = int(request.path_params["rack_id"])
    with get_session() as session:
        rack = session.exec(
            select(CoolingRack, Kettle.code)
            .join(Kettle, CoolingRack.kettle_id == Kettle.id)
            .where(CoolingRack.id == rack_id)
        ).first()
        if rack is None:
            return JSONResponse({"detail": "架位占用不存在"}, status_code=404)
        occupancy, code = rack
        try:
            assert_can_release(occupancy)
        except RuleError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=400)
        occupancy.released_at = utcnow()
        session.add(occupancy)
        session.commit()
        session.refresh(occupancy)
        return JSONResponse(rack_json(occupancy, code))


def init() -> None:
    SQLModel.metadata.create_all(engine)
    seed_demo()


init()

app = Starlette(
    routes=[
        Route("/api/health", health),
        Route("/api/auth/login", login, methods=["POST"]),
        Route("/api/auth/me", me),
        Route("/api/board", board),
        Route("/api/rack", list_rack),
        Route("/api/rack", occupy_rack, methods=["POST"]),
        Route("/api/rack/{rack_id:int}/release", release_rack, methods=["POST"]),
        Route("/api/kettles/{kettle_id:int}/cooks", add_cook, methods=["POST"]),
        Route("/api/kettles/{kettle_id:int}/status", set_status, methods=["POST"]),
    ],
    middleware=[Middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])],
)
