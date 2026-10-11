# Règles de travail

## Branches

| Branche | Rôle | Qui y écrit |
|---|---|---|
| `main` | Version stable, livrable. Un tag par phase (`v0.2.0`...) | Personne directement : seulement par PR depuis `develop` |
| `develop` | Intégration du travail de la semaine | Personne directement : seulement par PR depuis une branche de travail |
| `feature/<sujet>` | Une tâche (ex. `feature/generator-v2`) | Son auteur |
| `fix/<sujet>` | Correction d'un bug | Son auteur |
| `docs/<sujet>` | Rapport, README | Son auteur |

Une branche = une tâche = une Pull Request. On supprime la branche après la fusion.

## Travail quotidien

```bash
git switch develop && git pull
git switch -c feature/mon-sujet          # ou reprendre une branche existante

# ... travail, puis commits petits et fréquents
git add <fichiers>
git commit -m "feat(generator): ajoute les anomalies de surchauffe"

git push -u origin feature/mon-sujet
# Ouvrir la Pull Request vers develop sur GitHub
```

Pour récupérer le travail de l'autre pendant qu'on travaille :

```bash
git fetch origin
git rebase origin/develop
```

## Messages de commit

Format : `type(zone): description courte`

Types : `feat` (nouveauté), `fix` (correction), `docs`, `test`, `chore` (outillage), `refactor`.
Zones : `infra`, `generator`, `dashboard`, `sharding`, `geo`, `agg`.

## Pull Request

- Elle vise `develop` (jamais `main`, sauf la PR de fin de semaine `develop` vers `main`).
- Le **CI doit être vert**.
- **L'autre membre relit** et approuve (1 approbation minimum). On ne valide jamais sa propre PR.
- Fusion en **Squash and merge** : un seul commit propre sur `develop`.
- Remplir le modèle de PR (ce qui change, comment tester).

## Fin de semaine

1. PR `develop` vers `main`, relue par l'autre.
2. Après fusion, poser un tag : `git tag -a v0.3.0 -m "Phase 3" && git push --tags`.

## Secrets

`.env` et `secrets/` ne sont **jamais** versionnés. Utiliser `.env.example` comme modèle.
