# ntfy-admin

Interface web d'administration pour un serveur ntfy personnel.

## Architecture

- `frontend/` : interface web React + TypeScript
- `backend/` : API Python + FastAPI
- `deploy/` : fichiers de déploiement
- `docs/` : documentation

## Principes de sécurité

- Préserver l'installation ntfy existante.
- Ne jamais versionner de mots de passe, jetons ou clés privées.
- Vérifier les autorisations côté backend pour chaque action.
- Journaliser les opérations administratives sensibles.
- Ne pas exposer directement la base de données ntfy ni le socket Docker à l'interface web.

## État du projet

Structure initiale en cours de préparation.
