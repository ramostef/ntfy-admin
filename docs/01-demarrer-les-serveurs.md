# RMS — Démarrer les serveurs

Guide court pour l’installation actuelle sur `pc-home`.

## Les trois services

| Service | Rôle | Démarrage |
|---|---|---|
| `ntfy-admin-backend` | API RMS (FastAPI) et base SQLite | systemd |
| `ntfy-admin-frontend` | Interface locale de développement (Vite) | systemd |
| `ntfy` et `ntfy-caddy` | Notifications ntfy, HTTPS et accès public RMS | Docker Compose |

## Démarrer ou vérifier RMS

Depuis un terminal administrateur (par exemple `su -`) :

```bash
systemctl start ntfy-admin-backend ntfy-admin-frontend
systemctl status ntfy-admin-backend ntfy-admin-frontend --no-pager
```

L’interface locale est sur [http://localhost:5173](http://localhost:5173). Pour contrôler l’API :

```bash
curl http://172.18.0.1:8000/health
```

La réponse attendue est `{"status":"ok"}`.

## Démarrer ntfy et l’accès HTTPS

```bash
cd /opt/ntfy
docker compose up -d ntfy caddy
docker compose ps
```

RMS public : [https://rms-pc-home.duckdns.org](https://rms-pc-home.duckdns.org). Le serveur ntfy utilise son propre sous-domaine configuré dans Caddy.

## Redémarrer après un changement

```bash
systemctl restart ntfy-admin-backend
systemctl restart ntfy-admin-frontend
```

Après modification du Caddyfile ou de `compose.yml` :

```bash
cd /opt/ntfy
docker compose config -q
docker compose up -d caddy
```

Après modification du code frontend, la version locale sur le port 5173 se recharge généralement seule. Pour mettre à jour la version publique servie par Caddy :

```bash
cd /opt/ntfy-admin/frontend
npm run build
```

## Journaux en cas de problème

```bash
journalctl -u ntfy-admin-backend -n 50 --no-pager
journalctl -u ntfy-admin-frontend -n 50 --no-pager
docker logs --tail 50 ntfy-caddy
docker logs --tail 50 ntfy
```

Si un port est déjà utilisé, ne lancez pas une seconde copie du service : vérifiez d’abord son état avec `systemctl status ...` et son journal.

## Arrêter

```bash
systemctl stop ntfy-admin-frontend ntfy-admin-backend
cd /opt/ntfy
docker compose stop caddy ntfy
```

L’arrêt du backend ou du conteneur ntfy interrompt les fonctions qui en dépendent. Les données sont conservées dans leurs répertoires de données.
