from app.task_progress import progress_percent, task_progress


def test_incomplete_task_never_rounds_up_to_one_hundred_percent() -> None:
    assert progress_percent(225261, 225627) == 99
    assert task_progress(225261, 225627, unit="symbol_session_cells") == {
        "completed": 225261,
        "total": 225627,
        "percent": 99,
        "unit": "symbol_session_cells",
    }


def test_complete_task_reports_one_hundred_percent() -> None:
    assert progress_percent(10, 10) == 100
    assert progress_percent(11, 10) == 100
    assert progress_percent(0, 0, fallback=37) == 37
