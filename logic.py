"""
Cœur métier — Règles de calcul (cahier des charges, section 6).

Toute la logique de trésorerie est centralisée ici. Les soldes ne sont jamais
stockés comme source de vérité : ils sont TOUJOURS recalculés à partir des
transactions (cahier des charges, section 5).
"""

# ---------------------------------------------------------------------------
# Types d'opérations et leurs effets sur le float (solde électronique) et le
# cash (espèces). Source : section 6 du cahier des charges.
#
#   float / cash : multiplicateur appliqué au montant (+1, -1, 0)
#   wallet       : l'opération concerne-t-elle un portefeuille opérateur ?
#   commission   : l'opération compte-t-elle dans le cumul des commissions ?
#                  (les réappros et dépenses sont exclus pour ne pas fausser
#                   le calcul — section 4.4)
# ---------------------------------------------------------------------------
TX_TYPES = {
    "depot_client": {
        "label": "Dépôt client",
        "float": -1, "cash": +1,
        "wallet": True, "commission": True,
    },
    "retrait_client": {
        "label": "Retrait client",
        "float": +1, "cash": -1,
        "wallet": True, "commission": True,
    },
    "achat_float": {
        "label": "Achat d'UV",
        "float": +1, "cash": -1,
        "wallet": True, "commission": False,
    },
    "depense": {
        "label": "Dépense",
        "float": 0, "cash": -1,
        "wallet": False, "commission": False,
    },
    "depot_caisse": {
        "label": "Dépôt d'espèces en caisse",
        "float": 0, "cash": +1,
        "wallet": False, "commission": False,
    },
    "retrait_caisse": {
        "label": "Retrait d'espèces de la caisse",
        "float": 0, "cash": -1,
        "wallet": False, "commission": False,
    },
}

# Opérations considérées comme « réapprovisionnement » (écran 4.4)
REAPPRO_TYPES = {"achat_float", "depot_caisse", "retrait_caisse"}

# Opérateurs Mobile Money (portefeuilles de float principaux)
MONEY_OPERATORS = ["Orange Money", "Moov Money", "Wave", "MTN"]
# Services complémentaires proposés séparément
SERVICES = ["Crédit", "Factures"]
# Liste complète (utilisée par ex. dans les paramètres)
OPERATEURS = MONEY_OPERATORS + SERVICES


def float_effect(tx_type: str, amount: float) -> float:
    """Effet d'une transaction sur le float d'un portefeuille."""
    return amount * TX_TYPES[tx_type]["float"]


def cash_effect(tx_type: str, amount: float) -> float:
    """Effet d'une transaction sur la caisse (espèces)."""
    return amount * TX_TYPES[tx_type]["cash"]


def wallet_balance(opening_balance: float, transactions) -> float:
    """
    Solde courant d'un portefeuille
    = solde d'ouverture + somme des effets float des transactions du jour.
    `transactions` : itérable de dicts {type, amount} déjà filtrés sur ce
    portefeuille et la journée courante.
    """
    total = opening_balance
    for tx in transactions:
        total += float_effect(tx["type"], tx["amount"])
    return total


def cash_balance(opening_balance: float, transactions) -> float:
    """
    Solde courant de la caisse
    = solde d'ouverture + somme des effets cash de TOUTES les transactions
    du jour (clients, réappros, dépenses confondus).
    """
    total = opening_balance
    for tx in transactions:
        total += cash_effect(tx["type"], tx["amount"])
    return total


def consolidated_total(cash: float, wallet_balances) -> float:
    """Patrimoine consolidé = solde caisse + somme des soldes float."""
    return cash + sum(wallet_balances)


def commissions_total(transactions) -> float:
    """Cumul des commissions des transactions clients fournies."""
    total = 0.0
    for tx in transactions:
        if TX_TYPES.get(tx["type"], {}).get("commission"):
            total += tx.get("commission") or 0.0
    return total


def voyant(current: float, threshold: float) -> str:
    """
    Couleur du voyant d'un portefeuille selon le seuil d'alerte (section 4.2) :
      - rouge  : solde sous le seuil
      - orange : solde proche du seuil (jusqu'à +20 %)
      - vert   : sinon
    """
    if threshold is None or threshold <= 0:
        return "vert"
    if current < threshold:
        return "rouge"
    if current < threshold * 1.2:
        return "orange"
    return "vert"


def ecart(reel: float, theorique: float) -> float:
    """Écart de clôture (par ligne) = solde réel saisi − solde théorique."""
    return reel - theorique


# ---------------------------------------------------------------------------
# Grille de commission journalière Wave (Côte d'Ivoire).
# La commission est déterminée par PALIER, en fonction du CUMUL des
# transactions clients (dépôts + retraits) de la journée pour le portefeuille
# Wave. Chaque tuple = (palier_inférieur, palier_supérieur, commission_jour).
# Le dernier palier (palier_supérieur = None) signifie « illimité ».
# ---------------------------------------------------------------------------
WAVE_COMMISSION_GRID = [
    (1,           9_995,        50),
    (10_000,      99_995,       275),
    (100_000,     174_995,      600),
    (175_000,     249_995,      950),
    (250_000,     599_995,      1_425),
    (600_000,     999_995,      2_150),
    (1_000_000,   1_499_995,    3_000),
    (1_500_000,   1_999_995,    3_600),
    (2_000_000,   2_499_995,    4_150),
    (2_500_000,   2_999_995,    4_700),
    (3_000_000,   3_499_995,    5_250),
    (3_500_000,   3_999_995,    5_800),
    (4_000_000,   4_499_995,    6_350),
    (4_500_000,   4_999_995,    6_925),
    (5_000_000,   5_499_995,    7_500),
    (5_500_000,   5_999_995,    8_075),
    (6_000_000,   6_499_995,    8_650),
    (6_500_000,   6_999_995,    9_225),
    (7_000_000,   7_499_995,    9_800),
    (7_500_000,   7_999_995,    10_375),
    (8_000_000,   8_999_995,    11_050),
    (9_000_000,   9_999_995,    12_300),
    (10_000_000,  12_499_995,   16_050),
    (12_500_000,  14_999_995,   19_800),
    (15_000_000,  17_499_995,   23_550),
    (17_500_000,  19_999_995,   27_300),
    (20_000_000,  24_999_995,   32_300),
    (25_000_000,  29_999_995,   42_300),
    (30_000_000,  None,         52_000),  # 30 000 000F et plus (illimité)
]


def wave_daily_commission(volume: float) -> float:
    """
    Commission journalière Wave selon le cumul (dépôts + retraits clients) du
    jour. Renvoie 0 si aucun mouvement Wave.
    """
    if volume <= 0:
        return 0
    for low, high, comm in WAVE_COMMISSION_GRID:
        if high is None or volume <= high:
            return comm
    return 0


def wave_volume(transactions) -> float:
    """
    Cumul des montants de transactions clients (dépôts + retraits) servant de
    base à la grille Wave. `transactions` : opérations déjà filtrées sur le
    portefeuille Wave et la journée.
    """
    total = 0.0
    for tx in transactions:
        if tx["type"] in ("depot_client", "retrait_client"):
            total += tx["amount"]
    return total


# ---------------------------------------------------------------------------
# Grilles de commissions par opérateur.
# Wave est automatisé ; les autres opérateurs s'ajoutent ici dès que leur
# grille officielle est fournie (même format : palier bas, palier haut, F/jour).
# ---------------------------------------------------------------------------
COMMISSION_GRIDS = {
    "Wave": WAVE_COMMISSION_GRID,
}


# ---------------------------------------------------------------------------
# Analyse d'un SMS d'opérateur (lecture auto via app de transfert SMS).
# Heuristique : on extrait le montant, l'opérateur et le sens (dépôt/retrait).
# Tout reste MODIFIABLE par l'agent avant confirmation ; le but est de
# pré-remplir pour gagner du temps, pas de deviner parfaitement.
# ---------------------------------------------------------------------------
# Mots-clés (sur l'expéditeur surtout) pour reconnaître l'opérateur
_OP_KEYWORDS = {
    "Orange Money": ["orange"],
    "Moov Money": ["moov", "flooz"],
    "Wave": ["wave"],
    "MTN": ["mtn", "momo"],
    "Crédit": ["credit", "crédit"],
    "Factures": ["facture"],
}


def _sms_amount(token):
    """Convertit « 300000.00 », « 30 000 », « 10300.00 » → entier en F."""
    import re
    s = str(token).replace(" ", "")
    s = re.sub(r"[.,]\d{1,2}$", "", s)        # retire la décimale finale (.00 / ,00)
    s = s.replace(".", "").replace(",", "")   # retire les séparateurs de milliers
    return float(s) if s.isdigit() and s else None


def parse_sms(body, sender="", known_operators=None):
    """
    Analyse un SMS d'opérateur (calé sur de vrais SMS Orange/MTN Côte d'Ivoire).
    Renvoie {operator, type, amount} — chaque champ pouvant être None.
    Reste indicatif : l'agent confirme/corrige toujours avant enregistrement.
    """
    import re
    text = (body or "").lower()
    hay = (str(sender) + " " + text).lower()

    # Un montant = soit des groupes de milliers (« 465.425 », « 1 796 610 »),
    # soit des chiffres simples avec décimale éventuelle (« 300000.00 », « 30000 »).
    # Ce format strict évite de fusionner un numéro de téléphone avec le montant.
    NUM = r"(?:\d{1,3}(?:[ .]\d{3})+|\d+)(?:[.,]\d{1,2})?"
    AMT = r"(" + NUM + r")\s*(?:fcfa|f\.?\s*cfa|cfa|francs?|f)\b"

    # 1) Montant prioritaire : celui qui suit le mot « Montant » (= la transaction)
    amount = None
    m = re.search(r"montant\s*:?\s*(" + NUM + r")", text)
    if m:
        amount = _sms_amount(m.group(1))

    # 2) Sinon : 1er montant suivi de FCFA/F qui n'est PAS un solde/frais/commission
    if amount is None:
        for mm in re.finditer(AMT, text):
            before = text[max(0, mm.start() - 22):mm.start()]
            if any(k in before for k in ("solde", "frais", "commission")):
                continue
            amount = _sms_amount(mm.group(1))
            if amount:
                break

    # Opérateur : d'abord via l'expéditeur, puis le corps
    operator = None
    for op in (known_operators or []):
        for kw in _OP_KEYWORDS.get(op, [op.split()[0].lower()]):
            if kw and kw in hay:
                operator = op
                break
        if operator:
            break

    # Sens de l'opération (pour un AGENT : « envoyé/dépôt » = dépôt client ;
    # « retrait » = retrait client)
    typ = None
    if any(k in text for k in ("retrait", "retire", "retiré")):
        typ = "retrait_client"
    elif any(k in text for k in ("depot", "dépôt", "depose", "déposé",
                                 "envoye", "envoyé", "envoi")):
        typ = "depot_client"

    # Référence unique de l'opérateur (anti-doublon en création automatique)
    ref = None
    mr = re.search(r"id\s*(?:de\s*)?transaction\s*:?\s*([a-z0-9.\-]{4,})", text)
    if mr:
        ref = mr.group(1).strip(".").upper()

    return {"operator": operator, "type": typ, "amount": amount, "ref": ref}


def daily_commission(operator: str, volume: float):
    """
    Commission journalière de l'opérateur selon sa grille (cumul du jour).
    Renvoie None si l'opérateur n'a pas de grille connue (saisie manuelle).
    """
    grid = COMMISSION_GRIDS.get(operator)
    if grid is None:
        return None
    if volume <= 0:
        return 0
    for low, high, comm in grid:
        if high is None or volume <= high:
            return comm
    return 0


# ---------------------------------------------------------------------------
# Prévision de rupture d'UV.
# Idée : au rythme de consommation observé depuis la première opération du
# jour, à quelle heure le solde UV sera-t-il épuisé ? Si c'est avant la fin
# de la journée de travail, on prévient et on suggère un montant de réappro.
# ---------------------------------------------------------------------------
END_OF_DAY_HOUR = 21          # fin de journée type d'un point marchand
MIN_ACTIVE_HOURS = 0.5        # éviter les divisions par des durées minuscules


def predict_depletion(balance: float, transactions, now=None):
    """
    Prédit l'épuisement de l'UV d'un portefeuille.
    `transactions` : opérations du jour de CE portefeuille (type, amount,
    created_at au format YYYY-MM-DD HH:MM:SS).
    Renvoie None (pas de risque avant la fin de journée) ou un dict :
      {"eta": "15h30", "suggestion": 80000}
    """
    import math
    from datetime import datetime, timedelta

    now = now or datetime.now()
    if balance <= 0:
        return None

    # Consommation d'UV du jour = opérations qui font baisser le solde UV
    sorties = [t for t in transactions
               if TX_TYPES.get(t["type"], {}).get("float", 0) < 0]
    conso = sum(t["amount"] for t in sorties)
    if conso <= 0:
        return None

    try:
        t0 = min(datetime.strptime(t["created_at"], "%Y-%m-%d %H:%M:%S")
                 for t in sorties)
    except (ValueError, TypeError):
        return None

    hours_active = max((now - t0).total_seconds() / 3600.0, MIN_ACTIVE_HOURS)
    rate = conso / hours_active                   # F consommés par heure
    if rate <= 0:
        return None

    eta = now + timedelta(hours=balance / rate)
    end_of_day = now.replace(hour=END_OF_DAY_HOUR, minute=0, second=0,
                             microsecond=0)
    if eta >= end_of_day:
        return None                                # pas de rupture avant ce soir

    # Suggestion : couvrir la consommation projetée jusqu'à la fin de journée,
    # arrondie aux 5 000 F supérieurs.
    remaining_hours = max((end_of_day - now).total_seconds() / 3600.0, 0)
    needed = rate * remaining_hours - balance
    if needed <= 0:
        return None
    suggestion = int(math.ceil(needed / 5000.0) * 5000)

    return {"eta": eta.strftime("%Hh%M"), "suggestion": suggestion}
