"""Panneau gérant : suivi des abonnements et blocage doux des expirés."""
import datetime

import db
from conftest import admin_client, ADMIN_KEY


def _set_until(agent_id, value):
    conn = db.get_db()
    conn.execute("UPDATE agent SET subscription_until=? WHERE id=?", (value, agent_id))
    conn.commit()
    conn.close()


def test_admin_requires_key(client):
    r = client.get("/admin")
    assert r.status_code == 302 and "/admin/connexion" in r.headers["Location"]


def test_admin_wrong_key_rejected(agent):
    c = agent.application.test_client()
    c.post("/admin/connexion", data={"key": "mauvaise"})
    assert c.get("/admin").status_code == 302


def test_admin_extend_subscription(agent):
    adm = admin_client()
    adm.post("/admin/abonnement", data={"agent_id": "1", "action": "plus_mois"})
    conn = db.get_db()
    until = conn.execute("SELECT subscription_until FROM agent WHERE id=1").fetchone()["subscription_until"]
    conn.close()
    assert until and until > db.today_str()


def test_admin_invalid_date_ignored(agent):
    adm = admin_client()
    adm.post("/admin/abonnement", data={"agent_id": "1", "action": "date",
                                        "date": "pas-une-date"})
    conn = db.get_db()
    until = conn.execute("SELECT subscription_until FROM agent WHERE id=1").fetchone()["subscription_until"]
    conn.close()
    assert until is None


def test_expired_blocks_premium_but_keeps_core(agent):
    past = (datetime.date.today() - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    _set_until(1, past)
    # Fonctions premium coupées
    for path in ("/cloture", "/historique", "/journal"):
        html = agent.get(path, follow_redirects=True).get_data(as_text=True)
        assert "suspendue" in html, path
    # Fonctions de base toujours accessibles
    for path in ("/dashboard", "/transaction", "/reappro", "/dettes"):
        html = agent.get(path, follow_redirects=True).get_data(as_text=True)
        assert "suspendue" not in html, path


def test_expired_cloture_post_blocked(agent):
    past = (datetime.date.today() - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    _set_until(1, past)
    agent.post("/cloture", data={}, follow_redirects=True)
    conn = db.get_db()
    n = conn.execute("SELECT COUNT(*) AS n FROM cloture WHERE agent_id=1").fetchone()["n"]
    conn.close()
    assert n == 0        # aucune clôture forcée malgré le POST


def test_admin_delete_cascade(agent):
    from conftest import first_wallet_id
    wid = first_wallet_id()
    agent.post("/transaction", data={"type": "depot_client", "wallet_id": str(wid),
                                     "amount": "10000"})
    adm = admin_client()
    adm.post("/admin/supprimer", data={"agent_id": "1"})
    conn = db.get_db()
    n_agent = conn.execute("SELECT COUNT(*) AS n FROM agent WHERE id=1").fetchone()["n"]
    counts = {t: conn.execute(f'SELECT COUNT(*) AS n FROM {t} WHERE agent_id=1').fetchone()["n"]
              for t in ('wallet', 'caisse', '"transaction"')}
    conn.close()
    assert n_agent == 0 and all(v == 0 for v in counts.values())
