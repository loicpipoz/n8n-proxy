# Proxy du Hub SimpleMDM Diagnostics

## Contrat public

Le proxy direct Caddy expose uniquement les combinaisons suivantes sous
`https://n8n-wh01.spiritviews.com` :

| Methode | Chemin public |
| --- | --- |
| `POST` | `/webhook/0key/diagnostics/v1/arrivals` |
| `GET` | `/webhook/0key/diagnostics/v1/arrivals/{arrivalId}` |
| `POST` | `/webhook/0key/diagnostics/v1/arrivals/{arrivalId}/text` |
| `GET` | `/webhook/0key/diagnostics/v1/arrivals/{arrivalId}/segments` |
| `POST` | `/webhook/0key/diagnostics/v1/arrivals/{arrivalId}/segments/{segmentIndex}/url` |
| `POST` | `/webhook/0key/diagnostics/v1/arrivals/{arrivalId}/complete` |

Les six routes sont reecrites vers l'unique chemin interne statique :

```text
/webhook/0key/diagnostics/v1/intake
```

La methode, le corps brut, `Content-Type`, les headers HMAC Diagnostics et
`X-Request-Id` ne sont pas transformes. Avant la reecriture, Caddy remplace
systematiquement les valeurs eventuellement envoyees par le client :

```text
X-Diagnostics-Original-Method: methode publique recue
X-Diagnostics-Original-Path: chemin public original sans query string
```

Le chemin statique `/webhook/0key/diagnostics/v1/intake`, toute route inconnue
sous `/webhook/0key/diagnostics/*` et toute mauvaise methode retournent `404`
au niveau du proxy. Aucune route vers Swift ou `swift-control` n'est exposee.
La limite globale de corps reste `10 MB`.

## Canary sans secret

Ce test utilise volontairement une signature invalide. Le Hub doit refuser la
requete avant toute creation d'arrivee :

```bash
curl -i -X POST \
  'https://n8n-wh01.spiritviews.com/webhook/0key/diagnostics/v1/arrivals' \
  -H 'Content-Type: application/json' \
  -H 'X-Diagnostics-Key-Id: invalid-canary' \
  -H "X-Diagnostics-Timestamp: $(date +%s)" \
  -H 'X-Diagnostics-Signature: 0000000000000000000000000000000000000000000000000000000000000000' \
  --data-binary '{}'
```

Le resultat attendu est `401`, et non `404` ou `502`.

Pour verifier l'ecrasement des headers internes, ajouter au meme canary :

```bash
-H 'X-Diagnostics-Original-Method: DELETE' \
-H 'X-Diagnostics-Original-Path: /forged/path'
```

Le JSON adapte de Caddy doit conserver un handler `headers.request.set` avant
le handler `rewrite`, avec la methode et le chemin issus de la requete.

## Validation et deploiement

```bash
docker compose config --quiet
docker exec n8n-proxy-caddy caddy validate --config /etc/caddy/Caddyfile
docker exec n8n-proxy-caddy caddy adapt \
  --config /etc/caddy/Caddyfile --adapter caddyfile --pretty
docker exec n8n-proxy-caddy caddy reload --config /etc/caddy/Caddyfile
curl -fsS https://n8n-wh01.spiritviews.com/healthz
```

Le reload Caddy ne recree ni le sidecar Tailscale ni les services RustDesk.

## Rollback

Chaque deploiement doit commencer par une copie horodatee de
`config/includes/direct.caddy`. Pour restaurer une sauvegarde :

```bash
BACKUP_DIR=/home/debian/n8n-proxy/backups/diagnostics-route-YYYYMMDDTHHMMSSZ
cp "$BACKUP_DIR/direct.caddy" /home/debian/n8n-proxy/config/includes/direct.caddy
docker exec n8n-proxy-caddy caddy validate --config /etc/caddy/Caddyfile
docker exec n8n-proxy-caddy caddy reload --config /etc/caddy/Caddyfile
curl -fsS https://n8n-wh01.spiritviews.com/healthz
```

Le rollback restaure uniquement le snippet Caddy. Il ne modifie aucun volume,
service n8n, service RustDesk ou enregistrement DNS.
