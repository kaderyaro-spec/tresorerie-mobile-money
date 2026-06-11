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
    conn.close()

    txs_d = [dict(t) for t in txs]

    # Solde par portefeuille + voyant + commissions du jour de l'opérateur
    wallet_states = []
    wallet_balances = []
    for w in wallets:
        w_txs = [t for t in txs_d if t["wallet_id"] == w["id"]]
        bal = logic.wallet_balance(w["opening_balance"], w_txs)
        wallet_balances.append(bal)

        # Wave : commission calculée automatiquement via la grille (cumul du jour).
        # Autres opérateurs : cumul des commissions saisies manuellement.
        if w["operator"] == "Wave":
            vol = logic.wave_volume(w_txs)
            commission = logic.wave_daily_commission(vol)
        else:
            commission = logic.commissions_total(w_txs)

        wallet_states.append({
            "id": w["id"],
            "operator": w["operator"],
            "balance": bal,
            "threshold": w["alert_threshold"],
            "voyant": logic.voyant(bal, w["alert_threshold"]),
            "commission": commission,
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
    }


def require_onboarding():
    """Conservé pour compatibilité ; l'accès est géré par require_login()."""
    return None


# Points d'entrée accessibles sans être connecté
PUBLIC_ENDPOINTS = {
    "login", "signup", "static", "index",
    "onboarding_pin", "onboarding_operators", "onboarding_services",
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


def current_agent():
    """L'agent du compte connecté (selon la session), ou None."""
    return db.get_agent_by_id(session.get("agent_id"))


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
        return redirect(url_for("login"))
    return None


@app.route("/")
def index():
    if session.get("auth") and current_agent() is not None:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


# ---------------------------------------------------------------------------
# Connexion (numéro + code PIN) — multi-comptes
# ---------------------------------------------------------------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        phone = normalize_phone(request.form.get("phone", ""))
        pin = request.form.get("pin", "").strip()
        agent = db.get_agent_by_phone(phone)
        if agent and agent["pin_hash"] and check_password_hash(agent["pin_hash"], pin):
            session.clear()
            session["agent_id"] = agent["id"]
            session["auth"] = True
            return redirect(url_for("dashboard"))
        flash("Numéro ou code incorrect.", "error")
        return redirect(url_for("login"))

    return render_template("login.html")


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))


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

        # On démarre une nouvelle inscription propre.
        session.clear()
        session["reg"] = {"nom": nom, "prenom": prenom, "cni": cni, "phone": phone}
        return redirect(url_for("onboarding_pin"))

    return render_template("signup.html")


# ---------------------------------------------------------------------------
# Inscription — étape 2 : code PIN de connexion
# ---------------------------------------------------------------------------
@app.route("/inscription/pin", methods=["GET", "POST"])
def onboarding_pin():
    if not session.get("reg"):
        return redirect(url_for("signup"))

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
            "INSERT INTO agent (phone, nom, prenom, cni, business_day, pin_hash, created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (reg["phone"], reg["nom"], reg["prenom"], reg["cni"],
             db.today_str(), reg["pin_hash"], db.now_str()),
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

        session.clear()
        session["agent_id"] = agent_id
        session["auth"] = True
        flash("Compte créé. Bienvenue !", "success")
        return redirect(url_for("dashboard"))

    return render_template("onboarding_services.html", services=logic.SERVICES, step=3)


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
@app.route("/transaction", methods=["GET", "POST"])
def transaction():
    r = require_onboarding()
    if r:
        return r
    state = compute_state()

    if request.method == "POST":
        tx_type = request.form.get("type")
        wallet_id = request.form.get("wallet_id") or None
        amount = _to_float(request.form.get("amount", "0"))
        commission = _to_float(request.form.get("commission", "0"))

        if tx_type not in logic.TX_TYPES:
            flash("Type d'opération invalide.", "error")
            return redirect(url_for("transaction"))
        if amount <= 0:
            flash("Le montant doit être supérieur à zéro.", "error")
            return redirect(url_for("transaction"))
        if logic.TX_TYPES[tx_type]["wallet"] and not wallet_id:
            flash("Sélectionnez l'opérateur concerné.", "error")
            return redirect(url_for("transaction"))

        conn = db.get_db()
        agent = conn.execute("SELECT * FROM agent WHERE id=?", (session["agent_id"],)).fetchone()
        conn.execute(
            'INSERT INTO "transaction" '
            "(agent_id, business_day, created_at, type, wallet_id, amount, commission) "
            "VALUES (?,?,?,?,?,?,?)",
            (agent["id"], agent["business_day"], db.now_str(), tx_type,
             wallet_id if logic.TX_TYPES[tx_type]["wallet"] else None,
             amount, commission),
        )
        conn.commit()
        conn.close()
        flash("Transaction enregistrée.", "success")
        return redirect(url_for("dashboard"))

    return render_template("transaction.html", s=state, tx_types=logic.TX_TYPES)


# ---------------------------------------------------------------------------
# 4.4 — Réapprovisionnement
# ---------------------------------------------------------------------------
@app.route("/reappro", methods=["GET", "POST"])
def reappro():
    r = require_onboarding()
    if r:
        return r
    state = compute_state()

    if request.method == "POST":
        tx_type = request.form.get("type")
        wallet_id = request.form.get("wallet_id") or None
        amount = _to_float(request.form.get("amount", "0"))

        if tx_type not in logic.REAPPRO_TYPES:
            flash("Type de réapprovisionnement invalide.", "error")
            return redirect(url_for("reappro"))
        if amount <= 0:
            flash("Le montant doit être supérieur à zéro.", "error")
            return redirect(url_for("reappro"))
        if tx_type == "achat_float" and not wallet_id:
            flash("Sélectionnez l'opérateur pour l'achat d'UV.", "error")
            return redirect(url_for("reappro"))

        conn = db.get_db()
        agent = conn.execute("SELECT * FROM agent WHERE id=?", (session["agent_id"],)).fetchone()
        conn.execute(
            'INSERT INTO "transaction" '
            "(agent_id, business_day, created_at, type, wallet_id, amount, commission) "
            "VALUES (?,?,?,?,?,?,0)",
            (agent["id"], agent["business_day"], db.now_str(), tx_type,
             wallet_id if tx_type == "achat_float" else None, amount),
        )
        conn.commit()
        conn.close()
        flash("Réapprovisionnement enregistré.", "success")
        return redirect(url_for("dashboard"))

    return render_template("reappro.html", s=state)


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
    return render_template("cloture_recap.html", cl=cl, lines=lines,
                           total_commission=total_commission, total_ecart=total_ecart)


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
# 4.6 — Historique (+ exports CSV / PDF)
# ---------------------------------------------------------------------------
def _filtered_transactions(conn, agent_id, f_jour, f_wallet, f_type):
    """Transactions du compte, filtrées comme sur l'écran Historique."""
    query = ('SELECT t.*, w.operator AS operator FROM "transaction" t '
             "LEFT JOIN wallet w ON t.wallet_id = w.id "
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
    """Suppression douce d'une transaction saisie par erreur (avec trace)."""
    conn = db.get_db()
    conn.execute('UPDATE "transaction" SET deleted=1 WHERE id=? AND agent_id=?',
                 (tx_id, session["agent_id"]))
    conn.commit()
    conn.close()
    flash("Transaction supprimée. Les soldes ont été recalculés.", "success")
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

        conn.commit()
        conn.close()
        return redirect(url_for("parametres"))

    wallets = conn.execute(
        "SELECT * FROM wallet WHERE agent_id=? AND active=1 ORDER BY id", (agent["id"],)
    ).fetchall()
    active_ops = {w["operator"] for w in wallets}
    dispo = [op for op in logic.OPERATEURS if op not in active_ops]
    conn.close()

    return render_template("parametres.html", agent=agent, wallets=wallets, dispo=dispo)


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
