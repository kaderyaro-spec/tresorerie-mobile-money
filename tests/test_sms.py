"""Lecture automatique des SMS — calée sur de VRAIS messages d'opérateurs.
Les numéros de clients sont anonymisés ; montants, mots-clés et références réels."""
import logic

OPS = ["Orange Money", "MTN", "Moov Money", "Wave"]


def _parse(body, sender="OrangeMoney"):
    return logic.parse_sms(body, sender=sender, known_operators=OPS)


# --- Orange Money (formats réels Côte d'Ivoire) ---

def test_orange_depot():
    r = _parse("Le depot vers le 0700000000 est reussi. Montant 1200.00 F, "
               "Frais 0.00 F, Commission 0.00 F, ID Transaction: CI260705.1634.A79483, "
               "Nouveau Solde 20015.00 F.")
    assert r["operator"] == "Orange Money"
    assert r["type"] == "depot_client"
    assert r["amount"] == 1200            # le "Montant", pas le "Nouveau Solde"
    assert r["ref"] == "CI260705.1634.A79483"


def test_orange_retrait():
    r = _parse("Retrait de 0700000000 effectue. Montant 50000.00 F."
               "ID Transaction: CO260704.2105.D71855.")
    assert r["operator"] == "Orange Money"
    assert r["type"] == "retrait_client"
    assert r["amount"] == 50000
    assert r["ref"] == "CO260704.2105.D71855"


def test_orange_alerte_non_transaction_ignoree():
    """Un message d'alerte (pas une opération) ne doit RIEN pré-remplir."""
    r = _parse("Attention Vigilance Arnaque . Nouveau Solde 135715.00 F "
               "a verifier au #145*61#  avant paiement.")
    assert r["type"] is None
    assert r["amount"] is None
    assert r["ref"] is None
