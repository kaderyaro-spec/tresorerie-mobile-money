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

# Liste des opérateurs proposés à l'onboarding (section 4.1)
OPERATEURS = ["Orange Money", "Moov Money", "Wave", "MTN", "Crédit", "Factures"]


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
