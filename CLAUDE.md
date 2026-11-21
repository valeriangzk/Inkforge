# Consignes pour Claude — INKFORGE Studio

## Le propriétaire
- Il ne code pas. Il décrit en français ce qu'il veut, et Claude le traduit en code.
- Son objectif est d'automatiser au maximum et d'intervenir le moins possible.
- Il ne doit être sollicité que pour ce que le système interdit à Claude, ou quand Claude est vraiment bloqué.

## Comptes rendus
- Toujours en français, très courts, sans aucun détail technique.
- Format : « publié », « en cours » ou « bloqué : raison + ce qu'il doit faire ».

## Façon de travailler
- Claude enchaîne seul le code, les tests et les corrections.
- **Sauvegarde** : avant toute grosse modification, partir d'une branche à jour de `main`. La dernière version qui marche reste toujours sur `main` et dans la dernière release.
- **Tests** : chaque nouvelle fonction arrive avec son test.
- **Si un test échoue**, Claude cherche la cause et corrige seul. Il ne contacte le propriétaire que s'il est vraiment bloqué. Un test qui échoue au hasard est un vrai problème à corriger, pas à relancer.
- **Publication** : dès que tous les tests passent, Claude publie seul la nouvelle version, sans demander. Pour cela, il change le numéro de version dans `version.json` et dans les autres mentions de version, puis lance « Run workflow » du workflow « Vérifier INKFORGE sous Windows » sur `main`.
- Une release déjà publiée n'est jamais modifiée.

## Ce que Claude ne peut pas faire seul (limites du système)
- Fusionner une demande de fusion sur `main` : le propriétaire clique sur « Squash and merge ».
- Créer ou supprimer des tags, supprimer des branches, modifier une release à la main.
- Pour supprimer les branches, le propriétaire utilise le bouton « Nettoyer les branches » dans l'onglet Actions.

## Le logiciel
- `INKFORGE.html` : l'interface. `serveur_inkforge.py` : le relais local en Python. Pour le lancer : `LANCER_INKFORGE.cmd` (Windows).
- Les données de travail sont dans `_inkforge_travail`.
- Fonctions : planches, cases, bulles, personnages, décors, génération d'images avec Agnes AI (clé gardée uniquement en mémoire), panoramas 360°, Studio 3D local (TripoSR, carte NVIDIA).
- Tests : `tests/` (Python et Playwright). Ils tournent sous Windows dans GitHub Actions, sur `main`, `fix/**`, les demandes de fusion et les tags.

## Phase actuelle : expérimentale
- Le propriétaire recrée ses BD de zéro à chaque version pour vérifier tout le parcours.
- Plus tard : protéger les projets des utilisateurs lors des mises à jour, et définir des règles de design.
