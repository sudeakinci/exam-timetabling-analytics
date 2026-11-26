import pytest

from analysis import conflict_matrix
from load_data import load_dataset
from rooms import assign_rooms, make_rooms
from scheduler import build_timetables, compare, conflict_graph, lower_bound


@pytest.fixture(scope="module")
def data():
    courses, students = load_dataset()
    graph = conflict_graph(conflict_matrix(students, len(courses)))
    return courses, students, graph, build_timetables(graph, students)


def test_data_matches_published_stats(data):
    courses, students, _, _ = data
    assert (len(courses), len(students), courses["enrolled"].sum()) == (682, 16925, 56877)


def test_every_course_scheduled_without_clash(data):
    courses, students, _, timetables = data
    for slots in timetables.values():
        assert set(slots) == set(courses["course"])
    compare(timetables, students)  # raises on any clash


def test_dsatur_not_below_lower_bound(data):
    _, _, graph, timetables = data
    assert len(set(timetables["DSatur"].values())) >= lower_bound(graph)


def test_rooms_not_double_booked_or_overfull(data):
    courses, _, _, timetables = data
    plan = assign_rooms(timetables["DSatur + day + period order"], courses, make_rooms())
    seated = plan[plan["room"].notna()]
    assert not seated.duplicated(["slot", "room"]).any()
    assert (seated["students"] <= seated["capacity"]).all()
    assert plan["students"].sum() == courses["enrolled"].sum()
