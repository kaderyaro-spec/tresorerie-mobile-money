# Mettre l'application en ligne (synchronisation multi-appareils)

Une fois en ligne, tu obtiens **une adresse web** que tu ouvres sur tous tes
appareils (téléphone, tablette, autre PC), même en 4G et même PC éteint. Tous
partagent **le même compte et les mêmes données**, protégés par ton code PIN.

> ⚠️ **Avant de mettre en ligne : définis ton code PIN** dans
> Réglages → « Code de connexion ». Sans lui, tes données seraient publiques.

---

## Le point important : la persistance des données

Une app de trésorerie ne doit **jamais perdre ses données**. Or, les
hébergements gratuits ne gardent pas tous le fichier de base (`data.db`) :

| Hébergeur | Gratuit | Garde les données ? | Mise en ligne |
|---|---|---|---|
| **PythonAnywhere** | ✅ Oui | ✅ **Oui** (disque persistant) | Upload des fichiers (je te guide) |
| **Render** | ✅ Oui | ❌ Non sur l'offre gratuite (perte au redémarrage) | Connexion GitHub (très simple) |
| **Render + disque** | 💵 ~7 $/mois | ✅ Oui | Connexion GitHub |

➡️ **Recommandation : PythonAnywhere** — gratuit ET conserve les données. C'est
le meilleur compromis pour ce projet.

---

## Option A — PythonAnywhere (recommandée, gratuite, données conservées)

1. Crée un compte gratuit sur **https://www.pythonanywhere.com** (offre « Beginner »).
2. Onglet **Files** → crée un dossier `tresorerie` → téléverse tous les fichiers
   du projet (sauf `data.db`, `__pycache__`, `*.bak`).
3. Onglet **Web** → *Add a new web app* → **Manual configuration** → **Python 3.x**.
4. Dans la config WSGI, pointe vers `app.py` (variable `application = app`).
   *(je te fournis le fichier WSGI exact au moment venu)*
5. Onglet **Consoles** → installe Flask : `pip install --user Flask`.
6. Définis la variable d'environnement `SECRET_KEY` (une longue phrase secrète).
7. Clique **Reload**. Ton app est en ligne sur `https://TONNOM.pythonanywhere.com`.

## Option B — Render (mise en ligne la plus simple, mais données non conservées en gratuit)

1. Mets le code sur **GitHub** (je peux t'aider à créer le dépôt).
2. Sur **https://render.com** → *New Web App* → connecte le dépôt GitHub.
3. Render détecte le `Procfile` (déjà présent) : `gunicorn app:app`.
4. Ajoute la variable d'environnement `SECRET_KEY`.
5. Déploie. Adresse fournie : `https://ton-app.onrender.com`.
6. ⚠️ Pour conserver les données : ajoute un **disque persistant** (payant) et
   règle la variable `DB_PATH` vers ce disque (ex. `/var/data/data.db`).

---

## Fichiers déjà prêts pour le déploiement

- `requirements.txt` — dépendances (Flask + gunicorn)
- `Procfile` — commande de démarrage pour l'hébergeur
- `.gitignore` — exclut la base de données et les fichiers temporaires
- Variables d'environnement supportées : `SECRET_KEY`, `DB_PATH`

## Installer l'app sur le téléphone (après mise en ligne)

Ouvre l'adresse web dans **Chrome** sur le téléphone → menu → **« Ajouter à
l'écran d'accueil »**. L'app s'installe et se lance comme une application native.
