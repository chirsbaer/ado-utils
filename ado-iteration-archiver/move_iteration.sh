#!/usr/bin/env bash
#
# Move Azure DevOps iterations (by ID, read from a file) under a target
# iteration node, e.g. an "Archive" folder.

set -euo pipefail

usage() {
  cat <<EOF
Usage: $(basename "$0") -p <project> -t <target> [options]

Move every iteration ID listed in the input file under the target iteration.

Required:
  -p, --project <name>      Azure DevOps project name
  -t, --target <path>       Target parent iteration. Either a path relative to
                            the project's iteration root (e.g. "Archive" or
                            "Archive/2021"), or a full path starting with a
                            backslash (e.g. "\\MyProject\\Iteration\\Archive")

Options:
  -o, --org <url>           Organization URL, e.g. https://dev.azure.com/MyOrg/
                            (defaults to AZURE_DEVOPS_ORG or 'az devops configure')
  -f, --file <path>         File with one iteration ID per line
                            (default: ids_to_move.txt)
  -n, --dry-run             Print what would be moved without changing anything
  -h, --help                Show this help

Environment variables (used when the matching flag is not given):
  AZURE_DEVOPS_ORG, AZURE_DEVOPS_PROJECT
EOF
}

ORG="${AZURE_DEVOPS_ORG:-}"
PROJECT="${AZURE_DEVOPS_PROJECT:-}"
TARGET=""
INPUT="ids_to_move.txt"
DRY_RUN=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    -o|--org)     ORG="$2"; shift 2 ;;
    -p|--project) PROJECT="$2"; shift 2 ;;
    -t|--target)  TARGET="$2"; shift 2 ;;
    -f|--file)    INPUT="$2"; shift 2 ;;
    -n|--dry-run) DRY_RUN=true; shift ;;
    -h|--help)    usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 1 ;;
  esac
done

if [[ -z "$PROJECT" || -z "$TARGET" ]]; then
  echo "Error: --project and --target are required." >&2
  usage >&2
  exit 1
fi

if [[ ! -f "$INPUT" ]]; then
  echo "Error: input file '$INPUT' not found. Run find_iteration.sh first." >&2
  exit 1
fi

if ! $DRY_RUN; then
  for cmd in az jq; do
    command -v "$cmd" >/dev/null || { echo "Error: '$cmd' is not installed." >&2; exit 1; }
  done
fi

# Build the full target path: \<project>\Iteration\<target>
if [[ "$TARGET" == \\* ]]; then
  TARGET_PATH="$TARGET"
else
  TARGET_PATH="\\$PROJECT\\Iteration\\${TARGET//\//\\}"
fi

az_args=(--project "$PROJECT" --path "$TARGET_PATH" --output none)
[[ -n "$ORG" ]] && az_args+=(--organization "$ORG")

common_args=(--project "$PROJECT")
[[ -n "$ORG" ]] && common_args+=(--organization "$ORG")

# Moving an iteration clears its start/finish dates in Azure DevOps.
# Snapshot the whole iteration tree first so the dates can be restored.
TMP_DIR=$(mktemp -d)
trap 'rm -rf "$TMP_DIR"' EXIT
if ! $DRY_RUN; then
  echo "Saving current iteration dates..."
  az boards iteration project list "${common_args[@]}" --depth 20 --output json > "$TMP_DIR/before.json"
fi

moved=0
failed=0
while IFS= read -r ID || [[ -n "$ID" ]]; do
  ID="${ID//[[:space:]]/}"
  [[ -z "$ID" || "$ID" == \#* ]] && continue

  if $DRY_RUN; then
    echo "[dry-run] Would move iteration $ID -> $TARGET_PATH"
    continue
  fi

  echo "Moving iteration $ID -> $TARGET_PATH"
  if az boards iteration project update --child-id "$ID" "${az_args[@]}" </dev/null; then
    moved=$((moved + 1))
  else
    echo "  Failed to move iteration $ID" >&2
    failed=$((failed + 1))
  fi
done < "$INPUT"

restore_failed=0
if ! $DRY_RUN && [[ $moved -gt 0 ]]; then
  echo "Restoring iteration dates..."
  az boards iteration project list "${common_args[@]}" --depth 20 --output json > "$TMP_DIR/after.json"

  # Every iteration that had dates before the move but has none now.
  jq -r -n --slurpfile b "$TMP_DIR/before.json" --slurpfile a "$TMP_DIR/after.json" '
    def nodes: recurse(.children[]?);
    ($b[0] | [nodes
              | select(.attributes.startDate != null and .attributes.finishDate != null)
              | {key: (.id | tostring), value: .attributes}] | from_entries) as $dates
    | $a[0] | nodes
    | select(.attributes.startDate == null or .attributes.finishDate == null)
    | $dates[.id | tostring] as $d
    | select($d != null)
    | [.path, $d.startDate, $d.finishDate] | join("\t")' > "$TMP_DIR/restore.tsv"

  while IFS=$'\t' read -r NODE_PATH START FINISH; do
    [[ -z "$NODE_PATH" ]] && continue
    echo "  $NODE_PATH: ${START%%T*} - ${FINISH%%T*}"
    if ! az boards iteration project update "${common_args[@]}" --path "$NODE_PATH" \
         --start-date "$START" --finish-date "$FINISH" --output none </dev/null; then
      echo "  Failed to restore dates for $NODE_PATH" >&2
      restore_failed=$((restore_failed + 1))
    fi
  done < "$TMP_DIR/restore.tsv"
fi

$DRY_RUN || echo "Done. Moved: $moved, failed: $failed, date restores failed: $restore_failed."
[[ $failed -eq 0 && $restore_failed -eq 0 ]]
