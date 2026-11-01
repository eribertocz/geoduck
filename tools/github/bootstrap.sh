#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-or-later
# Crea etiquetas, milestones del roadmap e issues de v0.1.0a1 en eribertocz/geoduck usando la API REST
# de GitHub mediante `gh api` (sin GraphQL).
# Requisitos: el repositorio existe y `gh` está autenticado con permiso de escritura.
# No empuja código, no fusiona PR, no crea tags ni releases.
# Idempotente: etiquetas y milestones se actualizan si existen; un issue no se duplica si ya hay otro
# con el mismo título.
set -euo pipefail
REPO="${REPO:-eribertocz/geoduck}"
DIR="$(cd "$(dirname "$0")" && pwd)"
DRY_RUN="${DRY_RUN:-1}"   # por defecto solo muestra lo que haría; DRY_RUN=0 para ejecutar

run() { if [[ "$DRY_RUN" == "1" ]]; then printf '[dry-run]'; printf ' %q' "$@"; echo; else "$@"; fi; }

# Etiquetas
existing_labels="$( [[ "$DRY_RUN" == "1" ]] || gh api "repos/$REPO/labels?per_page=100" --jq '.[].name' )"
while IFS=$'\t' read -r name color desc; do
  if grep -qxF "$name" <<<"$existing_labels"; then
    run gh api -X PATCH "repos/$REPO/labels/$(jq -rn --arg n "$name" '$n|@uri')" \
      -f color="$color" -f description="$desc" --silent
  else
    run gh api "repos/$REPO/labels" -f name="$name" -f color="$color" -f description="$desc" --silent
  fi
done < "$DIR/labels.tsv"

# Milestones
existing_ms="$( [[ "$DRY_RUN" == "1" ]] || gh api "repos/$REPO/milestones?state=all&per_page=100" --jq '.[].title' )"
while IFS=$'\t' read -r title desc; do
  grep -qxF "$title" <<<"$existing_ms" || run gh api "repos/$REPO/milestones" -f title="$title" -f description="$desc" --silent
done < "$DIR/milestones.tsv"

# Issues de v0.1.0a1
if [[ "$DRY_RUN" == "1" ]]; then
  ms_number="<n>"
  existing_issues=""
else
  ms_number="$(gh api "repos/$REPO/milestones?state=all&per_page=100" --jq '.[] | select(.title=="v0.1.0a1") | .number')"
  existing_issues="$(gh api "repos/$REPO/issues?state=all&per_page=100" --jq '.[].title')"
fi
for n in 1 2 3 4 5 6 7 8 9 10 11 12; do
  f="$DIR/issues/GD-$n.md"
  title="$(sed -n 's/^title: "\(.*\)"$/\1/p' "$f")"
  labels="$(sed -n 's/^labels: //p' "$f")"
  body="$(awk 'BEGIN{n=0} /^---$/{n++; next} n>=2' "$f")"
  if grep -qxF "$title" <<<"$existing_issues"; then
    echo "ya existe: $title"
    continue
  fi
  label_args=()
  IFS=',' read -ra parts <<<"$labels"
  for l in "${parts[@]}"; do label_args+=(-f "labels[]=$l"); done
  run gh api "repos/$REPO/issues" -f title="$title" -f body="$body" -F milestone="$ms_number" \
    "${label_args[@]}" --jq '"#\(.number) \(.title)"'
done
