"""Inscription et connexion."""
import db
from conftest import make_agent, otp_code


def test_signup_creates_account_at_pin_step(client):
    """Le compte doit exister dès la validation du PIN (avant opérateurs/services)."""
    client.post("/signup", data={"nom": "A", "prenom": "B", "cni": "1",
                                 "phone": "0700000001", "accept": "1"})
    client.post("/inscription/verification", data={"code": otp_code(client)})
    client.post("/inscription/pin", data={"pin": "1234", "pin2": "1234"})
    conn = db.get_db()
    n = conn.execute("SELECT COUNT(*) AS n FROM agent").fetchone()["n"]
    conn.close()
    assert n == 1


def test_login_after_pin_only(client):
    """Numéro + PIN suffisent pour se connecter, même sans finir l'inscription."""
    client.post("/signup", data={"nom": "A", "prenom": "B", "cni": "1",
                                 "phone": "0700000001", "accept": "1"})
    client.post("/inscription/verification", data={"code": otp_code(client)})
    client.post("/inscription/pin", data={"pin": "1234", "pin2": "1234"})
    fresh = client.application.test_client()
    r = fresh.post("/login", data={"phone": "0700000001", "pin": "1234"})
    assert r.status_code == 302 and r.headers["Location"].endswith("/dashboard")


def test_login_wrong_pin_rejected(agent):
    fresh = agent.application.test_client()
    r = fresh.post("/login", data={"phone": "0700000001", "pin": "9999"},
                   follow_redirects=True)
    assert "incorrect" in r.get_data(as_text=True).lower()


def test_full_onboarding_creates_wallet_and_caisse(agent):
    conn = db.get_db()
    nw = conn.execute("SELECT COUNT(*) AS n FROM wallet WHERE agent_id=1").fetchone()["n"]
    nc = conn.execute("SELECT COUNT(*) AS n FROM caisse WHERE agent_id=1").fetchone()["n"]
    conn.close()
    assert nw == 1 and nc == 1


def test_phone_with_spaces_is_normalised(client):
    make_agent(client, phone="07 00 00 00 05")
    conn = db.get_db()
    phone = conn.execute("SELECT phone FROM agent").fetchone()["phone"]
    conn.close()
    assert phone == "0700000005"
