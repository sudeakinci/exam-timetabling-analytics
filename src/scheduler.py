from collections import Counter, defaultdict
from itertools import combinations, permutations

import networkx as nx
import numpy as np
import pandas as pd

from analysis import ACCENT, INK, MUTED, NEUTRAL, OUT_DIR, SOURCE, _note, conflict_matrix, plt
from load_data import load_dataset

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


def lower_bound(graph):
    """No timetable can use fewer slots: every course in a clique clashes with every other."""
    return len(nx.max_weight_clique(graph, weight=None)[0])


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

    return {
        "slots": len(set(slots.values())),
        "days": max(slots.values()) // SLOTS_PER_DAY + 1,
        "clashes": clashes,
        "students 2+ exams/day": same_day,
        "% students 2+ exams/day": round(100 * same_day / len(students), 1),
        "students back-to-back": back_to_back,
    }


def assign_days(slots, students, n_days):
    """Move whole slots between days to cut students with 2+ exams in a day.

    Hill climbing: swap two slots on different days, keep the swap if it helps,
    stop when no swap helps. Courses in a slot move together, so no clash is created.
    """
    n_positions = n_days * SLOTS_PER_DAY  # positions left over stay empty

    # takes[i, k] = 1 if student i has an exam in slot k
    takes = np.zeros((len(students), n_positions), dtype=np.float32)
    for i, courses in enumerate(students):
        for c in courses:
            takes[i, slots[c]] = 1

    def students_with_same_day(position):
        on_day = np.zeros((n_positions, n_days), dtype=np.float32)
        on_day[np.arange(n_positions), position // SLOTS_PER_DAY] = 1
        exams_per_day = takes @ on_day  # students x days
        return int((exams_per_day > 1).any(axis=1).sum())

    position = np.arange(n_positions)  # position[k] = where slot k sits now
    best = students_with_same_day(position)
    improved = True
    while improved:
        improved = False
        for a, b in combinations(range(n_positions), 2):
            if position[a] // SLOTS_PER_DAY == position[b] // SLOTS_PER_DAY:
                continue  # same day, swapping changes nothing
            position[[a, b]] = position[[b, a]]
            cost = students_with_same_day(position)
            if cost < best:
                best, improved = cost, True
            else:
                position[[a, b]] = position[[b, a]]  # undo

    return {course: int(position[k]) for course, k in slots.items()}


def order_within_days(slots, students):
    """Within each day, use the slot order with the fewest back-to-back exams.

    Only 3! = 6 orders per day, so try them all. Days stay the same.
    """
    sitting = defaultdict(set)  # position -> students with an exam there
    for i, courses in enumerate(students):
        for c in courses:
            sitting[slots[c]].add(i)

    def back_to_back(order):
        return len(set().union(*(sitting[a] & sitting[b] for a, b in zip(order, order[1:]))))

    n_days = max(slots.values()) // SLOTS_PER_DAY + 1
    move = {}
    for d in range(n_days):
        day = range(d * SLOTS_PER_DAY, (d + 1) * SLOTS_PER_DAY)
        best = min(permutations(day), key=back_to_back)
        move.update(zip(best, day))  # whatever sat at best[i] goes to the i-th period
    return {course: move[p] for course, p in slots.items()}


def build_timetables(graph, students):
    """All timetables to compare, from the plain greedy one to the fully tuned DSatur one."""
    timetables = {name: schedule(graph, strategy) for name, strategy in STRATEGIES.items()}

    # same DSatur slots, first moved between days, then reordered inside each day
    dsatur = timetables["DSatur"]
    n_days = max(dsatur.values()) // SLOTS_PER_DAY + 1
    timetables["DSatur + day reordering"] = assign_days(dsatur, students, n_days)
    timetables["DSatur + day + period order"] = order_within_days(timetables["DSatur + day reordering"], students)
    return timetables


def compare(timetables, students):
    """Metrics for every timetable, checked for clashes."""
    results = {name: evaluate(slots, students) for name, slots in timetables.items()}
    for name, r in results.items():
        assert r["clashes"] == 0, f"{name} produced a clash"
    # reordering inside a day must not change who has two exams that day
    assert (results["DSatur + day + period order"]["students 2+ exams/day"]
            == results["DSatur + day reordering"]["students 2+ exams/day"])
    return results


PANELS = [
    ("days", "Exam days", "{:.0f}"),
    ("% students 2+ exams/day", "Students with 2+ exams in a day", "{:.1f}%"),
    ("students back-to-back", "Students with back-to-back exams", "{:,}"),
]


def plot_comparison(axes, results, small=False):
    """Three bar panels side by side, one per metric. The last timetable is highlighted."""
    names = list(results)[::-1]  # barh draws bottom-up, so the first method ends up on top
    colors = [ACCENT if n == names[0] else NEUTRAL for n in names]
    for ax, (col, label, fmt) in zip(axes, PANELS):
        values = [results[n][col] for n in names]
        bars = ax.barh(names, values, height=0.6, color=colors)
        ax.bar_label(bars, labels=[fmt.format(v) for v in values], padding=4, color=INK)
        ax.set_title(label, loc="left", fontsize=10, color=INK, pad=8)
        ax.margins(x=0.2)
        ax.xaxis.set_visible(False)
        ax.grid(False)
        for spine in ax.spines.values():
            spine.set_visible(False)
    for ax in axes[1:]:
        ax.tick_params(labelleft=False)

    plain, tuned = results["DSatur"], results[names[0]]
    cut = 1 - tuned["students 2+ exams/day"] / plain["students 2+ exams/day"]
    _note(axes[0], f"Same {tuned['days']} days, {cut:.0%} fewer students with two exams in a day",
          56 if small else 62, fontsize=11 if small else 13, fontweight="bold", color=INK)
    _note(axes[0], "Five ways to build the timetable. None has a clash; DSatur is then tuned by moving "
                   "slots between days and reordering them inside each day",
          40 if small else 44, fontsize=9 if small else 10, color=MUTED)


# 520 (the most-clashing course) and 7 of its neighbours, picked so the drawing has no crossing lines
EXAMPLE_COURSES = [520, 600, 24, 151, 153, 450, 476, 152]
SLOT_COLORS = [ACCENT, "#e5b3c1", NEUTRAL]  # checked for colour blindness; slot is also written in each node


def plot_colouring_example(graph, path):
    """Small picture of graph colouring: a few real courses, coloured by their DSatur slot."""
    sub = graph.subgraph(EXAMPLE_COURSES)
    slots = schedule(sub, "saturation_largest_first")
    ring = [n for n in EXAMPLE_COURSES if n != 152]
    pos = nx.shell_layout(sub.subgraph(ring), [[520], ring[1:]])
    pos[152] = 0.3 * (pos[151] + pos[153])  # inside the 520-151-153 triangle, so no line crosses

    fig, ax = plt.subplots(figsize=(7, 6))
    nx.draw_networkx_edges(sub, pos, ax=ax, edge_color=NEUTRAL, alpha=0.5, width=1.5)
    nx.draw_networkx_nodes(sub, pos, ax=ax, node_size=2400, edgecolors=INK, linewidths=1,
                           node_color=[SLOT_COLORS[slots[n]] for n in sub])
    for n, (x, y) in pos.items():
        color = INK if slots[n] == 1 else "white"
        ax.text(x, y, str(n), ha="center", va="bottom", fontsize=12, fontweight="bold", color=color)
        ax.text(x, y, f"slot {slots[n] + 1}", ha="center", va="top", fontsize=9, color=color)
    ax.set_axis_off()
    ax.margins(0.12)

    n_slots = len(set(slots.values()))
    _note(ax, "Linked courses never share a slot", 40, fontsize=14, fontweight="bold", color=INK)
    _note(ax, f"{len(sub)} real courses. A line means at least one student takes both. "
              f"DSatur needs {n_slots} slots here", 22, fontsize=10, color=MUTED)
    _note(ax, SOURCE, -10, fontsize=8, color=MUTED, va="top")
    fig.savefig(path, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def save_comparison(results, path):
    fig, axes = plt.subplots(1, 3, figsize=(14, 3.6), sharey=True)
    plot_comparison(axes, results)
    _note(axes[0], SOURCE + f". Assumes {SLOTS_PER_DAY} exam slots per day", -20, fontsize=8, color=MUTED, va="top")
    fig.savefig(path, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)


if __name__ == "__main__":
    courses, students = load_dataset()
    graph = conflict_graph(conflict_matrix(students, len(courses)))
    results = compare(build_timetables(graph, students), students)

    print(f"{len(students):,} students, {len(courses)} courses, {SLOTS_PER_DAY} slots per day\n")
    print(pd.DataFrame.from_dict(results, orient="index").to_string())

    before = results["DSatur"]["students 2+ exams/day"]
    after = results["DSatur + day reordering"]["students 2+ exams/day"]
    print(f"\nLower bound: {lower_bound(graph)} slots (largest group of courses that all clash)")
    print(f"Day reordering: {before:,} -> {after:,} students with 2+ exams in a day "
          f"({(before - after) / before:.1%} fewer)")

    save_comparison(results, OUT_DIR / "schedule_comparison.png")
    plot_colouring_example(graph, OUT_DIR / "colouring_example.png")
    print(f"Charts saved to {OUT_DIR / 'schedule_comparison.png'} and {OUT_DIR / 'colouring_example.png'}")
