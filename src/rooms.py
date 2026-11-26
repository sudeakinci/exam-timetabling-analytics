import pandas as pd

from analysis import OUT_DIR, conflict_matrix
from load_data import DATA_DIR, load_dataset
from scheduler import SLOTS_PER_DAY, build_timetables, conflict_graph

# synthetic: the benchmark has no rooms. capacity = exam seats, about half the lecture seats
# (every other seat left empty). the biggest exams go to sports halls, as is common in Canada
ROOM_TYPES = [
    # type, prefix, count, capacity
    ("Sports hall", "SH", 2, 400),
    ("Lecture hall", "LH", 8, 150),
    ("Large classroom", "LC", 30, 60),
    ("Classroom", "C", 30, 30),
]
PERIODS = ["Morning", "Midday", "Afternoon"]


def make_rooms():
    rows = [
        {"room": f"{prefix}-{i:02d}", "type": kind, "capacity": capacity}
        for kind, prefix, count, capacity in ROOM_TYPES
        for i in range(1, count + 1)
    ]
    return pd.DataFrame(rows)


def assign_rooms(slots, courses, rooms):
    """One row per course and room. A room holds one course per slot; big courses get split.

    Biggest course first, into the smallest free room that fits it. If none fits,
    take the biggest free room and repeat for the students left over.
    Students who can't be seated get a row with room = None.
    """
    size = dict(zip(courses["course"], courses["enrolled"]))
    by_slot = {}
    for course, slot in slots.items():
        by_slot.setdefault(slot, []).append(course)

    rows = []
    for slot in sorted(by_slot):
        free = rooms.sort_values("capacity").to_dict("records")  # smallest first
        for course in sorted(by_slot[slot], key=size.get, reverse=True):
            left = size[course]
            while left > 0:
                if not free:
                    rows.append({"course": course, "slot": slot, "room": None, "capacity": 0, "students": left})
                    break
                room = next((r for r in free if r["capacity"] >= left), free[-1])
                free.remove(room)
                seated = min(left, room["capacity"])
                rows.append({"course": course, "slot": slot, "room": room["room"],
                             "capacity": room["capacity"], "students": seated})
                left -= seated

    plan = pd.DataFrame(rows)
    plan["day"] = plan["slot"] // SLOTS_PER_DAY + 1
    plan["period"] = plan["slot"].map(lambda s: PERIODS[s % SLOTS_PER_DAY])
    return plan[["day", "period", "slot", "course", "room", "capacity", "students"]]


def room_metrics(plan, rooms):
    seated = plan[plan["room"].notna()]
    per_slot = seated.groupby("slot")["students"].sum()
    rooms_per_course = seated.groupby("course")["room"].count()
    return {
        "rooms": len(rooms),
        "seats": int(rooms["capacity"].sum()),
        "unseated students": int(plan.loc[plan["room"].isna(), "students"].sum()),
        "seat use in booked rooms (%)": round(100 * seated["students"].sum() / seated["capacity"].sum(), 1),
        "busiest slot, share of all seats (%)": round(100 * per_slot.max() / rooms["capacity"].sum(), 1),
        "most rooms in one slot": int(seated.groupby("slot")["room"].count().max()),
        "courses split over 2+ rooms": int((rooms_per_course > 1).sum()),
    }


if __name__ == "__main__":
    courses, students = load_dataset()
    graph = conflict_graph(conflict_matrix(students, len(courses)))
    final = build_timetables(graph, students)["DSatur + day + period order"]

    rooms = make_rooms()
    plan = assign_rooms(final, courses, rooms)

    # every enrolled student is either seated or reported as unseated
    assert plan["students"].sum() == courses["enrolled"].sum()

    for key, value in room_metrics(plan, rooms).items():
        print(f"{key}: {value:,}")

    rooms.to_csv(DATA_DIR.parent / "rooms.csv", index=False)
    plan.to_csv(OUT_DIR / "timetable.csv", index=False)
    print(f"\nSaved {DATA_DIR.parent / 'rooms.csv'} and {OUT_DIR / 'timetable.csv'}")
