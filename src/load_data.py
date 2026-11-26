from collections import Counter
from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"
DATASET = "car-s-91"


def load_courses(path):
    """Read a .crs file: one line per course, 'id enrolled'."""
    return pd.read_csv(path, sep=r"\s+", header=None, names=["course", "enrolled"])


def load_students(path):
    """Read a .stu file. Each line is one student's list of course ids."""
    students = []
    with open(path) as f:
        for line in f:
            courses = [int(c) for c in line.split()]
            if courses:  # file ends with a blank line
                students.append(courses)
    return students


def load_dataset():
    """Courses and students of the benchmark instance used throughout."""
    return load_courses(DATA_DIR / f"{DATASET}.crs"), load_students(DATA_DIR / f"{DATASET}.stu")


if __name__ == "__main__":
    courses, students = load_dataset()
    print("Courses:", len(courses))
    print("Students:", len(students))

    # sanity check: enrollment counted from .stu should match .crs
    counts = Counter(c for s in students for c in s)
    courses["counted"] = courses["course"].map(counts)
    mismatches = (courses["counted"] != courses["enrolled"]).sum()
    print("Mismatched courses:", mismatches)
