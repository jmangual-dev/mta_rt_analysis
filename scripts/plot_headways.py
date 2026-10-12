"""
Plot median and p90 headway by hour of day for one platform and route.

Reads the `headways` view directly so the chart is reproducible from the
database rather than a screenshot. Times are America/New_York. Headways over
120 minutes are excluded as collection gaps (see docs/decisions.md).

Weekdays are the default because weekday and weekend service run on different
timetables; mixing them blurs the rush-hour pattern the chart exists to show.

Usage:
    python scripts/plot_headways.py                         # 1 train, 96 St southbound, weekdays
    python scripts/plot_headways.py --stop 127N --route 2   # 2 train, Times Sq northbound
    python scripts/plot_headways.py --stop 631S --route 6 --days weekend
    python scripts/plot_headways.py --list 4                # stop IDs served by the 4
"""

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import psycopg

DSN = "dbname=mta_rt"
MIN_SAMPLES = 10  # hours with fewer headways than this are too noisy for a p90

DAY_FILTERS = {
    "weekday": "BETWEEN 1 AND 5",
    "weekend": "IN (6, 7)",
    "all": "BETWEEN 1 AND 7",
}

QUERY = """
SELECT extract(hour FROM departed_at AT TIME ZONE 'America/New_York')::int AS hour,
       count(*) AS n,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY headway_minutes) AS median,
       percentile_cont(0.9) WITHIN GROUP (ORDER BY headway_minutes) AS p90
FROM headways
WHERE stop_id = %(stop)s
  AND route_id = %(route)s
  AND headway_minutes <= 120
  AND extract(isodow FROM departed_at AT TIME ZONE 'America/New_York') {days}
GROUP BY 1
ORDER BY 1;
"""

LIST_QUERY = """
SELECT d.stop_id, coalesce(s.stop_name, '?') AS stop_name, count(*) AS departures
FROM departures d
LEFT JOIN stops s ON s.stop_id = d.stop_id
WHERE d.route_id = %s AND d.trip_type = '0'
GROUP BY 1, 2
ORDER BY 1;
"""

# Colors: categorical slots 1 and 2 from the reference palette, validated
# for CVD separation and contrast on the light surface.
SURFACE = "#fcfcfb"
TEXT = "#0b0b0b"
TEXT_MUTED = "#52514e"
GRID = "#e4e3df"
MEDIAN_COLOR = "#2a78d6"
P90_COLOR = "#eb6834"


def fetch(stop, route, days):
    sql = QUERY.format(days=DAY_FILTERS[days])
    with psycopg.connect(DSN) as conn:
        return conn.execute(sql, {"stop": stop, "route": route}).fetchall()


def list_stops(route):
    with psycopg.connect(DSN) as conn:
        rows = conn.execute(LIST_QUERY, (route,)).fetchall()
    if not rows:
        print(f"no departures found for route {route!r}")
        return
    print(f"{'stop_id':<8} {'departures':>10}  station")
    for stop_id, name, n in rows:
        print(f"{stop_id:<8} {n:>10,}  {name}")


def station_name(stop):
    with psycopg.connect(DSN) as conn:
        row = conn.execute(
            "SELECT stop_name FROM stops WHERE stop_id = %s", (stop,)
        ).fetchone()
    return row[0] if row else stop


def plot(rows, title, subtitle, days, ymax, out):
    rows = [r for r in rows if r[1] >= MIN_SAMPLES]
    if not rows:
        raise SystemExit(
            f"headways exist here, but no hour has {MIN_SAMPLES}+ of "
            "them; try --days all or a busier stop (see --list)"
        )
    hours = [r[0] for r in rows]
    medians = [float(r[2]) for r in rows]
    p90s = [float(r[3]) for r in rows]
    total_n = sum(r[1] for r in rows)

    # One outlier hour (often thin overnight data) would otherwise flatten the
    # whole chart. Values above the cap sit on the top edge and are labelled
    # with their true value, so nothing is hidden.
    cap = ymax or max(p90s) * 1.12
    clipped = [(h, v) for h, v in zip(hours * 2, p90s + medians) if v > cap]

    fig, ax = plt.subplots(figsize=(10, 5.2), dpi=150)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)

    for series, color, label in (
        (p90s, P90_COLOR, "p90 (1 in 10 waits is longer)"),
        (medians, MEDIAN_COLOR, "Median"),
    ):
        # Plot on the full 0-23 grid with NaN where an hour has no data, so
        # the line breaks across hours the route doesn't run instead of
        # drawing a straight line through them.
        by_hour = dict(zip(hours, series))
        y = [min(by_hour[h], cap) if h in by_hour else float("nan") for h in range(24)]
        ax.plot(
            range(24),
            y,
            color=color,
            linewidth=2,
            marker="o",
            markersize=5,
            markeredgecolor=SURFACE,
            markeredgewidth=1.5,
            label=label,
            clip_on=False,
        )

    for h, v in clipped:
        ax.annotate(
            f"{v:.0f} min ↑",
            xy=(h, cap),
            xytext=(6, -2),
            textcoords="offset points",
            va="top",
            fontsize=8,
            color=TEXT,
        )

    # Direct labels at the right end, in text ink, so identity is not color-alone.
    # If the two end values sit close together, nudge the labels apart.
    gap = abs(min(p90s[-1], cap) - min(medians[-1], cap))
    nudge = 7 if gap < cap * 0.06 else 0
    for series, name, dy in ((p90s, "p90", nudge), (medians, "median", -nudge)):
        last = series[-1]
        ax.annotate(
            f"{name} {last:.1f}",
            xy=(hours[-1], min(last, cap)),
            xytext=(8, dy),
            textcoords="offset points",
            va="center",
            fontsize=9,
            color=TEXT,
        )

    ax.set_xlim(-0.5, 23.5)
    ax.set_ylim(0, cap)
    ax.set_xticks(range(0, 24, 3))
    ax.set_xticklabels(
        [f"{h % 12 or 12}{'am' if h < 12 else 'pm'}" for h in range(0, 24, 3)]
    )
    day_label = {"weekday": "weekdays", "weekend": "weekends", "all": "all days"}[days]
    ax.set_ylabel("Minutes between trains", color=TEXT_MUTED, fontsize=10)
    ax.set_xlabel(
        f"Hour of departure ({day_label}, Eastern)", color=TEXT_MUTED, fontsize=10
    )

    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(colors=TEXT_MUTED, labelsize=9, length=0)

    fig.text(
        0.06,
        0.955,
        title,
        ha="left",
        va="top",
        fontsize=14,
        fontweight="bold",
        color=TEXT,
    )
    fig.text(0.06, 0.895, subtitle, ha="left", va="top", fontsize=10, color=TEXT_MUTED)
    fig.legend(
        loc="upper right",
        bbox_to_anchor=(0.97, 0.965),
        frameon=False,
        fontsize=9,
        ncol=2,
        labelcolor=TEXT,
    )
    note = (
        f"n = {total_n:,} observed headways. Hours with fewer than "
        f"{MIN_SAMPLES} excluded. Headways over 120 min treated as "
        "collection gaps."
    )
    if clipped:
        note += f" Values above {cap:.0f} min shown at the top edge."
    fig.text(0.06, 0.01, note, fontsize=8, color=TEXT_MUTED)

    fig.tight_layout(rect=(0, 0.03, 1, 0.84))
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, facecolor=SURFACE)
    print(f"wrote {out}  ({len(rows)} hours, n={total_n}, {len(clipped)} clipped)")


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--stop", default="120S", help="station + direction, e.g. 120S (see --list)"
    )
    parser.add_argument("--route", default="1")
    parser.add_argument("--days", choices=DAY_FILTERS, default="weekday")
    parser.add_argument(
        "--ymax",
        type=float,
        default=40,
        help="y-axis cap in minutes; 0 to fit the data",
    )
    parser.add_argument(
        "--list", metavar="ROUTE", help="print the stop IDs served by ROUTE and exit"
    )
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    if args.list:
        list_stops(args.list)
        return

    suffix = "" if args.days == "weekday" else f"_{args.days}"
    out = args.out or f"docs/img/headways_{args.stop}_{args.route}{suffix}.png"
    direction = {"N": "northbound", "S": "southbound"}.get(args.stop[-1], "")
    name = station_name(args.stop[:-1]) if direction else station_name(args.stop)
    title = f"The {args.route} train at {name} {direction}".strip()
    subtitle = "Median and p90 headway by hour, observed from the MTA real-time feed"
    rows = fetch(args.stop, args.route, args.days)
    if not rows:
        raise SystemExit(
            f"route {args.route} has no {args.days} headways at {args.stop}. "
            f"Check the stop with: python scripts/plot_headways.py --list {args.route}"
        )
    plot(rows, title, subtitle, args.days, args.ymax, out)


if __name__ == "__main__":
    main()
