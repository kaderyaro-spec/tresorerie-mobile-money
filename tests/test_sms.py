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


def test_orange_detecte_par_shortcode_454():
    """Le SMS ne contient pas le mot « Orange » ; l'expéditeur « +454 » suffit."""
    r = logic.parse_sms(
        "Le depot vers le 0700000000 est reussi. Montant 1200.00 F, "
        "Frais 0.00 F, Commission 0.00 F, ID Transaction: CI260705.1634.A79483, "
        "Nouveau Solde 20015.00 F.",
        sender="+454", known_operators=OPS)
    assert r["operator"] == "Orange Money"
    assert r["type"] == "depot_client"
    assert r["amount"] == 1200


def test_shortcode_ne_matche_pas_le_corps():
    """« 454 » présent dans le CORPS (pas l'expéditeur) ne doit PAS router Orange."""
    r = logic.parse_sms("Depot de 454000 F reussi.", sender="12345",
                        known_operators=["MTN", "Moov Money"])
    assert r["operator"] is None


def test_orange_alerte_non_transaction_ignoree():
    """Un message d'alerte (pas une opération) ne doit RIEN pré-remplir."""
    r = _parse("Attention Vigilance Arnaque . Nouveau Solde 135715.00 F "
               "a verifier au #145*61#  avant paiement.")
    assert r["type"] is None
    assert r["amount"] is None
    assert r["ref"] is None


# --- MTN (formats réels Côte d'Ivoire, expéditeur « MobileMoney ») ---

def _mtn(body):
    return logic.parse_sms(body, sender="MobileMoney", known_operators=OPS)


def test_mtn_depot():
    r = _mtn("Vous avez envoye 2100 FCFA au 2250000000000 le 06-07-2026 21:22:44. "
             "Votre nouveau solde est de: 631718 FCFA. ID Transaction: 17216026013.")
    assert r["operator"] == "MTN"            # expéditeur « MobileMoney » -> MTN
    assert r["type"] == "depot_client"
    assert r["amount"] == 2100               # pas le « nouveau solde » 631718
    assert r["ref"] == "17216026013"


def test_mtn_retrait():
    r = _mtn("Le retrait initie le 06-07-2026 13:00:35 a ete effectue. Vous pouvez "
             "payer le montant: 2000 FCFA en especes au 2250000000000. Votre nouveau "
             "solde est de: 525958 FCFA. Frais: 0 FCFA. ID Transaction: 17210241818.")
    assert r["operator"] == "MTN"
    assert r["type"] == "retrait_client"
    assert r["amount"] == 2000               # ni le solde, ni les frais
    assert r["ref"] == "17210241818"


def test_mtn_sans_id_reste_en_attente():
    """Un SMS MTN sans ID Transaction est lu mais SANS référence -> confirmation."""
    r = _mtn("Le retrait initie 2026-07-06 13:00:35 a ete effectue. Vous pouvez "
             "payer le montant: 2000 FCFA en especes au 2250000000000.")
    assert r["operator"] == "MTN" and r["type"] == "retrait_client"
    assert r["amount"] == 2000
    assert r["ref"] is None                  # pas d'auto-création sans référence
