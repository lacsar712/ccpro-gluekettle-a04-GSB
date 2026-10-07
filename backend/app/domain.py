"""熬锅出胶与冷却架门槛。

- 锅不可标「已出胶」，除非最近一次煮胶峰值 ≥ 90℃。
- 已出胶的锅要拨回「冷锅」，须先持有一条未释放的冷却架占位。
- 占位只发给「已出胶」的锅；架位号为 1..20；架位不参与已出胶判定。
"""

from app.models import CoolingRack, Kettle

MIN_PEAK = 90.0


class RuleError(ValueError):
    pass


def latest_peak(kettle: Kettle) -> float | None:
    if not kettle.cooks:
        return None
    latest = max(kettle.cooks, key=lambda c: c.taken_at)
    return latest.peak_temp_c


def parse_slot_no(value) -> int:
    """架位号必须是 1..20 的正整数。"""
    if isinstance(value, bool):
        raise RuleError(f"架位号须为 {CoolingRack.MIN_SLOT} 到 {CoolingRack.MAX_SLOT} 的正整数")
    try:
        if isinstance(value, str):
            value = value.strip()
        slot = int(value)
    except (TypeError, ValueError):
        raise RuleError(f"架位号须为 {CoolingRack.MIN_SLOT} 到 {CoolingRack.MAX_SLOT} 的正整数")
    if not (CoolingRack.MIN_SLOT <= slot <= CoolingRack.MAX_SLOT):
        raise RuleError(f"架位号须为 {CoolingRack.MIN_SLOT} 到 {CoolingRack.MAX_SLOT} 的正整数")
    return slot


def open_occupancy(kettle: Kettle) -> CoolingRack | None:
    """该锅当前未释放的架位占用；至多一条。"""
    for rack in kettle.rack_occupancies or []:
        if rack.released_at is None:
            return rack
    return None


def assert_can_occupy(kettle: Kettle, slot_no: int) -> None:
    if kettle.status != Kettle.STATUS_DRAWN:
        raise RuleError("只有已出胶的锅才能占用冷却架位")
    parse_slot_no(slot_no)


def assert_can_release(rack: CoolingRack) -> None:
    if rack.released_at is not None:
        raise RuleError("该架位占用已释放，不能重复释放")


def assert_can_set_status(kettle: Kettle, new_status: str) -> None:
    allowed = {Kettle.STATUS_COLD, Kettle.STATUS_BOILING, Kettle.STATUS_DRAWN}
    if new_status not in allowed:
        raise RuleError(f"无效状态：{new_status}")
    if new_status == Kettle.STATUS_DRAWN:
        # 架位不参与已出胶判定，只看最近峰值。
        peak = latest_peak(kettle)
        if peak is None:
            raise RuleError("该锅尚无煮胶峰值，不能出胶")
        if peak < MIN_PEAK:
            raise RuleError(f"最近峰值 {peak}℃ 低于 {MIN_PEAK:.0f}℃，不能出胶")
        return
    if new_status == Kettle.STATUS_COLD and kettle.status == Kettle.STATUS_DRAWN:
        # 已出胶拨回冷锅，必须占用一个未释放的冷却架位号。
        if open_occupancy(kettle) is None:
            raise RuleError("该锅尚未占用冷却架位，不能拨回冷锅")
