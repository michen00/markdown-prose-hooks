#!/usr/bin/env bash

set -euo pipefail # Exit on errors, unbound vars, and failed pipelines

SCRIPT_NAME=$(basename "$0")

usage() {
  cat << EOF
Usage: $SCRIPT_NAME [--output <output_file>] [<input_file>]

Concatenate multiple .gitignore templates into a single file by fetching URLs from
stdin, a file, or built-in defaults.

Inputs:
  stdin            Read URLs from standard input when piped or redirected.
  <input_file>     Optional file containing one URL per line. Supports section headers
                   with lines starting "## ". A single argument ending with /.gitignore
                   (e.g. my-project/.gitignore) is treated as the output path (relative
                   to repo root) and default URLs are used.

Options:
  --output <file>  Destination file name. Defaults to .gitignore.
  -h, --help       Show this help message and exit.

Examples:
  cat urls.txt | $SCRIPT_NAME
  cat urls.txt | $SCRIPT_NAME --output custom.output.gitignore
  $SCRIPT_NAME
  $SCRIPT_NAME urls.txt
  $SCRIPT_NAME urls.txt --output custom.output.gitignore
  $SCRIPT_NAME my-project/.gitignore
EOF
  exit "${1:-0}"
}

# Hardcoded default entries (used if no input is provided). Section headers
# (## Title) appear in the generated .gitignore header; URLs are fetched.
DEFAULT_ENTRIES=(
  "https://github.com/github/gitignore/blob/main/Global/Cursor.gitignore"
  "https://github.com/github/gitignore/blob/main/Global/Eclipse.gitignore"
  "https://github.com/github/gitignore/blob/main/Global/Emacs.gitignore"
  "https://github.com/github/gitignore/blob/main/Global/JetBrains.gitignore"
  "https://github.com/github/gitignore/blob/main/Global/SublimeText.gitignore"
  "https://github.com/github/gitignore/blob/main/Global/Vim.gitignore"
  "https://github.com/github/gitignore/blob/main/Global/VisualStudioCode.gitignore"
  "https://github.com/github/gitignore/blob/main/VisualStudio.gitignore"
  "https://github.com/github/gitignore/blob/main/Global/Linux.gitignore"
  "https://github.com/github/gitignore/blob/main/Global/macOS.gitignore"
  "https://github.com/github/gitignore/blob/main/Global/Windows.gitignore"
  "https://github.com/github/gitignore/blob/main/Global/Archives.gitignore"
  "https://github.com/github/gitignore/blob/main/Global/Backup.gitignore"
  "https://github.com/github/gitignore/blob/main/Global/Diff.gitignore"
  "https://github.com/github/gitignore/blob/main/Global/MicrosoftOffice.gitignore"
  "https://github.com/github/gitignore/blob/main/Global/Patch.gitignore"
)

# Default output file
OUTPUT_FILE=".gitignore"

# Variables
INPUT_FILE=""
ENTRIES=()
URLS=()

add_entry() {
  local line="$1"
  local trimmed="$line"
  trimmed="${trimmed#"${trimmed%%[![:space:]]*}"}"
  trimmed="${trimmed%"${trimmed##*[![:space:]]}"}"
  [[ -z "$trimmed" ]] && return 0
  if [[ "$trimmed" == "## "* ]]; then
    ENTRIES+=("$trimmed")
  elif [[ "$trimmed" == \#* ]]; then
    return 0
  else
    ENTRIES+=("$trimmed")
    URLS+=("$trimmed")
  fi
}

parse_input_stream() {
  local line=""
  while IFS= read -r line || [[ -n "$line" ]]; do
    add_entry "$line"
  done
}

# Parse arguments
while [[ $# -gt 0 ]]; do
  case "$1" in
    --output)
      if [[ -z ${2:-} ]]; then
        echo "Error: --output requires a file name." >&2
        usage 1
      fi
      OUTPUT_FILE="$2"
      shift 2
      ;;
    -h | --help)
      usage 0
      ;;
    --*)
      echo "Unknown option: $1" >&2
      usage 1
      ;;
    *)
      if [[ -z $INPUT_FILE ]]; then
        INPUT_FILE="$1"
        shift
      else
        echo "Error: Multiple input files specified: '$INPUT_FILE' and '$1'" >&2
        usage 1
      fi
      ;;
  esac
done

# If the only positional argument looks like an output path (e.g. my-project/.gitignore),
# treat it as --output and use default URLs. Resolve relative to repo root (parent of
# script dir) so the same path is used regardless of current working directory.
if [[ -n $INPUT_FILE && $INPUT_FILE == */.gitignore ]]; then
  SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
  REPO_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
  OUTPUT_FILE="$REPO_ROOT/$INPUT_FILE"
  INPUT_FILE=""
fi

# Determine the source of URLs.
# Priority: explicit input file > stdin (pipe or redirection) > defaults.
if [[ -n $INPUT_FILE ]]; then
  if [[ -f $INPUT_FILE ]]; then
    parse_input_stream < "$INPUT_FILE"
  else
    echo "Input file not found: $INPUT_FILE" >&2
    exit 1
  fi
# A pipe or a redirected file, rather than the broader "stdin is not a terminal".
# A non-interactive parent hands this script a socket or a null device, and the
# original test was true for both: the read then either blocked forever, measured
# on a socket, or reached end of file at once and failed with "No URLs provided",
# measured on a null device. Neither shape is a pipe or a file, so both now fall
# through to the defaults. An inherited pipe is still read, as documented above.
# `make` is not itself the trigger -- it hands a recipe whatever stdin it was
# given, so a run from a terminal keeps the terminal and was never affected.
elif [ -p /dev/stdin ] || [ -f /dev/stdin ]; then
  parse_input_stream
else
  for entry in "${DEFAULT_ENTRIES[@]}"; do
    add_entry "$entry"
  done
fi

if [[ ${#URLS[@]} -eq 0 ]]; then
  echo "No URLs provided." >&2
  exit 1
fi

# Calculate the length of the longest header line (for ruler)
MAX_HEADER_LINE_LENGTH=0
for entry in "${ENTRIES[@]}"; do
  if [[ "$entry" == "## "* ]]; then
    HEADER_LINE="# ${entry#\#\# }"
  else
    HEADER_LINE="# - $entry"
  fi
  if [[ ${#HEADER_LINE} -gt $MAX_HEADER_LINE_LENGTH ]]; then
    MAX_HEADER_LINE_LENGTH=${#HEADER_LINE}
  fi
done

# Create the comment header
HEADER_LENGTH=$MAX_HEADER_LINE_LENGTH
HEADER=$(printf '#%.0s' $(seq 1 "$HEADER_LENGTH"))

OUTPUT_DIR=$(dirname "$OUTPUT_FILE")
if [[ ! -d "$OUTPUT_DIR" ]]; then
  mkdir -p "$OUTPUT_DIR" || {
    echo "Error: cannot create directory '$OUTPUT_DIR' for output file." >&2
    exit 1
  }
fi

{
  echo "$HEADER"
  echo "# This .gitignore is composed of the following templates (retrieved $(date +%Y-%m-%d)):"
  for entry in "${ENTRIES[@]}"; do
    if [[ "$entry" == "## "* ]]; then
      echo "# ${entry#\#\# }"
    else
      echo "# - $entry"
    fi
  done
  echo "$HEADER"
  echo ""
} > "$OUTPUT_FILE"

echo "Initialized output file with header: $OUTPUT_FILE"

# Convert blob URL to raw URL if needed (user-supplied input may use blob format)
to_raw_url() {
  local u="$1"
  if [[ "$u" == *"/blob/"* ]]; then
    echo "$u" | sed 's|github.com|raw.githubusercontent.com|; s|/blob||'
  else
    echo "$u"
  fi
}

# Loop through URLs
for url in "${URLS[@]}"; do
  echo "Processing URL: $url"

  RAW_URL=$(to_raw_url "$url")
  if [[ "$url" != "$RAW_URL" ]]; then
    echo "Converted to raw URL: $RAW_URL"
  fi

  # Extract the filename (e.g., Python.gitignore)
  FILENAME=$(basename "$url")

  # Calculate dynamic block length
  PREFACE_LENGTH=$((${#FILENAME} + 4)) # Length of " # FILENAME # "
  PREFACE=$(printf '#%.0s' $(seq 1 $PREFACE_LENGTH))

  # Preface block
  {
    echo "$PREFACE"
    echo "# $FILENAME #"
    echo "$PREFACE"
    echo ""
  } >> "$OUTPUT_FILE"

  # Fetch content (curl -f: fail on HTTP 4xx/5xx)
  TMP_CURL=$(mktemp)
  if ! curl -f -s "$RAW_URL" -o "$TMP_CURL"; then
    rm -f "$TMP_CURL"
    echo "Failed to fetch: $RAW_URL" >&2
    exit 1
  fi
  # macOS.gitignore encodes the CR-suffixed "Icon" file as the bracket class
  # `Icon[\r]` (a literal CR inside `[...]`). Stripping CR only at end-of-line
  # leaves the empty class `Icon[]`, which git matches literally, so collapse
  # the class before the end-of-line strip.
  CONTENT=$(awk '{ gsub(/\[\r\]/, ""); gsub(/\r$/, ""); gsub(/[ \t]+$/, ""); print }' "$TMP_CURL")
  rm -f "$TMP_CURL"

  if [[ -z "$CONTENT" ]]; then
    echo "Empty content from: $RAW_URL" >&2
    exit 1
  fi

  # Reject HTML (e.g. GitHub error page)
  content_prefix="${CONTENT:0:256}"
  if [[ "$content_prefix" =~ ^[[:space:]]*\<\![[:space:]]*[Dd][Oo][Cc][Tt][Yy][Pp][Ee] ]] ||
    [[ "$content_prefix" =~ ^[[:space:]]*\<[Hh][Tt][Mm][Ll] ]]; then
    echo "Received HTML instead of gitignore content from: $RAW_URL" >&2
    exit 1
  fi

  echo "Appending content from: $RAW_URL"
  printf '%s\n' "$CONTENT" >> "$OUTPUT_FILE"
  printf '\n# End of %s\n\n' "$url" >> "$OUTPUT_FILE"
done

# Normalize line endings in the final output file
NORMALIZE_TMP=$(mktemp)
tr -d '\r' < "$OUTPUT_FILE" > "$NORMALIZE_TMP" || {
  rm -f "$NORMALIZE_TMP"
  exit 1
}
mv "$NORMALIZE_TMP" "$OUTPUT_FILE"

# Ensure single trailing newline (collapse any trailing blank lines into exactly one newline)
if command -v perl > /dev/null 2>&1; then
  perl -0777 -pi -e 's/\n*\z/\n/' "$OUTPUT_FILE"
else
  # Command substitution strips trailing newlines; print one newline back.
  content=$(< "$OUTPUT_FILE")
  printf '%s\n' "$content" > "$OUTPUT_FILE"
fi

# Add additional ignore patterns
# Quoted so the block is emitted verbatim: these are gitignore glob patterns, and
# an unquoted heredoc would treat a `$` or a backtick in one as an expansion.
cat >> "$OUTPUT_FILE" << 'EOF'

####################
# Python artifacts #
####################

# Byte-compiled / cache
__pycache__/
*.py[cod]
*$py.class

# Tool caches
.pytest_cache/
.ruff_cache/
.mypy_cache/
.tox/
.nox/

# Virtual environments
.venv/
venv/
# `uv run --python <version>` creates a second environment named `.venv-1`,
# which the entry above does not match. Git hides it regardless, because uv
# writes a `.gitignore` holding `*` inside every environment it creates, so the
# files are ignored rather than untracked and `git status` says nothing.
# Hatchling reads only the root file, so without this line a local `uv build`
# walks in and packages the whole environment into the sdist.
.venv-*/

# Packaging / build output
build/
dist/
*.egg-info/
.eggs/

# Coverage
.coverage
.coverage.*
htmlcov/

coverage/**
!.gitkeep

##################
# Rust artifacts #
##################

# The generated section above carries `.target` from the sbteclipse template,
# which is a different pattern and does not match this one.
target/

# Two generated patterns above match `src/bin/`, which is where Cargo
# autodiscovers binaries whose name is their filename. Left alone, the entry
# point is ignored and never committed -- silently, since an ignored file is not
# an untracked one and `git status` says nothing.
#
# Both halves are needed. Eclipse's `bin/` excludes the directory, and git will
# not descend into an excluded directory to find a re-included file, so the
# directory itself has to be un-excluded first. VisualStudio's `**/[Bb]in/*`
# then excludes the contents, which the second line answers.
!src/bin/
!src/bin/**
EOF

echo "Combined .gitignore created as $OUTPUT_FILE"
