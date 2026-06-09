# Trésorerie Mobile Money — MVP

Application de suivi de caisse et de float multi-opérateurs pour points marchands
Mobile Money (Orange Money, Moov Money, Wave, MTN, Crédit, Factures).

> Outil de **suivi et de calcul** : il ne détient, ne transfère et ne manipule
> jamais de fonds réels.

## Démarrer l'application

1. Double-cliquez sur **`Lancer-app.bat`**
2. Ouvrez votre navigateur sur **http://localhost:5000**

Ou en ligne de commande :

```
py app.py
```

## Installer sur un téléphone Android (PWA)

1. Sur le PC, lancez l'app. Notez l'adresse réseau affichée (ex. `http://192.168.x.x:5000`).
2. Le téléphone doit être sur le **même Wi-Fi** que le PC.
3. Ouvrez cette adresse dans **Chrome** sur le téléphone.
4. Menu Chrome → **« Ajouter à l'écran d'accueil »**. L'app s'installe comme une vraie application.

## Structure du projet

| Fichier | Rôle |
|---|---|
| `app.py` | Serveur Flask, les 7 écrans et leurs routes |
| `logic.py` | **Cœur métier** — règles de calcul (section 6 du cahier des charges) |
| `db.py` | Base de données SQLite (modèle de données, section 5) |
| `templates/` | Les 7 écrans (HTML) |
| `static/` | Style, icônes, manifest et service worker (PWA) |
| `data.db` | Base de données locale (créée au premier lancement) |

## Les 7 écrans

1. **Onboarding** — création du compte et soldes d'ouverture
2. **Tableau de bord** — vue consolidée + voyants d'alerte
3. **Transaction** — dépôt / retrait / dépense
4. **Réapprovisionnement** — achat de float, mouvements d'espèces
5. **Clôture** — solde théorique vs réel, détection d'écart
6. **Historique** — liste filtrable, suppression avec recalcul
7. **Paramètres** — seuils, opérateurs, compte

## Règles de calcul (cœur métier)

| Opération | Float | Cash |
|---|---|---|
| Dépôt client | − montant | + montant |
| Retrait client | + montant | − montant |
| Achat de float | + montant | − montant |
| Dépense | — | − montant |
| Dépôt d'espèces | — | + montant |
| Retrait d'espèces | — | − montant |

Tous les soldes sont **recalculés à partir des transactions** : la base ne stocke
pas de solde « figé », elle stocke les opérations.

## Pile technique

- **Python 3 + Flask** (logique et serveur)
- **SQLite** (base locale, hors-ligne)
- **PWA** (installable sur Android, coquille hors-ligne via service worker)
