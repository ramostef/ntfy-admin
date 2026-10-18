# RMS — Missions & talents

Front mobile RMS connecté à l’API FastAPI et à la base SQLite déjà utilisée par `/opt/ntfy-admin/backend`.

## Parcours

- **Vue d’ensemble** : état des missions, profils et notifications.
- **Missions** : création d’une fiche, consultation des profils correspondants et notifications aux seuls profils sélectionnés.
- **Profils** : création et modification des profils dans SQLite, avec sélection des comptes ntfy et des topics enregistrés. Un topic déjà affecté à un autre profil est verrouillé.

Les autres écrans d’administration ntfy ne sont plus affichés dans le front RMS. Le backend, sa configuration ntfy et sa base SQLite restent en place.

## Lancer en développement

Dans un premier terminal :

```bash
cd /opt/ntfy-admin/backend
source .venv/bin/activate
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Au démarrage, le backend initialise les tables et applique les migrations SQLite prévues par le projet.

Dans un second terminal :

```bash
cd /opt/ntfy-admin/frontend
npm run dev -- --host 0.0.0.0 --port 5173
```

Ouvrez l’adresse affichée par Vite. Le proxy de développement transmet `/api` au backend sur le port 8000. Le front de production se trouve dans `dist/` et doit être servi derrière le proxy API existant.
