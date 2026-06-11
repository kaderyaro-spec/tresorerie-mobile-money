# Application en ligne — état et guide

## ✅ État actuel (déployé)

- **Lien public** : https://tresorerie-mobile-money.onrender.com
- **Hébergement** : Render (plan gratuit), déploiement automatique à chaque `git push`
- **Base de données** : PostgreSQL **Supabase** (gratuit, données PERMANENTES)
  via la variable d'environnement `DATABASE_URL` dans Render
- **Multi-comptes** : chaque testeur crée son propre compte (numéro 10 chiffres + PIN),
  données isolées par compte

> 😴 Seule limite restante du plan gratuit : l'app s'endort après ~15 min
> d'inactivité et met ~50 s à se réveiller à la visite suivante. Les données,
> elles, ne sont jamais perdues (elles vivent dans Supabase).

---

# Guide d'origine (mise en place initiale)

Le code est **déjà prêt** : dépôt Git initialisé, `render.yaml`, `Procfile`,
`requirements.txt` (avec gunicorn). Il reste 3 étapes.

---

## Étape 1 — Mettre le code sur GitHub

1. Crée un compte gratuit sur **https://github.com** (si tu n'en as pas).
2. Clique sur **New repository** (bouton vert).
   - Nom : `tresorerie-mobile-money`
   - Laisse-le **vide** (ne coche PAS « Add a README »).
   - Clique **Create repository**.
3. Copie l'adresse du dépôt affichée, du type :
   `https://github.com/TON-COMPTE/tresorerie-mobile-money.git`
4. Donne-moi cette adresse : je lance l'envoi du code (ou tu exécutes toi-même) :
   ```
   git remote add origin https://github.com/TON-COMPTE/tresorerie-mobile-money.git
   git branch -M main
   git push -u origin main
   ```
   Au push, une fenêtre de connexion GitHub s'ouvre dans le navigateur → connecte-toi
   pour autoriser. (Une seule fois.)

## Étape 2 — Déployer sur Render

1. Crée un compte gratuit sur **https://render.com** → choisis **« Sign in with GitHub »**
   (le plus simple, ça relie directement ton GitHub).
2. Tableau de bord Render → **New +** → **Blueprint**.
3. Sélectionne le dépôt `tresorerie-mobile-money`.
4. Render détecte le fichier `render.yaml` et propose le service tout configuré
   (clé secrète générée automatiquement). Clique **Apply** / **Create**.
5. Render installe et démarre l'app (2–4 minutes la première fois).

## Étape 3 — Récupérer et partager le lien

1. Quand le statut passe à **Live**, Render affiche l'URL en haut, du type
   `https://tresorerie-mobile-money.onrender.com`.
2. Ouvre-la, fais l'onboarding, **définis ton code PIN**.
3. Partage le lien (et le code PIN si tu veux que les testeurs entrent) à tes testeurs.
4. Sur leur téléphone : ouvrir le lien dans **Chrome** → menu → **« Ajouter à
   l'écran d'accueil »** pour l'installer comme une app.

---

## À savoir sur l'offre gratuite Render

- 😴 **Mise en veille** : après ~15 min sans visite, l'app s'endort. La visite
  suivante la réveille en ~30 secondes (un petit temps de chargement, puis normal).
- 💾 **Données** : l'offre gratuite peut réinitialiser la base au redémarrage du
  serveur. Acceptable pour une phase de test. Pour conserver durablement les
  données, on passera plus tard à un disque persistant (payant) ou à PythonAnywhere.

## Mettre à jour l'app en ligne plus tard

À chaque modification, il suffit de renvoyer le code : Render redéploie tout seul.
```
git add -A
git commit -m "Description des changements"
git push
```
