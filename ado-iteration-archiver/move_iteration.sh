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

$DRY_RUN || command -v az >/dev/null || { echo "Error: 'az' is not installed." >&2; exit 1; }

# Build the full target path: \<project>\Iteration\<target>
if [[ "$TARGET" == \\* ]]; then
  TARGET_PATH="$TARGET"
else
  TARGET_PATH="\\$PROJECT\\Iteration\\${TARGET//\//\\}"
fi

az_args=(--project "$PROJECT" --path "$TARGET_PATH" --output none)
[[ -n "$ORG" ]] && az_args+=(--organization "$ORG")

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

$DRY_RUN || echo "Done. Moved: $moved, failed: $failed."
[[ $failed -eq 0 ]]
