# Tests

Suite de tests automatiques (pytest) couvrant la logique critique de l'application :
inscription/connexion, sécurité (anti-force-brute, annulation tracée, validations),
comptabilité (fond de roulement, dettes, clôture, commissions), formatage, et
abonnements (panneau gérant, blocage des expirés).

## Lancer les tests en local

```bash
pip install -r requirements-dev.txt
pytest
```

Chaque test tourne sur une base SQLite neuve et isolée (fichier temporaire), en mode
démo — aucun vrai SMS, aucune base de production touchée.

## En continu

Les tests se lancent automatiquement à chaque push sur `main`
(voir `.github/workflows/tests.yml`). Un déploiement ne doit pas être fait si les
tests sont au rouge.
