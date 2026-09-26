#!/usr/bin/env bash
# Copy connector jars resolved by Ivy into Spark's jar directory without duplicating any
# library Spark already ships, and fail the build if an added jar would still collide.
#
# Ivy names jars "<org>_<artifact>-<version>.jar"; Spark ships "<artifact>-<version>[...].jar".
# Both are reduced to "<artifact>" before comparing, so e.g.
# com.fasterxml.jackson.core_jackson-core-2.13.5.jar is skipped in favour of Spark's jackson-core.
# Spark's own jar set is not policed: it legitimately ships several builds of some artifacts
# (per-platform netty natives, jline 2 and 3, hive-shims).
set -euo pipefail

ivy_dir="$1"
spark_jars="/opt/spark/jars"

# "<artifact>-<version>[-classifier]" -> "<artifact>": cut at the first "-<digits>.<digit>".
strip_version() {
  sed -E 's/-[0-9]+\.[0-9].*$//' <<< "$(basename "$1" .jar)"
}

# Ivy jars always carry an "<org>_" prefix (the org itself never contains "_").
ivy_artifact() {
  local name
  name="$(basename "$1")"
  strip_version "${name#*_}"
}

declare -A shipped=()
for jar in "$spark_jars"/*.jar; do
  shipped["$(strip_version "$jar")"]=1
done

declare -A added=()
for jar in "$ivy_dir"/*.jar; do
  name="$(ivy_artifact "$jar")"
  if [[ -n "${shipped[$name]:-}" ]]; then
    echo "skip (Spark ships $name): $(basename "$jar")"
    continue
  fi
  if [[ -n "${added[$name]:-}" ]]; then
    echo "ERROR: two resolved jars for artifact $name: ${added[$name]} and $(basename "$jar")" >&2
    exit 1
  fi
  cp "$jar" "$spark_jars/"
  added["$name"]="$(basename "$jar")"
  echo "add: $(basename "$jar")"
done

echo "added ${#added[@]} jars; none duplicates a shipped or another added artifact"
