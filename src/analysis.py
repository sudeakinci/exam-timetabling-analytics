from itertools import combinations

import matplotlib.pyplot as plt
import networkx as nx
import numpy as np
import pandas as pd
import textwrap

from matplotlib.colors import LinearSegmentedColormap, LogNorm
from matplotlib.patches import Patch

from load_data import DATA_DIR, load_courses, load_students

OUT_DIR = DATA_DIR.parent.parent / "outputs"
SOURCE = "Data: Toronto exam timetabling benchmark, car-s-91"

# bordeaux marks the focus group, gray is everything else
ACCENT, NEUTRAL = "#9b2348", "#8f8d86"
INK, MUTED, GRID, TILE = "#0b0b0b", "#52514e", "#e4e3df", "#f4f3f0"
# group matrix ramp; ACCENT is one of its steps so the colors match across charts
BORDEAUX = LinearSegmentedColormap.from_list(
    "bordeaux", ["#f7e8ec", "#e5b3c1", "#c86a85", ACCENT, "#5e0f29"]
).with_extremes(bad="white")

plt.rcParams.update({
    "font.family": ["Helvetica Neue", "Arial", "DejaVu Sans"],
    "font.size": 10,
    "axes.edgecolor": GRID,
    "axes.labelcolor": MUTED,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.axisbelow": True,
    "axes.grid": True,
    "grid.color": GRID,
    "xtick.color": MUTED,
    "ytick.color": MUTED,
    "xtick.major.size": 0,
    "ytick.major.size": 0,
})


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


def course_groups(m):
    """Group courses that share a lot of students (Louvain). Largest group first."""
    graph = nx.from_numpy_array(m[1:, 1:])  # node i is course i + 1
    groups = nx.community.louvain_communities(graph, weight="weight", seed=0)  # fixed seed, same groups every run
    return [sorted(n + 1 for n in g) for g in sorted(groups, key=len, reverse=True)]


def within_group_share(m, groups):
    """Share of all student overlap that stays inside a group."""
    label = np.zeros(len(m), dtype=int)
    for i, g in enumerate(groups):
        label[g] = i
    same = label[:, None] == label[None, :]
    return m[same].sum() / m.sum()




def label_groups(stats, groups):
    """Add a 'group' column, 1 = largest group."""
    group_of = {c: i + 1 for i, g in enumerate(groups) for c in g}
    return stats.assign(group=stats["course"].map(group_of))


def group_summary(stats):
    """Courses, enrollments and their shares per group."""
    summary = stats.groupby("group").agg(courses=("course", "size"), enrolled=("enrolled", "sum"))
    summary["course_share"] = summary["courses"] / summary["courses"].sum()
    summary["enrolled_share"] = summary["enrolled"] / summary["enrolled"].sum()
    return summary


# charts: each plot_* draws on a given ax, so it works alone or as a dashboard panel

def _note(ax, text, y, **kw):
    # y in points from the top (y > 0) or bottom (y < 0) of the axes
    ax.annotate(text, (0, 1 if y > 0 else 0), xycoords="axes fraction",
                xytext=(0, y), textcoords="offset points", **kw)


def _titles(ax, title, subtitle, small=False):
    _note(ax, title, 26 if small else 30, fontsize=11 if small else 13, fontweight="bold", color=INK)
    _note(ax, subtitle, 10 if small else 12, fontsize=9 if small else 10, color=MUTED)


def _legend(ax, focus, loc="upper right"):
    handles = [Patch(color=ACCENT, label=f"group {focus}"), Patch(color=NEUTRAL, label="other groups")]
    ax.legend(handles=handles, loc=loc, frameon=False, labelcolor=INK)


def _hist(ax, stats, col, xlabel, focus):
    ax.grid(axis="x", visible=False)
    in_focus = stats["group"] == focus
    ax.hist([stats.loc[~in_focus, col], stats.loc[in_focus, col]], bins=40, stacked=True,
            color=[NEUTRAL, ACCENT], edgecolor="white", linewidth=1)

    median = stats[col].median()
    top_y = ax.get_ylim()[1]
    ax.axvline(median, color=INK, linewidth=1, linestyle=(0, (4, 3)))
    ax.text(median, top_y * 0.97, f"  median {median:.0f}", color=INK, va="top")

    # the max sits in a bar of height 1, too small to notice without a pointer
    top = stats.loc[stats[col].idxmax()]
    ax.annotate(f"course {top.course}: {top[col]:,}", xy=(top[col], 1), xytext=(top[col], top_y * 0.35),
                ha="right", color=INK, arrowprops=dict(arrowstyle="-", color=MUTED, lw=1))

    ax.set(xlabel=xlabel, ylabel="Number of courses")
    ax.xaxis.set_major_formatter("{x:,.0f}")
    _legend(ax, focus)


def plot_enrolled(ax, stats, focus, small=False):
    _hist(ax, stats, "enrolled", "Students enrolled", focus)
    under_100 = (stats["enrolled"] < 100).mean()
    _titles(ax, "Most courses are small, a few are huge",
            f"{under_100:.0%} of courses have under 100 students; the largest has {stats.enrolled.max():,}", small)


def plot_conflicts(ax, stats, focus, small=False):
    _hist(ax, stats, "conflicts", "Number of other courses it shares students with", focus)
    in_focus = stats["group"] == focus
    _titles(ax, f"Group {focus} courses clash with more of the timetable",
            f"Median {stats.loc[in_focus, 'conflicts'].median():.0f} clashing courses in group {focus}, "
            f"{stats.loc[~in_focus, 'conflicts'].median():.0f} elsewhere", small)


def plot_scatter(ax, stats, focus, small=False):
    in_focus = stats["group"] == focus
    ax.scatter(stats.loc[~in_focus, "enrolled"], stats.loc[~in_focus, "conflicts"],
               s=14, color=NEUTRAL, alpha=0.5, linewidths=0)
    ax.scatter(stats.loc[in_focus, "enrolled"], stats.loc[in_focus, "conflicts"],
               s=16, color=ACCENT, alpha=0.75, linewidths=0)

    biggest = stats.loc[stats["enrolled"].idxmax()]
    hardest = stats.loc[stats["conflicts"].idxmax()]
    for row, dx, ha in [(hardest, 10, "left"), (biggest, -10, "right")]:
        ax.scatter(row.enrolled, row.conflicts, s=50, color=ACCENT if row.group == focus else NEUTRAL,
                   edgecolors=INK, linewidths=1, zorder=3)
        ax.annotate(f"course {row.course}\n{row.enrolled:,} students, {row.conflicts} clashes",
                    (row.enrolled, row.conflicts), xytext=(dx, 0), textcoords="offset points",
                    ha=ha, va="center", color=INK)
    ax.set(xlabel="Students enrolled", ylabel="Number of clashing courses")
    ax.xaxis.set_major_formatter("{x:,.0f}")
    _legend(ax, focus, loc="lower right")
    _titles(ax, "Bigger courses aren't always harder to schedule",
            f"Course {hardest.course} has fewer students than course {biggest.course} "
            "but clashes with more courses", small)


def plot_bottleneck(ax, stats, focus, small=False):
    top10 = stats.head(10).iloc[::-1]  # barh draws bottom-up, so reverse to put the hardest on top
    colors = np.where(top10["group"] == focus, ACCENT, NEUTRAL)
    ax.grid(axis="y", visible=False)
    labels = [f"course {c}  ({e:,} students)" for c, e in zip(top10["course"], top10["enrolled"])]
    bars = ax.barh(labels, top10["conflicts"], height=0.6, color=colors)
    ax.bar_label(bars, padding=4, color=INK)
    ax.set(xlabel="Number of clashing courses")
    ax.spines["left"].set_visible(False)
    _legend(ax, focus, loc="lower right")
    _titles(ax, f"{(top10.group == focus).sum()} of the 10 hardest courses are in group {focus}",
            f"Courses that clash with the most others, out of {len(stats)}", small)


def plot_groups(ax, stats, focus, small=False):
    summary = group_summary(stats)
    main = summary[summary["courses"] >= 10].iloc[::-1]
    colors = np.where(main.index == focus, ACCENT, NEUTRAL)
    ax.grid(axis="y", visible=False)
    labels = [f"group {g}  ({n} courses)" for g, n in zip(main.index, main["courses"])]
    bars = ax.barh(labels, main["enrolled_share"] * 100, height=0.6, color=colors)
    ax.bar_label(bars, labels=[f"{v:.0%}" for v in main["enrolled_share"]], padding=4, color=INK)
    ax.set(xlabel="Share of all exam enrollments (%)")
    ax.spines["left"].set_visible(False)
    f = summary.loc[focus]
    _titles(ax, f"Group {focus} holds {f.enrolled_share:.0%} of all exam enrollments",
            f"with only {f.course_share:.0%} of the courses", small)


def group_matrix(m, groups):
    """Exam pairs that share a student, summed between each pair of main groups."""
    main = [g for g in groups if len(g) >= 10]
    out = np.zeros((len(main), len(main)), dtype=int)
    for i, a in enumerate(main):
        for j, b in enumerate(main):
            out[i, j] = m[np.ix_(a, b)].sum()
    out[np.diag_indices(len(main))] //= 2  # inside a group every pair is counted from both sides
    return out


def plot_group_matrix(ax, m, groups, focus, small=False):
    g = group_matrix(m, groups)
    n = len(g)
    norm = LogNorm(vmin=g[g > 0].min(), vmax=g.max())  # log so the off-diagonal cells still show some color
    ax.imshow(g, cmap=BORDEAUX, norm=norm)

    for i in range(n):
        for j in range(n):
            ax.text(j, i, f"{g[i, j]:,}", ha="center", va="center", fontsize=9 if small else 10,
                    color="white" if norm(g[i, j]) > 0.6 else INK)

    labels = [f"group {i + 1}" for i in range(n)]
    ax.set_xticks(range(n), labels)
    ax.set_yticks(range(n), labels)
    for label in (ax.get_xticklabels()[focus - 1], ax.get_yticklabels()[focus - 1]):
        label.set_fontweight("bold")
        label.set_color(INK)

    # white lines between cells
    ax.grid(False)
    ax.set_xticks(np.arange(n + 1) - 0.5, minor=True)
    ax.set_yticks(np.arange(n + 1) - 0.5, minor=True)
    ax.grid(which="minor", color="white", linewidth=2)
    ax.tick_params(which="minor", size=0)
    for spine in ax.spines.values():
        spine.set_visible(False)

    inside = np.trace(g) / np.triu(g).sum()
    _titles(ax, "Most clashes happen inside a group",
            f"Exam pairs that share a student, by group. {inside:.0%} are on the diagonal", small)


def key_findings(stats, m, groups, focus):
    f = group_summary(stats).loc[focus]
    in_top10 = (stats.head(10)["group"] == focus).sum()
    return [
        f"Group {focus} has {f.course_share:.0%} of the courses but {f.enrolled_share:.0%} of all exam enrollments.",
        f"{in_top10} of the 10 hardest-to-schedule courses are in group {focus}.",
        f"{within_group_share(m, groups):.0%} of student overlap stays inside a group, "
        "so clashes are mostly local to a group.",
    ]


def save_plots(stats, m, groups, focus, out_dir):
    """Save each chart as its own PNG."""
    charts = [
        ("enrolled_hist", lambda ax: plot_enrolled(ax, stats, focus), (8, 4.5)),
        ("conflicts_hist", lambda ax: plot_conflicts(ax, stats, focus), (8, 4.5)),
        ("enrolled_vs_conflicts", lambda ax: plot_scatter(ax, stats, focus), (8, 5)),
        ("bottleneck_courses", lambda ax: plot_bottleneck(ax, stats, focus), (8, 4.5)),
        ("course_groups", lambda ax: plot_groups(ax, stats, focus), (8, 4)),
        ("group_matrix", lambda ax: plot_group_matrix(ax, m, groups, focus), (7, 6)),
    ]
    for name, draw, size in charts:
        fig, ax = plt.subplots(figsize=size)
        draw(ax)
        _note(ax, SOURCE, -50, fontsize=8, color=MUTED, va="top")
        fig.savefig(out_dir / f"{name}.png", dpi=150, bbox_inches="tight", facecolor="white")
        plt.close(fig)


def _tile(ax):
    ax.set_facecolor(TILE)
    ax.grid(False)
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)


def save_dashboard(stats, m, groups, focus, kpis, path):
    """One-page summary: KPIs, key findings, six charts."""
    fig = plt.figure(figsize=(16, 21))
    # header and charts get their own grids so their spacing can differ
    outer = fig.add_gridspec(2, 1, height_ratios=[0.36, 2.6], hspace=0.14)
    header = outer[0].subgridspec(2, 1, height_ratios=[1, 1.5], hspace=0.2)
    grid = outer[1].subgridspec(3, 2, height_ratios=[1, 0.8, 0.8], hspace=0.42, wspace=0.32)

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
    for i, text in enumerate(key_findings(stats, m, groups, focus)):
        x = 0.015 + i * 0.33
        ax.text(x, 0.55, str(i + 1), transform=ax.transAxes, fontsize=20, fontweight="bold", color=ACCENT, va="top")
        ax.text(x + 0.025, 0.53, textwrap.fill(text, 48), transform=ax.transAxes, fontsize=11,
                color=INK, va="top", linespacing=1.4)

    plot_group_matrix(fig.add_subplot(grid[0, 0]), m, groups, focus, small=True)
    plot_groups(fig.add_subplot(grid[0, 1]), stats, focus, small=True)
    plot_bottleneck(fig.add_subplot(grid[1, 0]), stats, focus, small=True)
    plot_scatter(fig.add_subplot(grid[1, 1]), stats, focus, small=True)
    plot_enrolled(fig.add_subplot(grid[2, 0]), stats, focus, small=True)
    last = fig.add_subplot(grid[2, 1])
    plot_conflicts(last, stats, focus, small=True)
    _note(last, SOURCE, -50, fontsize=9, color=MUTED, va="top")

    fig.savefig(path, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)


if __name__ == "__main__":
    courses = load_courses(DATA_DIR / "car-s-91.crs")
    students = load_students(DATA_DIR / "car-s-91.stu")
    n = len(courses)

    m = conflict_matrix(students, n)
    conflicting_pairs = (np.triu(m, k=1) > 0).sum()
    total_pairs = n * (n - 1) // 2
    density = conflicting_pairs / total_pairs
    print(f"Conflicting course pairs: {conflicting_pairs} / {total_pairs} (density {density:.3f})")

    print("\nTop 10 pairs by shared students:")
    print(top_pairs(m).to_string(index=False))

    groups = course_groups(m)
    stats = label_groups(course_stats(courses, m), groups)
    print("\nTop 10 courses by number of conflicts:")
    print(stats.head(10).to_string(index=False))

    # the group most of the hardest courses belong to
    focus = stats.head(10)["group"].mode()[0]
    print(f"\nCourse groups (Louvain): {[len(g) for g in groups]}, focus group: {focus}")
    print(f"Student overlap inside groups: {within_group_share(m, groups):.1%}")
    print(group_summary(stats).round(3).to_string())

    enrollments = courses["enrolled"].sum()
    kpis = {
        "Courses": f"{n:,}",
        "Students": f"{len(students):,}",
        "Exam enrollments": f"{enrollments:,}",
        "Exams per student (avg)": f"{enrollments / len(students):.1f}",
        "Course pairs that clash": f"{density:.1%}",
    }

    save_plots(stats, m, groups, focus, OUT_DIR)
    save_dashboard(stats, m, groups, focus, kpis, OUT_DIR / "dashboard.png")
    print(f"\nCharts saved to {OUT_DIR}")
