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
from app.domain import RuleError, assert_can_set_status, latest_peak, open_occupancy
from app.models import CookLog, Kettle, RackOccupancy, User, Workshop, utcnow
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
        .options(selectinload(Kettle.cooks), selectinload(Kettle.occupancies))
    ).first()


def kettle_json(kettle: Kettle) -> dict:
    occ = open_occupancy(kettle)
    return {
        "id": kettle.id,
        "code": kettle.code,
        "status": kettle.status,
        "bench": kettle.bench,
        "latestPeakC": latest_peak(kettle),
        "cookCount": len(kettle.cooks or []),
        "rackSlotNo": occ.slot_no if occ else None,
    }


def occupancy_json(occ: RackOccupancy, code_by_id: dict[int, str]) -> dict:
    return {
        "id": occ.id,
        "kettleId": occ.kettle_id,
        "kettleCode": code_by_id.get(occ.kettle_id, str(occ.kettle_id)),
        "slotNo": occ.slot_no,
        "occupiedAt": occ.occupied_at.isoformat() if occ.occupied_at else None,
        "occupiedBy": occ.occupied_by,
        "releasedAt": occ.released_at.isoformat() if occ.released_at else None,
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
            .options(selectinload(Kettle.cooks), selectinload(Kettle.occupancies))
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


async def rack_list(request: Request):
    user = await current_user(request)
    if user is None:
        return JSONResponse({"detail": "未登录"}, status_code=401)
    kettle_id = request.query_params.get("kettle_id")
    with get_session() as session:
        stmt = select(RackOccupancy).where(RackOccupancy.released_at.is_(None))
        if kettle_id:
            try:
                stmt = stmt.where(RackOccupancy.kettle_id == int(kettle_id))
            except ValueError:
                return JSONResponse({"detail": "锅号无效"}, status_code=400)
        occs = session.exec(stmt).all()
        codes = session.exec(select(Kettle.id, Kettle.code)).all()
        code_by_id = {kid: code for kid, code in codes}
        return JSONResponse(
            {
                "slotMin": RackOccupancy.RACK_MIN_SLOT,
                "slotMax": RackOccupancy.RACK_MAX_SLOT,
                "occupations": [occupancy_json(o, code_by_id) for o in sorted(occs, key=lambda x: x.slot_no)],
            }
        )


def _conflict_message(exc: IntegrityError) -> str:
    """依据触发的部分唯一索引给出中文撞车/重复提示。"""
    orig = getattr(exc, "orig", None)
    name = getattr(getattr(orig, "diag", None), "constraint_name", "") or ""
    if name == "uq_rack_kettle_open":
        return "该锅已占用一个未释放架位，不能重复占位"
    return f"架位号已被别的锅占用（撞车），请换一个架位号"


async def rack_occupy(request: Request):
    user = await current_user(request)
    if user is None:
        return JSONResponse({"detail": "未登录"}, status_code=401)
    body = await request.json()
    # 操作工（worker）与管理员均可占位。
    try:
        kettle_id = int(body.get("kettleId"))
        slot_no = int(body.get("slotNo"))
    except (TypeError, ValueError):
        return JSONResponse({"detail": "锅号与架位号必须是整数"}, status_code=400)
    if not (RackOccupancy.RACK_MIN_SLOT <= slot_no <= RackOccupancy.RACK_MAX_SLOT):
        return JSONResponse(
            {"detail": f"架位号须为 {RackOccupancy.RACK_MIN_SLOT} 到 {RackOccupancy.RACK_MAX_SLOT} 的正整数"},
            status_code=400,
        )
    with get_session() as session:
        kettle = load_kettle(session, kettle_id)
        if kettle is None:
            return JSONResponse({"detail": "锅不存在"}, status_code=404)
        if kettle.status != Kettle.STATUS_DRAWN:
            return JSONResponse({"detail": "仅已出胶的锅可占用冷却架位"}, status_code=400)
        if open_occupancy(kettle) is not None:
            return JSONResponse({"detail": "该锅已占用一个未释放架位，不能重复占位"}, status_code=400)
        clash = session.exec(
            select(RackOccupancy).where(
                RackOccupancy.slot_no == slot_no, RackOccupancy.released_at.is_(None)
            )
        ).first()
        if clash is not None:
            return JSONResponse({"detail": f"架位 {slot_no} 号已被别的锅占用（撞车），请换一个架位号"}, status_code=400)
        occ = RackOccupancy(kettle_id=kettle.id, slot_no=slot_no, occupied_by=user.username)
        session.add(occ)
        try:
            session.commit()
        except IntegrityError as exc:
            # 两名司炉几乎同时抢同一号：数据库部分唯一索引只放行一条。
            session.rollback()
            return JSONResponse({"detail": _conflict_message(exc)}, status_code=409)
        session.refresh(occ)
        codes = session.exec(select(Kettle.id, Kettle.code)).all()
        code_by_id = {kid: code for kid, code in codes}
        return JSONResponse(occupancy_json(occ, code_by_id), status_code=201)


async def rack_release(request: Request):
    user = await current_user(request)
    if user is None:
        return JSONResponse({"detail": "未登录"}, status_code=401)
    # 释放只给管理员。
    if user.role != "admin":
        return JSONResponse({"detail": "只有管理员能释放架位"}, status_code=403)
    occ_id = int(request.path_params["occ_id"])
    with get_session() as session:
        occ = session.exec(select(RackOccupancy).where(RackOccupancy.id == occ_id)).first()
        if occ is None:
            return JSONResponse({"detail": "占用记录不存在"}, status_code=404)
        if occ.released_at is not None:
            return JSONResponse({"detail": "该架位占用已释放"}, status_code=400)
        occ.released_at = utcnow()
        occ.released_by = user.username
        session.add(occ)
        session.commit()
        session.refresh(occ)
        codes = session.exec(select(Kettle.id, Kettle.code)).all()
        code_by_id = {kid: code for kid, code in codes}
        return JSONResponse(occupancy_json(occ, code_by_id))


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
        Route("/api/rack", rack_list),
        Route("/api/rack/occupations", rack_occupy, methods=["POST"]),
        Route("/api/rack/occupations/{occ_id:int}/release", rack_release, methods=["POST"]),
        Route("/api/kettles/{kettle_id:int}/cooks", add_cook, methods=["POST"]),
        Route("/api/kettles/{kettle_id:int}/status", set_status, methods=["POST"]),
    ],
    middleware=[Middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])],
)
