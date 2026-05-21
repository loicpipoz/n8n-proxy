# Notes pour la prochaine intervention Codex

Derniere mise a jour: 2026-05-21.

Ce fichier est une note de reprise pour Codex. Il resume les acquis, les choix d'architecture, les pieges rencontres et les commandes utiles autour du repo `n8n-proxy`.

## Contexte

- Repo local: `n8n-proxy`.
- Remote GitHub: `https://github.com/loicpipoz/n8n-proxy`.
- Objectif: exposer uniquement des endpoints publics n8n autorises, avec logs, en gardant n8n accessible via Tailscale.
- Domaine public du proxy: `n8n-wh01.spiritviews.com`.
- Instance n8n tailnet testee: `n8n.monkey-eel.ts.net`.
- IP Tailscale observee pour cette instance: `100.68.54.24`.
- Le serveur a deja Nginx Proxy Manager dans le stack Rustdesk, qui occupe les ports publics `80` et `443`.

## Architecture retenue

Flux cible:

```text
Internet
  -> Nginx Proxy Manager :443
  -> host Docker gateway 172.17.0.1:8080
  -> n8n-proxy Caddy :80
  -> Tailscale namespace
  -> n8n via HTTPS tailnet
```

Nginx Proxy Manager gere le certificat public Let's Encrypt. Caddy ne doit donc pas gerer TLS public dans ce mode.

Config NPM attendue:

```text
Domain Names: n8n-wh01.spiritviews.com
Scheme: http
Forward Hostname / IP: 172.17.0.1
Forward Port: 8080
SSL: Request a new SSL Certificate
Force SSL: enabled
HTTP/2 Support: enabled
```

Ne pas utiliser `127.0.0.1` dans NPM: depuis le conteneur NPM, cela pointe vers le conteneur NPM lui-meme, pas vers l'hote.

## `.env` serveur recommande

Secrets a garder hors Git. Ne jamais commit le vrai `TS_AUTHKEY`.

```env
TS_AUTHKEY=tskey-auth-REDACTED
TAILSCALE_VERSION=latest
TAILSCALE_HOSTNAME=n8n-wh01
TS_EXTRA_ARGS="--ssh --accept-dns=true"

PUBLIC_DOMAIN=n8n-wh01.spiritviews.com
CADDY_SITE_ADDRESS=:80

N8N_UPSTREAM_URL=https://100.68.54.24
N8N_UPSTREAM_HOST=n8n.monkey-eel.ts.net
N8N_UPSTREAM_TLS_SERVER_NAME=n8n.monkey-eel.ts.net

WEBHOOK_METHODS="POST GET"
WEBHOOK_PATHS="/webhook/* /webhook-test/*"

FORM_METHODS="GET POST"
FORM_PATHS="/form/* /form-test/* /form-waiting/*"

ALLOWED_SOURCE_CIDRS="0.0.0.0/0 ::/0"
MAX_BODY_SIZE=10MB
CADDY_LOG_DIR=/var/log/caddy

HTTP_BIND=0.0.0.0
HTTP_PORT=8080

HTTPS_BIND=127.0.0.1
HTTPS_PORT=18443
```

Notes:

- `CADDY_SITE_ADDRESS=:80` est critique derriere NPM. Sinon Caddy active Auto HTTPS et renvoie des `308`.
- `HTTP_BIND=0.0.0.0` rend le port `8080` joignable depuis le conteneur NPM via `172.17.0.1:8080`. Verifier le firewall pour ne pas exposer `8080` publiquement.
- `HTTPS_BIND/HTTPS_PORT` restent la pour satisfaire le compose, mais NPM n'utilise pas ce port.

## Pieges rencontres

### Caddy Auto HTTPS derriere NPM

Symptome:

```text
curl http://127.0.0.1:8080/healthz
-> 308 Permanent Redirect
```

Cause: Caddy utilise encore `PUBLIC_DOMAIN` comme site address et active Auto HTTPS.

Fix:

```env
CADDY_SITE_ADDRESS=:80
```

Puis:

```bash
docker compose down
docker compose up -d --force-recreate
```

### NPM vers backend

Symptome:

```text
https://n8n-wh01.spiritviews.com/healthz -> 502 openresty
```

Cause typique: NPM forward vers `127.0.0.1`.

Fix:

```text
Forward Hostname / IP: 172.17.0.1
Forward Port: 8080
```

### MagicDNS Tailscale non resolu dans Caddy

Symptome:

```text
wget: bad address 'n8n.monkey-eel.ts.net'
```

ou dans `logs/runtime.log`:

```text
dial tcp: lookup n8n.monkey-eel.ts.net on 127.0.0.11:53: no such host
```

Fix retenu: utiliser l'IP Tailscale comme upstream et garder le hostname pour Host/SNI TLS.

```env
N8N_UPSTREAM_URL=https://100.68.54.24
N8N_UPSTREAM_HOST=n8n.monkey-eel.ts.net
N8N_UPSTREAM_TLS_SERVER_NAME=n8n.monkey-eel.ts.net
```

Attention: l'IP Tailscale est stable en pratique pour un node, mais a revalider si la machine n8n est recrée.

### Upstream HTTPS par IP et HTTP/2

Symptome:

```text
http2: invalid Host header
```

Fix pousse dans le Caddyfile: forcer HTTP/1.1 vers l'upstream.

```caddyfile
transport http {
	versions 1.1
	tls_server_name {$N8N_UPSTREAM_TLS_SERVER_NAME}
}
```

### Logs Caddy

Les logs sont montes dans `logs/`, mais appartiennent souvent a root.

Utiliser:

```bash
sudo tail -n 100 logs/runtime.log
sudo tail -n 100 logs/access.log
```

`docker compose logs caddy` peut etre vide parce que Caddy redirige ses logs vers les fichiers.

### Git signing 1Password

Un commit a bloque avec:

```text
error: 1Password: failed to fill whole buffer
fatal: failed to write commit object
```

Contournement:

```bash
git -c commit.gpgsign=false commit -m "Message"
```

## Commandes de diagnostic utiles

Verifier la config effective Compose:

```bash
docker compose config | grep -A8 CADDY_SITE_ADDRESS
docker compose config | grep -A10 N8N_UPSTREAM
```

Verifier les variables dans Caddy:

```bash
docker compose exec caddy env | grep N8N_UPSTREAM
docker compose exec caddy env | grep CADDY_SITE_ADDRESS
```

Verifier backend Caddy local:

```bash
curl -v http://127.0.0.1:8080/healthz
curl -v http://172.17.0.1:8080/healthz
```

Verifier public via NPM:

```bash
curl -vvv https://n8n-wh01.spiritviews.com/healthz
curl -vvv https://n8n-wh01.spiritviews.com/webhook/f2e41356-f794-44d1-b19a-560feb7741cf
```

Verifier Tailscale:

```bash
docker compose exec tailscale tailscale status
docker compose exec tailscale tailscale ping 100.68.54.24
```

Verifier les logs d'erreur Caddy:

```bash
sudo tail -n 50 logs/runtime.log
sudo tail -n 50 logs/access.log
```

## Routes autorisees

Webhooks:

```env
WEBHOOK_METHODS="POST GET"
WEBHOOK_PATHS="/webhook/* /webhook-test/*"
```

Forms:

```env
FORM_METHODS="GET POST"
FORM_PATHS="/form/* /form-test/* /form-waiting/*"
```

Notes securite:

- Eviter `webhook-test` et `form-test` en production sauf besoin explicite.
- Preferer des chemins precis plutot que des wildcards quand les paths finaux sont connus.
- Pour les forms publiques, prevoir une validation cote workflow si les donnees sont sensibles.
- `ALLOWED_SOURCE_CIDRS` ouvert est acceptable pour des forms publiques, mais moins robuste pour des webhooks serveur-a-serveur.

## Etat fonctionnel observe

Etat valide avant cette note:

- `CADDY_SITE_ADDRESS=:80` fonctionne: `/healthz` local retourne `200 ok`.
- NPM peut joindre le backend quand il pointe vers `172.17.0.1:8080`.
- Le direct Tailscale vers `https://n8n.monkey-eel.ts.net/webhook/...` retourne `{"message":"Workflow was started"}` depuis le poste client tailnet.
- Le dernier correctif pousse force HTTP/1.1 vers l'upstream pour resoudre `http2: invalid Host header`; a retester cote serveur apres `git pull`.

## Ne pas faire

- Ne pas modifier directement les fichiers `data/nginx/proxy_host/*.conf` de Nginx Proxy Manager. NPM les genere depuis son interface/base SQLite et peut les ecraser.
- Ne pas commit `.env`, `logs/*.log`, auth keys, ou valeurs secretes.
- Ne pas supposer que MagicDNS Tailscale marche dans Caddy; tester et utiliser l'IP tailnet + SNI si besoin.
