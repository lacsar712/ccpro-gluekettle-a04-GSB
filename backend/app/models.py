from datetime import datetime, timezone
from typing import ClassVar, Optional

from sqlalchemy import Index, text
from sqlmodel import Field, Relationship, SQLModel


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(SQLModel, table=True):
    __tablename__ = "users"

    id: Optional[int] = Field(default=None, primary_key=True)
    username: str = Field(unique=True, index=True)
    password_hash: str
    role: str = "worker"


class Workshop(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    alley: str = ""
    kettles: list["Kettle"] = Relationship(back_populates="workshop")


class Kettle(SQLModel, table=True):
    STATUS_COLD: ClassVar[str] = "cold"
    STATUS_BOILING: ClassVar[str] = "boiling"
    STATUS_DRAWN: ClassVar[str] = "drawn"

    id: Optional[int] = Field(default=None, primary_key=True)
    workshop_id: int = Field(foreign_key="workshop.id")
    code: str
    status: str = STATUS_COLD
    bench: int = 0
    workshop: Optional[Workshop] = Relationship(back_populates="kettles")
    cooks: list["CookLog"] = Relationship(back_populates="kettle")
    occupancies: list["RackOccupancy"] = Relationship(back_populates="kettle")


class CookLog(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    kettle_id: int = Field(foreign_key="kettle.id")
    taken_at: datetime = Field(default_factory=utcnow)
    peak_temp_c: float
    operator: str = ""
    kettle: Optional[Kettle] = Relationship(back_populates="cooks")


class RackOccupancy(SQLModel, table=True):
    """冷却架位占用。released_at 为空即“未释放”。

    两条硬约束（Postgres 部分唯一索引，由数据库兜底并发）：
      1. 同一架位号至多一条未释放占用 —— 别锅撞车禁止入库；
      2. 同一锅至多一条未释放占用。
    """

    RACK_MIN_SLOT: ClassVar[int] = 1
    RACK_MAX_SLOT: ClassVar[int] = 20

    __tablename__ = "rack_occupancies"
    __table_args__ = (
        Index(
            "uq_rack_slot_open",
            "slot_no",
            unique=True,
            postgresql_where=text("released_at IS NULL"),
        ),
        Index(
            "uq_rack_kettle_open",
            "kettle_id",
            unique=True,
            postgresql_where=text("released_at IS NULL"),
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    kettle_id: int = Field(foreign_key="kettle.id", index=True)
    slot_no: int
    occupied_at: datetime = Field(default_factory=utcnow)
    occupied_by: str = ""
    released_at: Optional[datetime] = Field(default=None, index=True)
    released_by: str = ""
    kettle: Optional[Kettle] = Relationship(back_populates="occupancies")
