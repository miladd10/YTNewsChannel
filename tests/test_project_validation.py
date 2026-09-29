import pytest
from fastapi import HTTPException

from app.main import _validate_project_date_range


def test_project_date_range_accepts_ordered_iso_dates():
    assert _validate_project_date_range("2026-09-21", "2026-09-28") == ("2026-09-21", "2026-09-28")


@pytest.mark.parametrize(
    "start,end",
    [
        ("2026-09-28", "2026-09-21"),
        ("2026-09-21", "2026-09-21"),
        ("not-a-date", "2026-09-28"),
    ],
)
def test_project_date_range_rejects_invalid_or_reversed_dates(start, end):
    with pytest.raises(HTTPException):
        _validate_project_date_range(start, end)


def test_project_date_range_rejects_excessive_windows():
    with pytest.raises(HTTPException):
        _validate_project_date_range("2026-01-01", "2026-04-01")
