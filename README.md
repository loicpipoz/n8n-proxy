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
N8N_UPSTREAM_URL=http://n8n-prod.your-tailnet.ts.net:5678
WEBHOOK_PATHS="/webhook/stripe/* /webhook/github/*"
ALLOWED_SOURCE_CIDRS="0.0.0.0/0 ::/0"
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
