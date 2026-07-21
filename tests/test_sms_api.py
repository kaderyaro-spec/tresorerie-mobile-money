"""Filtre du point d'entrée /api/sms : SEULS les vrais dépôts/retraits sont
retenus. Les autres messages du téléphone (perso, promos, codes, alertes) sont
ignorés et ne polluent plus l'écran « SMS à confirmer »."""
import db
from conftest import make_agent


def _set_token(agent_id, token):
    conn = db.get_db()
    conn.execute("UPDATE agent SET sms_token=? WHERE id=?", (token, agent_id))
    conn.commit()
    conn.close()


def _inbox_count(agent_id):
    conn = db.get_db()
    n = conn.execute("SELECT COUNT(*) AS c FROM sms_inbox WHERE agent_id=?",
                     (agent_id,)).fetchone()["c"]
    conn.close()
    return n


def test_message_non_transaction_est_ignore(client):
    make_agent(client, operators="Orange Money")
    _set_token(1, "tok-1")
    r = client.post("/api/sms?token=tok-1",
                    data={"body": "Rejoignez notre offre du jour et gagnez des cadeaux !",
                          "sender": "PROMO"})
    assert r.status_code == 200
    assert r.get_json().get("ignored") == "non_transaction"
    assert _inbox_count(1) == 0            # rien n'est stocké


def test_code_otp_est_ignore(client):
    make_agent(client, operators="Orange Money")
    _set_token(1, "tok-2")
    r = client.post("/api/sms?token=tok-2",
                    data={"body": "Votre code de verification est 483920.", "sender": "Google"})
    assert r.get_json().get("ignored") == "non_transaction"
    assert _inbox_count(1) == 0


ORANGE_DEPOT = ("Le depot vers le 0700000000 est reussi. Montant 1200.00 F, "
                "ID Transaction: CI260705.1634.A79483, Nouveau Solde 20015.00 F.")
MTN_DEPOT = ("Vous avez envoye 2100 FCFA au 2250000000000 le 06-07-2026 21:22:44. "
             "Votre nouveau solde est de: 631718 FCFA. ID Transaction: 17216026013.")


def _tx_count(agent_id=None):
    conn = db.get_db()
    if agent_id:
        n = conn.execute('SELECT COUNT(*) AS c FROM "transaction" WHERE agent_id=?',
                         (agent_id,)).fetchone()["c"]
    else:
        n = conn.execute('SELECT COUNT(*) AS c FROM "transaction"').fetchone()["c"]
    conn.close()
    return n


def test_meme_reference_chez_deux_agents_cree_deux_transactions(client):
    """Anti-doublon PAR AGENT : la même réf. chez 2 agents = 2 transactions,
    l'une n'absorbe jamais l'autre."""
    make_agent(client, phone="0700000001", operators="Orange Money")
    client.post("/logout")
    make_agent(client, phone="0700000002", operators="Orange Money")
    _set_token(1, "tok-a1")
    _set_token(2, "tok-a2")

    r1 = client.post("/api/sms?token=tok-a1", data={"body": ORANGE_DEPOT, "sender": "+454"})
    r2 = client.post("/api/sms?token=tok-a2", data={"body": ORANGE_DEPOT, "sender": "+454"})
    assert r1.get_json()["auto"] is True
    assert r2.get_json()["auto"] is True          # PAS absorbé par l'agent 1
    assert _tx_count(1) == 1 and _tx_count(2) == 1


def test_meme_reference_deux_fois_chez_le_meme_agent_une_seule_transaction(client):
    """Le même SMS renvoyé 2 fois par le même téléphone -> 1 seule transaction."""
    make_agent(client, operators="Orange Money")
    _set_token(1, "tok-b")
    client.post("/api/sms?token=tok-b", data={"body": ORANGE_DEPOT, "sender": "+454"})
    client.post("/api/sms?token=tok-b", data={"body": ORANGE_DEPOT, "sender": "+454"})
    assert _tx_count(1) == 1


def test_conflit_double_sim_force_la_confirmation(client):
    """SMS MTN reçu sur un appareil rattaché au sous-compte Orange -> PAS
    d'auto-création (garde-fou double SIM), mise en attente de confirmation."""
    make_agent(client, operators=["Orange Money", "MTN"])
    conn = db.get_db()
    orange_id = conn.execute(
        "SELECT id FROM wallet WHERE agent_id=1 AND operator='Orange Money'").fetchone()["id"]
    conn.close()
    # appareil rattaché au sous-compte Orange
    client.post("/parametres", data={"action": "add_device", "device_name": "Tel Orange",
                                     "device_wallet_id": orange_id})
    conn = db.get_db()
    dev_token = conn.execute("SELECT token FROM sms_device WHERE agent_id=1").fetchone()["token"]
    conn.close()

    r = client.post(f"/api/sms?token={dev_token}",
                    data={"body": MTN_DEPOT, "sender": "MobileMoney"})
    assert r.status_code == 200
    assert r.get_json()["auto"] is False           # pas de création automatique
    assert _tx_count(1) == 0
    conn = db.get_db()
    row = conn.execute("SELECT status, parsed_operator FROM sms_inbox WHERE agent_id=1").fetchone()
    conn.close()
    assert row["status"] == "pending"              # l'agent confirmera
    assert row["parsed_operator"] == "MTN"         # le bon opérateur pré-sélectionné


def test_token_accepte_dans_l_en_tete_x_token(client):
    """Le jeton peut voyager dans l'en-tête X-Token (plus discret que l'URL)."""
    make_agent(client, operators="Orange Money")
    _set_token(1, "tok-h")
    r = client.post("/api/sms", data={"body": ORANGE_DEPOT, "sender": "+454"},
                    headers={"X-Token": "tok-h"})
    assert r.status_code == 200
    assert r.get_json()["auto"] is True


def test_vrai_depot_est_conserve(client):
    make_agent(client, operators="Orange Money")
    _set_token(1, "tok-3")
    r = client.post("/api/sms?token=tok-3",
                    data={"body": "Le depot vers le 0700000000 est reussi. Montant 1200.00 F, "
                                  "ID Transaction: CI260705.1634.A79483, Nouveau Solde 20015.00 F.",
                          "sender": "+454"})
    assert r.status_code == 200
    assert r.get_json().get("ignored") is None   # PAS ignoré : c'est une opération
    assert _inbox_count(1) == 1                   # une entrée créée (auto ou en attente)
