import textwrap

from analysis import (
    ACCENT, INK, MUTED, OUT_DIR, SOURCE, TILE, _note, clash_density, group_summary, plot_bottleneck,
    plot_conflicts, plot_enrolled, plot_group_matrix, plot_groups, plot_scatter, plt, summarize,
    within_group_share,
)
from load_data import DATA_DIR, load_courses, load_students
from scheduler import build_timetables, compare, conflict_graph, plot_comparison


def key_findings(stats, m, groups, focus, results):
    f = group_summary(stats).loc[focus]
    in_top10 = (stats.head(10)["group"] == focus).sum()
    before = results["DSatur"]["students 2+ exams/day"]
    after = results["DSatur + day + period order"]["students 2+ exams/day"]
    return [
        f"Group {focus} has {f.course_share:.0%} of the courses but {f.enrolled_share:.0%} of all exam enrollments.",
        f"{in_top10} of the 10 hardest-to-schedule courses are in group {focus}.",
        f"{within_group_share(m, groups):.0%} of student overlap stays inside a group.",
        f"Moving slots between days cut students with 2+ exams a day by {1 - after / before:.0%}.",
    ]


def _tile(ax):
    ax.set_facecolor(TILE)
    ax.grid(False)
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)


def save_dashboard(stats, m, groups, focus, results, kpis, path):
    """One-page summary: KPIs, key findings, six analysis charts and the timetable comparison."""
    fig = plt.figure(figsize=(16, 26))
    # header, charts and comparison get their own grids; rows 1 and 3 are fixed gaps
    outer = fig.add_gridspec(5, 1, height_ratios=[0.42, 0.14, 2.6, 0.32, 0.42], hspace=0)
    header = outer[0].subgridspec(2, 1, height_ratios=[1, 1.9], hspace=0.2)
    grid = outer[2].subgridspec(3, 2, height_ratios=[1, 0.8, 0.8], hspace=0.45, wspace=0.32)

    tiles = header[0].subgridspec(1, len(kpis), wspace=0.06)
    for i, (label, value) in enumerate(kpis.items()):
        ax = fig.add_subplot(tiles[i])
        _tile(ax)
        ax.text(0.07, 0.55, value, transform=ax.transAxes, fontsize=22, fontweight="bold", color=INK)
        ax.text(0.07, 0.2, label, transform=ax.transAxes, color=MUTED)
        if i == 0:
            _note(ax, "Exam conflict analysis", 48, fontsize=22, fontweight="bold", color=INK)
            _note(ax, "Personal project on a public benchmark dataset (car-s-91, Toronto exam timetabling "
                      "benchmark). Course ids are anonymised.", 26, fontsize=11, color=MUTED)

    ax = fig.add_subplot(header[1])
    _tile(ax)
    ax.text(0.015, 0.78, "Key findings", transform=ax.transAxes, fontsize=13, fontweight="bold", color=INK)
    findings = key_findings(stats, m, groups, focus, results)
    for i, text in enumerate(findings):
        x = 0.015 + i / len(findings)
        ax.text(x, 0.55, str(i + 1), transform=ax.transAxes, fontsize=20, fontweight="bold", color=ACCENT, va="top")
        ax.text(x + 0.022, 0.53, textwrap.fill(text, 36), transform=ax.transAxes, fontsize=11,
                color=INK, va="top", linespacing=1.4)

    plot_group_matrix(fig.add_subplot(grid[0, 0]), m, groups, focus, small=True)
    plot_groups(fig.add_subplot(grid[0, 1]), stats, focus, small=True)
    plot_bottleneck(fig.add_subplot(grid[1, 0]), stats, focus, small=True)
    plot_scatter(fig.add_subplot(grid[1, 1]), stats, focus, small=True)
    plot_enrolled(fig.add_subplot(grid[2, 0]), stats, focus, small=True)
    plot_conflicts(fig.add_subplot(grid[2, 1]), stats, focus, small=True)

    panels = outer[4].subgridspec(1, 3, wspace=0.08)
    axes = [fig.add_subplot(panels[i]) for i in range(3)]
    for ax in axes[1:]:
        ax.sharey(axes[0])
    plot_comparison(axes, results, small=True)
    _note(axes[0], SOURCE, -20, fontsize=9, color=MUTED, va="top")

    fig.savefig(path, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)


if __name__ == "__main__":
    courses = load_courses(DATA_DIR / "car-s-91.crs")
    students = load_students(DATA_DIR / "car-s-91.stu")
    m, stats, groups, focus = summarize(courses, students)
    results = compare(build_timetables(conflict_graph(m), students), students)

    enrollments = courses["enrolled"].sum()
    final = results["DSatur + day + period order"]
    kpis = {
        "Courses": f"{len(courses):,}",
        "Students": f"{len(students):,}",
        "Exam enrollments": f"{enrollments:,}",
        "Course pairs that clash": f"{clash_density(m):.1%}",
        "Exam days needed": f"{final['days']}",
        "Timetable clashes": f"{final['clashes']}",
    }
    save_dashboard(stats, m, groups, focus, results, kpis, OUT_DIR / "dashboard.png")
    print(f"Dashboard saved to {OUT_DIR / 'dashboard.png'}")
