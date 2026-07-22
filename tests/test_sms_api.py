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


def test_limite_de_debit_renvoie_429(client, monkeypatch):
    """Au-delà de la limite par minute, le serveur répond 429 (l'app Android
    réessaie plus tard : le SMS n'est pas perdu)."""
    import app as appmod
    monkeypatch.setattr(appmod, "SMS_RATE_LIMIT", 3)
    make_agent(client, operators="Orange Money")
    _set_token(1, "tok-rate")
    for _ in range(3):
        r = client.post("/api/sms?token=tok-rate",
                        data={"body": "promo sans interet", "sender": "PUB"})
        assert r.status_code == 200
    r = client.post("/api/sms?token=tok-rate",
                    data={"body": "promo sans interet", "sender": "PUB"})
    assert r.status_code == 429
    assert r.get_json()["error"] == "trop_de_requetes"


def test_purge_des_sms_rejetes_apres_30_jours(client):
    """Les SMS ignorés ne restent pas indéfiniment en base (confidentialité)."""
    make_agent(client, operators="Orange Money")
    conn = db.get_db()
    conn.execute("INSERT INTO sms_inbox (agent_id,sender,body,received_at,status) "
                 "VALUES (1,'x','tres vieux','2026-01-01 10:00:00','rejected')")
    conn.execute("INSERT INTO sms_inbox (agent_id,sender,body,received_at,status) "
                 "VALUES (1,'x','recent',?,'rejected')", (db.now_str(),))
    conn.commit()
    conn.close()
    client.get("/sms")                              # la purge tourne à l'affichage
    conn = db.get_db()
    bodies = [r["body"] for r in conn.execute("SELECT body FROM sms_inbox").fetchall()]
    conn.close()
    assert "tres vieux" not in bodies
    assert "recent" in bodies                       # < 30 jours : conservé


def test_migration_purge_les_anciens_messages_non_transaction(client):
    """Nettoyage unique : les « en attente » illisibles stockés AVANT le filtre
    (messages perso, promos…) sont supprimés ; les vrais en-attente restent."""
    import app as appmod
    make_agent(client, operators="Orange Money")
    conn = db.get_db()
    conn.execute("INSERT INTO sms_inbox (agent_id,sender,body,received_at,status,"
                 "parsed_type,parsed_amount) VALUES (1,'promo','Gagnez un cadeau !',?,"
                 "'pending',NULL,NULL)", (db.now_str(),))
    conn.execute("INSERT INTO sms_inbox (agent_id,sender,body,received_at,status,"
                 "parsed_type,parsed_amount) VALUES (1,'MobileMoney','retrait 2000',?,"
                 "'pending','retrait_client',2000)", (db.now_str(),))
    conn.commit()
    conn.close()
    with appmod.app.app_context():
        db.init_db()                                # rejoue les migrations
    conn = db.get_db()
    bodies = [r["body"] for r in conn.execute(
        "SELECT body FROM sms_inbox WHERE status='pending'").fetchall()]
    conn.close()
    assert "Gagnez un cadeau !" not in bodies       # parasite purgé
    assert "retrait 2000" in bodies                 # vrai en-attente conservé


def _add_device_row(agent_id, token, wallet_id):
    conn = db.get_db()
    conn.execute("INSERT INTO sms_device (agent_id, name, token, wallet_id, created_at) "
                 "VALUES (?,?,?,?,?)", (agent_id, "Tel test", token, wallet_id, db.now_str()))
    conn.commit()
    conn.close()


def _wallet_id(operator, agent_id=1):
    conn = db.get_db()
    row = conn.execute("SELECT id FROM wallet WHERE agent_id=? AND operator=?",
                       (agent_id, operator)).fetchone()
    conn.close()
    return row["id"] if row else None


def test_rattachement_wave_ignore_l_operateur_du_sms_fait_foi(client):
    """BUG TESTEURS : appareil rattaché à Wave + SMS Orange -> l'opération
    partait sur WAVE. Désormais le rattachement Wave est ignoré : l'opération
    va sur ORANGE (l'opérateur lu dans le SMS fait foi)."""
    make_agent(client, operators=["Orange Money", "Wave"])
    _add_device_row(1, "tok-wave", _wallet_id("Wave"))

    r = client.post("/api/sms?token=tok-wave", data={"body": ORANGE_DEPOT, "sender": "+454"})
    assert r.get_json()["auto"] is True
    conn = db.get_db()
    tx = conn.execute('SELECT wallet_id FROM "transaction" WHERE agent_id=1').fetchone()
    conn.close()
    assert tx["wallet_id"] == _wallet_id("Orange Money")   # PAS le portefeuille Wave


def test_rattachement_wave_sans_operateur_reconnu_reste_en_attente(client):
    """Appareil rattaché à Wave + SMS dont l'opérateur n'est PAS reconnu :
    AUCUNE création automatique (avant : auto-créé sur Wave via l'empreinte)."""
    make_agent(client, operators=["Orange Money", "Wave"])
    _add_device_row(1, "tok-wave2", _wallet_id("Wave"))

    r = client.post("/api/sms?token=tok-wave2",
                    data={"body": "Retrait de 5000 F effectue avec succes.",
                          "sender": "12345"})     # expéditeur inconnu
    assert r.get_json()["auto"] is False
    assert _tx_count(1) == 0                       # rien d'auto-créé
    conn = db.get_db()
    row = conn.execute("SELECT status FROM sms_inbox WHERE agent_id=1").fetchone()
    conn.close()
    assert row["status"] == "pending"              # l'agent décidera


def test_creation_appareil_refuse_le_rattachement_wave(client):
    """L'écran Réglages ne peut plus créer d'appareil rattaché à Wave."""
    make_agent(client, operators=["Orange Money", "Wave"])
    client.post("/parametres", data={"action": "add_device", "device_name": "Tel X",
                                     "device_wallet_id": _wallet_id("Wave")})
    conn = db.get_db()
    dev = conn.execute("SELECT wallet_id FROM sms_device WHERE agent_id=1").fetchone()
    conn.close()
    assert dev["wallet_id"] is None                # créé en mode « Auto »


def test_migration_delie_les_appareils_rattaches_a_wave(client):
    """Les appareils déjà rattachés à Wave (bug testeurs) sont déliés."""
    import app as appmod
    make_agent(client, operators=["Orange Money", "Wave"])
    _add_device_row(1, "tok-old", _wallet_id("Wave"))
    with appmod.app.app_context():
        db.init_db()                               # rejoue les migrations
    conn = db.get_db()
    dev = conn.execute("SELECT wallet_id FROM sms_device WHERE token='tok-old'").fetchone()
    conn.close()
    assert dev["wallet_id"] is None


def test_rattachement_vers_sous_compte_supprime_route_par_le_sms(client):
    """Appareil rattaché à un sous-compte disparu : pas de plantage, on route
    par l'opérateur lu dans le SMS."""
    make_agent(client, operators="Orange Money")
    _add_device_row(1, "tok-ghost", 99999)         # portefeuille inexistant
    r = client.post("/api/sms?token=tok-ghost", data={"body": ORANGE_DEPOT, "sender": "+454"})
    assert r.get_json()["auto"] is True
    conn = db.get_db()
    tx = conn.execute('SELECT wallet_id FROM "transaction" WHERE agent_id=1').fetchone()
    conn.close()
    assert tx["wallet_id"] == _wallet_id("Orange Money")


RETRAIT_COLLE_ALERTE = ("Attention Vigilance Arnaque . Nouveau Solde 420806.00 F "
                        "a verifier au #145*61#  avant paiement.Retrait de 0708223099 "
                        "effectue. Montant 40000.00 F.ID Transaction: CO260722.1546.C94702.")


def test_bout_en_bout_retrait_reel_auto_cree_sur_orange(client):
    """Bout en bout, format terrain : le retrait collé à l'alerte crée la
    transaction AUTOMATIQUEMENT, sur Orange (même si l'agent a aussi Wave)."""
    make_agent(client, operators=["Orange Money", "Wave"])
    _set_token(1, "tok-e2e")
    r = client.post("/api/sms?token=tok-e2e",
                    data={"body": RETRAIT_COLLE_ALERTE, "sender": "+454"})
    assert r.get_json()["auto"] is True
    conn = db.get_db()
    tx = conn.execute('SELECT type, amount, wallet_id FROM "transaction" '
                      'WHERE agent_id=1').fetchone()
    conn.close()
    assert tx["type"] == "retrait_client"
    assert tx["amount"] == 40000
    assert tx["wallet_id"] == _wallet_id("Orange Money")   # PAS Wave


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
