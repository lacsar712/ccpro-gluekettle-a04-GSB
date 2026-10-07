from sqlmodel import select

from app.db import get_session
from app.models import CookLog, Kettle, User, Workshop
from app.security import hash_password

# 种子里保留的那一锅“已出胶”，及其冷却架占用情况（零占用）。
SEEDED_DRAWN_CODE = "锅-3"


def seed_demo() -> None:
    with get_session() as session:
        admin = session.exec(select(User).where(User.username == "admin")).first()
        if admin is None:
            session.add(User(username="admin", password_hash=hash_password("123456"), role="admin"))
        else:
            admin.password_hash = hash_password("123456")
            admin.role = "admin"
        worker = session.exec(select(User).where(User.username == "worker")).first()
        if worker is None:
            session.add(User(username="worker", password_hash=hash_password("123456"), role="worker"))
        else:
            worker.password_hash = hash_password("123456")
            worker.role = "worker"

        shop = session.exec(select(Workshop)).first()
        if shop is not None:
            # 幂等规整：任意启动后种子库都恰好一锅“已出胶”。
            kettles = session.exec(select(Kettle).where(Kettle.workshop_id == shop.id)).all()
            drawn = [k for k in kettles if k.status == Kettle.STATUS_DRAWN]
            if len(drawn) > 1:
                keep = next(
                    (k for k in sorted(drawn, key=lambda x: x.bench) if k.code == SEEDED_DRAWN_CODE),
                    min(drawn, key=lambda x: x.bench),
                )
                for k in drawn:
                    if k.id != keep.id:
                        k.status = Kettle.STATUS_COLD
            session.commit()
            return

        shop = Workshop(name="骨巷熬胶坊", alley="西市骨巷")
        session.add(shop)
        session.flush()
        # 恰好一锅“已出胶”（锅-3），冷却架零占用。
        layout = [
            ("锅-1", Kettle.STATUS_BOILING, 0, 96.0),
            ("锅-2", Kettle.STATUS_COLD, 1, None),
            ("锅-3", Kettle.STATUS_DRAWN, 2, 102.0),
            ("锅-4", Kettle.STATUS_BOILING, 3, 82.0),
            ("锅-5", Kettle.STATUS_COLD, 4, None),
            ("锅-6", Kettle.STATUS_COLD, 5, None),
        ]
        for code, status, bench, peak in layout:
            kettle = Kettle(workshop_id=shop.id, code=code, status=status, bench=bench)
            session.add(kettle)
            session.flush()
            if peak is not None:
                session.add(CookLog(kettle_id=kettle.id, peak_temp_c=peak, operator="worker"))
        session.commit()
