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
