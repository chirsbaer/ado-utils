#!/usr/bin/env bash
#
# Find Azure DevOps iterations whose name matches a pattern and write their IDs
# to a file, ready to be passed to move_iteration.sh.

set -euo pipefail

usage() {
  cat <<EOF
Usage: $(basename "$0") -p <project> -m <pattern> [options]

Find iterations in an Azure DevOps project whose name matches a regex and
write their IDs (one per line) to an output file.

Required:
  -p, --project <name>      Azure DevOps project name
  -m, --match <regex>       Case-insensitive regex matched against iteration
                            names (jq/Oniguruma syntax), e.g. "2021"

Options:
  -o, --org <url>           Organization URL, e.g. https://dev.azure.com/MyOrg/
                            (defaults to AZURE_DEVOPS_ORG or 'az devops configure')
  -d, --depth <n>           Depth of the iteration tree to search (default: 10)
  -f, --file <path>         Output file (default: ids_to_move.txt)
  -c, --include-children    Also list matching children of a matching
                            iteration (by default they are skipped, since
                            moving the parent moves them too)
  -h, --help                Show this help

Environment variables (used when the matching flag is not given):
  AZURE_DEVOPS_ORG, AZURE_DEVOPS_PROJECT
EOF
}

ORG="${AZURE_DEVOPS_ORG:-}"
PROJECT="${AZURE_DEVOPS_PROJECT:-}"
PATTERN=""
DEPTH=10
OUTPUT="ids_to_move.txt"
INCLUDE_CHILDREN=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    -o|--org)     ORG="$2"; shift 2 ;;
    -p|--project) PROJECT="$2"; shift 2 ;;
    -m|--match)   PATTERN="$2"; shift 2 ;;
    -d|--depth)   DEPTH="$2"; shift 2 ;;
    -f|--file)    OUTPUT="$2"; shift 2 ;;
    -c|--include-children) INCLUDE_CHILDREN=true; shift ;;
    -h|--help)    usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 1 ;;
  esac
done

if [[ -z "$PROJECT" || -z "$PATTERN" ]]; then
  echo "Error: --project and --match are required." >&2
  usage >&2
  exit 1
fi

for cmd in az jq; do
  command -v "$cmd" >/dev/null || { echo "Error: '$cmd' is not installed." >&2; exit 1; }
done

az_args=(--project "$PROJECT" --depth "$DEPTH" --output json)
[[ -n "$ORG" ]] && az_args+=(--organization "$ORG")

# The root node is the project itself; only search its children.
# Unless --include-children is set, stop descending once a node matches.
matches=$(az boards iteration project list "${az_args[@]}" \
  | jq -r --arg re "$PATTERN" --argjson all "$INCLUDE_CHILDREN" '
      def walk_match:
        (.name | test($re; "i")) as $hit
        | (if $hit then "\(.id)\t\(.path)" else empty end),
          (if $hit and ($all | not) then empty else .children[]? | walk_match end);
      .children[]? | walk_match')

if [[ -z "$matches" ]]; then
  : > "$OUTPUT"
  echo "No iterations matched '$PATTERN'. Wrote empty $OUTPUT." >&2
  exit 0
fi

cut -f1 <<< "$matches" > "$OUTPUT"

echo "Matched $(wc -l < "$OUTPUT" | tr -d ' ') iteration(s), IDs written to $OUTPUT:" >&2
echo "$matches" | sed 's/^/  /' >&2
