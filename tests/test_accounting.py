"""Comptabilité : fond de roulement, dettes, clôture, règlement."""
import db
from conftest import first_wallet_id


def _fdr(c):
    """Fond de roulement affiché sur le tableau de bord (texte)."""
    return c.get("/dashboard").get_data(as_text=True)


def test_deposit_is_net_zero_on_fdr(agent):
    """Un dépôt transfère UV -> caisse : le fond de roulement ne bouge pas."""
    assert "150 000" in _fdr(agent)
    wid = first_wallet_id()
    agent.post("/transaction", data={"type": "depot_client", "wallet_id": str(wid),
                                     "amount": "10000"})
    html = _fdr(agent)
    assert "90 000" in html      # Wave 100000 - 10000
    assert "60 000" in html      # caisse 50000 + 10000
    assert "150 000" in html     # FdR inchangé (commission NON incluse)


def test_expense_reduces_fdr(agent):
    agent.post("/transaction", data={"type": "depense", "amount": "2000"})
    assert "148 000" in _fdr(agent)


def test_debt_deducted_from_poste_and_fdr(agent):
    wid = first_wallet_id()
    agent.post("/dettes", data={"client_name": "M", "amount": "15000",
                                "op_type": "depot_client", "wallet_id": str(wid)})
    html = _fdr(agent)
    assert "85 000" in html      # Wave net
    assert "135 000" in html     # FdR net


def test_operator_debt_settlement_keeps_uv_down(agent):
    """Après règlement d'une dette opérateur : l'UV reste diminué, la caisse monte."""
    wid = first_wallet_id()
    agent.post("/dettes", data={"client_name": "M", "amount": "15000",
                                "op_type": "depot_client", "wallet_id": str(wid)})
    conn = db.get_db()
    did = conn.execute("SELECT id FROM dette WHERE agent_id=1").fetchone()["id"]
    conn.close()
    agent.post(f"/dettes/{did}/regler")
    html = _fdr(agent)
    assert "85 000" in html          # Wave RESTE à 85 000 (ne remonte pas)
    assert "65 000" in html          # caisse 50000 + 15000
    assert "150 000" in html         # FdR revenu à l'équilibre
    assert "100 000" not in html     # Wave n'est PAS remonté


def test_caisse_debt_settlement_returns_cash(agent):
    agent.post("/dettes", data={"client_name": "A", "amount": "8000",
                                "op_type": "retrait_caisse"})
    assert "42 000" in _fdr(agent)   # caisse nette
    conn = db.get_db()
    did = conn.execute("SELECT id FROM dette WHERE agent_id=1").fetchone()["id"]
    conn.close()
    agent.post(f"/dettes/{did}/regler")
    html = _fdr(agent)
    assert "50 000" in html          # caisse revenue à 50 000
    assert "58 000" not in html      # pas de double comptage


def test_cloture_shows_debt_as_negative_ecart(agent):
    wid = first_wallet_id()
    agent.post("/dettes", data={"client_name": "C", "amount": "5000",
                                "op_type": "depot_client", "wallet_id": str(wid)})
    agent.post("/cloture", data={})
    conn = db.get_db()
    row = conn.execute("SELECT COALESCE(SUM(ecart),0) AS e, COALESCE(SUM(dette),0) AS d "
                       "FROM cloture_line").fetchone()
    conn.close()
    assert abs(row["e"] + 5000) < 1      # écart = -5000
    assert abs(row["d"] - 5000) < 1      # dette imputée = 5000


def test_no_duplicate_cloture_same_date(agent):
    """Le garde-fou empêche 2 clôtures pour la MÊME date (la clôture avance sinon
    la journée : un 2e appel normal clôture le jour suivant, ce qui est correct)."""
    conn = db.get_db()
    day = conn.execute("SELECT business_day FROM agent WHERE id=1").fetchone()["business_day"]
    conn.close()
    agent.post("/cloture", data={})
    # On ramène la journée à la date déjà clôturée (simule un double envoi).
    conn = db.get_db()
    conn.execute("UPDATE agent SET business_day=? WHERE id=1", (day,))
    conn.commit()
    conn.close()
    agent.post("/cloture", data={})
    conn = db.get_db()
    n = conn.execute("SELECT COUNT(*) AS n FROM cloture WHERE agent_id=1 AND date=?",
                     (day,)).fetchone()["n"]
    conn.close()
    assert n == 1


def test_orange_commission_grid(client):
    """Cumul Orange Money 100 000-199 999 -> palier RÉEL 837 F (grille journalière)."""
    from conftest import make_agent, first_wallet_id
    make_agent(client, operators="Orange Money", solde="500000", cash="50000")
    wid = first_wallet_id()
    client.post("/transaction", data={"type": "depot_client", "wallet_id": str(wid),
                                      "amount": "150000"})
    client.post("/cloture", data={})
    conn = db.get_db()
    comm = conn.execute("SELECT COALESCE(SUM(commission),0) AS c "
                        "FROM cloture_line").fetchone()["c"]
    conn.close()
    assert abs(comm - 837) < 1


def test_wave_commission_grid(agent):
    """Cumul Wave 10 000-99 995 -> palier 275 F (grille journalière)."""
    wid = first_wallet_id()
    agent.post("/transaction", data={"type": "depot_client", "wallet_id": str(wid),
                                     "amount": "20000"})
    agent.post("/cloture", data={})
    conn = db.get_db()
    comm = conn.execute("SELECT COALESCE(SUM(commission),0) AS c "
                        "FROM cloture_line").fetchone()["c"]
    conn.close()
    assert abs(comm - 275) < 1
