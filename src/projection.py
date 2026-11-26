import numpy as np
import pandas as pd

from analysis import ACCENT, INK, MUTED, NEUTRAL, OUT_DIR, SOURCE, TILE, _note, conflict_matrix, plt
from load_data import load_dataset
from rooms import assign_rooms, make_rooms, room_metrics
from scheduler import SLOTS_PER_DAY, build_timetables, conflict_graph, evaluate

GROWTH = 0.15
EXTRA_ROOM = ("Classroom", "C", 30)  # what gets added when rooms run out


def grow(courses, rate=GROWTH):
    """Every course grows by the same rate, rounded up. Who takes what together stays the same."""
    return courses.assign(enrolled=np.ceil(courses["enrolled"] * (1 + rate)).astype(int))


def add_rooms(rooms, n):
    kind, prefix, capacity = EXTRA_ROOM
    start = (rooms["type"] == kind).sum() + 1
    extra = pd.DataFrame([{"room": f"{prefix}-{i:02d}", "type": kind, "capacity": capacity}
                          for i in range(start, start + n)])
    return pd.concat([rooms, extra], ignore_index=True)


def rooms_needed(slots, courses, rooms):
    """Smallest number of extra rooms that seats everyone."""
    n = 0
    while assign_rooms(slots, courses, add_rooms(rooms, n))["room"].isna().any():
        n += 1
    return n


def move_exams(slots, courses, rooms, graph):
    """Move the smallest exams out of a slot that can't be seated, into a slot with no clash.

    Slots on the same day come first, so nobody gets a new exam day; then the emptiest
    slots anywhere. One exam moves at a time and the rooms are reassigned after each move.
    """
    slots = dict(slots)
    size = dict(zip(courses["course"], courses["enrolled"]))
    n_positions = (max(slots.values()) // SLOTS_PER_DAY + 1) * SLOTS_PER_DAY
    moves = []
    while True:
        plan = assign_rooms(slots, courses, rooms)
        unseated = plan[plan["room"].isna()]
        if unseated.empty:
            return slots, moves
        crowded = int(unseated["slot"].iloc[0])
        day = crowded // SLOTS_PER_DAY
        load = plan.groupby("slot")["students"].sum().reindex(range(n_positions), fill_value=0)
        targets = sorted((p for p in range(n_positions) if p != crowded),
                         key=lambda p: (p // SLOTS_PER_DAY != day, load[p]))
        here = sorted((c for c, s in slots.items() if s == crowded), key=size.get)
        for course in here:
            target = next((p for p in targets
                           if not any(slots[n] == p for n in graph[course])), None)
            if target is not None:
                slots[course] = target
                moves.append((course, crowded, target))
                break
        else:
            raise RuntimeError(f"no exam in slot {crowded} can move without a clash")


def demand_per_slot(slots, courses, rooms):
    """Seats and rooms each slot would use if rooms never ran out."""
    plan = assign_rooms(slots, courses, add_rooms(rooms, 200))
    assert plan["room"].notna().all()
    n_positions = (max(slots.values()) // SLOTS_PER_DAY + 1) * SLOTS_PER_DAY
    per_slot = plan.groupby("slot").agg(seats=("students", "sum"), rooms=("room", "count"))
    return per_slot.reindex(range(n_positions), fill_value=0)


def plot_growth(demand, n_seats, n_rooms, path):
    """Two panels on the same slots: seats needed vs all seats, rooms needed vs all rooms."""
    fig, (top, bottom) = plt.subplots(2, 1, figsize=(12, 6.5), sharex=True, gridspec_kw={"hspace": 0.45})
    over = demand["rooms"] > n_rooms
    x = demand.index
    days = len(x) // SLOTS_PER_DAY
    for ax, col, limit, label in ((top, "seats", n_seats, "seats"), (bottom, "rooms", n_rooms, "rooms")):
        ax.grid(axis="x", visible=False)
        for d in range(1, days, 2):  # shade every other day so the three slots of a day read as a group
            ax.axvspan(d * SLOTS_PER_DAY - 0.5, (d + 1) * SLOTS_PER_DAY - 0.5, color=TILE, zorder=0)
        ax.bar(x, demand[col], width=0.75, color=[ACCENT if o else NEUTRAL for o in over])
        ax.axhline(limit, color=INK, linewidth=1, linestyle="--")
        ax.annotate(f"All {limit:,} {label}", (x.max() + 0.6, limit), xytext=(4, 0), textcoords="offset points",
                    va="center", color=INK, fontsize=9)
        ax.set_ylim(0, max(limit, demand[col].max()) * 1.15)
        ax.margins(x=0.01)
    for slot in x[over]:
        bottom.annotate(f"{demand.at[slot, 'rooms']}", (slot, demand.at[slot, "rooms"]), xytext=(0, 3),
                        textcoords="offset points", ha="center", color=INK, fontsize=9, fontweight="bold")
    _note(top, "Seats needed in each slot", 8, fontsize=10, fontweight="bold", color=INK)
    _note(bottom, "Rooms needed in each slot (one exam per room)", 8, fontsize=10, fontweight="bold", color=INK)

    bottom.set_xticks([d * SLOTS_PER_DAY + 1 for d in range(days)], [f"Day {d + 1}" for d in range(days)])
    _note(top, f"At +{GROWTH:.0%}, {over.sum()} slots run out of rooms, not seats", 52,
          fontsize=14, fontweight="bold", color=INK)
    _note(top, "Many small exams each take a whole room. Every slot has enough seats, but two need more "
               f"than the {n_rooms} rooms", 34, fontsize=10, color=MUTED)
    _note(bottom, SOURCE + f", enrolments +{GROWTH:.0%}. Assumes {SLOTS_PER_DAY} slots per day; rooms are synthetic",
          -26, fontsize=8, color=MUTED, va="top")
    fig.savefig(path, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def scenario(name, slots, courses, rooms, students):
    plan = assign_rooms(slots, courses, rooms)
    m, r = room_metrics(plan, rooms), evaluate(slots, students)
    return {
        "scenario": name,
        "exam seats needed": int(courses["enrolled"].sum()),
        "rooms": m["rooms"],
        "days": r["days"],
        "unseated students": m["unseated students"],
        "busiest slot, % of seats": m["busiest slot, share of all seats (%)"],
        "% students 2+ exams/day": r["% students 2+ exams/day"],
        "students back-to-back": r["students back-to-back"],
        "clashes": r["clashes"],
    }


if __name__ == "__main__":
    courses, students = load_dataset()
    graph = conflict_graph(conflict_matrix(students, len(courses)))
    final = build_timetables(graph, students)["DSatur + day + period order"]
    rooms, grown = make_rooms(), grow(courses)

    extra = rooms_needed(final, grown, rooms)
    moved, moves = move_exams(final, grown, rooms, graph)

    # student lists don't grow, so student shares assume new students behave like current ones
    table = pd.DataFrame([
        scenario("Today", final, courses, rooms, students),
        scenario(f"+{GROWTH:.0%}, no change", final, grown, rooms, students),
        scenario(f"+{GROWTH:.0%}, {extra} extra classrooms", final, grown, add_rooms(rooms, extra), students),
        scenario(f"+{GROWTH:.0%}, move {len(moves)} small exams", moved, grown, rooms, students),
    ]).set_index("scenario")

    assert (table["clashes"] == 0).all()
    assert table["unseated students"].iloc[[0, 2, 3]].eq(0).all()

    print(table.drop(columns="clashes").to_string())
    print("\nMoved exams (course: from slot -> to slot):")
    for course, a, b in moves:
        print(f"  {course} ({grown.set_index('course').at[course, 'enrolled']} students): "
              f"day {a // SLOTS_PER_DAY + 1}.{a % SLOTS_PER_DAY + 1} -> day {b // SLOTS_PER_DAY + 1}.{b % SLOTS_PER_DAY + 1}")
    table.to_csv(OUT_DIR / "growth_scenarios.csv")
    plot_growth(demand_per_slot(final, grown, rooms), int(rooms["capacity"].sum()), len(rooms),
                OUT_DIR / "growth_rooms.png")
    print(f"\nSaved {OUT_DIR / 'growth_scenarios.csv'} and {OUT_DIR / 'growth_rooms.png'}")
