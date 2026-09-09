# Étude : passer le stockage de fichiers sur Amazon S3

*Analyse exploratoire — état du code au commit `8de595c`.*

## 1. Ce qui est stocké sur le système de fichiers aujourd'hui

### 1.1 Les six `UploadSet` de Flask-Uploads

Tous les fichiers déposés par les utilisateurs passent par `flask_uploads`, configuré
dans `collectives/forms/__init__.py:38-44`, avec les destinations définies dans
`config.py:361-395` :

| `UploadSet` | Destination | Contenu | Colonne SQL associée |
|---|---|---|---|
| `photos` | `collectives/static/uploads` | photos de collectives | `Event.photo` |
| `avatars` | `.../uploads/avatars` | avatars adhérents | `User.avatar` |
| `imgtypeequip` | `.../uploads/typeEquipmentImg` | visuels des types de matériel | `EquipmentType.path_img` |
| `documents` | `.../uploads/documents` | pièces jointes aux collectives et documents d'activité | `UploadedFile.path` |
| `tech` | `.../uploads/tech` | fichiers de configuration publics (CGV, logo, cover…) | `ConfigurationItem.content` |
| `private` | `collectives/private_assets` | fichiers de configuration secrets (`VOLUNTEER_CERT_IMAGE`) | `ConfigurationItem.content` |

Point important : **le nombre de points d'appel est très faible** (une dizaine),
ce qui rend la migration beaucoup moins lourde qu'on pourrait le craindre :

- `collectives/models/user/misc.py:41` et `:49` — `save_avatar` / `delete_avatar`
- `collectives/models/event/misc.py:81` et `:103` — `delete_photo` / `save_photo`
- `collectives/models/equipment.py:105-125` — `save_type_img`
- `collectives/models/upload.py:145-206` — `is_image`, `save_file`, `full_path`,
  `delete_file`, `url`, `thumbnail_url`
- `collectives/models/upload.py:212-227` — `purge_old_uploads`
- `collectives/routes/technician.py:207-222` — enregistrement des `File` / `SecretFile`

Deux endroits court-circuitent l'abstraction et construisent l'URL à la main :
`collectives/api/equipment.py:25` et les gabarits
`templates/equipment/gestion/equipment_type/equipment_type.html:52` et
`templates/equipment/gestion/equipment/equipment.html:47`
(`url_for('static', filename='uploads/typeEquipmentImg/…')`). Ils devront
obligatoirement repasser par une méthode `url()`.

### 1.2 Flask-Images (vignettes)

`profile.images` (`collectives/routes/profile.py:56`, initialisé dans
`collectives/__init__.py:89`) sert les redimensionnements sur `/imgsizer` :
`url_for('images.fit'|'images.crop', filename=…)` est utilisé dans 8 gabarits/API
(avatars, photos de collectives, vignettes de pièces jointes via
`models/upload.py:201`).

La bibliothèque résout `filename` en cherchant sur le disque dans `IMAGES_PATH`
(`config.py:403`) et écrit le résultat dans `IMAGES_CACHE`
(`collectives/static/uploads/cache`).

### 1.3 Ce qui *n'est pas* concerné

- Les exports XLSX / PDF (badges, attestations bénévole, stats, listes d'inscrits)
  sont générés en mémoire (`BytesIO`) et renvoyés par `send_file` — aucun impact.
- Les logs applicatifs (`routes/technician.py:100-140`) sont locaux au conteneur.
- Les assets construits par flask-assets (`static/dist`) sont des artefacts de build.

### 1.4 Le déploiement

`deployment/k8s/collectives.example.yaml` monte un PVC de 2 Gi (`ReadWriteOnce`)
sur `/app/collectives/static/uploads`, avec `strategy: Recreate`. Autrement dit,
**le stockage local est aujourd'hui ce qui interdit de faire tourner plus d'un pod**.

## 2. Ce qui coince réellement

Par ordre de risque décroissant :

1. **Flask-Uploads n'a pas de backend objet** et n'est plus maintenu (le projet est
   déjà épinglé sur un fork Git dans `requirements.txt`). Il faut soit écrire une
   couche de stockage par-dessus, soit s'en séparer.

2. **`UploadedFile.is_image()` (`models/upload.py:145`) ouvre le fichier depuis le
   disque** via `full_path()` pour le valider avec PIL, et il est appelé à chaque
   sérialisation d'une pièce jointe (`api/upload.py`). Tel quel sur S3, cela signifie
   un `GET` par fichier et par affichage de page. Le bon réflexe est de calculer le
   flag une fois au dépôt et de le stocker en base (migration Alembic, colonne
   booléenne), ce qui accessoirement supprime des I/O aujourd'hui déjà inutiles.

3. **`save_file()` (`models/upload.py:158-161`) lit la taille via `os.stat()`** après
   écriture ; il faudra la prendre sur le flux ou sur la réponse S3.

4. **Les vignettes.** Flask-Images sait travailler sur des URLs distantes
   (`http(s)` accepté, cf. `flask_images/core.py:169-176` et `:317-348` : il télécharge
   l'objet puis met en cache localement), donc `url_for('images.fit', filename=<URL S3>)`
   fonctionne — mais avec deux réserves :
   - la clé de cache est le hash de l'URL : des URLs **présignées** (qui changent à
     chaque génération) casseraient le cache et feraient exploser le nombre de GET.
     Il faut donc des objets *publics* (bucket public en lecture ou CDN) pour les
     images affichées ;
   - en mode distant, Flask-Images n'ajoute pas le paramètre `version` basé sur la
     `mtime` : le cache-busting disparaît. Comme les noms de fichiers sont
     déterministes (`user-<id>.jpg`, `event-<id>.jpg`), un changement d'avatar ne
     serait plus visible. Il faut passer à des clés versionnées
     (`user-<id>-<uuid>.jpg`) — c'est le vrai changement fonctionnel de cette migration.

5. **Les fichiers privés** (`private_assets`, type `SecretFile`) ne doivent pas devenir
   publics. Ils sont aujourd'hui uniquement lus côté serveur (`Image.open` sur
   `VOLUNTEER_CERT_IMAGE` dans `routes/profile.py:331`) : un `get_object()` vers un
   `BytesIO` suffit, pas besoin d'URL présignée dans un premier temps.

6. **Suppressions.** `delete_avatar`, `delete_photo`, `delete_file`, `purge_old_uploads`
   et l'anonymisation RGPD (`models/user/misc.py:anonymize`) doivent supprimer côté S3,
   en restant tolérants à l'absence d'objet comme aujourd'hui.

7. **Les tests.** Il n'y a quasiment pas de test sur les uploads
   (`tests/events/test_event.py:223` affecte `event.photo` en dur), mais introduire un
   appel réseau dans les modèles impose soit `moto`, soit un backend « filesystem »
   conservé pour les tests. C'est un argument de plus pour la couche d'abstraction.

## 3. Approche recommandée

**Une interface de stockage minimale** (`save(stream, key)`, `delete(key)`,
`open(key)`, `url(key)`) avec deux implémentations : `FilesystemStorage` (existant,
gardé pour le dev et la CI) et `S3Storage` (boto3). Flask-Uploads peut être conservé
uniquement pour ce qu'il fait bien — la validation d'extensions (`IMAGES`, `DOCUMENTS`)
— ou remplacé par une simple liste blanche.

Cette approche a un avantage collatéral : le code n'étant pas lié à AWS, le club peut
choisir un fournisseur compatible S3 (OVH Object Storage, Scaleway, Cloudflare R2)
sans changer une ligne — ce qui est pertinent puisque le déploiement documenté est
déjà chez OVH, et pour garder les données en France (RGPD).

**À écarter** : monter le bucket via `s3fs`/`goofys` pour ne rien changer au code.
C'est séduisant sur le papier mais les accès aléatoires de PIL et de Flask-Images sur
un système de fichiers émulé donnent des performances et des modes de panne mauvais.

## 4. Chiffrage

### 4.1 Coût de développement

| Lot | Charge |
|---|---|
| Interface de stockage + backend boto3 + configuration | 2 – 3 j |
| Portage des 6 `UploadSet` et de leurs ~10 points d'appel | 1 – 2 j |
| Vignettes : clés versionnées, cache, Flask-Images en mode distant | 1 – 2 j |
| Fichiers privés / `SecretFile` | 0,5 – 1 j |
| Tests (`moto` ou MinIO) + intégration CI | 1 – 2 j |
| Script de reprise des données, doc, manifeste k8s, IAM/bucket/CORS | 1 j |
| Recette et marge | 1 – 2 j |
| **Total** | **8 – 13 jours-homme** |

Soit environ **2 à 3 semaines** pour un développeur à temps partiel. La migration des
données existantes est en revanche triviale : un `aws s3 sync` du PVC vers le bucket,
en conservant les chemins relatifs, laisse toutes les valeurs déjà en base valides.

### 4.2 Coût d'exploitation

Ordres de grandeur sur la base des volumes actuels (PVC provisionné à 2 Gi,
`MAX_CONTENT_LENGTH` = 5 Mo, `MAX_UPLOADS_PER_EVENT` = 5), tarifs S3 Standard
eu-west-3 (Paris) :

| Poste | Volume estimé | Coût mensuel |
|---|---|---|
| Stockage (0,024 $/Go/mois) | 2 – 5 Go | 0,05 – 0,12 $ |
| Requêtes PUT (5,3 $/million) | quelques milliers | < 0,05 $ |
| Requêtes GET (0,42 $/million) | quelques dizaines de milliers | < 0,05 $ |
| Sortie internet (100 Go/mois gratuits, puis ~0,09 $/Go) | < 100 Go | 0 $ |
| **Total** | | **~ 1 $/mois, très probablement moins** |

Le poste réellement variable est la bande passante sortante : elle reste nulle tant que
le trafic reste sous les 100 Go/mois offerts, et le cache local de Flask-Images
l'amortit encore (les vignettes ne sont téléchargées qu'une fois par conteneur).
Chez un fournisseur sans frais d'egress (R2) ou avec egress inclus (OVH), ce risque
disparaît complètement.

En face, on économise le PVC de 2 Gi (quelques euros/mois selon le fournisseur) et
surtout sa sauvegarde.

### 4.3 Ce que ça rapporte

- **Les pods deviennent sans état** : plus de `ReadWriteOnce` ni de `strategy: Recreate`,
  donc plusieurs répliques et des déploiements sans coupure deviennent possibles.
- Sauvegarde, versioning et cycle de vie (expiration automatique des uploads orphelins,
  cf. `purge_old_uploads`) sont délégués au stockage objet.
- Possibilité, plus tard, de servir les images via un CDN et de faire les dépôts en
  direct depuis le navigateur (POST présigné), ce qui déchargerait l'application.

### 4.4 Ce que ça coûte en plus, hors développement

- Une latence réseau supplémentaire sur les écritures et sur les premières lectures.
- Des secrets à gérer (clés IAM) et une politique de bucket à écrire correctement :
  c'est le principal risque opérationnel, puisqu'une erreur rend publics des documents
  qui ne devraient pas l'être — en particulier `private_assets`.
- Une dépendance externe supplémentaire dans le chemin critique des pages qui
  affichent des images.

## 5. Ce que le POC couvre

Une première implémentation de la couche décrite au §3 est disponible dans
`collectives/utils/storage/` (voir `doc/source/storage.rst`) :

- l'interface `StorageBackend` et ses deux implémentations, `FilesystemBackend`
  (comportement historique, y compris la résolution des conflits de noms) et
  `S3Backend` (boto3, dépendance optionnelle installée par l'extra `s3`) ;
- l'objet `FileStore`, qui remplace `UploadSet` côté application et reste
  compatible avec le validateur `FileAllowed` de Flask-WTF ;
- trois stores portés : `documents` (pièces jointes), `avatars` et `photos` —
  ces deux derniers avec des clés versionnées, qui règlent le problème de
  cache-busting du §2.4 ;
- le calcul de `is_image` au dépôt, stocké en base (§2.2), avec la migration
  Alembic correspondante ;
- des tests exécutés **deux fois, une fois par backend** — API d'upload,
  téléchargement, suppression, refus d'extension — via un client S3 en mémoire.

Restent à porter, avec le même mécanisme : `imgtypeequip` (nécessite de passer
les deux gabarits équipement par `url()`), et les stores `tech` et `private` de
la configuration à chaud. Restent également à faire : un test d'intégration
contre MinIO ou `moto`, et la bascule des URLs de vignettes vers un CDN.

## 6. Conclusion

Techniquement, le chantier est **modéré et bien circonscrit** : le code de stockage est
déjà concentré dans quatre modèles et une route, ce qui est la meilleure nouvelle de
cette étude. Les deux vrais sujets sont les **vignettes** (versionnement des clés,
mode distant de Flask-Images) et la **séparation public/privé** des buckets.

Le coût d'exploitation AWS est négligeable à l'échelle du club (de l'ordre de l'euro par
mois) ; la dépense réelle, ce sont les **8 à 13 jours de développement**. La question à
trancher n'est donc pas financière mais fonctionnelle : le passage à S3 se justifie
surtout si l'on veut pouvoir faire tourner plusieurs pods et simplifier les sauvegardes.
Si le mono-pod actuel convient, le PVC reste une solution parfaitement adaptée.
