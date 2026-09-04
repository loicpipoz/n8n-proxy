# CSP de l'application myevents

## Perimetre et precondition

Le vhost `myevents.tonsurton.ch` est une application first-party de confiance,
distincte de l'editeur n8n. Le feu vert applicatif du 4 septembre 2026 indique
que la version 1.5.23 corrige le XSS du titre public, la validation CSRF et la
generation cryptographique des jetons. Ce feu vert n'est pas un audit exhaustif.
L'atomicite des liens magiques reste un suivi applicatif distinct.

Ne pas reutiliser cette exception sur des webhooks servant du HTML arbitraire.
Avec `allow-scripts` et `allow-same-origin`, le sandbox ne doit plus etre considere
comme une isolation du code applicatif vis-a-vis des donnees de cette origine.

## Implementation

La source canonique est `config/includes/direct.caddy`, snippet
`tonsurton_events_public_site`. Le handler `header` differe son execution jusqu'a
la reponse de l'upstream et remplace uniquement la directive sandbox connue de
n8n, delimitee par le debut/fin de politique, une virgule ou un point-virgule.

- Ajoute `allow-same-origin`.
- Retire `allow-orientation-lock` et `allow-presentation`.
- Conserve les autres permissions, directives CSP et valeurs d'en-tete.
- Ne cree pas de seconde CSP et ne modifie aucun body ni cookie.
- Si la directive amont change, elle reste inchangee : revoir cette exception
  explicitement au lieu d'assouplir une nouvelle politique automatiquement.
- Aucun ajout de CORS, d'OPTIONS, de route ou de methode.
- Le proxy partage, Host/SNI, HTTP/1.1, les en-tetes IP/ingress, la limite de
  requete et la suppression de `X-Spirit-Edge-Key` restent inchanges.

Directive attendue apres remplacement :

```text
sandbox allow-downloads allow-forms allow-modals allow-pointer-lock allow-popups allow-popups-to-escape-sandbox allow-scripts allow-same-origin allow-top-navigation-by-user-activation allow-top-navigation-to-custom-protocols
```

## Validation locale reproductible

```sh
CADDY_CONFIG_FILE=Caddyfile.direct-combined-public docker compose --env-file .env.example config --quiet
python3 tests/test_myevents_csp.py
git diff --check
```

Les tests utilisent Python standard et le binaire `caddy`. Ils adaptent et
valident le Caddyfile canonique avec l'environnement d'exemple, sans lire de
secret. Une copie JSON en memoire conserve les handlers et remplace uniquement
les transports/listeners pour un faux upstream HTTP sur loopback. Aucun appel
au vrai n8n, aucune demande de certificat et aucun email.

Couverture : preservation des autres directives et CSP multiples, absence de
CSP, politique deja corrigee, politique inconnue conservee, bytes et cookies
inchanges, POST et query preserves, en-tetes ingress/IP, secret client supprime,
routes/methodes refusees et CSP historique inchangee. La configuration adaptee
est comparee au commit de cutover `a0a53229a8c825732c03ffaa6683304ecd666d80` :
seul le handler de remplacement CSP est permis comme difference.

## Publication et preuve live

Demander 1Password avant signature/push, puis une nouvelle confirmation avant
SSH. Sur le VPS : `git pull --ff-only`, validation de la configuration montee,
puis `caddy reload` uniquement. Ne pas recreer les conteneurs.

Les tests locaux ne prouvent pas le correctif navigateur en production.
Apres reload, verifier Safari et Chromium, les pages publiques/admin, CSS/logo,
liens, acces same-origin au stockage et comportement des cookies sans exposer
de session reelle. Depuis la page, un POST JSON a `/register/login/start` avec
`{"email":""}` et sans `event_code` doit recevoir le JSON applicatif HTTP 422,
sans OPTIONS ni erreur CORS. Ne pas utiliser d'adresse valide ni soumettre le
formulaire d'envoi d'un lien admin.

Verifier aussi les 404 techniques/UI n8n, le TLS, la redaction des logs,
l'absence de mutation des autres vhosts et l'egalite des SHA local/origin/VPS.
Un chargement GET sans erreur console ne remplace pas la preuve du POST.

Reference : https://caddyserver.com/docs/caddyfile/directives/header
