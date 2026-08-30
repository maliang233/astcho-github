from datetime import datetime

from astcho.services.schedule import ScheduleService, _in_range


def test_cross_midnight_range():
    assert _in_range("23:30", "22:00", "06:00")
    assert _in_range("05:30", "22:00", "06:00")
    assert not _in_range("12:00", "22:00", "06:00")


def test_default_schedule(tmp_path):
    service = ScheduleService(tmp_path / "missing.json")
    assert service.current(datetime(2026, 1, 1, 12)).talk_value == 50

