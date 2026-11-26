from collections import Counter

import pandas as pd

from analysis import ACCENT, GRID, INK, MUTED, NEUTRAL, OUT_DIR, SOURCE, TILE, clash_density, conflict_matrix
from load_data import load_dataset
from rooms import PERIODS, assign_rooms, make_rooms, room_metrics
from scheduler import SLOTS_PER_DAY, build_timetables, compare, conflict_graph, lower_bound

# steps of the bordeaux ramp in analysis.py; light enough for black text on top
PINK, BAR, MID = "#f7e8ec", "#e5b3c1", "#c86a85"
ROW_PX = 20  # default Excel row height, used to keep charts from covering the next block
HEADER = {"bold": True, "font_color": "white", "bg_color": ACCENT, "border": 1, "border_color": ACCENT}


def course_table(slots, plan, courses):
    """One row per course: when it is and how many rooms it needs."""
    rooms = plan.dropna(subset=["room"]).groupby("course")["room"].agg(**{"rooms": "count", "room list": ", ".join})
    table = courses.assign(slot=courses["course"].map(slots))
    table["day"] = table["slot"] // SLOTS_PER_DAY + 1
    table["period"] = table["slot"].map(lambda s: PERIODS[s % SLOTS_PER_DAY])
    return table.join(rooms, on="course")[["course", "enrolled", "day", "period", "slot", "rooms", "room list"]]


def student_table(slots, students):
    """One row per student: how their exams are spread over the days."""
    rows = []
    for i, courses in enumerate(students, 1):
        taken = sorted(slots[c] for c in courses)
        per_day = Counter(s // SLOTS_PER_DAY for s in taken)
        back_to_back = any(b - a == 1 and a // SLOTS_PER_DAY == b // SLOTS_PER_DAY for a, b in zip(taken, taken[1:]))
        rows.append({"student": f"S{i:05d}", "exams": len(taken), "exam days": len(per_day),
                     "most exams in a day": max(per_day.values()), "back-to-back": "Yes" if back_to_back else "No"})
    return pd.DataFrame(rows)


def kpi_rows(courses, students, m, graph, results, metrics):
    plain, final = results["DSatur"], results["DSatur + day + period order"]
    same_before, same_after = plain["students 2+ exams/day"], final["students 2+ exams/day"]
    b2b_before, b2b_after = plain["students back-to-back"], final["students back-to-back"]
    # (section, metric, value, number format)
    return [
        ("Data", "Courses", len(courses), "int"),
        ("Data", "Students", len(students), "int"),
        ("Data", "Exam enrolments", int(courses["enrolled"].sum()), "int"),
        ("Data", "Course pairs that clash", clash_density(m), "pct"),
        ("Timetable", "Exam slots (DSatur)", final["slots"], "int"),
        ("Timetable", "Lower bound on slots", lower_bound(graph), "int"),
        ("Timetable", "Exam days", final["days"], "int"),
        ("Timetable", "Clashes", final["clashes"], "int"),
        ("Students", "2+ exams in a day, DSatur", same_before, "int"),
        ("Students", "2+ exams in a day, after reordering", same_after, "int"),
        ("Students", "2+ exams in a day, change", same_after / same_before - 1, "pct"),
        ("Students", "Back-to-back exams, DSatur", b2b_before, "int"),
        ("Students", "Back-to-back exams, after reordering", b2b_after, "int"),
        ("Students", "Back-to-back exams, change", b2b_after / b2b_before - 1, "pct"),
        ("Rooms", "Rooms", metrics["rooms"], "int"),
        ("Rooms", "Exam seats", metrics["seats"], "int"),
        ("Rooms", "Unseated students", metrics["unseated students"], "int"),
        ("Rooms", "Seat use in booked rooms", metrics["seat use in booked rooms (%)"] / 100, "pct"),
        ("Rooms", "Busiest slot, share of all seats", metrics["busiest slot, share of all seats (%)"] / 100, "pct"),
    ]


def _title(name):
    return name[:1].upper() + name[1:]


def _table(xw, df, sheet, formats=None):
    """Write df as a filterable Excel table with a frozen header. Headers get a capital letter."""
    df.to_excel(xw, sheet_name=sheet, index=False, startrow=1, header=False)
    ws = xw.sheets[sheet]
    header = xw.book.add_format(HEADER)
    ws.add_table(0, 0, len(df), len(df.columns) - 1,
                 {"columns": [{"header": _title(c), "header_format": header} for c in df.columns],
                  "style": "Table Style Light 1", "name": sheet})
    for i, c in enumerate(df.columns):
        ws.set_column(i, i, max(12, len(c) + 5), (formats or {}).get(c))  # +5 leaves room for the filter button
    ws.freeze_panes(1, 0)
    return ws


def _chart(book, kind, width, height):
    """A bare chart: no title (the cell above says what it shows), no border, no gridlines."""
    chart = book.add_chart({"type": kind})
    chart.set_title({"none": True})
    chart.set_legend({"none": True})
    chart.set_chartarea({"border": {"none": True}})
    chart.set_size({"width": width, "height": height})
    categories = {"line": {"color": GRID}, "num_font": {"color": INK, "size": 10}, "major_tick_mark": "none"}
    hidden = {"visible": False, "major_gridlines": {"visible": False}}
    chart.set_x_axis(hidden)  # bar charts: x is the value axis
    chart.set_y_axis({**categories, "reverse": True})
    return chart


def add_dashboard(book, ws, data, tiles, plan, results, seats):
    """KPI tiles, then a 2 x 2 grid. Each block has a one-line finding on top.

    Charts read from the 'Chart data' sheet; the method table and heatmap are plain cells.
    """
    ws.activate()
    ws.hide_gridlines(2)
    ws.set_landscape()
    ws.fit_to_pages(1, 0)

    f = lambda **kw: book.add_format(kw)
    banner = f(bold=True, font_size=18, font_color="white", bg_color=ACCENT, valign="vcenter", indent=1)
    section = f(bold=True, font_size=12, font_color=INK, bg_color=PINK, left=5, left_color=ACCENT,
                valign="vcenter", indent=1)
    note = f(font_color=MUTED, italic=True)
    head = f(**HEADER)
    head_r = f(**HEADER, align="right")

    # left block B:G, gap H, right block I:M
    ws.set_column(0, 0, 2)
    ws.set_column(1, 6, 12)
    ws.set_column(7, 7, 4)
    ws.set_column(8, 8, 28)
    ws.set_column(9, 10, 8)
    ws.set_column(11, 12, 15)
    left, right, width = 1, 8, 500

    ws.set_row(0, 34)
    ws.merge_range(0, left, 0, 12, "Exam timetable dashboard", banner)
    ws.write(1, left, f"{SOURCE}. Assumes {SLOTS_PER_DAY} exam slots per day; rooms are synthetic.", note)

    big = {"bold": True, "font_size": 22, "bg_color": TILE, "font_color": INK, "valign": "vcenter", "align": "left",
           "indent": 1}
    label = f(font_color=MUTED, bg_color=TILE, valign="top", text_wrap=True, indent=1)
    ws.set_row(3, 36)
    ws.set_row(4, 30)
    tile_cols = [(1, 2), (3, 4), (5, 6), (8, 8), (9, 10), (11, 12)]
    for (a, b), (text, value, fmt) in zip(tile_cols, tiles):
        value_fmt = f(**big, num_format=fmt or "General")
        if a == b:
            ws.write(3, a, value, value_fmt)
            ws.write(4, a, text, label)
        else:
            ws.merge_range(3, a, 3, b, value, value_fmt)
            ws.merge_range(4, a, 4, b, text, label)

    def block(row, col, title, subtitle):
        ws.set_row(row, 24)
        ws.merge_range(row, col, row, col + (5 if col == left else 4), title, section)
        ws.write(row + 1, col, subtitle, note)
        return row + 3

    plain, final = results["DSatur"], results["DSatur + day + period order"]
    same_cut = 1 - final["students 2+ exams/day"] / plain["students 2+ exams/day"]
    b2b_cut = 1 - final["students back-to-back"] / plain["students back-to-back"]

    # --- row A, left: before / after
    row_a, chart_h = 6, 220
    data.write_row(0, 0, ["Students affected", "DSatur", "After reordering"], head)
    data.write_row(1, 0, ["2+ exams in a day", plain["students 2+ exams/day"], final["students 2+ exams/day"]])
    data.write_row(2, 0, ["Back-to-back exams", plain["students back-to-back"], final["students back-to-back"]])
    top = block(row_a, left, f"Reordering cut affected students by {same_cut:.0%} and {b2b_cut:.0%}",
                "Same slots and days. Gray: DSatur as built; bordeaux: after reordering.")
    c = _chart(book, "bar", width, chart_h)
    for col, color in ((1, NEUTRAL), (2, ACCENT)):
        c.add_series({"name": ["Chart data", 0, col], "categories": ["Chart data", 1, 0, 2, 0],
                      "values": ["Chart data", 1, col, 2, col], "fill": {"color": color}, "gap": 80,
                      "data_labels": {"value": True, "num_format": "#,##0", "font": {"color": INK, "size": 10}}})
    c.set_legend({"position": "top", "font": {"color": INK, "size": 10}})
    ws.insert_chart(top, left, c)

    # --- row A, right: every method
    top = block(row_a, right, "DSatur needs the fewest slots; reordering does the rest",
                "All five timetables are clash-free. Bold: the final timetable.")
    ws.write(top, right, "Method", head)
    ws.write_row(top, right + 1, ["Slots", "Days", "2+ exams/day", "Back-to-back"], head_r)
    for i, (name, r) in enumerate(results.items(), top + 1):
        band = {"bg_color": TILE} if (i - top) % 2 == 0 else {}
        style = {"bold": True, "bg_color": PINK} if name == "DSatur + day + period order" else band
        ws.write(i, right, name, f(font_color=INK, **style))
        ws.write_row(i, right + 1, [r["slots"], r["days"]], f(font_color=INK, **style))
        ws.write(i, right + 3, r["% students 2+ exams/day"] / 100, f(num_format="0.0%", font_color=INK, **style))
        ws.write(i, right + 4, r["students back-to-back"], f(num_format="#,##0", font_color=INK, **style))

    # --- row B, left: seat use heatmap, day x period
    row_b = row_a + 3 + chart_h // ROW_PX + 2
    n_days = int(plan["day"].max())
    per_slot = plan.groupby("slot")["students"].sum().reindex(range(n_days * SLOTS_PER_DAY), fill_value=0)
    top = block(row_b, left, f"Busiest slot uses {per_slot.max() / seats:.0%} of all {seats:,} seats",
                "Share of all exam seats in use. Midday is kept light on purpose.")
    ws.write(top, left, "Day", head)
    ws.write_row(top, left + 1, PERIODS + ["Exam seats"], head_r)
    pct_cell = f(num_format="0%", align="center", font_color=INK)
    empty = f(align="center", font_color=MUTED)
    for d in range(n_days):
        row = top + 1 + d
        ws.write(row, left, f"Day {d + 1}", f(font_color=INK))
        for k in range(SLOTS_PER_DAY):
            used = per_slot[d * SLOTS_PER_DAY + k]
            ws.write(row, left + 1 + k, used / seats if used else "–", pct_cell if used else empty)
        day_total = int(per_slot[d * SLOTS_PER_DAY:(d + 1) * SLOTS_PER_DAY].sum())
        ws.write(row, left + 1 + SLOTS_PER_DAY, day_total, f(num_format="#,##0", font_color=MUTED))
    ws.conditional_format(top + 1, left + 1, top + n_days, left + SLOTS_PER_DAY,
                          {"type": "2_color_scale", "min_color": PINK, "max_color": MID,
                           "min_type": "num", "min_value": 0, "max_type": "num", "max_value": 1})
    ws.write(top + n_days + 1, left, "Empty: no exam in that slot. Exam seats count a student once per exam.", note)

    # --- row B, right: room use by type
    booked = plan.dropna(subset=["room"]).groupby("room type")[["students", "capacity"]].sum()
    booked = (booked["students"] / booked["capacity"]).sort_values(ascending=False)
    data.write_row(4, 0, ["Room type", "Seat use when booked"], head)
    for i, (kind, share) in enumerate(booked.items(), 5):
        data.write(i, 0, kind)
        data.write(i, 1, share, f(num_format="0%"))
    end = 4 + len(booked)
    top = block(row_b, right, f"Booked rooms are {plan['students'].sum() / plan['capacity'].sum():.0%} full on average",
                "Seats used as a share of seats in the rooms booked.")
    c = _chart(book, "bar", width, 240)
    c.add_series({"categories": ["Chart data", 5, 0, end, 0], "values": ["Chart data", 5, 1, end, 1],
                  "fill": {"color": NEUTRAL}, "gap": 90,
                  "data_labels": {"value": True, "num_format": "0%", "font": {"color": INK, "size": 10}}})
    c.set_x_axis({"visible": False, "major_gridlines": {"visible": False}, "min": 0, "max": 1})
    ws.insert_chart(top, right, c)
    data.set_column(0, 0, 22)
    data.set_column(1, 2, 20)


def save_report(kpis, tiles, plan, course_df, student_df, enrolments, results, seats, path):
    with pd.ExcelWriter(path, engine="xlsxwriter") as xw:
        book = xw.book
        title = book.add_format({"bold": True, "font_size": 14, "font_color": ACCENT})
        muted = book.add_format({"font_color": MUTED, "italic": True})
        head = book.add_format(HEADER)
        num = {"int": book.add_format({"num_format": "#,##0"}), "pct": book.add_format({"num_format": "0.0%"})}
        highlight = book.add_format({"bg_color": PINK})

        dashboard = book.add_worksheet("Dashboard")  # created first so it is the first tab

        ws = book.add_worksheet("KPI")
        ws.hide_gridlines(2)
        ws.write(0, 0, "Exam timetable report", title)
        ws.write(1, 0, f"{SOURCE}. Assumes {SLOTS_PER_DAY} exam slots per day; rooms are synthetic.", muted)
        ws.write_row(3, 0, ["Section", "Metric", "Value"], head)
        band = {"int": book.add_format({"num_format": "#,##0", "bg_color": TILE}),
                "pct": book.add_format({"num_format": "0.0%", "bg_color": TILE}),
                "text": book.add_format({"bg_color": TILE})}
        for row, (section, metric, value, fmt) in enumerate(kpis, 4):
            shaded = row % 2 == 1
            ws.write(row, 0, section, band["text"] if shaded else None)
            ws.write(row, 1, metric, band["text"] if shaded else None)
            ws.write(row, 2, value, band[fmt] if shaded else num[fmt])
        ws.set_column(0, 0, 12)
        ws.set_column(1, 1, 38)
        ws.set_column(2, 2, 12)

        ws = book.add_worksheet("Pivot")
        ws.write(0, 7, "Each cell is also the number of different students: nobody has two exams in one slot.", muted)
        ws.write(1, 7, "Row and column totals count a student once per exam, so they are exam seats, not students.", muted)

        ws = _table(xw, plan, "Timetable", {"fill": num["pct"]})
        last = len(plan)
        fill_col = plan.columns.get_loc("fill")
        ws.conditional_format(1, fill_col, last, fill_col,
                              {"type": "data_bar", "bar_color": BAR, "bar_solid": True, "min_type": "num",
                               "min_value": 0, "max_type": "num", "max_value": 1})

        _table(xw, course_df, "Courses").set_column(6, 6, 40)

        ws = _table(xw, student_df, "Students")
        n = len(student_df)
        ws.conditional_format(1, 3, n, 3, {"type": "cell", "criteria": ">=", "value": 2, "format": highlight})
        ws.conditional_format(1, 4, n, 4, {"type": "cell", "criteria": "==", "value": '"Yes"', "format": highlight})

        _table(xw, enrolments, "Enrolments")
        add_dashboard(book, dashboard, book.add_worksheet("Chart data"), tiles, plan, results, seats)

        # pivot over the Timetable sheet; Excel builds it when the file is opened
        xw.sheets["Pivot"].add_pivot_table(0, 0, {
            "source": f"Timetable!A1:{chr(ord('A') + len(plan.columns) - 1)}{last + 1}",
            "rows": ["Day"], "columns": ["Period"], "layout": "tabular", "style": "PivotStyleMedium1",
            "values": [{"field": "Students", "function": "sum", "name": "Exam seats", "num_format": "#,##0"}],
        })


if __name__ == "__main__":
    courses, students = load_dataset()
    m = conflict_matrix(students, len(courses))
    graph = conflict_graph(m)
    timetables = build_timetables(graph, students)
    results = compare(timetables, students)
    final = timetables["DSatur + day + period order"]

    rooms = make_rooms()
    plan = assign_rooms(final, courses, rooms)
    plan = plan.merge(rooms[["room", "type"]], on="room", how="left").rename(columns={"type": "room type"})
    plan["fill"] = plan["students"] / plan["capacity"]
    plan = plan[["day", "period", "slot", "course", "room", "room type", "capacity", "students", "fill"]]

    student_df = student_table(final, students)
    enrolments = pd.DataFrame([(f"S{i:05d}", c) for i, cs in enumerate(students, 1) for c in cs],
                              columns=["student", "course"])

    # the per-student sheet must agree with the timetable metrics
    r = results["DSatur + day + period order"]
    assert (student_df["most exams in a day"] >= 2).sum() == r["students 2+ exams/day"]
    assert (student_df["back-to-back"] == "Yes").sum() == r["students back-to-back"]
    assert plan["students"].sum() == len(enrolments) == courses["enrolled"].sum()

    metrics = room_metrics(plan, rooms)
    kpis = kpi_rows(courses, students, m, graph, results, metrics)
    before = results["DSatur"]
    tiles = [  # (label, value, number format)
        ("Students", len(students), "#,##0"),
        ("Exam days", r["days"], None),
        ("Timetable clashes", r["clashes"], None),
        ("Students with 2+ exams a day", r["students 2+ exams/day"] / before["students 2+ exams/day"] - 1, "0%"),
        ("Students with back-to-back exams", r["students back-to-back"] / before["students back-to-back"] - 1, "0%"),
        ("Unseated students", metrics["unseated students"], None),
    ]
    path = OUT_DIR / "exam_report.xlsx"
    save_report(kpis, tiles, plan, course_table(final, plan, courses), student_df, enrolments, results,
                metrics["seats"], path)
    print(f"Saved {path}")
