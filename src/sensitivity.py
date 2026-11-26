import pandas as pd

import scheduler
from analysis import OUT_DIR, conflict_matrix
from load_data import load_dataset


def slots_per_day_table(graph, students, options=(2, 3, 4)):
    """Same DSatur slots, packed into days of 2, 3 or 4 exam periods."""
    rows = {}
    for k in options:
        # the scheduler reads this constant at call time
        scheduler.SLOTS_PER_DAY = k
        results = scheduler.compare(scheduler.build_timetables(graph, students), students)
        plain, tuned = results["DSatur"], results["DSatur + day + period order"]
        rows[k] = {
            "days": tuned["days"],
            "% 2+ exams/day (DSatur)": plain["% students 2+ exams/day"],
            "% 2+ exams/day (tuned)": tuned["% students 2+ exams/day"],
            "students back-to-back (tuned)": tuned["students back-to-back"],
        }
    scheduler.SLOTS_PER_DAY = 3
    return pd.DataFrame.from_dict(rows, orient="index").rename_axis("slots per day")


if __name__ == "__main__":
    courses, students = load_dataset()
    graph = scheduler.conflict_graph(conflict_matrix(students, len(courses)))
    table = slots_per_day_table(graph, students)
    print(table.to_string())
    table.to_csv(OUT_DIR / "slots_per_day.csv")
    print(f"\nSaved {OUT_DIR / 'slots_per_day.csv'}")
