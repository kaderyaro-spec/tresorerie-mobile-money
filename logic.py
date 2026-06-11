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
