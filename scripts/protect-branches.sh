#!/usr/bin/env bash
# Protège main et develop : PR obligatoire, 1 approbation, CI vert.
# Prérequis : GitHub CLI installé et connecté (gh auth login).
# Dépôt privé : la protection exige un compte GitHub payant ; sinon rendre le dépôt public.
# Usage : ./scripts/protect-branches.sh OWNER/REPO
set -euo pipefail

REPO="${1:?Usage: $0 OWNER/REPO}"

for BRANCH in main develop; do
  gh api -X PUT "repos/${REPO}/branches/${BRANCH}/protection" --input - <<'EOF'
{
  "required_status_checks": {
    "strict": true,
    "contexts": ["python-tests", "compose-validate"]
  },
  "enforce_admins": false,
  "required_pull_request_reviews": {
    "required_approving_review_count": 1
  },
  "restrictions": null,
  "allow_force_pushes": false,
  "allow_deletions": false
}
EOF
  echo "Protégée : ${BRANCH}"
done
