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
    rack_occupancies: list["CoolingRack"] = Relationship(back_populates="kettle")


class CookLog(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    kettle_id: int = Field(foreign_key="kettle.id")
    taken_at: datetime = Field(default_factory=utcnow)
    peak_temp_c: float
    operator: str = ""
    kettle: Optional[Kettle] = Relationship(back_populates="cooks")


class CoolingRack(SQLModel, table=True):
    """冷却架占位：一条 = 某锅占用某架位号的一段区间（released_at 为空即未释放）。"""

    MIN_SLOT: ClassVar[int] = 1
    MAX_SLOT: ClassVar[int] = 20

    id: Optional[int] = Field(default=None, primary_key=True)
    kettle_id: int = Field(foreign_key="kettle.id")
    slot_no: int
    occupied_at: datetime = Field(default_factory=utcnow)
    occupied_by: str = ""
    released_at: Optional[datetime] = Field(default=None, index=True)
    kettle: Optional[Kettle] = Relationship(back_populates="rack_occupancies")

    __table_args__ = (
        # 架位号撞车：同一架位号，全坊只许有一条未释放占用（跨锅也撞）。
        Index(
            "uq_rack_open_slot",
            "slot_no",
            unique=True,
            postgresql_where=text("released_at IS NULL"),
            sqlite_where=text("released_at IS NULL"),
        ),
        # 同一锅未释放占用最多一条。
        Index(
            "uq_rack_open_kettle",
            "kettle_id",
            unique=True,
            postgresql_where=text("released_at IS NULL"),
            sqlite_where=text("released_at IS NULL"),
        ),
    )
