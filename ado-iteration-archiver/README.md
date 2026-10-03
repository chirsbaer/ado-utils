# ADO Iteration Archiver

Two small scripts for tidying up the iteration tree of an Azure DevOps project,
for example moving all old sprints into an `Archive` folder.

| Script | What it does |
| --- | --- |
| `find_iteration.sh` | Finds iterations whose name matches a regex and writes their IDs to a file |
| `move_iteration.sh` | Moves every iteration ID in that file under a target iteration |

Splitting the work in two lets you review (and edit) the list of IDs before
anything is changed.

## Prerequisites

- **bash** (macOS/Linux terminal, WSL, or Git Bash on Windows)
- **Azure CLI** – <https://learn.microsoft.com/cli/azure/install-azure-cli>
- **Azure DevOps CLI extension**
  ```bash
  az extension add --name azure-devops
  ```
- **jq** (only needed by `find_iteration.sh`) – <https://jqlang.org/download/>
- **Signed in** to Azure DevOps, either with `az login` or with a
  [personal access token](https://learn.microsoft.com/azure/devops/cli/log-in-via-pat):
  ```bash
  az devops login --organization https://dev.azure.com/MyOrg/
  ```
- **Permissions** to edit iterations in the project (Project Administrator or
  "Edit this node" on the iteration area).
- The **target iteration must already exist** (e.g. create an `Archive`
  iteration under *Project settings → Boards → Project configuration*).

Make the scripts executable if needed:

```bash
chmod +x find_iteration.sh move_iteration.sh
```

## Configuration

Organization and project can be passed as flags, set as environment variables,
or (for the organization) taken from your Azure DevOps CLI defaults. Flags win
over environment variables.

| Flag | Environment variable | CLI default |
| --- | --- | --- |
| `-o, --org` | `AZURE_DEVOPS_ORG` | `az devops configure --defaults organization=...` |
| `-p, --project` | `AZURE_DEVOPS_PROJECT` | – |

```bash
export AZURE_DEVOPS_ORG="https://dev.azure.com/MyOrg/"
export AZURE_DEVOPS_PROJECT="My Project"
```

## Usage

### 1. Find iterations

```bash
./find_iteration.sh --project "My Project" --match "2021"
```

| Option | Description | Default |
| --- | --- | --- |
| `-p, --project` | Project name | *required* |
| `-m, --match` | Case-insensitive regex matched against iteration names | *required* |
| `-o, --org` | Organization URL | env / CLI default |
| `-d, --depth` | How deep in the iteration tree to search | `10` |
| `-f, --file` | Output file with one ID per line | `ids_to_move.txt` |
| `-c, --include-children` | Also list matching children of a matching iteration | off |

The matched IDs and paths are printed so you can check them. Open the output
file and remove any line you don't want to move.

By default, when an iteration matches, its children are **not** listed, even if
they match too. Moving the parent moves the whole subtree, so the hierarchy is
kept. For example, with `--match "2021"`:

```
Iteration
├── 2021             ← listed
│   ├── Sprint 2021-1   (skipped, moves with its parent)
│   └── Sprint 2021-2   (skipped, moves with its parent)
└── 2022
    └── Sprint 2021-x   ← listed (its parent did not match)
```

Use `--include-children` to list every matching iteration regardless of its
parent.

> **Note:** The output file is **replaced** every time the script runs. It is
> not appended to. To find several patterns, either combine them in one regex
> (`--match "2021|2022"`) or write each run to its own file with `--file` and
> pass each file to `move_iteration.sh`.

### 2. Move iterations

Always do a dry run first:

```bash
./move_iteration.sh --project "My Project" --target "Archive" --dry-run
./move_iteration.sh --project "My Project" --target "Archive"
```

| Option | Description | Default |
| --- | --- | --- |
| `-p, --project` | Project name | *required* |
| `-t, --target` | Target parent iteration (see below) | *required* |
| `-o, --org` | Organization URL | env / CLI default |
| `-f, --file` | Input file with one ID per line | `ids_to_move.txt` |
| `-n, --dry-run` | Show what would be moved without changing anything | off |

`--target` can be:

- a path relative to the project's iteration root, e.g. `Archive` or
  `Archive/2021` → `\My Project\Iteration\Archive\2021`
- a full iteration path starting with a backslash, e.g.
  `'\My Project\Iteration\Archive'` (use single quotes so the shell keeps the
  backslashes)

Blank lines and lines starting with `#` in the input file are ignored. The
script continues past failures and exits non-zero if any move failed.

## Example: archive all 2021 sprints

```bash
export AZURE_DEVOPS_ORG="https://dev.azure.com/MyOrg/"
export AZURE_DEVOPS_PROJECT="My Project"

./find_iteration.sh --match "2021"
./move_iteration.sh --target "Archive" --dry-run
./move_iteration.sh --target "Archive"
```

## Notes

- With `--include-children`, the file can contain both a parent and its
  children. Moving the parent already moves its children, and moving a child
  afterwards pulls it out of its parent and places it directly under the target.
  Leave out `--include-children` (the default) if you want to keep the
  hierarchy.
- The pattern should not match the target iteration itself (e.g. don't use a
  pattern that matches `Archive`).
- Moving an iteration keeps the work items assigned to it; only their iteration
  path changes.
