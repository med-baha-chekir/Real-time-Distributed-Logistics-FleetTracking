# Règles de travail

## Branches

| Branche | Rôle | Qui y écrit |
|---|---|---|
| `main` | Version stable, livrable. Un tag par phase (`v0.2.0`...) | Personne directement : seulement par PR depuis `develop` |
| `develop` | Intégration du travail de la semaine | Personne directement : seulement par PR depuis une branche de travail |
| `<auteur>/feature/<sujet>` | Une tâche (ex. `feature/generator-v2`) | Son auteur |
| `<auteur>/fix/<sujet>` | Correction d'un bug | Son auteur |

Une branche = une tâche = une Pull Request. On supprime la branche après la fusion.

## Travail quotidien

```bash
git switch develop && git pull
git switch -c <auteur>/feature/mon-sujet          # ou reprendre une branche existante

# ... travail, puis commits petits et fréquents
git add <fichiers>
git commit -m "feat(generator): ajoute les anomalies de surchauffe"

git push -u origin <auteur>/feature/mon-sujet
# Ouvrir la Pull Request vers develop sur GitHub
```

Pour récupérer le travail de l'autre pendant qu'on travaille :

```bash
git fetch origin
git rebase origin/develop
```
