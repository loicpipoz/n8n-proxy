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
FORM_METHODS="GET POST"
FORM_PATHS="/form/* /form-test/* /form-waiting/*"
ALLOWED_SOURCE_CIDRS="203.0.113.10/32"
NPM_EDGE_KEY=replace-with-64-hex-characters
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

Si Nginx Proxy Manager est deja sur la meme machine et ecoute les ports publics `80` et `443`, laisse NPM gerer le certificat HTTPS et utilise `n8n-proxy` comme backend HTTP via la passerelle Docker de l'hote.

Dans `.env` :

```env
PUBLIC_DOMAIN=n8n-wh01.spiritviews.com
CADDY_SITE_ADDRESS=:80
HTTP_BIND=0.0.0.0
HTTP_PORT=8080
HTTPS_BIND=127.0.0.1
HTTPS_PORT=18443
N8N_UPSTREAM_URL=https://n8n-prod.your-tailnet.ts.net
N8N_UPSTREAM_HOST=n8n-prod.your-tailnet.ts.net
N8N_UPSTREAM_TLS_SERVER_NAME=n8n-prod.your-tailnet.ts.net
WEBHOOK_PATHS="/webhook-test/* /webhook/*"
FORM_PATHS="/form-test/* /form/* /form-waiting/*"
ALLOWED_SOURCE_CIDRS="172.18.0.1/32"
NPM_EDGE_KEY=replace-with-64-hex-characters
```

Les liens d'approbation n8n générés par les nodes `Send and Wait` utilisent
`/webhook-waiting/*`. Le `config/Caddyfile` les transfere explicitement en
`GET` et `POST`, comme `/form-waiting/*`, vers l'instance n8n cible.

Puis :

```bash
docker compose down
docker compose up -d
```

Dans Nginx Proxy Manager, cree un Proxy Host :

```text
Domain Names: n8n-wh01.spiritviews.com
Scheme: http
Forward Hostname / IP: 172.17.0.1
Forward Port: 8080
SSL: Request a new SSL Certificate
Force SSL: enabled
HTTP/2 Support: enabled
```

Depuis le conteneur NPM, `127.0.0.1` designe NPM lui-meme et non l'hote.
L'adresse `172.17.0.1` est la passerelle Docker utilisee dans le deploiement
actuel. Le port `8080` ne doit pas etre expose par le firewall public ; il sert
uniquement au trajet NPM vers Caddy.

### Traitement des erreurs dans Nginx Proxy Manager

Caddy reste la barriere de securite principale : il limite les chemins, les
methodes HTTP et, si necessaire, les adresses source. Nginx Proxy Manager est
la couche TLS et de transport devant Caddy. Son masquage d'erreurs ne doit pas
remplacer l'allowlist Caddy.

Les reponses applicatives n8n `400`, `401`, `403`, `404`, `405`, `500` et
`503` doivent traverser NPM sans etre remplacees. SpiritBooking utilise
notamment `401` pour signaler un lien de gestion invalide ou expire, avec un
corps JSON et les en-tetes CORS attendus par le navigateur.

Dans l'onglet **Advanced** du Proxy Host NPM, limiter l'interception aux erreurs
de passerelle `502` et `504`, et injecter le secret partage avec Caddy :

```nginx
proxy_intercept_errors on;

# Cette valeur doit etre identique a NPM_EDGE_KEY dans le .env de n8n-proxy.
# NPM ecrase ainsi tout en-tete fourni par le client.
proxy_set_header X-Spirit-Edge-Key "SECRET_ALEATOIRE_64_CARACTERES";

error_page 502 504 = @generic_gateway_error;

location @generic_gateway_error {
    default_type application/json;

    add_header Cache-Control "no-store" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header Retry-After "30" always;

    return 503 '{"status":"service_unavailable"}';
}
```

Genere le secret sur le VPS avec `openssl rand -hex 32`, sans le copier dans un
ticket ou un journal. Caddy exige a la fois l'adresse immediate NPM declaree
dans `ALLOWED_SOURCE_CIDRS` et cet en-tete. Il supprime ensuite
`X-Spirit-Edge-Key` avant de transmettre la requete a n8n.

Ne pas intercepter globalement les erreurs applicatives :

```nginx
# A ne pas utiliser : cette regle casse les statuts metier et leurs en-tetes CORS.
error_page 400 401 403 404 405 500 502 503 504 =404 /generic-n8n-error.json;
```

Test non destructif de non-regression pour SpiritBooking :

```bash
curl -i \
  -H 'Origin: null' \
  -H 'Content-Type: application/json' \
  --data '{"action":"manage/details","token":"invalid"}' \
  https://n8n-wh01.spiritviews.com/webhook/0key/spiritbooking
```

Resultat attendu :

- statut HTTP `401`, pas `404` ;
- corps JSON metier indiquant que le lien est invalide ou expire ;
- `Access-Control-Allow-Origin: *` ;
- `Cache-Control: no-store` ;
- `Via: 1.1 Caddy`, qui confirme le passage par Caddy.

Dans cette topologie, l'URL publique est :

```text
https://n8n-wh01.spiritviews.com/webhook-test/...
https://n8n-wh01.spiritviews.com/form-test/...
```

Pas besoin d'utiliser `:1443`, sauf si tu veux volontairement exposer un port HTTPS non standard.

Si le conteneur ne resout pas le nom MagicDNS Tailscale, cible l'IP Tailscale et garde le hostname pour le Host header et le SNI TLS :

```env
N8N_UPSTREAM_URL=https://100.68.54.24
N8N_UPSTREAM_HOST=n8n.monkey-eel.ts.net
N8N_UPSTREAM_TLS_SERVER_NAME=n8n.monkey-eel.ts.net
```

## Configuration n8n

Avec Caddy comme seul reverse proxy devant n8n :

```env
N8N_WEBHOOK_URL=https://hooks.example.com/
N8N_PROXY_HOPS=1
```

Dans le deploiement Spiritviews, Nginx Proxy Manager et Caddy sont en amont du
proxy HTTPS Tailscale qui transmet finalement vers `n8n:5678`. n8n ne doit
faire confiance qu'a ce dernier saut :

```env
N8N_WEBHOOK_URL=https://n8n-wh01.spiritviews.com/
N8N_PROXY_HOPS=1
```

La variable historique `WEBHOOK_URL` est depreciee sur les versions recentes
de n8n ; utiliser `N8N_WEBHOOK_URL`. Chaque instance n8n avec son propre
domaine doit avoir sa propre valeur.

## Logs

Logs applicatifs Caddy :

```bash
docker compose logs -f caddy
```

Logs d'accès JSON persistés :

```bash
tail -f logs/access.log
```

Le format de logs filtre les parametres de requete sensibles (`token`, `code`,
`csrf`, `session`, `signature` et `key`) avant ecriture. Ne remplace pas ce
filtre par un simple `format json` en production.

Logs runtime Caddy :

```bash
tail -f logs/runtime.log
```

## Whitelist

La whitelist active se configure dans `.env` :

```env
WEBHOOK_METHODS=POST
WEBHOOK_PATHS="/webhook/stripe/* /webhook/github/*"
FORM_METHODS="GET POST"
FORM_PATHS="/form/contact/* /form-test/contact/* /form-waiting/*"
ALLOWED_SOURCE_CIDRS="3.18.12.63/32 3.130.192.231/32"
```

Garde `WEBHOOK_PATHS` et `FORM_PATHS` aussi précis que possible. Les Form Trigger utilisent `/form/*` en production et `/form-test/*` en test. Les formulaires générés au milieu d'une exécution, par exemple via Wait/Form, peuvent utiliser `/form-waiting/*`.
Les validations humaines générées par `Send and Wait`, par exemple les liens
envoyés par mail ou Slack, utilisent `/webhook-waiting/*`; si `N8N_WEBHOOK_URL`
pointe vers ce proxy public, ce chemin doit etre routé vers la même instance
n8n que celle qui porte l'exécution en attente.

Si le fournisseur webhook ne publie pas d'IP stables, laisse `ALLOWED_SOURCE_CIDRS` ouvert mais ajoute une vérification de signature dans le workflow n8n dès le premier node. Pour les forms publiques, préfère un chemin difficile à deviner, un champ caché signé, une validation côté workflow, ou une protection supplémentaire devant NPM si le formulaire contient des données sensibles.

Derriere NPM, le matcher Caddy `remote_ip` voit l'adresse du proxy NPM, pas
directement celle du navigateur. Ne remplace pas `ALLOWED_SOURCE_CIDRS` par des
CIDR clients sans configurer d'abord `trusted_proxies`, puis utiliser le matcher
`client_ip`.

Les routes `/webhook-test/0key/*` sont exclues de la configuration de
production Spiritviews. Retire aussi `/form-test/*` des que l'inventaire des
Form Triggers confirme qu'elles ne sont plus utiles.

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
N8N_WEBHOOK_URL=https://hooks-client-a.example.com/
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
