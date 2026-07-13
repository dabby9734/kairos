import pytest


def lesson(class_no, lesson_type, day, start, end, weeks=None, venue="COM1-0201"):
    return {
        "classNo": class_no,
        "lessonType": lesson_type,
        "day": day,
        "startTime": start,
        "endTime": end,
        "weeks": weeks if weeks is not None else list(range(1, 14)),
        "venue": venue,
    }


@pytest.fixture
def alpha_json():
    """ALPHA: one Mon+Wed lecture bundle; 3 tutorials, of which 02/03 share a footprint."""
    return {
        "moduleCode": "ALPHA",
        "semesterData": [
            {
                "semester": 1,
                "timetable": [
                    lesson("1", "Lecture", "Monday", "1000", "1200"),
                    lesson("1", "Lecture", "Wednesday", "1000", "1100"),
                    lesson("01", "Tutorial", "Monday", "1400", "1500"),
                    lesson("02", "Tutorial", "Tuesday", "0900", "1000"),
                    lesson("03", "Tutorial", "Tuesday", "0900", "1000", venue="COM1-0202"),
                ],
            }
        ],
    }


@pytest.fixture
def beta_json():
    """BETA: two lecture groups (group 1 online); two labs (L1 clashes ALPHA TUT 01)."""
    return {
        "moduleCode": "BETA",
        "semesterData": [
            {
                "semester": 1,
                "timetable": [
                    lesson("1", "Lecture", "Friday", "0800", "1000", venue="E-Learn_C"),
                    lesson("2", "Lecture", "Thursday", "1600", "1800"),
                    lesson("L1", "Laboratory", "Monday", "1400", "1600"),
                    lesson("L2", "Laboratory", "Friday", "1000", "1200"),
                ],
            }
        ],
    }


@pytest.fixture
def config():
    from optimiser.config import DEFAULT_PREFERENCES, Config, Preferences

    return Config(
        acad_year="2026-2027",
        semester=1,
        balloted_types=["TUT", "LAB", "REC", "SEC"],
        modules={"ALPHA": {"LEC": 2, "TUT": 4}, "BETA": 3},
        fixed={"BETA": {"LEC": "1"}},
        priority=["ALPHA", "BETA"],
        preferences=Preferences(
            earliest_start=600,
            latest_end=1080,
            max_difficulty_per_day=8,
            lunch_start=660,
            lunch_end=840,
            lunch_minutes=60,
            weights=dict(DEFAULT_PREFERENCES["weights"]),
        ),
        alternatives_per_module=4,
        top_n=5,
    )
