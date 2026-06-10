#!/usr/bin/env bash

set -u

_REPO_URL="git+https://github.com/sungjunlee/finjuice"
INSTALL_COMMAND="uv tool install ${_REPO_URL}"
UPDATE_COMMAND="uv tool install --force ${_REPO_URL}"
FALLBACK_COMMAND="uvx --from git+https://github.com/sungjunlee/finjuice finjuice --help"
HELPER_COMMAND="${0:-skills/finjuice/scripts/ensure_finjuice_cli.sh}"
REMOTE_VERSION_URL="${FINJUICE_RUNTIME_UPDATE_URL:-https://api.github.com/repos/sungjunlee/finjuice/tags?per_page=1}"
DEFAULT_UPDATE_TTL_SECONDS=86400
MAX_SNOOZE_DAYS=30
JSON_MODE=false
UPDATE_REQUESTED=false
SNOOZE_DAYS="${FINJUICE_RUNTIME_UPDATE_SNOOZE_DAYS:-}"
REQUIRED_VERSION=""
REQUIRED_COMMANDS=()
REQUIRED_FLAGS=()
REQUIRED_CAPABILITIES=()
REQUIRED_IMPORTS=()
REQUIRED_EXTRAS=()
COMMAND_CHECKS_JSON=""
FLAG_CHECKS_JSON=""
CAPABILITY_CHECKS_JSON=""
CAPABILITY_CHECKS_TEXT=""
IMPORT_CHECKS_JSON=""
IMPORT_CHECKS_TEXT=""
LAST_UNSUPPORTED_CLI_PATH=""
LAST_UNSUPPORTED_IMPORT=""
ANALYTICS_EXTRA_REQUIRED=false
UPDATE_CHECK_STATUS=""
UPDATE_CHECK_MESSAGE=""
UPDATE_CHECK_REMOTE_VERSION=""
UPDATE_CHECK_AVAILABLE=false
UPDATE_CHECK_SNOOZED_UNTIL=""
UPDATE_CHECK_SNOOZED_UNTIL_ISO=""
UPDATE_CHECK_STATE_PATH=""

usage() {
  cat <<'USAGE'
Usage: ensure_finjuice_cli.sh [--json] [--update] [--snooze-update-check DAYS]
                              [--require-version VERSION]
                              [--require-command "COMMAND [SUBCOMMAND]"]
                              [--require-flag "COMMAND [SUBCOMMAND]:--flag"]
                              [--require-capability CAPABILITY]
                              [--require-import MODULE]
                              [--require-extra EXTRA]

Checks that the finjuice CLI runtime is available for finjuice skills.
If finjuice is missing and uv is available, installs the runtime with:
  uv tool install git+https://github.com/sungjunlee/finjuice

Normal checks do not update an existing finjuice runtime. When finjuice already
exists, the helper checks GitHub tag metadata at most once per 24-hour TTL window
and reports a newer remote version without updating. Remote check failures are
non-fatal while the local finjuice CLI works.

Use --update or FINJUICE_AUTO_UPDATE=1 to explicitly update with:
  uv tool install --force git+https://github.com/sungjunlee/finjuice

Use --snooze-update-check DAYS, capped at 30 days, to suppress update suggestions
temporarily. Set FINJUICE_RUNTIME_UPDATE_CHECK=0 to skip the remote check for the
current run only.

Skills may declare runtime requirements before use:
  --require-version 0.6.2
  --require-command "status"
  --require-flag "tag:--edit"
  --require-capability tag.edit
  --require-import duckdb
  --require-extra analytics

Known capabilities:
  tag.edit  checks tag --edit

Known extras:
  analytics checks duckdb via finjuice doctor --json and installs with --with duckdb
USAGE
}

json_escape() {
  local value=${1//\\/\\\\}
  value=${value//\"/\\\"}
  value=${value//$'\n'/\\n}
  value=${value//$'\r'/\\r}
  value=${value//$'\t'/\\t}
  printf '%s' "$value"
}

is_uint() {
  case "${1:-}" in
    "" | *[!0-9]*)
      return 1
      ;;
    *)
      return 0
      ;;
  esac
}

bounded_snooze_days_or_fail() {
  local value=$1

  if ! is_uint "$value" || [ "$value" -lt 1 ]; then
    printf 'Invalid --snooze-update-check value: %s\n' "$value" >&2
    printf 'Use a whole number of days from 1 to %s.\n' "$MAX_SNOOZE_DAYS" >&2
    return 1
  fi

  if [ "$value" -gt "$MAX_SNOOZE_DAYS" ]; then
    printf '%s' "$MAX_SNOOZE_DAYS"
    return 0
  fi

  printf '%s' "$value"
}

current_epoch() {
  local override=${FINJUICE_RUNTIME_NOW_EPOCH:-}

  if is_uint "$override"; then
    printf '%s' "$override"
    return
  fi

  date -u +%s
}

format_epoch_utc() {
  local epoch=$1

  if date -u -r "$epoch" +"%Y-%m-%dT%H:%M:%SZ" >/dev/null 2>&1; then
    date -u -r "$epoch" +"%Y-%m-%dT%H:%M:%SZ"
    return
  fi

  if date -u -d "@$epoch" +"%Y-%m-%dT%H:%M:%SZ" >/dev/null 2>&1; then
    date -u -d "@$epoch" +"%Y-%m-%dT%H:%M:%SZ"
    return
  fi

  printf '%s' "$epoch"
}

state_path() {
  if [ -n "${FINJUICE_AGENT_RUNTIME_STATE_PATH:-}" ]; then
    printf '%s' "$FINJUICE_AGENT_RUNTIME_STATE_PATH"
    return
  fi

  printf '%s/.finjuice/agent-runtime-state.json' "${HOME:-.}"
}

read_state_field() {
  local field=$1
  local file=$2

  if [ ! -f "$file" ]; then
    return 0
  fi

  sed -nE "s/^[[:space:]]*\"${field}\"[[:space:]]*:[[:space:]]*\"?([^\",}]*)\"?,?[[:space:]]*$/\1/p" "$file" |
    head -n 1
}

write_update_state() {
  local state_file=$1
  local checked_at=$2
  local local_version=$3
  local remote_version=$4
  local check_status=$5
  local snoozed_until=${6:-}
  local state_dir
  local temp_file
  local checked_iso
  local snoozed_iso=""

  state_dir=$(dirname "$state_file")
  if ! mkdir -p "$state_dir" >/dev/null 2>&1; then
    return 0
  fi

  checked_iso=$(format_epoch_utc "$checked_at")
  if is_uint "$snoozed_until"; then
    snoozed_iso=$(format_epoch_utc "$snoozed_until")
  fi

  temp_file="${state_file}.$$"
  {
    printf '{\n'
    printf '  "last_update_check_at": %s,\n' "$checked_at"
    printf '  "last_update_check_at_iso": "%s",\n' "$(json_escape "$checked_iso")"
    printf '  "last_seen_local_version": "%s",\n' "$(json_escape "$local_version")"
    printf '  "last_seen_remote_version": "%s",\n' "$(json_escape "$remote_version")"
    printf '  "last_update_check_status": "%s",\n' "$(json_escape "$check_status")"
    if is_uint "$snoozed_until"; then
      printf '  "snoozed_until": %s,\n' "$snoozed_until"
      printf '  "snoozed_until_iso": "%s"\n' "$(json_escape "$snoozed_iso")"
    else
      printf '  "snoozed_until": null,\n'
      printf '  "snoozed_until_iso": ""\n'
    fi
    printf '}\n'
  } >"$temp_file" 2>/dev/null || return 0

  mv "$temp_file" "$state_file" >/dev/null 2>&1 || rm -f "$temp_file"
}

extract_version() {
  printf '%s\n' "$1" |
    grep -Eo '[vV]?[0-9]+([.][0-9]+){0,2}' |
    head -n 1 |
    sed -E 's/^[vV]//'
}

version_gt() {
  local newer=$1
  local current=$2
  local n1 n2 n3 c1 c2 c3

  newer=$(extract_version "$newer")
  current=$(extract_version "$current")
  if [ -z "$newer" ] || [ -z "$current" ]; then
    return 1
  fi

  IFS=. read -r n1 n2 n3 _ <<EOF
$newer
EOF
  IFS=. read -r c1 c2 c3 _ <<EOF
$current
EOF

  n1=${n1:-0}
  n2=${n2:-0}
  n3=${n3:-0}
  c1=${c1:-0}
  c2=${c2:-0}
  c3=${c3:-0}

  if [ "$n1" -gt "$c1" ]; then
    return 0
  fi
  if [ "$n1" -lt "$c1" ]; then
    return 1
  fi
  if [ "$n2" -gt "$c2" ]; then
    return 0
  fi
  if [ "$n2" -lt "$c2" ]; then
    return 1
  fi
  [ "$n3" -gt "$c3" ]
}

json_string_array_from_values() {
  local first=true
  local value

  printf '['
  for value in "$@"; do
    if [ "$first" = true ]; then
      first=false
    else
      printf ','
    fi
    printf '"%s"' "$(json_escape "$value")"
  done
  printf ']'
}

join_values() {
  local first=true
  local value

  for value in "$@"; do
    if [ "$first" = true ]; then
      first=false
    else
      printf ', '
    fi
    printf '%s' "$value"
  done
}

version_satisfies_required() {
  local version_output=$1
  local required=$2
  local local_version

  if [ -z "$required" ]; then
    return 0
  fi

  local_version=$(extract_version "$version_output")
  if [ -z "$local_version" ]; then
    return 1
  fi

  ! version_gt "$required" "$local_version"
}

append_check_json() {
  local target=$1
  local item=$2
  local current

  case "$target" in
    command)
      current=$COMMAND_CHECKS_JSON
      if [ -z "$current" ]; then
        COMMAND_CHECKS_JSON=$item
      else
        COMMAND_CHECKS_JSON="$current,$item"
      fi
      ;;
    flag)
      current=$FLAG_CHECKS_JSON
      if [ -z "$current" ]; then
        FLAG_CHECKS_JSON=$item
      else
        FLAG_CHECKS_JSON="$current,$item"
      fi
      ;;
    capability)
      current=$CAPABILITY_CHECKS_JSON
      if [ -z "$current" ]; then
        CAPABILITY_CHECKS_JSON=$item
      else
        CAPABILITY_CHECKS_JSON="$current,$item"
      fi
      ;;
    import)
      current=$IMPORT_CHECKS_JSON
      if [ -z "$current" ]; then
        IMPORT_CHECKS_JSON=$item
      else
        IMPORT_CHECKS_JSON="$current,$item"
      fi
      ;;
  esac
}

append_capability_text() {
  local capability=$1
  local status=$2

  if [ -z "$CAPABILITY_CHECKS_TEXT" ]; then
    CAPABILITY_CHECKS_TEXT="capability ${capability}: ${status}"
  else
    CAPABILITY_CHECKS_TEXT="${CAPABILITY_CHECKS_TEXT}
capability ${capability}: ${status}"
  fi
}

append_import_text() {
  local module=$1
  local status=$2

  if [ -z "$IMPORT_CHECKS_TEXT" ]; then
    IMPORT_CHECKS_TEXT="import ${module}: ${status}"
  else
    IMPORT_CHECKS_TEXT="${IMPORT_CHECKS_TEXT}
import ${module}: ${status}"
  fi
}

make_command_check_json() {
  local command_path=$1
  local status=$2
  local check=$3

  printf '{"command":"%s","status":"%s","cli_path":"%s","check":"%s"}' \
    "$(json_escape "$command_path")" \
    "$(json_escape "$status")" \
    "$(json_escape "finjuice $command_path")" \
    "$(json_escape "$check")"
}

make_flag_check_json() {
  local flag_spec=$1
  local status=$2
  local cli_path=$3
  local check=$4

  printf '{"flag":"%s","status":"%s","cli_path":"%s","check":"%s"}' \
    "$(json_escape "$flag_spec")" \
    "$(json_escape "$status")" \
    "$(json_escape "$cli_path")" \
    "$(json_escape "$check")"
}

make_capability_check_json() {
  local capability=$1
  local status=$2
  local cli_path=$3
  local check=$4

  printf '{"capability":"%s","status":"%s","cli_path":"%s","check":"%s"}' \
    "$(json_escape "$capability")" \
    "$(json_escape "$status")" \
    "$(json_escape "$cli_path")" \
    "$(json_escape "$check")"
}

make_import_check_json() {
  local module=$1
  local status=$2
  local cli_path=$3
  local check=$4

  printf '{"module":"%s","status":"%s","cli_path":"%s","check":"%s"}' \
    "$(json_escape "$module")" \
    "$(json_escape "$status")" \
    "$(json_escape "$cli_path")" \
    "$(json_escape "$check")"
}

run_help_for_command() {
  local command_path=$1
  local -a parts

  read -r -a parts <<<"$command_path"
  finjuice "${parts[@]}" --help 2>&1
}

check_required_command() {
  local command_path=$1
  local output
  local status
  local item

  output=$(run_help_for_command "$command_path")
  status=$?
  if [ "$status" -eq 0 ]; then
    item=$(make_command_check_json "$command_path" "pass" "finjuice $command_path --help exits 0")
    append_check_json command "$item"
    return 0
  fi

  item=$(make_command_check_json "$command_path" "fail" "finjuice $command_path --help exits 0")
  append_check_json command "$item"
  LAST_UNSUPPORTED_CLI_PATH="finjuice $command_path"
  return 1
}

check_required_flag() {
  local flag_spec=$1
  local command_path
  local flag
  local output
  local status
  local cli_path
  local check
  local item

  case "$flag_spec" in
    *:*)
      command_path=${flag_spec%%:*}
      flag=${flag_spec#*:}
      ;;
    *)
      command_path=${flag_spec% *}
      flag=${flag_spec##* }
      ;;
  esac

  cli_path="finjuice ${command_path} ${flag}"
  check="finjuice ${command_path} --help contains ${flag}"
  output=$(run_help_for_command "$command_path")
  status=$?
  if [ "$status" -eq 0 ] && printf '%s\n' "$output" | grep -F -- "$flag" >/dev/null 2>&1; then
    item=$(make_flag_check_json "$flag_spec" "pass" "$cli_path" "$check")
    append_check_json flag "$item"
    return 0
  fi

  item=$(make_flag_check_json "$flag_spec" "fail" "$cli_path" "$check")
  append_check_json flag "$item"
  LAST_UNSUPPORTED_CLI_PATH="$cli_path"
  return 1
}

capability_details() {
  local capability=$1

  case "$capability" in
    tag.edit)
      CAPABILITY_COMMAND="tag"
      CAPABILITY_CLI_PATH="finjuice tag --edit"
      CAPABILITY_CHECK="finjuice tag --help contains --edit"
      CAPABILITY_NEEDLE_ONE="--edit"
      CAPABILITY_NEEDLE_TWO=""
      return 0
      ;;
    *)
      CAPABILITY_COMMAND=""
      CAPABILITY_CLI_PATH="finjuice ${capability}"
      CAPABILITY_CHECK="known finjuice skill capability"
      CAPABILITY_NEEDLE_ONE=""
      CAPABILITY_NEEDLE_TWO=""
      return 1
      ;;
  esac
}

check_required_capability() {
  local capability=$1
  local output
  local status
  local item

  if ! capability_details "$capability"; then
    item=$(make_capability_check_json \
      "$capability" \
      "fail" \
      "$CAPABILITY_CLI_PATH" \
      "$CAPABILITY_CHECK")
    append_check_json capability "$item"
    append_capability_text "$capability" "fail"
    return 1
  fi

  output=$(run_help_for_command "$CAPABILITY_COMMAND")
  status=$?
  if [ "$status" -eq 0 ] &&
    printf '%s\n' "$output" | grep -F -- "$CAPABILITY_NEEDLE_ONE" >/dev/null 2>&1 &&
    { [ -z "$CAPABILITY_NEEDLE_TWO" ] ||
      printf '%s\n' "$output" | grep -F -- "$CAPABILITY_NEEDLE_TWO" >/dev/null 2>&1; }; then
    item=$(make_capability_check_json \
      "$capability" \
      "pass" \
      "$CAPABILITY_CLI_PATH" \
      "$CAPABILITY_CHECK")
    append_check_json capability "$item"
    append_capability_text "$capability" "pass"
    return 0
  fi

  item=$(make_capability_check_json \
    "$capability" \
    "fail" \
    "$CAPABILITY_CLI_PATH" \
    "$CAPABILITY_CHECK")
  append_check_json capability "$item"
  append_capability_text "$capability" "fail"
  return 1
}

doctor_reports_check_pass() {
  local payload=$1
  local check_name=$2

  printf '%s\n' "$payload" | awk -v check_name="$check_name" '
    /"name"[[:space:]]*:[[:space:]]*"/ {
      in_check = index($0, "\"" check_name "\"") > 0
    }
    in_check && /"status"[[:space:]]*:[[:space:]]*"pass"/ {
      found = 1
    }
    in_check && /^[[:space:]]*}/ {
      in_check = 0
    }
    END {
      exit found ? 0 : 1
    }
  '
}

check_required_import() {
  local module=$1
  local output
  local status
  local item
  local check_name
  local check

  case "$module" in
    duckdb)
      check_name="analytics_duckdb"
      check="finjuice doctor --json reports analytics_duckdb pass"
      ;;
    *)
      item=$(make_import_check_json \
        "$module" \
        "fail" \
        "finjuice doctor --json" \
        "known finjuice runtime import")
      append_check_json import "$item"
      append_import_text "$module" "fail"
      LAST_UNSUPPORTED_IMPORT="$module"
      return 1
      ;;
  esac

  output=$(finjuice doctor --json 2>&1)
  status=$?
  if [ "$status" -eq 0 ] && doctor_reports_check_pass "$output" "$check_name"; then
    item=$(make_import_check_json "$module" "pass" "finjuice doctor --json" "$check")
    append_check_json import "$item"
    append_import_text "$module" "pass"
    return 0
  fi

  item=$(make_import_check_json "$module" "fail" "finjuice doctor --json" "$check")
  append_check_json import "$item"
  append_import_text "$module" "fail"
  LAST_UNSUPPORTED_IMPORT="$module"
  return 1
}

standard_unsupported_message() {
  local cli_path=$1
  local capability=$2

  printf 'Unsupported CLI path: %s. Confidence lost for this workflow because the local finjuice runtime lacks required capability %s. Do not recommend or run the failed command after preflight failure.' \
    "$cli_path" \
    "$capability"
}

emit_version_unsupported() {
  local version_output=$1
  local install_action=$2
  local runtime=$3
  local local_version
  local message

  local_version=$(extract_version "$version_output")
  message="finjuice ${local_version:-unknown} does not satisfy required finjuice version ${REQUIRED_VERSION}; explicitly update the runtime before using this skill."

  if [ "$JSON_MODE" = true ]; then
    printf '{"status":"blocked","reason":"version_unsupported","message":"%s","install_action":"%s","runtime":"%s","finjuice_version":"%s","local_version":"%s","required_version":"%s","update_command":"%s"}\n' \
      "$(json_escape "$message")" \
      "$(json_escape "$install_action")" \
      "$(json_escape "$runtime")" \
      "$(json_escape "$version_output")" \
      "$(json_escape "$local_version")" \
      "$(json_escape "$REQUIRED_VERSION")" \
      "$(json_escape "$HELPER_COMMAND --update --json")"
    return
  fi

  printf '%s\n' "finjuice runtime ensure blocked"
  printf 'reason: version_unsupported\n'
  printf 'message: %s\n' "$message"
  printf 'install: %s\n' "$install_action"
  printf 'runtime: %s\n' "$runtime"
  printf 'version: %s\n' "$version_output"
  printf 'local_version: %s\n' "$local_version"
  printf 'required_version: %s\n' "$REQUIRED_VERSION"
  printf 'update: run %s --update --json or set FINJUICE_AUTO_UPDATE=1\n' "$HELPER_COMMAND"
}

emit_capability_unsupported() {
  local version_output=$1
  local install_action=$2
  local runtime=$3
  local capability=$4
  local cli_path=$5
  local message

  message=$(standard_unsupported_message "$cli_path" "$capability")

  if [ "$JSON_MODE" = true ]; then
    printf '{"status":"blocked","reason":"capability_unsupported","message":"%s","install_action":"%s","runtime":"%s","finjuice_version":"%s"' \
      "$(json_escape "$message")" \
      "$(json_escape "$install_action")" \
      "$(json_escape "$runtime")" \
      "$(json_escape "$version_output")"
    if [ -n "$REQUIRED_VERSION" ]; then
      printf ',"required_version":"%s"' "$(json_escape "$REQUIRED_VERSION")"
    fi
    if [ "${#REQUIRED_CAPABILITIES[@]}" -gt 0 ]; then
      printf ',"required_capabilities":'
      json_string_array_from_values "${REQUIRED_CAPABILITIES[@]}"
    fi
    printf ',"unsupported_cli_path":"%s","confidence_lost":true' "$(json_escape "$cli_path")"
    if [ -n "$CAPABILITY_CHECKS_JSON" ]; then
      printf ',"capability_checks":[%s]' "$CAPABILITY_CHECKS_JSON"
    fi
    printf ',"update_command":"%s"}\n' "$(json_escape "$HELPER_COMMAND --update --json")"
    return
  fi

  printf '%s\n' "finjuice runtime ensure blocked"
  printf 'reason: capability_unsupported\n'
  printf 'message: %s\n' "$message"
  printf 'install: %s\n' "$install_action"
  printf 'runtime: %s\n' "$runtime"
  printf 'version: %s\n' "$version_output"
  if [ -n "$REQUIRED_VERSION" ]; then
    printf 'required_version: %s\n' "$REQUIRED_VERSION"
  fi
  if [ "${#REQUIRED_CAPABILITIES[@]}" -gt 0 ]; then
    printf 'required_capabilities: '
    join_values "${REQUIRED_CAPABILITIES[@]}"
    printf '\n'
  fi
  printf 'unsupported_cli_path: %s\n' "$cli_path"
  printf 'confidence_lost: true\n'
  if [ -n "$CAPABILITY_CHECKS_TEXT" ]; then
    printf '%s\n' "$CAPABILITY_CHECKS_TEXT"
  fi
  printf 'update: run %s --update --json or set FINJUICE_AUTO_UPDATE=1\n' "$HELPER_COMMAND"
}

emit_import_unsupported() {
  local version_output=$1
  local install_action=$2
  local runtime=$3
  local module=$4
  local message

  message="Missing runtime import: ${module}. Confidence lost for analytics workflows because the local finjuice runtime does not provide required optional dependency ${module}. Reinstall or update with analytics support before running analysis commands."

  if [ "$JSON_MODE" = true ]; then
    printf '{"status":"blocked","reason":"runtime_import_missing","message":"%s","install_action":"%s","runtime":"%s","finjuice_version":"%s","unsupported_import":"%s","confidence_lost":true' \
      "$(json_escape "$message")" \
      "$(json_escape "$install_action")" \
      "$(json_escape "$runtime")" \
      "$(json_escape "$version_output")" \
      "$(json_escape "$module")"
    if [ "${#REQUIRED_IMPORTS[@]}" -gt 0 ]; then
      printf ',"required_imports":'
      json_string_array_from_values "${REQUIRED_IMPORTS[@]}"
    fi
    if [ "${#REQUIRED_EXTRAS[@]}" -gt 0 ]; then
      printf ',"required_extras":'
      json_string_array_from_values "${REQUIRED_EXTRAS[@]}"
    fi
    if [ -n "$IMPORT_CHECKS_JSON" ]; then
      printf ',"import_checks":[%s]' "$IMPORT_CHECKS_JSON"
    fi
    printf ',"update_command":"%s","recovery_command":"%s"}\n' \
      "$(json_escape "$HELPER_COMMAND --update --json --require-import $module")" \
      "$(json_escape "$UPDATE_COMMAND")"
    return
  fi

  printf '%s\n' "finjuice runtime ensure blocked"
  printf 'reason: runtime_import_missing\n'
  printf 'message: %s\n' "$message"
  printf 'install: %s\n' "$install_action"
  printf 'runtime: %s\n' "$runtime"
  printf 'version: %s\n' "$version_output"
  if [ "${#REQUIRED_IMPORTS[@]}" -gt 0 ]; then
    printf 'required_imports: '
    join_values "${REQUIRED_IMPORTS[@]}"
    printf '\n'
  fi
  if [ "${#REQUIRED_EXTRAS[@]}" -gt 0 ]; then
    printf 'required_extras: '
    join_values "${REQUIRED_EXTRAS[@]}"
    printf '\n'
  fi
  printf 'unsupported_import: %s\n' "$module"
  printf 'confidence_lost: true\n'
  if [ -n "$IMPORT_CHECKS_TEXT" ]; then
    printf '%s\n' "$IMPORT_CHECKS_TEXT"
  fi
  printf 'update: run %s --update --json --require-import %s or set FINJUICE_AUTO_UPDATE=1\n' \
    "$HELPER_COMMAND" \
    "$module"
  printf 'recovery: %s\n' "$UPDATE_COMMAND"
}

finjuice_runtime_path() {
  local resolved
  local path_entry
  local candidate
  local old_ifs

  resolved=$(command -v finjuice 2>/dev/null || true)
  if [ -n "$resolved" ]; then
    printf '%s' "$resolved"
    return
  fi

  old_ifs=$IFS
  IFS=:
  for path_entry in $PATH; do
    candidate="${path_entry:-.}/finjuice"
    if [ -L "$candidate" ] || [ -e "$candidate" ]; then
      printf '%s' "$candidate"
      IFS=$old_ifs
      return
    fi
  done
  IFS=$old_ifs
}

resolved_symlink_target() {
  local link_path=$1
  local target
  local target_dir

  target=$(readlink "$link_path" 2>/dev/null || true)
  if [ -z "$target" ]; then
    return 1
  fi
  case "$target" in
    /*)
      printf '%s' "$target"
      ;;
    *)
      target_dir=$(dirname "$link_path")
      printf '%s/%s' "$target_dir" "$target"
      ;;
  esac
}

emit_runtime_path_broken() {
  local install_action=$1
  local runtime=$2
  local runtime_path=$3
  local symlink_target=$4
  local message

  message="finjuice exists on PATH but its executable path is broken; update or force reinstall the uv tool runtime before using this skill."

  if [ "$JSON_MODE" = true ]; then
    printf '{"status":"blocked","reason":"runtime_path_broken","message":"%s","install_action":"%s","runtime":"%s","runtime_path":"%s","symlink_target":"%s","confidence_lost":true,"update_command":"%s","recovery_command":"%s"}\n' \
      "$(json_escape "$message")" \
      "$(json_escape "$install_action")" \
      "$(json_escape "$runtime")" \
      "$(json_escape "$runtime_path")" \
      "$(json_escape "$symlink_target")" \
      "$(json_escape "$HELPER_COMMAND --update --json")" \
      "$(json_escape "$UPDATE_COMMAND")"
    return
  fi

  printf '%s\n' "finjuice runtime ensure blocked"
  printf 'reason: runtime_path_broken\n'
  printf 'message: %s\n' "$message"
  printf 'install: %s\n' "$install_action"
  printf 'runtime: %s\n' "$runtime"
  printf 'runtime_path: %s\n' "$runtime_path"
  printf 'symlink_target: %s\n' "$symlink_target"
  printf 'confidence_lost: true\n'
  printf 'update: run %s --update --json or set FINJUICE_AUTO_UPDATE=1\n' "$HELPER_COMMAND"
  printf 'recovery: %s\n' "$UPDATE_COMMAND"
}

runtime_path_or_block() {
  local install_action=$1
  local runtime=$2
  local runtime_path
  local symlink_target=""

  runtime_path=$(finjuice_runtime_path)
  if [ -z "$runtime_path" ]; then
    return 0
  fi

  if [ -L "$runtime_path" ]; then
    symlink_target=$(resolved_symlink_target "$runtime_path")
    if [ -z "$symlink_target" ] || [ ! -e "$symlink_target" ]; then
      emit_runtime_path_broken "$install_action" "$runtime" "$runtime_path" "$symlink_target"
      return 1
    fi
  fi

  if [ ! -x "$runtime_path" ]; then
    emit_runtime_path_broken "$install_action" "$runtime" "$runtime_path" "$runtime_path"
    return 1
  fi

  return 0
}

requirements_or_block() {
  local version_output=$1
  local install_action=$2
  local runtime=$3
  local command_path
  local flag_spec
  local capability
  local module

  if ! version_satisfies_required "$version_output" "$REQUIRED_VERSION"; then
    emit_version_unsupported "$version_output" "$install_action" "$runtime"
    return 1
  fi

  for command_path in ${REQUIRED_COMMANDS[@]+"${REQUIRED_COMMANDS[@]}"}; do
    if ! check_required_command "$command_path"; then
      emit_capability_unsupported "$version_output" "$install_action" "$runtime" \
        "$command_path" "$LAST_UNSUPPORTED_CLI_PATH"
      return 1
    fi
  done

  for flag_spec in ${REQUIRED_FLAGS[@]+"${REQUIRED_FLAGS[@]}"}; do
    if ! check_required_flag "$flag_spec"; then
      emit_capability_unsupported "$version_output" "$install_action" "$runtime" \
        "$flag_spec" "$LAST_UNSUPPORTED_CLI_PATH"
      return 1
    fi
  done

  for capability in ${REQUIRED_CAPABILITIES[@]+"${REQUIRED_CAPABILITIES[@]}"}; do
    if ! check_required_capability "$capability"; then
      emit_capability_unsupported "$version_output" "$install_action" "$runtime" \
        "$capability" "$CAPABILITY_CLI_PATH"
      return 1
    fi
  done

  for module in ${REQUIRED_IMPORTS[@]+"${REQUIRED_IMPORTS[@]}"}; do
    if ! check_required_import "$module"; then
      emit_import_unsupported "$version_output" "$install_action" "$runtime" \
        "$LAST_UNSUPPORTED_IMPORT"
      return 1
    fi
  done

  return 0
}

read_finjuice_version() {
  local version_output
  local version_exit

  version_output="$(finjuice --version 2>&1)"
  version_exit=$?
  if [ "$version_exit" -eq 0 ]; then
    printf '%s\n' "$version_output"
    return 0
  fi

  if finjuice --help >/dev/null 2>&1; then
    printf '%s\n' "finjuice unknown (--version unsupported)"
    return 0
  fi

  printf '%s\n' "$version_output"
  return "$version_exit"
}

parse_remote_version() {
  local payload=$1
  local version

  version=$(printf '%s\n' "$payload" |
    sed -nE 's/.*"tag_name"[[:space:]]*:[[:space:]]*"([^"]+)".*/\1/p' |
    head -n 1)
  if [ -z "$version" ]; then
    version=$(printf '%s\n' "$payload" |
      sed -nE 's/.*"name"[[:space:]]*:[[:space:]]*"([^"]+)".*/\1/p' |
      head -n 1)
  fi

  extract_version "$version"
}

fetch_remote_metadata() {
  if ! command -v curl >/dev/null 2>&1; then
    return 127
  fi

  curl -fsSL \
    --connect-timeout "${FINJUICE_RUNTIME_UPDATE_CONNECT_TIMEOUT:-2}" \
    --max-time "${FINJUICE_RUNTIME_UPDATE_MAX_TIME:-3}" \
    -H "Accept: application/vnd.github+json" \
    "$REMOTE_VERSION_URL"
}

run_update_check() {
  local version_output=$1
  local local_version
  local state_file
  local now
  local ttl
  local last_check
  local last_remote
  local snoozed_until
  local snooze_days
  local remote_payload
  local remote_exit
  local remote_version

  UPDATE_CHECK_STATUS=""
  UPDATE_CHECK_MESSAGE=""
  UPDATE_CHECK_REMOTE_VERSION=""
  UPDATE_CHECK_AVAILABLE=false
  UPDATE_CHECK_SNOOZED_UNTIL=""
  UPDATE_CHECK_SNOOZED_UNTIL_ISO=""

  local_version=$(extract_version "$version_output")
  state_file=$(state_path)
  UPDATE_CHECK_STATE_PATH=$state_file
  now=$(current_epoch)
  ttl=${FINJUICE_RUNTIME_UPDATE_TTL_SECONDS:-$DEFAULT_UPDATE_TTL_SECONDS}
  if ! is_uint "$ttl"; then
    ttl=$DEFAULT_UPDATE_TTL_SECONDS
  fi

  last_check=$(read_state_field "last_update_check_at" "$state_file")
  last_remote=$(read_state_field "last_seen_remote_version" "$state_file")
  snoozed_until=$(read_state_field "snoozed_until" "$state_file")

  if [ "${FINJUICE_RUNTIME_UPDATE_CHECK:-1}" = "0" ]; then
    UPDATE_CHECK_STATUS="disabled"
    UPDATE_CHECK_MESSAGE="remote runtime update check skipped for this run"
    return
  fi

  if [ -n "$SNOOZE_DAYS" ]; then
    if ! snooze_days=$(bounded_snooze_days_or_fail "$SNOOZE_DAYS"); then
      exit 2
    fi
    snoozed_until=$((now + (snooze_days * 86400)))
    UPDATE_CHECK_STATUS="snoozed"
    UPDATE_CHECK_MESSAGE="runtime update suggestions snoozed"
    UPDATE_CHECK_SNOOZED_UNTIL=$snoozed_until
    UPDATE_CHECK_SNOOZED_UNTIL_ISO=$(format_epoch_utc "$snoozed_until")
    UPDATE_CHECK_REMOTE_VERSION=$last_remote
    write_update_state "$state_file" "${last_check:-$now}" "$local_version" "$last_remote" \
      "snoozed" "$snoozed_until"
    return
  fi

  if is_uint "$snoozed_until" && [ "$now" -lt "$snoozed_until" ]; then
    UPDATE_CHECK_STATUS="snoozed"
    UPDATE_CHECK_MESSAGE="runtime update suggestions are snoozed"
    UPDATE_CHECK_SNOOZED_UNTIL=$snoozed_until
    UPDATE_CHECK_SNOOZED_UNTIL_ISO=$(format_epoch_utc "$snoozed_until")
    UPDATE_CHECK_REMOTE_VERSION=$last_remote
    return
  fi

  if is_uint "$last_check"; then
    local age=$((now - last_check))
    if [ "$age" -lt 0 ] || [ "$age" -lt "$ttl" ]; then
      UPDATE_CHECK_STATUS="fresh"
      UPDATE_CHECK_REMOTE_VERSION=$last_remote
      if version_gt "$last_remote" "$local_version"; then
        UPDATE_CHECK_AVAILABLE=true
      fi
      return
    fi
  fi

  remote_payload=$(fetch_remote_metadata 2>/dev/null)
  remote_exit=$?
  if [ "$remote_exit" -ne 0 ]; then
    UPDATE_CHECK_STATUS="failed"
    UPDATE_CHECK_MESSAGE="remote runtime update check failed; continuing with local finjuice"
    UPDATE_CHECK_REMOTE_VERSION=$last_remote
    write_update_state "$state_file" "$now" "$local_version" "$last_remote" "failed" ""
    return
  fi

  remote_version=$(parse_remote_version "$remote_payload")
  if [ -z "$remote_version" ]; then
    UPDATE_CHECK_STATUS="malformed"
    UPDATE_CHECK_MESSAGE="remote runtime metadata did not include a parseable version; continuing with local finjuice"
    UPDATE_CHECK_REMOTE_VERSION=$last_remote
    write_update_state "$state_file" "$now" "$local_version" "$last_remote" "malformed" ""
    return
  fi

  UPDATE_CHECK_STATUS="checked"
  UPDATE_CHECK_REMOTE_VERSION=$remote_version
  if version_gt "$remote_version" "$local_version"; then
    UPDATE_CHECK_AVAILABLE=true
  fi
  write_update_state "$state_file" "$now" "$local_version" "$remote_version" "checked" ""
}

emit_ready() {
  local install_action=$1
  local version=$2
  local runtime=$3
  local update_requested=${4:-false}

  if [ "$JSON_MODE" = true ]; then
    printf '{"status":"ready","install_action":"%s","finjuice_version":"%s","runtime":"%s"' \
      "$(json_escape "$install_action")" \
      "$(json_escape "$version")" \
      "$(json_escape "$runtime")"
    if [ "$update_requested" = true ]; then
      printf ',"update_requested":true'
    fi
    if [ -n "$REQUIRED_VERSION" ]; then
      printf ',"required_version":"%s"' "$(json_escape "$REQUIRED_VERSION")"
    fi
    if [ "${#REQUIRED_COMMANDS[@]}" -gt 0 ]; then
      printf ',"required_commands":'
      json_string_array_from_values "${REQUIRED_COMMANDS[@]}"
      if [ -n "$COMMAND_CHECKS_JSON" ]; then
        printf ',"command_checks":[%s]' "$COMMAND_CHECKS_JSON"
      fi
    fi
    if [ "${#REQUIRED_FLAGS[@]}" -gt 0 ]; then
      printf ',"required_flags":'
      json_string_array_from_values "${REQUIRED_FLAGS[@]}"
      if [ -n "$FLAG_CHECKS_JSON" ]; then
        printf ',"flag_checks":[%s]' "$FLAG_CHECKS_JSON"
      fi
    fi
    if [ "${#REQUIRED_CAPABILITIES[@]}" -gt 0 ]; then
      printf ',"required_capabilities":'
      json_string_array_from_values "${REQUIRED_CAPABILITIES[@]}"
      if [ -n "$CAPABILITY_CHECKS_JSON" ]; then
        printf ',"capability_checks":[%s]' "$CAPABILITY_CHECKS_JSON"
      fi
    fi
    if [ "${#REQUIRED_IMPORTS[@]}" -gt 0 ]; then
      printf ',"required_imports":'
      json_string_array_from_values "${REQUIRED_IMPORTS[@]}"
      if [ -n "$IMPORT_CHECKS_JSON" ]; then
        printf ',"import_checks":[%s]' "$IMPORT_CHECKS_JSON"
      fi
    fi
    if [ "${#REQUIRED_EXTRAS[@]}" -gt 0 ]; then
      printf ',"required_extras":'
      json_string_array_from_values "${REQUIRED_EXTRAS[@]}"
    fi
    if [ -n "$UPDATE_CHECK_STATUS" ]; then
      printf ',"update_check_status":"%s"' "$(json_escape "$UPDATE_CHECK_STATUS")"
      printf ',"update_available":%s' "$UPDATE_CHECK_AVAILABLE"
      if [ -n "$UPDATE_CHECK_REMOTE_VERSION" ]; then
        printf ',"remote_version":"%s"' "$(json_escape "$UPDATE_CHECK_REMOTE_VERSION")"
      fi
      if [ -n "$UPDATE_CHECK_MESSAGE" ]; then
        printf ',"update_check_message":"%s"' "$(json_escape "$UPDATE_CHECK_MESSAGE")"
      fi
      if [ -n "$UPDATE_CHECK_SNOOZED_UNTIL" ]; then
        printf ',"snoozed_until":%s' "$UPDATE_CHECK_SNOOZED_UNTIL"
        printf ',"snoozed_until_iso":"%s"' "$(json_escape "$UPDATE_CHECK_SNOOZED_UNTIL_ISO")"
      fi
      if [ "$UPDATE_CHECK_AVAILABLE" = true ]; then
        printf ',"update_command":"%s"' \
          "$(json_escape "$HELPER_COMMAND --update --json")"
      fi
    fi
    printf '}\n'
    return
  fi

  printf '%s\n' "finjuice ready"
  printf 'version: %s\n' "$version"
  printf 'install: %s\n' "$install_action"
  printf 'runtime: %s\n' "$runtime"
  if [ "$update_requested" = true ]; then
    printf 'update_requested: true\n'
  fi
  if [ -n "$REQUIRED_VERSION" ]; then
    printf 'required_version: %s\n' "$REQUIRED_VERSION"
  fi
  if [ "${#REQUIRED_COMMANDS[@]}" -gt 0 ]; then
    printf 'required_commands: '
    join_values "${REQUIRED_COMMANDS[@]}"
    printf '\n'
  fi
  if [ "${#REQUIRED_FLAGS[@]}" -gt 0 ]; then
    printf 'required_flags: '
    join_values "${REQUIRED_FLAGS[@]}"
    printf '\n'
  fi
  if [ "${#REQUIRED_CAPABILITIES[@]}" -gt 0 ]; then
    printf 'required_capabilities: '
    join_values "${REQUIRED_CAPABILITIES[@]}"
    printf '\n'
  fi
  if [ "${#REQUIRED_IMPORTS[@]}" -gt 0 ]; then
    printf 'required_imports: '
    join_values "${REQUIRED_IMPORTS[@]}"
    printf '\n'
  fi
  if [ "${#REQUIRED_EXTRAS[@]}" -gt 0 ]; then
    printf 'required_extras: '
    join_values "${REQUIRED_EXTRAS[@]}"
    printf '\n'
  fi
  if [ -n "$CAPABILITY_CHECKS_TEXT" ]; then
    printf '%s\n' "$CAPABILITY_CHECKS_TEXT"
  fi
  if [ -n "$IMPORT_CHECKS_TEXT" ]; then
    printf '%s\n' "$IMPORT_CHECKS_TEXT"
  fi
  if [ -n "$UPDATE_CHECK_STATUS" ]; then
    printf 'update_check: %s\n' "$UPDATE_CHECK_STATUS"
    if [ -n "$UPDATE_CHECK_REMOTE_VERSION" ]; then
      printf 'latest_version: %s\n' "$UPDATE_CHECK_REMOTE_VERSION"
    fi
    if [ "$UPDATE_CHECK_AVAILABLE" = true ]; then
      printf 'update_available: true\n'
      printf 'update: run %s --update --json or set FINJUICE_AUTO_UPDATE=1\n' "$HELPER_COMMAND"
    fi
    if [ -n "$UPDATE_CHECK_MESSAGE" ]; then
      printf 'update_check_message: %s\n' "$UPDATE_CHECK_MESSAGE"
    fi
    if [ -n "$UPDATE_CHECK_SNOOZED_UNTIL_ISO" ]; then
      printf 'snoozed_until: %s\n' "$UPDATE_CHECK_SNOOZED_UNTIL_ISO"
    fi
  fi
}

emit_blocked() {
  local reason=$1
  local message=$2
  local install_action=$3
  local runtime=$4
  local exit_code=${5:-}
  local fallback_example=${6:-}
  local update_requested=${7:-false}

  if [ "$JSON_MODE" = true ]; then
    printf '{"status":"blocked","reason":"%s","message":"%s","install_action":"%s","runtime":"%s"' \
      "$(json_escape "$reason")" \
      "$(json_escape "$message")" \
      "$(json_escape "$install_action")" \
      "$(json_escape "$runtime")"
    if [ -n "$exit_code" ]; then
      printf ',"exit_code":%s' "$exit_code"
    fi
    if [ -n "$fallback_example" ]; then
      printf ',"fallback_example":"%s"' "$(json_escape "$fallback_example")"
    fi
    if [ "$update_requested" = true ]; then
      printf ',"update_requested":true'
    fi
    printf '}\n'
    return
  fi

  printf '%s\n' "finjuice runtime ensure blocked"
  printf 'reason: %s\n' "$reason"
  printf 'message: %s\n' "$message"
  printf 'install: %s\n' "$install_action"
  printf 'runtime: %s\n' "$runtime"
  if [ -n "$exit_code" ]; then
    printf 'exit_code: %s\n' "$exit_code"
  fi
  if [ -n "$fallback_example" ]; then
    printf 'fallback: %s\n' "$fallback_example"
  fi
  if [ "$update_requested" = true ]; then
    printf 'update_requested: true\n'
  fi
}

version_or_block() {
  local install_action=$1
  local runtime=$2
  local update_requested=${3:-false}
  local check_updates=${4:-false}
  local version_output
  local version_exit

  version_output="$(read_finjuice_version)"
  version_exit=$?
  if [ "$version_exit" -ne 0 ]; then
    local reason="finjuice_version_failed"
    local message="finjuice exists but finjuice --version failed; the runtime was not reinstalled."
    if [ "$update_requested" = true ]; then
      reason="update_failed"
      message="finjuice update completed, but finjuice --version failed."
    fi
    emit_blocked \
      "$reason" \
      "$message" \
      "$install_action" \
      "$runtime" \
      "$version_exit" \
      "" \
      "$update_requested"
    return 1
  fi

  if ! requirements_or_block "$version_output" "$install_action" "$runtime"; then
    return 1
  fi

  if [ "$check_updates" = true ]; then
    run_update_check "$version_output"
  fi

  emit_ready "$install_action" "$version_output" "$runtime" "$update_requested"
}

if [ "${FINJUICE_AUTO_UPDATE:-}" = "1" ]; then
  UPDATE_REQUESTED=true
fi

while [ "$#" -gt 0 ]; do
  case "$1" in
    --json)
      JSON_MODE=true
      ;;
    --update)
      UPDATE_REQUESTED=true
      ;;
    --snooze-update-check)
      if [ "$#" -lt 2 ]; then
        printf 'Missing value for --snooze-update-check\n' >&2
        usage >&2
        exit 2
      fi
      SNOOZE_DAYS=$2
      shift
      ;;
    --require-version)
      if [ "$#" -lt 2 ]; then
        printf 'Missing value for --require-version\n' >&2
        usage >&2
        exit 2
      fi
      REQUIRED_VERSION=$2
      shift
      ;;
    --require-command)
      if [ "$#" -lt 2 ]; then
        printf 'Missing value for --require-command\n' >&2
        usage >&2
        exit 2
      fi
      REQUIRED_COMMANDS+=("$2")
      shift
      ;;
    --require-flag)
      if [ "$#" -lt 2 ]; then
        printf 'Missing value for --require-flag\n' >&2
        usage >&2
        exit 2
      fi
      REQUIRED_FLAGS+=("$2")
      shift
      ;;
    --require-capability)
      if [ "$#" -lt 2 ]; then
        printf 'Missing value for --require-capability\n' >&2
        usage >&2
        exit 2
      fi
      REQUIRED_CAPABILITIES+=("$2")
      shift
      ;;
    --require-import)
      if [ "$#" -lt 2 ]; then
        printf 'Missing value for --require-import\n' >&2
        usage >&2
        exit 2
      fi
      REQUIRED_IMPORTS+=("$2")
      if [ "$2" = "duckdb" ]; then
        ANALYTICS_EXTRA_REQUIRED=true
      fi
      shift
      ;;
    --require-extra)
      if [ "$#" -lt 2 ]; then
        printf 'Missing value for --require-extra\n' >&2
        usage >&2
        exit 2
      fi
      case "$2" in
        analytics)
          REQUIRED_EXTRAS+=("$2")
          REQUIRED_IMPORTS+=("duckdb")
          ANALYTICS_EXTRA_REQUIRED=true
          ;;
        *)
          printf 'Unknown --require-extra value: %s\n' "$2" >&2
          usage >&2
          exit 2
          ;;
      esac
      shift
      ;;
    -h | --help)
      usage
      exit 0
      ;;
    *)
      printf 'Unknown argument: %s\n' "$1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

# Compute version-pinned install URL when --require-version is set.
# This pins the git tag so that install/update respects the required version.
_resolve_install_url() {
  local base_url="$_REPO_URL"
  if [ -n "$REQUIRED_VERSION" ]; then
    printf '%s@v%s' "$base_url" "$REQUIRED_VERSION"
  else
    printf '%s' "$base_url"
  fi
}
_INSTALL_URL="$(_resolve_install_url)"
if [ "$ANALYTICS_EXTRA_REQUIRED" = true ]; then
  INSTALL_COMMAND="uv tool install --with duckdb ${_INSTALL_URL}"
  UPDATE_COMMAND="uv tool install --force --with duckdb ${_INSTALL_URL}"
  FALLBACK_COMMAND="uvx --from ${_INSTALL_URL} --with duckdb finjuice --help"
else
  INSTALL_COMMAND="uv tool install ${_INSTALL_URL}"
  UPDATE_COMMAND="uv tool install --force ${_INSTALL_URL}"
  FALLBACK_COMMAND="uvx --from ${_INSTALL_URL} finjuice --help"
fi

if [ "$UPDATE_REQUESTED" = true ]; then
  if ! command -v uv >/dev/null 2>&1; then
    emit_blocked \
      "update_failed" \
      "finjuice update was requested, but uv is not available; install uv first, then rerun the helper with --update." \
      "failed" \
      "none" \
      "" \
      "" \
      true
    exit 1
  fi

  update_output=""
  if [ "$ANALYTICS_EXTRA_REQUIRED" = true ]; then
    update_output="$(uv tool install --force --with duckdb ${_INSTALL_URL} 2>&1)"
  else
    update_output="$(uv tool install --force ${_INSTALL_URL} 2>&1)"
  fi
  update_exit=$?
  if [ "$update_exit" -ne 0 ]; then
    if [ "$JSON_MODE" != true ] && [ -n "$update_output" ]; then
      printf '%s\n' "$update_output" >&2
    fi
    emit_blocked \
      "update_failed" \
      "${UPDATE_COMMAND} failed; finjuice was not updated." \
      "failed" \
      "uv-tool" \
      "$update_exit" \
      "" \
      true
    exit 1
  fi

  if [ -z "$(finjuice_runtime_path)" ]; then
    emit_blocked \
      "update_failed" \
      "uv tool install --force completed, but finjuice is still not on PATH; run uv tool update-shell or restart the shell." \
      "updated" \
      "uv-tool" \
      "" \
      "" \
      true
    exit 1
  fi

  if ! runtime_path_or_block "updated" "uv-tool"; then
    exit 1
  fi

  version_or_block "updated" "uv-tool" true
  exit $?
fi

if [ -n "$(finjuice_runtime_path)" ]; then
  if ! runtime_path_or_block "none" "path"; then
    exit 1
  fi
  version_or_block "none" "path" false true
  exit $?
fi

if ! command -v uv >/dev/null 2>&1; then
  emit_blocked \
    "uv_missing" \
    "finjuice CLI is not installed and uv is not available; install uv first, then rerun this helper." \
    "none" \
    "none" \
    "" \
    "$FALLBACK_COMMAND"
  exit 1
fi

install_output=""
if [ "$ANALYTICS_EXTRA_REQUIRED" = true ]; then
  install_output="$(uv tool install --with duckdb ${_INSTALL_URL} 2>&1)"
else
  install_output="$(uv tool install ${_INSTALL_URL} 2>&1)"
fi
install_exit=$?
if [ "$install_exit" -ne 0 ]; then
  if [ "$JSON_MODE" != true ] && [ -n "$install_output" ]; then
    printf '%s\n' "$install_output" >&2
  fi
  emit_blocked \
    "install_failed" \
    "${INSTALL_COMMAND} failed; finjuice was not installed." \
    "failed" \
    "uv-tool" \
    "$install_exit"
  exit 1
fi

if [ -z "$(finjuice_runtime_path)" ]; then
  emit_blocked \
    "finjuice_missing_after_install" \
    "uv tool install completed, but finjuice is still not on PATH; run uv tool update-shell or restart the shell." \
    "installed" \
    "uv-tool"
  exit 1
fi

if ! runtime_path_or_block "installed" "uv-tool"; then
  exit 1
fi

version_or_block "installed" "uv-tool"
