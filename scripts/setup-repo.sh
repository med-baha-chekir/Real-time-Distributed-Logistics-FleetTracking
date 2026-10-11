#!/usr/bin/env bash
# Prépare le dépôt Git : main, develop et les branches de travail.
# À lancer UNE fois, par un seul membre.
# Usage : ./scripts/setup-repo.sh [URL_DU_DEPOT_GITHUB]
set -euo pipefail

REMOTE_URL="${1:-}"
FEATURES=(
  feature/sharding-cluster
  feature/geo-queries
  feature/generator-v2
  feature/indexes-aggregations
)

cd "$(dirname "$0")/.."

if [ -d .git ]; then
  echo "Un dépôt Git existe déjà ici. Rien à faire." >&2
  exit 1
fi

git init -b main
git add -A
git commit -m "chore: initial commit (phases 1 et 2 : Replica Set, générateur v1)"
git tag -a v0.2.0 -m "Phases 1 et 2"

git branch develop
for b in "${FEATURES[@]}"; do
  git branch "$b" develop
done

if [ -n "$REMOTE_URL" ]; then
  git remote add origin "$REMOTE_URL"
  git push -u origin main develop
  git push origin "${FEATURES[@]}"
  git push origin --tags
fi

git switch develop
echo
echo "Branches créées :"
git branch
