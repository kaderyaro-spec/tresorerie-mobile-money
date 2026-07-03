"""Sécurité : anti-force-brute, annulation tracée, validations."""
import db
from conftest import make_agent, first_wallet_id


def test_login_lockout_after_5_failures(agent):
    fresh = agent.application.test_client()
    for _ in range(5):
        fresh.post("/login", data={"phone": "0700000001", "pin": "0000"})
    # 6e essai, même avec le BON PIN → bloqué
    html = fresh.post("/login", data={"phone": "0700000001", "pin": "1234"},
                      follow_redirects=True).get_data(as_text=True)
    assert "Trop d" in html and "essais" in html


def test_login_lockout_recorded_in_db(agent):
    fresh = agent.application.test_client()
    for _ in range(5):
        fresh.post("/login", data={"phone": "0700000001", "pin": "0000"})
    conn = db.get_db()
    row = conn.execute("SELECT fails, locked_until FROM throttle "
                       "WHERE k='login:0700000001'").fetchone()
    conn.close()
    assert row["fails"] >= 5 and row["locked_until"]


def test_phone_change_rejects_bad_format(agent):
    agent.post("/parametres", data={"action": "account", "shop_name": "X", "phone": "123"})
    conn = db.get_db()
    phone = conn.execute("SELECT phone FROM agent WHERE id=1").fetchone()["phone"]
    conn.close()
    assert phone == "0700000001"


def test_phone_change_rejects_duplicate(client):
    make_agent(client, phone="0700000001")
    c2 = client.application.test_client()
    make_agent(c2, phone="0700000002")
    # l'agent 1 tente de prendre le numéro de l'agent 2
    client.post("/parametres", data={"action": "account", "shop_name": "X",
                                     "phone": "0700000002"})
    conn = db.get_db()
    phone = conn.execute("SELECT phone FROM agent WHERE id=1").fetchone()["phone"]
    conn.close()
    assert phone == "0700000001"


def test_cancel_current_day_traced(agent):
    wid = first_wallet_id()
    agent.post("/transaction", data={"type": "depot_client", "wallet_id": str(wid),
                                     "amount": "10000"})
    conn = db.get_db()
    txid = conn.execute('SELECT id FROM "transaction" ORDER BY id DESC LIMIT 1').fetchone()["id"]
    conn.close()
    agent.post(f"/transaction/{txid}/delete")
    conn = db.get_db()
    row = conn.execute('SELECT deleted, deleted_at FROM "transaction" WHERE id=?',
                       (txid,)).fetchone()
    conn.close()
    assert row["deleted"] == 1 and row["deleted_at"]


def test_cancel_closed_day_blocked(agent):
    wid = first_wallet_id()
    agent.post("/transaction", data={"type": "depot_client", "wallet_id": str(wid),
                                     "amount": "5000"})
    conn = db.get_db()
    txid = conn.execute('SELECT id FROM "transaction" ORDER BY id DESC LIMIT 1').fetchone()["id"]
    conn.execute("UPDATE agent SET business_day='2099-01-01' WHERE id=1")
    conn.commit()
    conn.close()
    agent.post(f"/transaction/{txid}/delete")
    conn = db.get_db()
    deleted = conn.execute('SELECT deleted FROM "transaction" WHERE id=?',
                           (txid,)).fetchone()["deleted"]
    conn.close()
    assert deleted == 0        # opération d'une journée close : non annulable


def test_debt_rejects_foreign_wallet(agent):
    agent.post("/dettes", data={"client_name": "Z", "amount": "5000",
                                "op_type": "depot_client", "wallet_id": "9999"})
    conn = db.get_db()
    n = conn.execute("SELECT COUNT(*) AS n FROM dette").fetchone()["n"]
    conn.close()
    assert n == 0


def test_unique_phone_constraint(agent):
    conn = db.get_db()
    blocked = False
    try:
        conn.execute("INSERT INTO agent (phone, business_day, created_at) "
                     "VALUES ('0700000001', '2026-01-01', 'x')")
        conn.commit()
    except Exception:
        blocked = True
    conn.close()
    assert blocked


def test_session_cookie_hardening():
    from conftest import appmod
    assert appmod.app.config["SESSION_COOKIE_HTTPONLY"] is True
    assert appmod.app.config["SESSION_COOKIE_SAMESITE"] == "Lax"
