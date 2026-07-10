# Warri — Application Android

App Android native qui **affiche l'application web Warri** (dans une WebView) **et
lit automatiquement les SMS** des opérateurs (dépôts/retraits) — sans passer par
une application tierce, exactement comme les apps mobile money natives.

## Comment ça marche

1. La WebView charge `https://tresorerie-mobile-money.onrender.com/` : toute
   l'application (login, saisie, clôture, dettes…) fonctionne telle quelle.
2. Un **récepteur de SMS** natif (`SmsReceiver`) capte chaque SMS entrant et
   l'envoie au serveur Warri (`POST /api/sms?token=…`) via `ForwardWorker`
   (file d'attente fiable, réessais si hors-ligne).
3. Le serveur (déjà en place) décode le SMS et crée la transaction.

**Activation (côté agent) :** dans l'app → Réglages → Automatisation → « Ajouter un
appareil » → choisir le sous-compte (Orange/MTN) → toucher **« Activer la lecture
SMS sur ce téléphone »**. L'app enregistre le lien et demande la permission SMS.

## Générer l'APK (avec Android Studio — gratuit)

1. Installer **Android Studio** (https://developer.android.com/studio).
2. **Open** → sélectionner ce dossier `warri-android`.
3. Laisser Gradle se synchroniser (télécharge Gradle 8.7 + dépendances au 1er lancement).
4. Menu **Build → Build Bundle(s) / APK(s) → Build APK(s)**.
5. L'APK est généré dans `app/build/outputs/apk/debug/app-debug.apk`.
6. Copier cet APK sur un téléphone Android et l'installer (autoriser
   « sources inconnues »). Idéal pour le **test pilote** (hors Play Store).

## Publier sur le Play Store (plus tard)

- Générer un **APK/AAB signé** (Build → Generate Signed Bundle/APK).
- Compte Google Play Developer (25 $, une fois).
- **Déclaration d'usage des SMS** obligatoire (la catégorie « gestion financière /
  mobile money agent » est un cas d'exception reconnu — examen manuel de Google).
- Nouveaux comptes personnels : test fermé (20 testeurs / 14 jours) avant production.

## Paramètres clés
- `applicationId` : `ci.warri.app`  (à changer si besoin)
- URL chargée : `MainActivity.startUrl`
- minSdk 24 (Android 7.0+), targetSdk 34
