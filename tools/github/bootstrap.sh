#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-or-later
# Crea etiquetas, milestones del roadmap e issues de v0.1.0a1 en eribertocz/geoduck con `gh`.
# Requisitos: el repositorio existe, `gh auth status` es válido y el usuario autorizó la operación.
# No empuja código, no fusiona PR, no crea tags ni releases. Es idempotente para etiquetas y milestones.
set -euo pipefail
REPO="${REPO:-eribertocz/geoduck}"
DIR="$(cd "$(dirname "$0")" && pwd)"
DRY_RUN="${DRY_RUN:-1}"   # por defecto solo muestra lo que haría; DRY_RUN=0 para ejecutar

run() { if [[ "$DRY_RUN" == "1" ]]; then printf '[dry-run]'; printf ' %q' "$@"; echo; else "$@"; fi; }

while IFS=$'\t' read -r name color desc; do
  run gh label create "$name" --repo "$REPO" --color "$color" --description "$desc" --force
done < "$DIR/labels.tsv"

existing="$( [[ "$DRY_RUN" == "1" ]] || gh api "repos/$REPO/milestones?state=all" --jq '.[].title' )"
while IFS=$'\t' read -r title desc; do
  grep -qxF "$title" <<<"$existing" || run gh api "repos/$REPO/milestones" -f title="$title" -f description="$desc"
done < "$DIR/milestones.tsv"

for f in "$DIR"/issues/GD-*.md; do
  title="$(sed -n 's/^title: "\(.*\)"$/\1/p' "$f")"
  labels="$(sed -n 's/^labels: //p' "$f")"
  body="$(awk 'BEGIN{n=0} /^---$/{n++; next} n>=2' "$f")"
  run gh issue create --repo "$REPO" --title "$title" --label "$labels" --milestone v0.1.0a1 --body "$body"
done
