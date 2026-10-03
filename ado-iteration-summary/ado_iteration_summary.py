#!/usr/bin/env python3
"""
ado_iteration_summary.py

Fetches the CURRENT and NEXT iteration for a team in Azure DevOps and
summarizes:
  - total effort (sum of Effort / Story Points / Size) for all items
  - count of items broken down by work item type

Optionally (--previous N), also reports on the N most recent past
iterations: effort completed vs. still-open (leftover) items and effort.

Requires:
  - Azure CLI (`az`) installed
  - Azure DevOps extension: az extension add --name azure-devops
  - Authenticated: `az login` and, if needed, `az devops login --organization <org>`
    (or set env var AZURE_DEVOPS_EXT_PAT to a PAT with Work Items (Read) scope)

Usage:
    python ado_iteration_summary.py --org https://dev.azure.com/YourOrg --project YourProject
    python ado_iteration_summary.py --org https://dev.azure.com/YourOrg --project YourProject --team "YourTeam"
    python ado_iteration_summary.py --org https://dev.azure.com/YourOrg --project YourProject --effort-field "Microsoft.VSTS.Scheduling.StoryPoints"
    python ado_iteration_summary.py --org https://dev.azure.com/YourOrg --project YourProject --exclude-type "Feature" --exclude-type "Epic" --exclude-type "Bug"
    python ado_iteration_summary.py --org https://dev.azure.com/YourOrg --project YourProject --previous 3
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone

# Effort-like fields to try, in priority order. Different process templates
# (Scrum / Agile / CMMI) name this field differently.
DEFAULT_EFFORT_FIELDS = [
    "Microsoft.VSTS.Scheduling.Effort",
    "Microsoft.VSTS.Scheduling.StoryPoints",
    "Microsoft.VSTS.Scheduling.Size",
]

# Types that aren't relevant to sprint-level planning by default.
DEFAULT_EXCLUDED_TYPES = ["Feature", "Epic", "Task"]

# States treated as "done" when reviewing past iterations. Varies by process
# template (Agile: Closed/Resolved, Scrum: Done, CMMI: Closed).
DEFAULT_DONE_STATES = ["Closed", "Done", "Resolved", "Completed"]


def run_az(args, description):
    cmd = ["az"] + args + ["--output", "json"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"[error] {description} failed:\n{result.stderr.strip()}", file=sys.stderr)
        sys.exit(1)
    if not result.stdout.strip():
        return None
    return json.loads(result.stdout)


def get_default_team(org, project):
    teams = run_az(
        ["devops", "team", "list", "--org", org, "--project", project],
        "listing teams",
    )
    for t in teams:
        if t.get("isDefaultTeam"):
            return t["name"]
    return teams[0]["name"] if teams else None


def get_iterations(org, project, team):
    return run_az(
        ["boards", "iteration", "team", "list", "--org", org, "--project", project, "--team", team],
        "listing team iterations",
    )


def get_team_areas(org, project, team):
    """Return (path, include_children) tuples for the team's configured area paths.

    A shared Iteration Path alone doesn't scope work items to one team - Area
    Path does. Without this, a WIQL filter on IterationPath returns every
    team's items in that sprint.

    `az boards area team list` returns a single object (the team's field-value
    settings), with the actual area paths under its "values" list:
        {"defaultValue": "...", "field": {...}, "values": [{"value": "...", "includeChildren": bool}]}
    This parses that shape but falls back gracefully (with a warning, no
    crash) if a different shape shows up on some az CLI version.
    """
    raw = run_az(
        ["boards", "area", "team", "list", "--org", org, "--project", project, "--team", team],
        "listing team area paths",
    )

    if isinstance(raw, dict):
        entries = raw.get("values") or []
    elif isinstance(raw, list):
        entries = raw
    else:
        entries = []

    result = []
    for a in entries:
        if isinstance(a, str):
            path, include_children = a, True
        elif isinstance(a, dict):
            path = a.get("value") or a.get("path") or a.get("name") or ""
            include_children = a.get("includeChildren")
            if include_children is None:
                include_children = a.get("hasChildren", True)
        else:
            continue
        path = path.lstrip("\\")  # normalize to match System.AreaPath's own format
        if path:
            result.append((path, bool(include_children)))

    if raw and not result:
        print(
            "[warn] Could not parse team area paths from `az boards area team list` output "
            "(unexpected shape); proceeding without area-path filtering. "
            "Pass --no-area-filter to silence this warning.",
            file=sys.stderr,
        )
    return result


def build_area_clause(areas):
    if not areas:
        return ""
    parts = []
    for path, include_children in areas:
        escaped = path.replace("'", "''")
        if include_children:
            parts.append(f"[System.AreaPath] UNDER '{escaped}'")
        else:
            parts.append(f"[System.AreaPath] = '{escaped}'")
    return " AND (" + " OR ".join(parts) + ")"


def parse_dt(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def pick_current_and_next(iterations):
    """Return (current, next_it, dated, current_idx).

    dated is the full chronologically-sorted [(start_dt, finish_dt, iteration), ...]
    list, and current_idx is current's position within it - both are exposed
    so callers can also walk backwards for previous iterations.
    """
    now = datetime.now(timezone.utc)
    dated = []
    for it in iterations:
        attrs = it.get("attributes") or {}
        start, finish = attrs.get("startDate"), attrs.get("finishDate")
        if not start or not finish:
            continue
        dated.append((parse_dt(start), parse_dt(finish), it))
    dated.sort(key=lambda x: x[0])

    current, current_idx = None, None
    for i, (start_dt, finish_dt, it) in enumerate(dated):
        if start_dt <= now <= finish_dt:
            current, current_idx = it, i
            break

    if current is None:
        # Fall back to the API's own "current" flag, or the next upcoming one.
        for i, (start_dt, finish_dt, it) in enumerate(dated):
            if (it.get("attributes") or {}).get("timeFrame") == "current":
                current, current_idx = it, i
                break
    if current is None:
        for i, (start_dt, finish_dt, it) in enumerate(dated):
            if start_dt > now:
                current, current_idx = it, i
                break

    next_it = dated[current_idx + 1][2] if current_idx is not None and current_idx + 1 < len(dated) else None
    return current, next_it, dated, current_idx


def query_iteration_items(org, project, iteration_path, effort_fields, area_clause="", excluded_types=None):
    field_select = ",".join(
        ["[System.Id]", "[System.Title]", "[System.WorkItemType]", "[System.State]"]
        + [f"[{f}]" for f in effort_fields]
    )
    escaped_iteration = iteration_path.replace("'", "''")
    exclude_clause = ""
    if excluded_types:
        escaped_types = ", ".join(f"'{t.replace(chr(39), chr(39)+chr(39))}'" for t in excluded_types)
        exclude_clause = f" AND [System.WorkItemType] NOT IN ({escaped_types})"
    wiql = (
        f"SELECT {field_select} FROM WorkItems "
        f"WHERE [System.IterationPath] = '{escaped_iteration}' "
        f"AND [System.WorkItemType] <> ''"
        f"{exclude_clause}"
        f"{area_clause}"
    )
    items = run_az(
        ["boards", "query", "--org", org, "--project", project, "--wiql", wiql],
        f"querying items for iteration '{iteration_path}'",
    )
    return items or []


def summarize(items, effort_fields):
    by_type = {}
    total_effort = 0.0
    items_with_effort = 0
    items_missing_effort = []

    for item in items:
        fields = item.get("fields", item)  # az sometimes flattens fields to top level
        wtype = fields.get("System.WorkItemType", "Unknown")
        by_type[wtype] = by_type.get(wtype, 0) + 1

        effort = None
        for f in effort_fields:
            val = fields.get(f)
            if val is not None:
                effort = val
                break

        if effort is not None:
            total_effort += float(effort)
            items_with_effort += 1
        else:
            items_missing_effort.append(
                (fields.get("System.Id", item.get("id")), fields.get("System.Title", ""))
            )

    return {
        "count": len(items),
        "by_type": by_type,
        "total_effort": total_effort,
        "items_with_effort": items_with_effort,
        "items_missing_effort": items_missing_effort,
    }


def summarize_completion(items, effort_fields, done_states):
    """Like summarize(), but splits effort into completed vs. still-open (leftover),
    with leftover items grouped by state."""
    by_type = {}
    total_effort = 0.0
    completed_effort = 0.0
    completed_count = 0
    leftover_effort = 0.0
    leftover_count = 0
    leftover_by_state = {}  # state -> {"count": int, "effort": float}

    for item in items:
        fields = item.get("fields", item)
        wtype = fields.get("System.WorkItemType", "Unknown")
        state = fields.get("System.State", "")
        by_type[wtype] = by_type.get(wtype, 0) + 1

        effort = 0.0
        for f in effort_fields:
            val = fields.get(f)
            if val is not None:
                effort = float(val)
                break

        total_effort += effort
        if state in done_states:
            completed_effort += effort
            completed_count += 1
        else:
            leftover_effort += effort
            leftover_count += 1
            bucket = leftover_by_state.setdefault(state, {"count": 0, "effort": 0.0})
            bucket["count"] += 1
            bucket["effort"] += effort

    return {
        "count": len(items),
        "by_type": by_type,
        "total_effort": total_effort,
        "completed_effort": completed_effort,
        "completed_count": completed_count,
        "leftover_count": leftover_count,
        "leftover_effort": leftover_effort,
        "leftover_by_state": leftover_by_state,
    }


def print_leftover_by_state(leftover_by_state):
    for state, stats in sorted(leftover_by_state.items(), key=lambda x: -x[1]["count"]):
        print(f"    - {state}: {stats['count']} items, {stats['effort']:g} effort")


def print_iteration_report(label, iteration, summary, completion=None):
    print(f"\n=== {label}: {iteration.get('name', '(unknown)')} ===")
    attrs = iteration.get("attributes") or {}
    if attrs.get("startDate") and attrs.get("finishDate"):
        print(f"  {attrs['startDate'][:10]} → {attrs['finishDate'][:10]}")
    print(f"  Total items: {summary['count']}")
    print(f"  Total effort: {summary['total_effort']:g} "
          f"({summary['items_with_effort']}/{summary['count']} items had a value)")
    if completion:
        print(f"  Completed: {completion['completed_count']} items, {completion['completed_effort']:g} effort")
        if completion["leftover_count"]:
            print(f"  Not done: {completion['leftover_count']} items, {completion['leftover_effort']:g} effort remaining")
            print_leftover_by_state(completion["leftover_by_state"])
        else:
            print("  Not done: none - everything completed")
    if summary["by_type"]:
        print("  By type:")
        for wtype, n in sorted(summary["by_type"].items(), key=lambda x: -x[1]):
            print(f"    - {wtype}: {n}")
    if summary["items_missing_effort"]:
        print(f"  Items with no effort set ({len(summary['items_missing_effort'])}):")
        for wid, title in summary["items_missing_effort"]:
            print(f"    - #{wid} {title}")


def print_previous_iteration_report(iteration, summary):
    print(f"\n=== Previous iteration: {iteration.get('name', '(unknown)')} ===")
    attrs = iteration.get("attributes") or {}
    if attrs.get("startDate") and attrs.get("finishDate"):
        print(f"  {attrs['startDate'][:10]} → {attrs['finishDate'][:10]}")
    print(f"  Total items: {summary['count']} (total effort: {summary['total_effort']:g})")
    print(f"  Completed: {summary['completed_count']} items, {summary['completed_effort']:g} effort")
    if summary["leftover_count"]:
        print(f"  Not done: {summary['leftover_count']} items, {summary['leftover_effort']:g} effort remaining")
        print_leftover_by_state(summary["leftover_by_state"])
    else:
        print("  Not done: none - everything completed")
    if summary["by_type"]:
        print("  By type:")
        for wtype, n in sorted(summary["by_type"].items(), key=lambda x: -x[1]):
            print(f"    - {wtype}: {n}")


def main():
    parser = argparse.ArgumentParser(description="Summarize effort and item types for the current and next ADO iteration.")
    parser.add_argument("--org", required=True, help="Org URL, e.g. https://dev.azure.com/YourOrg")
    parser.add_argument("--project", required=True, help="Project name")
    parser.add_argument("--team", default=None, help="Team name (defaults to the project's default team)")
    parser.add_argument(
        "--effort-field",
        action="append",
        default=None,
        help="Field reference name to treat as effort (repeatable). Defaults to trying Effort, StoryPoints, Size in order.",
    )
    parser.add_argument(
        "--no-area-filter",
        action="store_true",
        help="Skip filtering by the team's area path(s) - returns all teams' items in the iteration.",
    )
    parser.add_argument(
        "--exclude-type",
        action="append",
        default=None,
        help="Work item type to exclude (repeatable). Defaults to excluding Feature and Epic.",
    )
    parser.add_argument(
        "--no-exclude-types",
        action="store_true",
        help="Don't exclude any types - include Feature/Epic and everything else.",
    )
    parser.add_argument(
        "--previous",
        type=int,
        default=0,
        metavar="N",
        help="Also report on the N most recent past iterations: effort completed and any leftover (not-done) items/effort.",
    )
    parser.add_argument(
        "--done-state",
        action="append",
        default=None,
        help="State name that counts as 'done' for --previous (repeatable). Defaults to Closed, Done, Resolved, Completed.",
    )
    args = parser.parse_args()

    effort_fields = args.effort_field or DEFAULT_EFFORT_FIELDS
    excluded_types = [] if args.no_exclude_types else (args.exclude_type or DEFAULT_EXCLUDED_TYPES)
    done_states = args.done_state or DEFAULT_DONE_STATES

    team = args.team or get_default_team(args.org, args.project)
    if not team:
        print("[error] Could not determine a team. Pass --team explicitly.", file=sys.stderr)
        sys.exit(1)

    iterations = get_iterations(args.org, args.project, team)
    if not iterations:
        print("[error] No iterations found for this team.", file=sys.stderr)
        sys.exit(1)

    current, next_it, dated, current_idx = pick_current_and_next(iterations)
    if not current:
        print("[error] Could not determine a current iteration.", file=sys.stderr)
        sys.exit(1)

    areas = [] if args.no_area_filter else get_team_areas(args.org, args.project, team)
    area_clause = build_area_clause(areas)

    print(f"Org: {args.org} | Project: {args.project} | Team: {team}")

    current_items = query_iteration_items(args.org, args.project, current["path"], effort_fields, area_clause, excluded_types)
    current_summary = summarize(current_items, effort_fields)
    current_completion = summarize_completion(current_items, effort_fields, done_states)
    print_iteration_report("Current iteration", current, current_summary, completion=current_completion)

    if next_it:
        next_items = query_iteration_items(args.org, args.project, next_it["path"], effort_fields, area_clause, excluded_types)
        next_summary = summarize(next_items, effort_fields)
        print_iteration_report("Next iteration", next_it, next_summary)
    else:
        print("\n=== Next iteration ===\n  No future iteration found under this team's iterations.")

    if args.previous > 0:
        if current_idx is None or current_idx == 0:
            print(f"\n=== Previous iterations ===\n  No past iterations found under this team's iterations.")
        else:
            start = max(0, current_idx - args.previous)
            previous_slice = dated[start:current_idx]
            for _, _, iteration in reversed(previous_slice):  # most recent first
                items = query_iteration_items(args.org, args.project, iteration["path"], effort_fields, area_clause, excluded_types)
                summary = summarize_completion(items, effort_fields, done_states)
                print_previous_iteration_report(iteration, summary)


if __name__ == "__main__":
    main()
