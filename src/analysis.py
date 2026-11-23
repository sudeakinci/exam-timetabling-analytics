from itertools import combinations

import numpy as np
import pandas as pd

from load_data import DATA_DIR, load_courses, load_students


def conflict_matrix(students, n_courses):
    """m[a, b] = number of students taking both a and b."""
    m = np.zeros((n_courses + 1, n_courses + 1), dtype=int)  # indexed by course id, row 0 unused
    for courses in students:
        for a, b in combinations(courses, 2):
            m[a, b] += 1
            m[b, a] += 1
    return m


def top_pairs(m, k=10):
    """The k course pairs with the most shared students."""
    a, b = np.triu_indices_from(m, k=1)  # upper triangle, so each pair shows up once
    pairs = pd.DataFrame({"course_a": a, "course_b": b, "shared": m[a, b]})
    return pairs.sort_values("shared", ascending=False).head(k)


def course_stats(courses, m):
    """Courses sorted by how many other courses they clash with."""
    stats = courses.copy()
    stats["conflicts"] = (m[stats["course"].to_numpy()] > 0).sum(axis=1)
    return stats.sort_values("conflicts", ascending=False)


if __name__ == "__main__":
    courses = load_courses(DATA_DIR / "car-s-91.crs")
    students = load_students(DATA_DIR / "car-s-91.stu")
    n = len(courses)

    m = conflict_matrix(students, n)
    conflicting_pairs = (np.triu(m, k=1) > 0).sum()
    total_pairs = n * (n - 1) // 2
    print(f"Conflicting course pairs: {conflicting_pairs} / {total_pairs} "
          f"(density {conflicting_pairs / total_pairs:.3f})")

    print("\nTop 10 pairs by shared students:")
    print(top_pairs(m).to_string(index=False))

    print("\nTop 10 courses by number of conflicts:")
    print(course_stats(courses, m).head(10).to_string(index=False))
