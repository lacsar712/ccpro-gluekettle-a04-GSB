"""熬锅出胶门槛：最近一次煮胶峰值温度须 ≥ 90℃。

已出胶的锅要拨回冷锅，还须占用一个未释放的冷却架位（架位不影响出胶判定）。
"""

from app.models import Kettle, RackOccupancy

MIN_PEAK = 90.0


class RuleError(ValueError):
    pass


def latest_peak(kettle: Kettle) -> float | None:
    if not kettle.cooks:
        return None
    latest = max(kettle.cooks, key=lambda c: c.taken_at)
    return latest.peak_temp_c


def open_occupancy(kettle: Kettle) -> RackOccupancy | None:
    """该锅当前未释放的架位占用；至多一条（数据库另有唯一索引兜底）。"""
    for occ in (kettle.occupancies or []):
        if occ.released_at is None:
            return occ
    return None


def assert_can_set_status(kettle: Kettle, new_status: str) -> None:
    allowed = {Kettle.STATUS_COLD, Kettle.STATUS_BOILING, Kettle.STATUS_DRAWN}
    if new_status not in allowed:
        raise RuleError(f"无效状态：{new_status}")
    # 已出胶拨回冷锅：必须先占用一个未释放的冷却架位。
    if new_status == Kettle.STATUS_COLD and kettle.status == Kettle.STATUS_DRAWN:
        if open_occupancy(kettle) is None:
            raise RuleError("该锅已出胶，须先在冷却架占用一个架位，才能拨回冷锅")
    if new_status != Kettle.STATUS_DRAWN:
        return
    peak = latest_peak(kettle)
    if peak is None:
        raise RuleError("该锅尚无煮胶峰值，不能出胶")
    if peak < MIN_PEAK:
        raise RuleError(f"最近峰值 {peak}℃ 低于 {MIN_PEAK:.0f}℃，不能出胶")
