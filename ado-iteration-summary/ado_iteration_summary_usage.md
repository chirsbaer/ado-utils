# ADO Iteration Summary — Usage

Fetches the **current** and **next** iteration for a team in Azure DevOps and summarizes total effort and item-type counts for each. Optionally also reviews the N most recent **past** iterations, showing effort completed vs. left over.

## Prerequisites

```bash
az extension add --name azure-devops   # if not already installed
az login
az devops login --organization https://dev.azure.com/YourOrg   # paste a PAT if prompted
```

The PAT (or your `az login` session) needs **Work Items (Read)** scope at minimum.

## Basic usage

```bash
python ado_iteration_summary.py --org https://dev.azure.com/YourOrg --project YourProject
```

## Optional flags

| Flag | Purpose | Default |
|---|---|---|
| `--team "YourTeam"` | Which team's iterations to use | Project's default team |
| `--effort-field "Microsoft.VSTS.Scheduling.StoryPoints"` | Field(s) to treat as effort; repeatable | Tries `Effort` → `StoryPoints` → `Size`, in that order |
| `--no-area-filter` | Skip filtering by the team's area path(s); returns every team's items in that iteration | Off (area filter applied) |
| `--exclude-type "Bug"` | Work item type to exclude; repeatable | Excludes `Feature` and `Epic` |
| `--no-exclude-types` | Don't exclude anything, including Feature/Epic | Off |
| `--previous N` | Also report on the N most recent past iterations | Off (0) |
| `--done-state "Closed"` | State name counted as "done" for `--previous`; repeatable | `Closed`, `Done`, `Resolved`, `Completed` |

Example reviewing the last 3 sprints:

```bash
python ado_iteration_summary.py \
  --org https://dev.azure.com/YourOrg \
  --project YourProject \
  --previous 3
```

Example with both:

```bash
python ado_iteration_summary.py \
  --org https://dev.azure.com/YourOrg \
  --project YourProject \
  --team "Ekonomi" \
  --effort-field "Microsoft.VSTS.Scheduling.StoryPoints"
```

## What it does

1. Lists the team's iterations (`az boards iteration team list`), picks the one covering today's date as current, and the chronologically next one as next.
2. Looks up the team's area path(s) (`az boards area team list`), since Iteration Path is often shared across teams on the same sprint calendar — Area Path is what actually scopes items to a team.
3. Runs a WIQL query scoped to each iteration's path **and** the team's area path(s), excluding `Feature`/`Epic` by default, pulling id, title, type, state, and effort field(s).
4. Prints per iteration (current/next):
   - Date range
   - Total item count
   - Summed effort, with a note on how many items had a value set
   - **Current iteration only:** completed items/effort, and not-done items/effort remaining grouped by state (state is one of `--done-state`)
   - A breakdown of item count by work item type
   - A list of any items with no effort value, by id and title
5. If `--previous N` is set, also prints for each of the last N iterations (most recent first):
   - Date range and total item count/effort
   - Completed items and effort (state is one of `--done-state`)
   - Leftover (not-done) items and remaining effort, grouped by state with item count and effort per state
   - A breakdown of item count by work item type

## Notes

- If no iteration lines up with today's date, the script falls back to the API's own "current" flag, then to the nearest future iteration.
- Effort field naming depends on your process template (Scrum uses `Effort`, Agile uses `Story Points`) — use `--effort-field` if the default guesses don't match your setup.
- "Done" state names also vary by process template — check your board's state names and pass `--done-state` if the defaults (`Closed`, `Done`, `Resolved`, `Completed`) don't match.
