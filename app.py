"""
Application de suivi de trésorerie Mobile Money — MVP
Serveur Flask + SQLite. 100 % en français, mobile-first, PWA installable.

Lancement :  python app.py   puis ouvrir http://localhost:5000
"""
import os
from flask import (
    Flask, render_template, request, redirect, url_for, session, flash,
    jsonify, Response
)
from werkzeug.security import generate_password_hash, check_password_hash
import db
import logic

app = Flask(__name__)
# Clé secrète : définie par variable d'environnement en production (cloud),
# valeur de repli pour le développement local.
app.secret_key = os.environ.get("SECRET_KEY", "mvp-tresorerie-mobile-money-dev")
# Session longue durée : l'agent reste connecté sur son téléphone (essentiel
# pour que la synchronisation hors-ligne fonctionne même des jours plus tard).
from datetime import timedelta
app.permanent_session_lifetime = timedelta(days=30)


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------
with app.app_context():
    db.init_db()


def fmt(montant):
    """Formate un montant en FCFA avec séparateur de milliers (espace)."""
    try:
        return f"{int(round(montant)):,}".replace(",", " ")
    except (ValueError, TypeError):
        return "0"


app.jinja_env.filters["fcfa"] = fmt


# Version des fichiers statiques (CSS/JS) : à incrémenter à chaque changement.
# Ajoutée en « ?v= » sur les liens → le navigateur recharge toujours la dernière
# version (fini les anciens styles affichés depuis le cache de l'appareil).
ASSET_VERSION = "15"


@app.context_processor
def _inject_asset_version():
    return {"asset_v": ASSET_VERSION}


# Identité visuelle de chaque opérateur : pastille colorée + initiales.
# Représentation originale (couleurs évocatrices), pas de logo de marque.
OPERATOR_STYLE = {
    "Orange Money": {"bg": "#FF6600", "fg": "#ffffff", "short": "OM"},
    "Moov Money":   {"bg": "#004B9B", "fg": "#ffffff", "short": "Mo"},
    "Wave":         {"bg": "#1DA1F2", "fg": "#ffffff", "short": "Wv"},
    "MTN":          {"bg": "#FFCC00", "fg": "#1a2024", "short": "MTN"},
    "Crédit":       {"bg": "#6B7780", "fg": "#ffffff", "short": "📱"},
    "Factures":     {"bg": "#0d6e5c", "fg": "#ffffff", "short": "🧾"},
}


# Nom de fichier attendu pour le vrai logo de chaque opérateur.
# Dépose les images officielles dans static/logos/ (voir static/logos/LISEZMOI.txt).
OPERATOR_SLUG = {
    "Orange Money": "orange-money",
    "Moov Money": "moov-money",
    "Wave": "wave",
    "MTN": "mtn",
    "Crédit": "credit",
    "Factures": "factures",
}
LOGO_DIR = os.path.join(app.static_folder, "logos")
LOGO_EXTS = ("png", "svg", "webp", "jpg", "jpeg")


def op_style(name):
    """
    Style d'un opérateur. Si un vrai fichier logo est présent dans
    static/logos/, on l'utilise ; sinon on retombe sur la pastille colorée.
    """
    base = OPERATOR_STYLE.get(
        name,
        {"bg": "#6B7780", "fg": "#ffffff", "short": (name[:2].upper() if name else "?")},
    )
    logo = None
    slug = OPERATOR_SLUG.get(name)
    if slug:
        for ext in LOGO_EXTS:
            if os.path.exists(os.path.join(LOGO_DIR, f"{slug}.{ext}")):
                logo = f"logos/{slug}.{ext}"
                break
    return {**base, "logo": logo}


app.jinja_env.globals["op_style"] = op_style


# ---------------------------------------------------------------------------
# Calcul de l'état de trésorerie consolidé (réutilisé par plusieurs écrans)
# ---------------------------------------------------------------------------
def compute_state():
    """Renvoie un dict décrivant la position de trésorerie de la journée."""
    conn = db.get_db()
    agent = conn.execute("SELECT * FROM agent WHERE id=?", (session["agent_id"],)).fetchone()
    if agent is None:
        conn.close()
        return None

    bday = agent["business_day"]
    wallets = conn.execute(
        "SELECT * FROM wallet WHERE agent_id=? AND active=1 ORDER BY id",
        (agent["id"],),
    ).fetchall()
    caisse = conn.execute(
        "SELECT * FROM caisse WHERE agent_id=? LIMIT 1", (agent["id"],)
    ).fetchone()
    txs = db.current_transactions(conn, agent["id"], bday)
    dettes_row = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) AS total FROM dette "
        "WHERE agent_id=? AND settled_at IS NULL", (agent["id"],)
    ).fetchone()
    sms_row = conn.execute(
        "SELECT COUNT(*) AS n FROM sms_inbox WHERE agent_id=? AND status='pending'",
        (agent["id"],)).fetchone()
    conn.close()
    dettes_total = dettes_row["total"] if dettes_row else 0
    sms_pending = sms_row["n"] if sms_row else 0

    txs_d = [dict(t) for t in txs]

    # Solde par portefeuille + voyant + commissions du jour de l'opérateur
    wallet_states = []
    wallet_balances = []
    for w in wallets:
        w_txs = [t for t in txs_d if t["wallet_id"] == w["id"]]
        bal = logic.wallet_balance(w["opening_balance"], w_txs)
        wallet_balances.append(bal)

        # Commission : automatique si l'opérateur a une grille connue (Wave…),
        # sinon cumul des commissions saisies manuellement.
        vol = logic.wave_volume(w_txs)
        commission = logic.daily_commission(w["operator"], vol)
        if commission is None:
            commission = logic.commissions_total(w_txs)

        wallet_states.append({
            "id": w["id"],
            "operator": w["operator"],
            "balance": bal,
            "threshold": w["alert_threshold"],
            "voyant": logic.voyant(bal, w["alert_threshold"]),
            "commission": commission,
            "prediction": logic.predict_depletion(bal, w_txs),
        })

    cash_open = caisse["opening_balance"] if caisse else 0
    cash_bal = logic.cash_balance(cash_open, txs_d)
    total = logic.consolidated_total(cash_bal, wallet_balances)
    commissions = logic.commissions_total(txs_d)

    nb_alertes = sum(1 for w in wallet_states if w["voyant"] == "rouge")

    return {
        "agent": agent,
        "business_day": bday,
        "wallets": wallet_states,
        "cash": cash_bal,
        "total": total,
        "commissions": commissions,
        "nb_alertes": nb_alertes,
        "dettes": dettes_total,
        "sms_pending": sms_pending,
    }


def require_onboarding():
    """Conservé pour compatibilité ; l'accès est géré par require_login()."""
    return None


# Points d'entrée accessibles sans être connecté
PUBLIC_ENDPOINTS = {
    "login", "signup", "static", "index", "ping", "api_sms", "conditions",
    "onboarding_otp", "onboarding_pin", "onboarding_operators", "onboarding_services",
    "recovery_request", "recovery_newpin",
}


def normalize_phone(raw):
    """Garde uniquement les chiffres ; retire l'indicatif 225 s'il est présent."""
    digits = "".join(c for c in str(raw or "") if c.isdigit())
    if digits.startswith("225") and len(digits) > 10:
        digits = digits[3:]
    return digits


def valid_ci_phone(phone):
    """Numéro ivoirien : exactement 10 chiffres."""
    return len(phone) == 10 and phone.isdigit()


def _new_recovery_code():
    """Code de récupération lisible, ex. « K7M3-P9R2 » (sans caractères ambigus)."""
    import secrets
    alphabet = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
    raw = "".join(secrets.choice(alphabet) for _ in range(8))
    return f"{raw[:4]}-{raw[4:]}"


# ---------------------------------------------------------------------------
# Envoi de SMS / OTP.
# Par défaut : mode démonstration (le code s'affiche à l'écran, aucun SMS réel).
# En production : définir OTP_PROVIDER=africastalking + AT_USERNAME + AT_API_KEY
# (+ AT_SENDER_ID) dans les variables d'environnement → envoi de vrais SMS.
# ---------------------------------------------------------------------------
OTP_PROVIDER = os.environ.get("OTP_PROVIDER")
AT_USERNAME = os.environ.get("AT_USERNAME")
AT_API_KEY = os.environ.get("AT_API_KEY")
AT_SENDER = os.environ.get("AT_SENDER_ID", "")


def otp_demo_mode():
    """True si aucun fournisseur SMS n'est configuré (le code s'affiche à l'écran)."""
    return not (OTP_PROVIDER == "africastalking" and AT_USERNAME and AT_API_KEY)


def send_sms(phone, message):
    """Envoie un SMS via le fournisseur configuré. Retourne True si parti."""
    if otp_demo_mode():
        return False
    import urllib.request
    import urllib.parse
    try:
        to = phone if str(phone).startswith("+") else "+225" + str(phone)
        data = urllib.parse.urlencode({
            "username": AT_USERNAME, "to": to, "message": message, "from": AT_SENDER,
        }).encode()
        req = urllib.request.Request(
            "https://api.africastalking.com/version1/messaging", data=data,
            headers={"apiKey": AT_API_KEY, "Accept": "application/json",
                     "Content-Type": "application/x-www-form-urlencoded"})
        urllib.request.urlopen(req, timeout=10)
        return True
    except Exception:
        return False


def _new_otp():
    import secrets
    return f"{secrets.randbelow(900000) + 100000}"   # 6 chiffres


def _start_otp(phone):
    """Génère un OTP, le mémorise (haché) en session, et tente l'envoi par SMS."""
    from datetime import datetime, timedelta
    code = _new_otp()
    session["otp"] = {
        "hash": generate_password_hash(code),
        "phone": phone,
        "exp": (datetime.now() + timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S"),
        "tries": 0,
    }
    send_sms(phone, f"Trésorerie Mobile Money : votre code de vérification est {code}. "
                    "Il expire dans 10 minutes.")
    session["otp_demo"] = code if otp_demo_mode() else None


def current_agent():
    """L'agent du compte connecté (selon la session), ou None."""
    return db.get_agent_by_id(session.get("agent_id"))


# Écrans réservés au gérant (un employé connecté n'y accède pas)
GERANT_ONLY = {"parametres", "rapport", "export_csv", "export_pdf"}


@app.before_request
def require_login():
    """
    Verrou d'accès multi-comptes : chaque écran protégé exige une session
    authentifiée rattachée à un compte existant. Sinon → écran de connexion.
    """
    if request.endpoint in PUBLIC_ENDPOINTS:
        return None
    if not session.get("auth") or current_agent() is None:
        session.pop("auth", None)
        # Les appels API (sync hors-ligne) reçoivent un statut JSON, pas une page.
        if request.path.startswith("/api/"):
            return jsonify({"ok": False, "error": "non_connecte"}), 401
        return redirect(url_for("login"))
    if request.endpoint in GERANT_ONLY and session.get("employee_id"):
        flash("Cette section est réservée au gérant.", "error")
        return redirect(url_for("dashboard"))
    return None


@app.route("/ping")
def ping():
    """Sonde de disponibilité (utilisée pour garder le serveur éveillé)."""
    return "ok", 200


@app.route("/")
def index():
    if session.get("auth") and current_agent() is not None:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/conditions")
def conditions():
    return render_template("conditions.html")


# ---------------------------------------------------------------------------
# Connexion (numéro + code PIN) — multi-comptes
# ---------------------------------------------------------------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        phone = normalize_phone(request.form.get("phone", ""))
        pin = request.form.get("pin", "").strip()
        agent = db.get_agent_by_phone(phone)
        if agent and pin:
            # 1) PIN du gérant ?
            if agent["pin_hash"] and check_password_hash(agent["pin_hash"], pin):
                session.clear()
                session.permanent = True
                session["agent_id"] = agent["id"]
                session["auth"] = True
                return redirect(url_for("dashboard"))
            # 2) PIN d'un employé du point ?
            conn = db.get_db()
            emps = conn.execute(
                "SELECT * FROM employee WHERE agent_id=? AND active=1",
                (agent["id"],)).fetchall()
            conn.close()
            for emp in emps:
                if check_password_hash(emp["pin_hash"], pin):
                    session.clear()
                    session.permanent = True
                    session["agent_id"] = agent["id"]
                    session["auth"] = True
                    session["employee_id"] = emp["id"]
                    session["employee_name"] = emp["name"]
                    return redirect(url_for("dashboard"))
        flash("Numéro ou code incorrect.", "error")
        return redirect(url_for("login"))

    return render_template("login.html")


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))


# ---------------------------------------------------------------------------
# PIN oublié — récupération par numéro + code de secours
# ---------------------------------------------------------------------------
@app.route("/recuperation", methods=["GET", "POST"])
def recovery_request():
    if request.method == "POST":
        phone = normalize_phone(request.form.get("phone", ""))
        code = request.form.get("code", "").strip().upper().replace(" ", "")
        if "-" not in code and len(code) == 8:
            code = f"{code[:4]}-{code[4:]}"
        agent = db.get_agent_by_phone(phone)
        if (agent and agent["recovery_hash"]
                and check_password_hash(agent["recovery_hash"], code)):
            session.clear()
            session["reset_agent_id"] = agent["id"]
            return redirect(url_for("recovery_newpin"))
        flash("Numéro ou code de récupération incorrect.", "error")
        return redirect(url_for("recovery_request"))
    return render_template("recovery.html")


@app.route("/recuperation/nouveau-pin", methods=["GET", "POST"])
def recovery_newpin():
    agent_id = session.get("reset_agent_id")
    if not agent_id:
        return redirect(url_for("recovery_request"))

    if request.method == "POST":
        pin = request.form.get("pin", "").strip()
        pin2 = request.form.get("pin2", "").strip()
        if not pin or len(pin) < 4 or not pin.isdigit():
            flash("Choisissez un code à 4 chiffres minimum.", "error")
            return redirect(url_for("recovery_newpin"))
        if pin != pin2:
            flash("Les deux codes ne correspondent pas.", "error")
            return redirect(url_for("recovery_newpin"))

        conn = db.get_db()
        conn.execute("UPDATE agent SET pin_hash=? WHERE id=?",
                     (generate_password_hash(pin), agent_id))
        conn.commit()
        conn.close()
        # Connexion directe avec le nouveau PIN.
        session.clear()
        session.permanent = True
        session["agent_id"] = agent_id
        session["auth"] = True
        flash("Nouveau code PIN enregistré. Pensez à générer un nouveau "
              "code de récupération dans les Réglages.", "success")
        return redirect(url_for("dashboard"))

    return render_template("recovery_pin.html")


# ---------------------------------------------------------------------------
# Inscription — étape 1 : identité (Nom, Prénom, CNI, numéro, conditions)
# ---------------------------------------------------------------------------
@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        nom = request.form.get("nom", "").strip()
        prenom = request.form.get("prenom", "").strip()
        cni = request.form.get("cni", "").strip()
        phone = normalize_phone(request.form.get("phone", ""))
        accept = request.form.get("accept")

        if not nom or not prenom:
            flash("Le nom et le prénom sont obligatoires.", "error")
            return redirect(url_for("signup"))
        if not valid_ci_phone(phone):
            flash("Le numéro de téléphone doit comporter 10 chiffres.", "error")
            return redirect(url_for("signup"))
        if not accept:
            flash("Vous devez accepter les conditions pour continuer.", "error")
            return redirect(url_for("signup"))
        if db.get_agent_by_phone(phone) is not None:
            flash("Ce numéro est déjà utilisé. Connectez-vous.", "error")
            return redirect(url_for("login"))

        # On démarre une nouvelle inscription propre, puis on vérifie le numéro.
        session.clear()
        session["reg"] = {"nom": nom, "prenom": prenom, "cni": cni, "phone": phone}
        _start_otp(phone)
        return redirect(url_for("onboarding_otp"))

    return render_template("signup.html")


# ---------------------------------------------------------------------------
# Inscription — vérification du numéro par code OTP
# ---------------------------------------------------------------------------
@app.route("/inscription/verification", methods=["GET", "POST"])
def onboarding_otp():
    reg = session.get("reg")
    otp = session.get("otp")
    if not reg or not otp:
        return redirect(url_for("signup"))

    if request.method == "POST":
        from datetime import datetime
        if request.form.get("action") == "resend":
            _start_otp(reg["phone"])
            flash("Un nouveau code a été envoyé.", "success")
            return redirect(url_for("onboarding_otp"))

        code = request.form.get("code", "").strip()
        expired = datetime.now() > datetime.strptime(otp["exp"], "%Y-%m-%d %H:%M:%S")
        if otp["tries"] >= 5:
            flash("Trop de tentatives. Demandez un nouveau code.", "error")
            return redirect(url_for("onboarding_otp"))
        if expired:
            flash("Code expiré. Demandez un nouveau code.", "error")
            return redirect(url_for("onboarding_otp"))
        if check_password_hash(otp["hash"], code):
            reg["otp_ok"] = True
            session["reg"] = reg
            session.pop("otp", None)
            session.pop("otp_demo", None)
            return redirect(url_for("onboarding_pin"))
        otp["tries"] += 1
        session["otp"] = otp
        flash("Code incorrect.", "error")
        return redirect(url_for("onboarding_otp"))

    return render_template("onboarding_otp.html",
                           phone=reg["phone"],
                           demo_code=session.get("otp_demo"))


# ---------------------------------------------------------------------------
# Inscription — étape 2 : code PIN de connexion
# ---------------------------------------------------------------------------
@app.route("/inscription/pin", methods=["GET", "POST"])
def onboarding_pin():
    reg = session.get("reg")
    if not reg:
        return redirect(url_for("signup"))
    if not reg.get("otp_ok"):
        return redirect(url_for("onboarding_otp"))

    if request.method == "POST":
        pin = request.form.get("pin", "").strip()
        pin2 = request.form.get("pin2", "").strip()
        if not pin or len(pin) < 4 or not pin.isdigit():
            flash("Choisissez un code à 4 chiffres minimum.", "error")
            return redirect(url_for("onboarding_pin"))
        if pin != pin2:
            flash("Les deux codes ne correspondent pas.", "error")
            return redirect(url_for("onboarding_pin"))
        reg = session["reg"]
        reg["pin_hash"] = generate_password_hash(pin)
        session["reg"] = reg
        return redirect(url_for("onboarding_operators"))

    return render_template("onboarding_pin.html", step=1)


# ---------------------------------------------------------------------------
# Inscription — étape 3 : choix des opérateurs Mobile Money + caisse
# ---------------------------------------------------------------------------
@app.route("/inscription/operateurs", methods=["GET", "POST"])
def onboarding_operators():
    reg = session.get("reg")
    if not reg or "pin_hash" not in reg:
        return redirect(url_for("signup"))

    if request.method == "POST":
        operators = request.form.getlist("operators")
        if not operators:
            flash("Sélectionnez au moins un opérateur.", "error")
            return redirect(url_for("onboarding_operators"))
        ops = []
        for op in operators:
            ops.append({
                "operator": op,
                "opening": _to_float(request.form.get(f"solde_{op}", "0")),
                "seuil": _to_float(request.form.get(f"seuil_{op}", "0")),
            })
        reg["ops"] = ops
        reg["cash"] = _to_float(request.form.get("cash_initial", "0"))
        session["reg"] = reg
        return redirect(url_for("onboarding_services"))

    return render_template("onboarding_operators.html",
                           operateurs=logic.MONEY_OPERATORS, step=2)


# ---------------------------------------------------------------------------
# Inscription — étape 4 : choix des services (Crédit / Factures) + création
# ---------------------------------------------------------------------------
@app.route("/inscription/services", methods=["GET", "POST"])
def onboarding_services():
    reg = session.get("reg")
    if not reg or "ops" not in reg:
        return redirect(url_for("signup"))

    if request.method == "POST":
        services = request.form.getlist("services")

        conn = db.get_db()
        cur = conn.execute(
            "INSERT INTO agent (phone, nom, prenom, cni, business_day, pin_hash, "
            " phone_verified, created_at) VALUES (?,?,?,?,?,?,?,?)",
            (reg["phone"], reg["nom"], reg["prenom"], reg["cni"],
             db.today_str(), reg["pin_hash"], 1 if reg.get("otp_ok") else 0, db.now_str()),
        )
        agent_id = cur.lastrowid

        for o in reg["ops"]:
            conn.execute(
                "INSERT INTO wallet (agent_id, operator, opening_balance, alert_threshold) "
                "VALUES (?,?,?,?)",
                (agent_id, o["operator"], o["opening"], o["seuil"]),
            )
        for srv in services:
            conn.execute(
                "INSERT INTO wallet (agent_id, operator, opening_balance, alert_threshold) "
                "VALUES (?,?,0,0)",
                (agent_id, srv),
            )
        conn.execute(
            "INSERT INTO caisse (agent_id, opening_balance) VALUES (?,?)",
            (agent_id, reg.get("cash", 0)),
        )
        conn.commit()
        conn.close()

        # Code de récupération du PIN : généré une fois, montré une seule fois.
        recovery_code = _new_recovery_code()
        conn2 = db.get_db()
        conn2.execute("UPDATE agent SET recovery_hash=? WHERE id=?",
                      (generate_password_hash(recovery_code), agent_id))
        conn2.commit()
        conn2.close()

        session.clear()
        session.permanent = True
        session["agent_id"] = agent_id
        session["auth"] = True
        session["show_recovery"] = recovery_code
        flash("Compte créé. Bienvenue !", "success")
        return redirect(url_for("onboarding_recovery"))

    return render_template("onboarding_services.html", services=logic.SERVICES, step=3)


@app.route("/inscription/code-secours")
def onboarding_recovery():
    """Affiche le code de récupération une seule fois après l'inscription."""
    code = session.pop("show_recovery", None)
    if not code:
        return redirect(url_for("dashboard"))
    return render_template("onboarding_recovery.html", code=code)


# ---------------------------------------------------------------------------
# 4.2 — Tableau de bord
# ---------------------------------------------------------------------------
@app.route("/dashboard")
def dashboard():
    r = require_onboarding()
    if r:
        return r
    state = compute_state()
    return render_template("dashboard.html", s=state)


# ---------------------------------------------------------------------------
# 4.3 — Saisie d'une transaction
# ---------------------------------------------------------------------------
_SESSION = object()  # sentinelle : « prendre la valeur dans la session »


def _save_operation(tx_type, wallet_id, amount, commission=0, client_uid=None,
                    created_at=None, agent_id=None, employee_id=_SESSION):
    """
    Valide et enregistre une opération.
    Par défaut pour le compte connecté ; `agent_id`/`employee_id` permettent de
    créer une opération hors session (ex. lecture automatique des SMS).
    Idempotent : si `client_uid` existe déjà, l'opération n'est pas dupliquée.
    Retourne (tx_id, None) en cas de succès, (None, message) sinon.
    """
    aid = agent_id if agent_id is not None else session["agent_id"]
    emp = session.get("employee_id") if employee_id is _SESSION else employee_id

    if tx_type not in logic.TX_TYPES:
        return None, "Type d'opération invalide."
    if amount <= 0:
        return None, "Le montant doit être supérieur à zéro."
    needs_wallet = logic.TX_TYPES[tx_type]["wallet"]
    if needs_wallet and not wallet_id:
        return None, "Sélectionnez l'opérateur concerné."

    conn = db.get_db()
    agent = conn.execute("SELECT * FROM agent WHERE id=?", (aid,)).fetchone()

    # Idempotence (synchronisation hors-ligne : le même envoi peut arriver 2 fois)
    if client_uid:
        existing = conn.execute(
            'SELECT id FROM "transaction" WHERE client_uid=?', (client_uid,)
        ).fetchone()
        if existing:
            conn.close()
            return existing["id"], None

    # Le portefeuille doit appartenir au compte connecté
    if needs_wallet:
        w = conn.execute("SELECT id FROM wallet WHERE id=? AND agent_id=?",
                         (wallet_id, agent["id"])).fetchone()
        if w is None:
            conn.close()
            return None, "Opérateur introuvable."

    cur = conn.execute(
        'INSERT INTO "transaction" '
        "(agent_id, business_day, created_at, type, wallet_id, amount, commission, "
        " client_uid, employee_id) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (agent["id"], agent["business_day"], created_at or db.now_str(), tx_type,
         wallet_id if needs_wallet else None, amount, commission, client_uid, emp),
    )
    tx_id = cur.lastrowid
    conn.commit()
    conn.close()
    return tx_id, None


def _wants_json():
    """La requête vient-elle du JavaScript de l'app (fetch) ?"""
    return request.headers.get("X-Requested-With") == "fetch"


@app.route("/transaction", methods=["GET", "POST"])
def transaction():
    state = compute_state()

    if request.method == "POST":
        tx_id, err = _save_operation(
            tx_type=request.form.get("type"),
            wallet_id=request.form.get("wallet_id") or None,
            amount=_to_float(request.form.get("amount", "0")),
            commission=_to_float(request.form.get("commission", "0")),
            client_uid=request.form.get("client_uid") or None,
        )
        if err:
            if _wants_json():
                return jsonify({"ok": False, "error": err}), 400
            flash(err, "error")
            return redirect(url_for("transaction"))
        if _wants_json():
            return jsonify({"ok": True, "undo": tx_id})
        flash("Transaction enregistrée.", "success")
        return redirect(url_for("dashboard", undo=tx_id))

    return render_template("transaction.html", s=state, tx_types=logic.TX_TYPES)


# ---------------------------------------------------------------------------
# 4.4 — Réapprovisionnement
# ---------------------------------------------------------------------------
@app.route("/reappro", methods=["GET", "POST"])
def reappro():
    state = compute_state()

    if request.method == "POST":
        tx_type = request.form.get("type")
        if tx_type not in logic.REAPPRO_TYPES:
            if _wants_json():
                return jsonify({"ok": False, "error": "Type invalide."}), 400
            flash("Type de réapprovisionnement invalide.", "error")
            return redirect(url_for("reappro"))

        tx_id, err = _save_operation(
            tx_type=tx_type,
            wallet_id=request.form.get("wallet_id") or None,
            amount=_to_float(request.form.get("amount", "0")),
            client_uid=request.form.get("client_uid") or None,
        )
        if err:
            if _wants_json():
                return jsonify({"ok": False, "error": err}), 400
            flash(err, "error")
            return redirect(url_for("reappro"))
        if _wants_json():
            return jsonify({"ok": True, "undo": tx_id})
        flash("Réapprovisionnement enregistré.", "success")
        return redirect(url_for("dashboard", undo=tx_id))

    return render_template("reappro.html", s=state)


# ---------------------------------------------------------------------------
# API de synchronisation hors-ligne
# ---------------------------------------------------------------------------
@app.route("/api/sync", methods=["POST"])
def api_sync():
    """
    Reçoit les opérations saisies hors-ligne (file d'attente du téléphone)
    et les enregistre. Idempotent grâce au client_uid : renvoyer deux fois
    la même opération ne crée jamais de doublon.
    """
    data = request.get_json(silent=True) or {}
    ops = data.get("ops", [])
    accepted, rejected = [], []
    for op in ops[:200]:                      # garde-fou
        uid = op.get("uid")
        if not uid:
            continue
        tx_id, err = _save_operation(
            tx_type=op.get("type"),
            wallet_id=op.get("wallet_id") or None,
            amount=_to_float(op.get("amount", 0)),
            commission=_to_float(op.get("commission", 0)),
            client_uid=str(uid)[:64],
            created_at=str(op.get("created_at", ""))[:19] or None,
        )
        if err:
            rejected.append({"uid": uid, "error": err})
        else:
            accepted.append(uid)
    return jsonify({"ok": True, "accepted": accepted, "rejected": rejected})


# ---------------------------------------------------------------------------
# Lecture automatique des SMS (via une app de transfert SMS sur le téléphone)
# ---------------------------------------------------------------------------
@app.route("/api/sms", methods=["POST"])
def api_sms():
    """
    Reçoit un SMS transféré depuis le téléphone (app type « SMS Forwarder »).
    Authentifié par le jeton personnel de l'agent (?token=...). Le SMS est
    analysé puis mis en attente de confirmation par l'agent (jamais validé seul).
    """
    token = request.args.get("token") or request.headers.get("X-Token")
    agent = db.get_agent_by_sms_token(token)
    if not agent:
        return jsonify({"ok": False, "error": "token_invalide"}), 401

    data = request.get_json(silent=True) or request.form
    body = (data.get("body") or data.get("text") or data.get("message") or "").strip()
    sender = (data.get("sender") or data.get("from") or "")[:64]
    if not body:
        return jsonify({"ok": False, "error": "sms_vide"}), 400

    conn = db.get_db()
    wallets = conn.execute(
        "SELECT id, operator FROM wallet WHERE agent_id=? AND active=1",
        (agent["id"],)).fetchall()
    ops = [w["operator"] for w in wallets]
    parsed = logic.parse_sms(body, sender, ops)

    # Clé anti-doublon : l'ID Transaction de l'opérateur si présent (Orange, MTN).
    # Pour les opérateurs SANS ID dans la notification (Wave), on se rabat sur une
    # empreinte du texte : une notification identique reçue 2 fois ne crée jamais
    # 2 transactions. (Wave n'envoie qu'UNE notification par opération.)
    REFLESS_OPERATORS = {"Wave"}
    ref = parsed["ref"]
    if not ref and parsed["operator"] in REFLESS_OPERATORS:
        import hashlib
        norm = " ".join(body.lower().split())
        ref = "h:" + hashlib.sha1(norm.encode("utf-8")).hexdigest()[:16]

    # Création automatique si activée ET lecture complète et fiable :
    # opérateur reconnu (parmi les portefeuilles), sens, montant ET clé anti-doublon.
    wallet_id = next((w["id"] for w in wallets if w["operator"] == parsed["operator"]), None)
    status, tx_id = "pending", None
    can_auto = (agent["sms_auto"] and parsed["type"] and parsed["amount"]
                and wallet_id and ref)
    if can_auto:
        conn.close()
        tx_id, err = _save_operation(
            tx_type=parsed["type"], wallet_id=wallet_id, amount=parsed["amount"],
            client_uid="sms:" + ref, agent_id=agent["id"], employee_id=None,
        )
        if not err:
            status = "confirmed"
        conn = db.get_db()

    conn.execute(
        "INSERT INTO sms_inbox (agent_id, sender, body, received_at, status, "
        " parsed_type, parsed_operator, parsed_amount, tx_id) VALUES (?,?,?,?,?,?,?,?,?)",
        (agent["id"], sender, body[:500], db.now_str(), status,
         parsed["type"], parsed["operator"], parsed["amount"], tx_id),
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "auto": status == "confirmed", "parsed": parsed})


@app.route("/sms")
def sms_inbox():
    conn = db.get_db()
    aid = session["agent_id"]
    pending = conn.execute(
        "SELECT * FROM sms_inbox WHERE agent_id=? AND status='pending' "
        "ORDER BY received_at DESC", (aid,)).fetchall()
    wallets = conn.execute(
        "SELECT * FROM wallet WHERE agent_id=? AND active=1 ORDER BY id", (aid,)).fetchall()
    conn.close()
    return render_template("sms.html", pending=pending, wallets=wallets,
                           tx_types=logic.TX_TYPES)


@app.route("/sms/<int:sms_id>/confirm", methods=["POST"])
def sms_confirm(sms_id):
    conn = db.get_db()
    aid = session["agent_id"]
    sms = conn.execute("SELECT * FROM sms_inbox WHERE id=? AND agent_id=?",
                       (sms_id, aid)).fetchone()
    conn.close()
    if not sms or sms["status"] != "pending":
        flash("SMS introuvable ou déjà traité.", "error")
        return redirect(url_for("sms_inbox"))

    tx_id, err = _save_operation(
        tx_type=request.form.get("type"),
        wallet_id=request.form.get("wallet_id") or None,
        amount=_to_float(request.form.get("amount", "0")),
    )
    if err:
        flash(err, "error")
        return redirect(url_for("sms_inbox"))

    conn = db.get_db()
    conn.execute("UPDATE sms_inbox SET status='confirmed', tx_id=? WHERE id=? AND agent_id=?",
                 (tx_id, sms_id, aid))
    conn.commit()
    conn.close()
    flash("Transaction créée depuis le SMS. ✓", "success")
    return redirect(url_for("sms_inbox"))


@app.route("/sms/<int:sms_id>/reject", methods=["POST"])
def sms_reject(sms_id):
    conn = db.get_db()
    conn.execute("UPDATE sms_inbox SET status='rejected' WHERE id=? AND agent_id=?",
                 (sms_id, session["agent_id"]))
    conn.commit()
    conn.close()
    return redirect(url_for("sms_inbox"))


# ---------------------------------------------------------------------------
# 4.5 — Clôture de journée
# ---------------------------------------------------------------------------
@app.route("/cloture", methods=["GET", "POST"])
def cloture():
    r = require_onboarding()
    if r:
        return r
    state = compute_state()

    if request.method == "POST":
        conn = db.get_db()
        agent = conn.execute("SELECT * FROM agent WHERE id=?", (session["agent_id"],)).fetchone()
        cur = conn.execute(
            "INSERT INTO cloture (agent_id, date, created_at) VALUES (?,?,?)",
            (agent["id"], state["business_day"], db.now_str()),
        )
        cloture_id = cur.lastrowid

        # Lignes portefeuilles
        for w in state["wallets"]:
            reel = _to_float(request.form.get(f"reel_wallet_{w['id']}", w["balance"]))
            ec = logic.ecart(reel, w["balance"])
            conn.execute(
                "INSERT INTO cloture_line "
                "(cloture_id, label, kind, ref_id, theorique, reel, ecart, commission) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (cloture_id, w["operator"], "wallet", w["id"], w["balance"], reel, ec,
                 w["commission"]),
            )
            # Report : le solde réel devient l'ouverture du lendemain
            conn.execute("UPDATE wallet SET opening_balance=? WHERE id=?", (reel, w["id"]))

        # Ligne caisse
        reel_cash = _to_float(request.form.get("reel_cash", state["cash"]))
        ec_cash = logic.ecart(reel_cash, state["cash"])
        conn.execute(
            "INSERT INTO cloture_line "
            "(cloture_id, label, kind, ref_id, theorique, reel, ecart, commission) "
            "VALUES (?,?,?,?,?,?,?,0)",
            (cloture_id, "Caisse", "cash", None, state["cash"], reel_cash, ec_cash),
        )
        conn.execute(
            "UPDATE caisse SET opening_balance=? WHERE agent_id=?",
            (reel_cash, agent["id"]),
        )

        # Avance de la journée comptable : repartir à zéro de transactions
        new_day = db.today_str()
        # si on clôture deux fois le même jour, on incrémente artificiellement
        if new_day == agent["business_day"]:
            from datetime import datetime, timedelta
            new_day = (datetime.strptime(agent["business_day"], "%Y-%m-%d")
                       + timedelta(days=1)).strftime("%Y-%m-%d")
        conn.execute("UPDATE agent SET business_day=? WHERE id=?", (new_day, agent["id"]))

        conn.commit()
        conn.close()
        flash("Journée clôturée. Les soldes réels deviennent l'ouverture du lendemain.", "success")
        return redirect(url_for("cloture_recap", cloture_id=cloture_id))

    return render_template("cloture.html", s=state)


@app.route("/cloture/<int:cloture_id>")
def cloture_recap(cloture_id):
    """Bilan d'une clôture : écarts + commissions par opérateur."""
    conn = db.get_db()
    # La clôture doit appartenir au compte connecté (isolation multi-comptes).
    cl = conn.execute("SELECT * FROM cloture WHERE id=? AND agent_id=?",
                      (cloture_id, session["agent_id"])).fetchone()
    if cl is None:
        conn.close()
        flash("Clôture introuvable.", "error")
        return redirect(url_for("dashboard"))
    lines = conn.execute(
        "SELECT * FROM cloture_line WHERE cloture_id=? ORDER BY kind DESC, id",
        (cloture_id,),
    ).fetchall()
    conn.close()

    total_commission = sum(l["commission"] for l in lines)
    total_ecart = sum(l["ecart"] for l in lines)

    # Texte de partage WhatsApp (compte-rendu au propriétaire du point)
    agent = current_agent()
    conn2 = db.get_db()
    drow = conn2.execute(
        "SELECT COALESCE(SUM(amount),0) AS total FROM dette "
        "WHERE agent_id=? AND settled_at IS NULL", (agent["id"],)).fetchone()
    conn2.close()
    dettes_total = drow["total"] if drow else 0

    txt = [f"🔒 BILAN DU {cl['date']}"]
    if agent["shop_name"]:
        txt.append(f"🏪 {agent['shop_name']}")
    txt.append("")
    txt.append(f"💰 Commissions du jour : {fmt(total_commission)} F")
    signe = "+" if total_ecart > 0 else ""
    txt.append(f"📊 Écart global : {signe}{fmt(total_ecart)} F")
    txt.append("")
    txt.append("Par portefeuille :")
    for l in lines:
        s2 = "+" if l["ecart"] > 0 else ""
        txt.append(f"• {l['label']} : réel {fmt(l['reel'])} F "
                   f"(écart {s2}{fmt(l['ecart'])} F)")
    if dettes_total > 0:
        txt.append("")
        txt.append(f"📓 Dettes clients en cours : {fmt(dettes_total)} F")
    txt.append("")
    txt.append("— Généré par Trésorerie Mobile Money")

    from urllib.parse import quote
    wa_text = quote("\n".join(txt))

    return render_template("cloture_recap.html", cl=cl, lines=lines,
                           total_commission=total_commission, total_ecart=total_ecart,
                           wa_text=wa_text)


# ---------------------------------------------------------------------------
# Journal des clôtures passées
# ---------------------------------------------------------------------------
@app.route("/journal")
def journal():
    conn = db.get_db()
    clotures = conn.execute(
        "SELECT c.id, c.date, c.created_at, "
        "       COALESCE(SUM(l.ecart), 0) AS total_ecart, "
        "       COALESCE(SUM(l.commission), 0) AS total_commission "
        "FROM cloture c LEFT JOIN cloture_line l ON l.cloture_id = c.id "
        "WHERE c.agent_id=? "
        "GROUP BY c.id, c.date, c.created_at "
        "ORDER BY c.date DESC, c.id DESC",
        (session["agent_id"],),
    ).fetchall()
    conn.close()
    return render_template("journal.html", clotures=clotures)


# ---------------------------------------------------------------------------
# Journal des téléchargements : un export CSV/PDF par jour d'activité
# ---------------------------------------------------------------------------
@app.route("/telechargements")
def telechargements():
    conn = db.get_db()
    jours = conn.execute(
        'SELECT business_day AS jour, COUNT(*) AS n, '
        '       MIN(created_at) AS premier, MAX(created_at) AS dernier '
        'FROM "transaction" WHERE agent_id=? AND deleted=0 '
        'GROUP BY business_day ORDER BY business_day DESC',
        (session["agent_id"],),
    ).fetchall()
    conn.close()
    return render_template("telechargements.html", jours=jours)


# ---------------------------------------------------------------------------
# Carnet de dettes clients
# ---------------------------------------------------------------------------
@app.route("/dettes", methods=["GET", "POST"])
def dettes():
    conn = db.get_db()
    aid = session["agent_id"]

    if request.method == "POST":
        name = request.form.get("client_name", "").strip()
        phone = normalize_phone(request.form.get("client_phone", ""))
        amount = _to_float(request.form.get("amount", "0"))
        note = request.form.get("note", "").strip()
        if not name:
            flash("Le nom du client est obligatoire.", "error")
        elif amount <= 0:
            flash("Le montant doit être supérieur à zéro.", "error")
        else:
            conn.execute(
                "INSERT INTO dette (agent_id, client_name, client_phone, amount, note, created_at) "
                "VALUES (?,?,?,?,?,?)",
                (aid, name, phone or None, amount, note or None, db.now_str()),
            )
            conn.commit()
            flash(f"Dette de {fmt(amount)} FCFA notée pour {name}.", "success")
        conn.close()
        return redirect(url_for("dettes"))

    en_cours = conn.execute(
        "SELECT * FROM dette WHERE agent_id=? AND settled_at IS NULL "
        "ORDER BY created_at DESC", (aid,)
    ).fetchall()
    reglees = conn.execute(
        "SELECT * FROM dette WHERE agent_id=? AND settled_at IS NOT NULL "
        "ORDER BY settled_at DESC LIMIT 20", (aid,)
    ).fetchall()
    conn.close()
    total = sum(d["amount"] for d in en_cours)
    return render_template("dettes.html", en_cours=en_cours, reglees=reglees, total=total)


@app.route("/dettes/<int:dette_id>/regler", methods=["POST"])
def dette_regler(dette_id):
    conn = db.get_db()
    conn.execute("UPDATE dette SET settled_at=? WHERE id=? AND agent_id=?",
                 (db.now_str(), dette_id, session["agent_id"]))
    conn.commit()
    conn.close()
    flash("Dette marquée comme réglée. ✓", "success")
    return redirect(url_for("dettes"))


@app.route("/dettes/<int:dette_id>/delete", methods=["POST"])
def dette_delete(dette_id):
    conn = db.get_db()
    conn.execute("DELETE FROM dette WHERE id=? AND agent_id=?",
                 (dette_id, session["agent_id"]))
    conn.commit()
    conn.close()
    flash("Dette supprimée.", "success")
    return redirect(url_for("dettes"))


# ---------------------------------------------------------------------------
# 4.6 — Historique (+ exports CSV / PDF)
# ---------------------------------------------------------------------------
def _filtered_transactions(conn, agent_id, f_jour, f_wallet, f_type):
    """Transactions du compte, filtrées comme sur l'écran Historique."""
    query = ('SELECT t.*, w.operator AS operator, e.name AS employee_name '
             'FROM "transaction" t '
             "LEFT JOIN wallet w ON t.wallet_id = w.id "
             "LEFT JOIN employee e ON t.employee_id = e.id "
             "WHERE t.agent_id=? AND t.deleted=0")
    params = [agent_id]
    if f_jour:
        query += " AND t.business_day=?"
        params.append(f_jour)
    if f_wallet:
        query += " AND t.wallet_id=?"
        params.append(f_wallet)
    if f_type:
        query += " AND t.type=?"
        params.append(f_type)
    query += " ORDER BY t.created_at DESC"
    return conn.execute(query, params).fetchall()


@app.route("/historique")
def historique():
    f_jour = request.args.get("jour", "")
    f_wallet = request.args.get("wallet", "")
    f_type = request.args.get("type", "")

    conn = db.get_db()
    agent = conn.execute("SELECT * FROM agent WHERE id=?", (session["agent_id"],)).fetchone()
    wallets = conn.execute(
        "SELECT * FROM wallet WHERE agent_id=? ORDER BY id", (agent["id"],)
    ).fetchall()

    txs = _filtered_transactions(conn, agent["id"], f_jour, f_wallet, f_type)
    jours = conn.execute(
        'SELECT DISTINCT business_day FROM "transaction" '
        "WHERE agent_id=? ORDER BY business_day DESC", (agent["id"],)
    ).fetchall()
    conn.close()

    return render_template(
        "historique.html", txs=txs, wallets=wallets, jours=jours,
        tx_types=logic.TX_TYPES,
        f_jour=f_jour, f_wallet=f_wallet, f_type=f_type,
    )


@app.route("/transaction/<int:tx_id>/delete", methods=["POST"])
def delete_transaction(tx_id):
    """Suppression douce d'une transaction (annulation rapide ou correction)."""
    conn = db.get_db()
    conn.execute('UPDATE "transaction" SET deleted=1 WHERE id=? AND agent_id=?',
                 (tx_id, session["agent_id"]))
    conn.commit()
    conn.close()
    flash("Opération annulée. Les soldes ont été recalculés.", "success")
    if request.form.get("next") == "dashboard":
        return redirect(url_for("dashboard"))
    return redirect(url_for("historique"))


def _export_rows():
    """Lignes de l'historique pour les exports (respecte les filtres d'URL)."""
    f_jour = request.args.get("jour", "")
    f_wallet = request.args.get("wallet", "")
    f_type = request.args.get("type", "")
    conn = db.get_db()
    agent = conn.execute("SELECT * FROM agent WHERE id=?", (session["agent_id"],)).fetchone()
    txs = _filtered_transactions(conn, agent["id"], f_jour, f_wallet, f_type)
    conn.close()
    return agent, txs


@app.route("/export/csv")
def export_csv():
    """Télécharge l'historique (filtré) au format CSV (compatible Excel)."""
    import csv
    import io
    agent, txs = _export_rows()

    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";")
    writer.writerow(["Date/heure", "Journée", "Type", "Opérateur",
                     "Montant (FCFA)", "Commission (FCFA)"])
    for t in txs:
        writer.writerow([
            t["created_at"], t["business_day"],
            logic.TX_TYPES.get(t["type"], {}).get("label", t["type"]),
            t["operator"] or "Caisse",
            int(t["amount"]), int(t["commission"] or 0),
        ])

    # BOM UTF-8 pour qu'Excel affiche correctement les accents.
    data = "﻿" + buf.getvalue()
    filename = f"historique_{db.today_str()}.csv"
    return Response(
        data,
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@app.route("/export/pdf")
def export_pdf():
    """Télécharge l'historique (filtré) au format PDF."""
    from fpdf import FPDF
    agent, txs = _export_rows()

    def lat(s):
        """fpdf (polices de base) est limité au latin-1."""
        return str(s).encode("latin-1", "replace").decode("latin-1")

    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=14)
    pdf.add_page()

    # En-tête du document
    pdf.set_font("helvetica", "B", 15)
    pdf.set_text_color(13, 110, 92)
    pdf.cell(0, 9, lat("Historique des transactions"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("helvetica", "", 10)
    pdf.set_text_color(90, 90, 90)
    titulaire = " ".join(x for x in [agent["prenom"], agent["nom"]] if x) or agent["phone"]
    boutique = f" — {agent['shop_name']}" if agent["shop_name"] else ""
    pdf.cell(0, 6, lat(f"Compte : {titulaire}{boutique} ({agent['phone']})"),
             new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 6, lat(f"Édité le {db.now_str()} — {len(txs)} opération(s)"),
             new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    # Tableau
    widths = [38, 24, 36, 38, 28, 26]   # total 190 mm
    headers = ["Date/heure", "Journée", "Type", "Opérateur", "Montant", "Commission"]
    pdf.set_font("helvetica", "B", 9)
    pdf.set_fill_color(13, 110, 92)
    pdf.set_text_color(255, 255, 255)
    for w, h in zip(widths, headers):
        pdf.cell(w, 8, lat(h), border=1, fill=True, align="C")
    pdf.ln()

    pdf.set_font("helvetica", "", 9)
    pdf.set_text_color(30, 30, 30)
    fill = False
    pdf.set_fill_color(240, 245, 243)
    for t in txs:
        label = logic.TX_TYPES.get(t["type"], {}).get("label", t["type"])
        row = [t["created_at"], t["business_day"], label, t["operator"] or "Caisse",
               fmt(t["amount"]), fmt(t["commission"] or 0)]
        aligns = ["L", "L", "L", "L", "R", "R"]
        for w, val, al in zip(widths, row, aligns):
            pdf.cell(w, 7, lat(val), border=1, fill=fill, align=al)
        pdf.ln()
        fill = not fill

    filename = f"historique_{db.today_str()}.pdf"
    return Response(
        bytes(pdf.output()),
        mimetype="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# ---------------------------------------------------------------------------
# Rapport mensuel PDF — dossier d'activité du point marchand
# ---------------------------------------------------------------------------
@app.route("/rapport")
def rapport():
    mois = request.args.get("mois") or db.today_str()[:7]      # YYYY-MM
    if len(mois) != 7 or mois[4] != "-":
        mois = db.today_str()[:7]

    conn = db.get_db()
    aid = session["agent_id"]
    agent = conn.execute("SELECT * FROM agent WHERE id=?", (aid,)).fetchone()
    txs = conn.execute(
        'SELECT t.*, w.operator AS operator FROM "transaction" t '
        "LEFT JOIN wallet w ON t.wallet_id = w.id "
        "WHERE t.agent_id=? AND t.deleted=0 AND t.business_day LIKE ? "
        "ORDER BY t.business_day, t.created_at",
        (aid, mois + "%"),
    ).fetchall()
    ecarts = {r["date"]: r["ecart"] for r in conn.execute(
        "SELECT c.date AS date, COALESCE(SUM(l.ecart),0) AS ecart "
        "FROM cloture c LEFT JOIN cloture_line l ON l.cloture_id = c.id "
        "WHERE c.agent_id=? AND c.date LIKE ? GROUP BY c.date",
        (aid, mois + "%"),
    ).fetchall()}
    drow = conn.execute(
        "SELECT COALESCE(SUM(amount),0) AS total, COUNT(*) AS n FROM dette "
        "WHERE agent_id=? AND settled_at IS NULL", (aid,)).fetchone()
    conn.close()

    # Agrégats par jour et par opérateur
    jours, operateurs = {}, {}
    for t in txs:
        d = t["business_day"]
        jours.setdefault(d, {"n": 0, "vol": 0.0, "comm_manuelle": 0.0,
                             "vol_grille": {}})
        j = jours[d]
        j["n"] += 1
        if t["type"] in ("depot_client", "retrait_client"):
            j["vol"] += t["amount"]
            op = t["operator"] or "?"
            o = operateurs.setdefault(op, {"vol": 0.0, "comm": 0.0, "n": 0})
            o["vol"] += t["amount"]
            o["n"] += 1
            if op in logic.COMMISSION_GRIDS:
                j["vol_grille"][op] = j["vol_grille"].get(op, 0.0) + t["amount"]
            else:
                j["comm_manuelle"] += t["commission"] or 0
                o["comm"] += t["commission"] or 0

    # Commission des opérateurs à grille : par JOUR (grille journalière), puis cumul
    total_comm = 0.0
    for d, j in jours.items():
        c_jour = j["comm_manuelle"]
        for op, vol in j["vol_grille"].items():
            c_grille = logic.daily_commission(op, vol) or 0
            c_jour += c_grille
            operateurs[op]["comm"] += c_grille
        j["comm"] = c_jour
        total_comm += c_jour

    total_vol = sum(j["vol"] for j in jours.values())
    total_ops = sum(j["n"] for j in jours.values())
    total_ecart = sum(ecarts.get(d, 0) for d in jours)

    # --- Génération du PDF ---
    from fpdf import FPDF

    def lat(s):
        return str(s).encode("latin-1", "replace").decode("latin-1")

    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=14)
    pdf.add_page()

    pdf.set_font("helvetica", "B", 16)
    pdf.set_text_color(13, 110, 92)
    pdf.cell(0, 10, lat(f"Rapport d'activité — {mois}"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("helvetica", "", 10)
    pdf.set_text_color(90, 90, 90)
    titulaire = " ".join(x for x in [agent["prenom"], agent["nom"]] if x) or agent["phone"]
    boutique = f" — {agent['shop_name']}" if agent["shop_name"] else ""
    pdf.cell(0, 6, lat(f"Point marchand : {titulaire}{boutique} ({agent['phone']})"),
             new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 6, lat(f"Édité le {db.now_str()} par Trésorerie Mobile Money"),
             new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    # Synthèse
    pdf.set_font("helvetica", "B", 12)
    pdf.set_text_color(30, 30, 30)
    pdf.cell(0, 8, lat("Synthèse du mois"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("helvetica", "", 10)
    for label, val in [
        ("Volume traité (dépôts + retraits clients)", f"{fmt(total_vol)} FCFA"),
        ("Nombre d'opérations", str(total_ops)),
        ("Commissions estimées du mois", f"{fmt(total_comm)} FCFA"),
        ("Jours d'activité", str(len(jours))),
        ("Écart cumulé des clôtures", f"{fmt(total_ecart)} FCFA"),
        ("Dettes clients en cours", f"{fmt(drow['total'])} FCFA ({drow['n']} client(s))"),
    ]:
        pdf.cell(110, 7, lat(label), border=0)
        pdf.set_font("helvetica", "B", 10)
        pdf.cell(0, 7, lat(val), border=0, new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("helvetica", "", 10)
    pdf.ln(3)

    # Par opérateur
    if operateurs:
        pdf.set_font("helvetica", "B", 12)
        pdf.cell(0, 8, lat("Par opérateur"), new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("helvetica", "B", 9)
        pdf.set_fill_color(13, 110, 92)
        pdf.set_text_color(255, 255, 255)
        for w_, h_ in zip([60, 40, 50, 40], ["Opérateur", "Opérations", "Volume", "Commissions"]):
            pdf.cell(w_, 8, lat(h_), border=1, fill=True, align="C")
        pdf.ln()
        pdf.set_font("helvetica", "", 9)
        pdf.set_text_color(30, 30, 30)
        for op, o in sorted(operateurs.items()):
            pdf.cell(60, 7, lat(op), border=1)
            pdf.cell(40, 7, str(o["n"]), border=1, align="R")
            pdf.cell(50, 7, lat(fmt(o["vol"])), border=1, align="R")
            pdf.cell(40, 7, lat(fmt(o["comm"])), border=1, align="R")
            pdf.ln()
        pdf.ln(3)

    # Par jour
    if jours:
        pdf.set_font("helvetica", "B", 12)
        pdf.cell(0, 8, lat("Détail par jour"), new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("helvetica", "B", 9)
        pdf.set_fill_color(13, 110, 92)
        pdf.set_text_color(255, 255, 255)
        for w_, h_ in zip([40, 30, 45, 40, 35], ["Date", "Opérations", "Volume", "Commissions", "Écart clôture"]):
            pdf.cell(w_, 8, lat(h_), border=1, fill=True, align="C")
        pdf.ln()
        pdf.set_font("helvetica", "", 9)
        pdf.set_text_color(30, 30, 30)
        fill = False
        pdf.set_fill_color(240, 245, 243)
        for d in sorted(jours):
            j = jours[d]
            ec = ecarts.get(d)
            pdf.cell(40, 7, lat(d), border=1, fill=fill)
            pdf.cell(30, 7, str(j["n"]), border=1, align="R", fill=fill)
            pdf.cell(45, 7, lat(fmt(j["vol"])), border=1, align="R", fill=fill)
            pdf.cell(40, 7, lat(fmt(j["comm"])), border=1, align="R", fill=fill)
            pdf.cell(35, 7, lat(fmt(ec) if ec is not None else "non clôturé"),
                     border=1, align="R", fill=fill)
            pdf.ln()
            fill = not fill

    pdf.ln(5)
    pdf.set_font("helvetica", "I", 8)
    pdf.set_text_color(120, 120, 120)
    pdf.multi_cell(0, 5, lat(
        "Document généré automatiquement à partir des opérations enregistrées par "
        "l'agent dans l'application Trésorerie Mobile Money. Les commissions des "
        "opérateurs à grille connue (Wave) sont estimées selon la grille officielle ; "
        "les autres selon les saisies de l'agent."))

    filename = f"rapport_{mois}.pdf"
    return Response(
        bytes(pdf.output()),
        mimetype="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# ---------------------------------------------------------------------------
# 4.7 — Paramètres
# ---------------------------------------------------------------------------
@app.route("/parametres", methods=["GET", "POST"])
def parametres():
    r = require_onboarding()
    if r:
        return r

    conn = db.get_db()
    agent = conn.execute("SELECT * FROM agent WHERE id=?", (session["agent_id"],)).fetchone()

    if request.method == "POST":
        action = request.form.get("action")

        if action == "account":
            shop_name = request.form.get("shop_name", "").strip()
            phone = request.form.get("phone", "").strip()
            if not phone:
                flash("Le numéro de téléphone est obligatoire.", "error")
            else:
                conn.execute("UPDATE agent SET shop_name=?, phone=? WHERE id=?",
                             (shop_name, phone, agent["id"]))
                flash("Informations du compte mises à jour.", "success")

        elif action == "seuils":
            wallets = conn.execute(
                "SELECT * FROM wallet WHERE agent_id=? AND active=1", (agent["id"],)
            ).fetchall()
            for w in wallets:
                seuil = _to_float(request.form.get(f"seuil_{w['id']}", w["alert_threshold"]))
                conn.execute("UPDATE wallet SET alert_threshold=? WHERE id=?", (seuil, w["id"]))
            flash("Seuils d'alerte mis à jour.", "success")

        elif action == "add_operator":
            op = request.form.get("new_operator")
            opening = _to_float(request.form.get("new_opening", "0"))
            seuil = _to_float(request.form.get("new_seuil", "0"))
            if op:
                existing = conn.execute(
                    "SELECT * FROM wallet WHERE agent_id=? AND operator=?",
                    (agent["id"], op)
                ).fetchone()
                if existing:
                    conn.execute("UPDATE wallet SET active=1 WHERE id=?", (existing["id"],))
                else:
                    conn.execute(
                        "INSERT INTO wallet (agent_id, operator, opening_balance, alert_threshold) "
                        "VALUES (?,?,?,?)", (agent["id"], op, opening, seuil))
                flash(f"Opérateur « {op} » ajouté.", "success")

        elif action == "remove_operator":
            wid = request.form.get("wallet_id")
            conn.execute("UPDATE wallet SET active=0 WHERE id=? AND agent_id=?",
                         (wid, agent["id"]))
            flash("Opérateur retiré du suivi.", "success")

        elif action == "set_pin":
            pin = request.form.get("pin", "").strip()
            if not pin or len(pin) < 4 or not pin.isdigit():
                flash("Le code doit comporter au moins 4 chiffres.", "error")
            else:
                conn.execute("UPDATE agent SET pin_hash=? WHERE id=?",
                             (generate_password_hash(pin), agent["id"]))
                session["auth"] = True
                flash("Code de connexion enregistré.", "success")

        elif action == "recovery":
            code = _new_recovery_code()
            conn.execute("UPDATE agent SET recovery_hash=? WHERE id=?",
                         (generate_password_hash(code), agent["id"]))
            session["show_recovery"] = code
            flash("Nouveau code de secours généré. Notez-le : il ne sera plus affiché.", "success")

        elif action == "add_employee":
            name = request.form.get("emp_name", "").strip()
            pin = request.form.get("emp_pin", "").strip()
            if not name:
                flash("Le nom de l'employé est obligatoire.", "error")
            elif not pin or len(pin) < 4 or not pin.isdigit():
                flash("Le code PIN de l'employé doit comporter au moins 4 chiffres.", "error")
            else:
                # Le PIN doit être unique sur ce compte (il identifie qui se connecte)
                clash = agent["pin_hash"] and check_password_hash(agent["pin_hash"], pin)
                if not clash:
                    others = conn.execute(
                        "SELECT pin_hash FROM employee WHERE agent_id=? AND active=1",
                        (agent["id"],)).fetchall()
                    clash = any(check_password_hash(o["pin_hash"], pin) for o in others)
                if clash:
                    flash("Ce code PIN est déjà utilisé sur ce compte. Choisissez-en un autre.", "error")
                else:
                    conn.execute(
                        "INSERT INTO employee (agent_id, name, pin_hash, created_at) "
                        "VALUES (?,?,?,?)",
                        (agent["id"], name, generate_password_hash(pin), db.now_str()))
                    flash(f"Employé « {name} » ajouté. Il se connecte avec votre numéro "
                          "et SON code PIN.", "success")

        elif action == "toggle_employee":
            emp_id = request.form.get("emp_id")
            emp = conn.execute("SELECT * FROM employee WHERE id=? AND agent_id=?",
                               (emp_id, agent["id"])).fetchone()
            if emp:
                conn.execute("UPDATE employee SET active=? WHERE id=?",
                             (0 if emp["active"] else 1, emp["id"]))
                flash(("Accès désactivé pour " if emp["active"] else "Accès réactivé pour ")
                      + emp["name"] + ".", "success")

        elif action == "sms_token":
            import secrets
            conn.execute("UPDATE agent SET sms_token=? WHERE id=?",
                         (secrets.token_urlsafe(24), agent["id"]))
            flash("Lien de lecture des SMS (re)généré.", "success")

        elif action == "sms_auto":
            val = 1 if request.form.get("sms_auto") == "on" else 0
            conn.execute("UPDATE agent SET sms_auto=? WHERE id=?", (val, agent["id"]))
            flash("Création automatique " + ("activée." if val else "désactivée."), "success")

        conn.commit()
        conn.close()
        return redirect(url_for("parametres"))

    wallets = conn.execute(
        "SELECT * FROM wallet WHERE agent_id=? AND active=1 ORDER BY id", (agent["id"],)
    ).fetchall()
    active_ops = {w["operator"] for w in wallets}
    dispo = [op for op in logic.OPERATEURS if op not in active_ops]
    employees = conn.execute(
        "SELECT * FROM employee WHERE agent_id=? ORDER BY active DESC, name",
        (agent["id"],)).fetchall()
    conn.close()

    return render_template("parametres.html", agent=agent, wallets=wallets, dispo=dispo,
                           employees=employees,
                           recovery_code=session.pop("show_recovery", None))


# ---------------------------------------------------------------------------
# Utilitaires
# ---------------------------------------------------------------------------
def _to_float(v):
    # On ne garde que les chiffres et séparateurs ; tolère espaces, espaces
    # insécables, points de milliers saisis par l'utilisateur, etc.
    s = "".join(ch for ch in str(v) if ch.isdigit() or ch in ".,-")
    s = s.replace(",", ".")
    try:
        return float(s) if s else 0.0
    except ValueError:
        return 0.0


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
