# n8n-proxy

Reverse proxy public pour webhooks n8n, avec Caddy en frontal HTTPS et Tailscale pour joindre les instances n8n privées du tailnet.

Le proxy n'expose pas l'éditeur n8n. Il ne transfère que les méthodes, chemins et sources IP autorisés dans `config/Caddyfile` via les variables `.env`. Tout le reste retourne `404`.

## Fichiers

- `compose.yaml`: stack Docker Compose Caddy + Tailscale.
- `.env.example`: variables à copier vers `.env`.
- `config/Caddyfile`: règles HTTPS, allowlist et logs JSON.
- `logs/`: fichiers de logs Caddy montés depuis le conteneur.

## Démarrage

```bash
cd n8n-proxy
cp .env.example .env
```

Édite `.env` :

```env
TS_AUTHKEY=tskey-auth-...
PUBLIC_DOMAIN=hooks.example.com
CADDY_SITE_ADDRESS=hooks.example.com
N8N_UPSTREAM_URL=https://n8n-prod.your-tailnet.ts.net
N8N_UPSTREAM_HOST=n8n-prod.your-tailnet.ts.net
N8N_UPSTREAM_TLS_SERVER_NAME=n8n-prod.your-tailnet.ts.net
WEBHOOK_PATHS="/webhook/stripe/* /webhook/github/*"
ALLOWED_SOURCE_CIDRS="0.0.0.0/0 ::/0"
HTTP_PORT=80
HTTPS_PORT=443
```

`PUBLIC_DOMAIN` doit contenir uniquement le hostname, sans schéma et sans port :

```env
PUBLIC_DOMAIN=n8n-wh01.spiritviews.com
```

Si tu exposes Caddy sur un port externe non standard, mets seulement le port dans `HTTPS_PORT` :

```env
PUBLIC_DOMAIN=n8n-wh01.spiritviews.com
HTTPS_PORT=1443
```

`CADDY_SITE_ADDRESS` controle l'adresse d'ecoute dans le Caddyfile. Pour un Caddy public qui gere lui-meme TLS, garde le domaine :

```env
CADDY_SITE_ADDRESS=n8n-wh01.spiritviews.com
```

Pour un Caddy place derriere un autre reverse proxy, utilise une ecoute HTTP simple :

```env
CADDY_SITE_ADDRESS=:80
```

Puis démarre :

```bash
docker compose up -d
```

Le service Tailscale utilise explicitement :

```bash
tailscale up --authkey="${TS_AUTHKEY}" ...
```

Dans `compose.yaml`, les `$` sont doublés (`$${TS_AUTHKEY}`) pour que Docker Compose ne remplace pas la variable trop tôt.

## DNS

Crée un `A` ou `AAAA` public pour `PUBLIC_DOMAIN` vers le serveur qui exécute ce proxy. Caddy gère automatiquement le certificat HTTPS Let's Encrypt sur les ports `80` et `443`.

Si `80` ou `443` est déjà utilisé sur le serveur, change les ports exposés côté hôte :

```env
HTTP_PORT=8080
HTTPS_PORT=8443
```

Dans ce cas, il faut placer un autre reverse proxy devant, ou ouvrir/appeler explicitement ces ports. Pour que Caddy obtienne automatiquement un certificat Let's Encrypt en HTTP-01/TLS-ALPN-01, les ports publics standards `80`/`443` doivent arriver jusqu'à Caddy.

Un symptôme courant quand Caddy ne peut pas obtenir de certificat est :

```text
tlsv1 alert internal error
```

Vérifie alors :

```bash
docker compose logs caddy
```

Et assure-toi que `PUBLIC_DOMAIN` ne contient pas `:1443`. Pour un certificat public Let's Encrypt automatique, au moins le port public `80` ou `443` doit permettre la validation ACME vers Caddy. Sinon, utilise un reverse proxy existant sur `80/443`, ou monte un certificat existant dans Caddy.

## Derriere Nginx Proxy Manager

Si Nginx Proxy Manager est deja sur la meme machine et ecoute les ports publics `80` et `443`, laisse NPM gerer le certificat HTTPS et utilise `n8n-proxy` comme backend HTTP local.

Dans `.env` :

```env
PUBLIC_DOMAIN=n8n-wh01.spiritviews.com
CADDY_SITE_ADDRESS=:80
HTTP_BIND=127.0.0.1
HTTP_PORT=18080
HTTPS_BIND=127.0.0.1
HTTPS_PORT=18443
N8N_UPSTREAM_URL=https://n8n-prod.your-tailnet.ts.net
N8N_UPSTREAM_HOST=n8n-prod.your-tailnet.ts.net
N8N_UPSTREAM_TLS_SERVER_NAME=n8n-prod.your-tailnet.ts.net
WEBHOOK_PATHS="/webhook-test/* /webhook/*"
```

Puis :

```bash
docker compose down
docker compose up -d
```

Dans Nginx Proxy Manager, cree un Proxy Host :

```text
Domain Names: n8n-wh01.spiritviews.com
Scheme: http
Forward Hostname / IP: 127.0.0.1
Forward Port: 18080
SSL: Request a new SSL Certificate
Force SSL: enabled
HTTP/2 Support: enabled
```

Dans cette topologie, l'URL publique est :

```text
https://n8n-wh01.spiritviews.com/webhook-test/...
```

Pas besoin d'utiliser `:1443`, sauf si tu veux volontairement exposer un port HTTPS non standard.

Si le conteneur ne resout pas le nom MagicDNS Tailscale, cible l'IP Tailscale et garde le hostname pour le Host header et le SNI TLS :

```env
N8N_UPSTREAM_URL=https://100.68.54.24
N8N_UPSTREAM_HOST=n8n.monkey-eel.ts.net
N8N_UPSTREAM_TLS_SERVER_NAME=n8n.monkey-eel.ts.net
```

## Configuration n8n

Sur chaque instance n8n exposée derrière ce proxy :

```env
WEBHOOK_URL=https://hooks.example.com/
N8N_PROXY_HOPS=1
```

Si tu utilises un domaine par instance, chaque n8n doit avoir son propre `WEBHOOK_URL`.

## Logs

Logs applicatifs Caddy :

```bash
docker compose logs -f caddy
```

Logs d'accès JSON persistés :

```bash
tail -f logs/access.log
```

Logs runtime Caddy :

```bash
tail -f logs/runtime.log
```

## Whitelist

La whitelist active se configure dans `.env` :

```env
WEBHOOK_METHODS=POST
WEBHOOK_PATHS="/webhook/stripe/* /webhook/github/*"
ALLOWED_SOURCE_CIDRS="3.18.12.63/32 3.130.192.231/32"
```

Garde `WEBHOOK_PATHS` aussi précis que possible. Si le fournisseur webhook ne publie pas d'IP stables, laisse `ALLOWED_SOURCE_CIDRS` ouvert mais ajoute une vérification de signature dans le workflow n8n dès le premier node.

## Plusieurs instances n8n

Le plus propre est un domaine webhook par instance :

```caddyfile
hooks-client-a.example.com {
	log {
		output file /var/log/caddy/client-a-access.log
		format json
	}

	@webhooks {
		method POST
		path /webhook/client-a/*
		remote_ip 0.0.0.0/0 ::/0
	}

	handle @webhooks {
		reverse_proxy http://n8n-client-a.your-tailnet.ts.net:5678
	}

	respond 404
}
```

Dans ce cas, l'instance cible doit utiliser :

```env
WEBHOOK_URL=https://hooks-client-a.example.com/
N8N_PROXY_HOPS=1
```

## Tailscale ACL / grants

Exemple minimal côté policy Tailscale :

```json
{
  "tagOwners": {
    "tag:webhook-proxy": ["autogroup:admin"],
    "tag:n8n": ["autogroup:admin"]
  },
  "grants": [
    {
      "src": ["tag:webhook-proxy"],
      "dst": ["tag:n8n"],
      "ip": ["tcp:5678"]
    }
  ]
}
```

Tague tes instances n8n avec `tag:n8n` et le proxy avec `tag:webhook-proxy`. Le proxy ne doit pas avoir accès au reste du tailnet.
