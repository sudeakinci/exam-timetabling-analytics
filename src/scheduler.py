from collections import Counter

import networkx as nx
import pandas as pd

from analysis import conflict_matrix
from load_data import DATA_DIR, load_courses, load_students

SLOTS_PER_DAY = 3  # assumption: morning, midday, afternoon. the benchmark has no days

# how greedy_color picks the next course to place
STRATEGIES = {
    "Greedy (course order)": lambda graph, colors: sorted(graph),
    "Greedy (largest first)": "largest_first",
    "DSatur": "saturation_largest_first",
}


def conflict_graph(m):
    """Courses as nodes, an edge wherever two courses share a student."""
    graph = nx.from_numpy_array(m[1:, 1:])
    return nx.relabel_nodes(graph, lambda i: i + 1)  # node = course id


def schedule(graph, strategy):
    """Course id -> time slot (0, 1, 2, ...)."""
    return nx.greedy_color(graph, strategy=strategy)


def evaluate(slots, students):
    """Timetable metrics, counted from the student lists rather than the graph."""
    clashes = same_day = back_to_back = 0
    for courses in students:
        taken = sorted(slots[c] for c in courses)
        clashes += len(taken) - len(set(taken))
        per_day = Counter(s // SLOTS_PER_DAY for s in taken)
        same_day += any(n > 1 for n in per_day.values())
        back_to_back += any(b - a == 1 and a // SLOTS_PER_DAY == b // SLOTS_PER_DAY
                            for a, b in zip(taken, taken[1:]))

    n_slots = max(slots.values()) + 1
    return {
        "slots": n_slots,
        "days": -(-n_slots // SLOTS_PER_DAY),  # round up
        "clashes": clashes,
        "students 2+ exams/day": same_day,
        "% students 2+ exams/day": round(100 * same_day / len(students), 1),
        "students back-to-back": back_to_back,
    }


if __name__ == "__main__":
    courses = load_courses(DATA_DIR / "car-s-91.crs")
    students = load_students(DATA_DIR / "car-s-91.stu")
    graph = conflict_graph(conflict_matrix(students, len(courses)))

    results = {}
    for name, strategy in STRATEGIES.items():
        slots = schedule(graph, strategy)
        results[name] = evaluate(slots, students)
        assert results[name]["clashes"] == 0, f"{name} produced a clash"

    print(f"{len(students):,} students, {len(courses)} courses, {SLOTS_PER_DAY} slots per day\n")
    print(pd.DataFrame.from_dict(results, orient="index").to_string())
