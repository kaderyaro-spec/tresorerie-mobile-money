"""Fixtures partagées pour la suite de tests.

Chaque test tourne sur une base SQLite **neuve et isolée** (fichier temporaire),
en mode démo (pas de vrai SMS, pas de PostgreSQL).
"""
import os
import re
import tempfile

import pytest

# IMPORTANT : configurer l'environnement AVANT d'importer l'application, car
# db.DB_PATH et app.ADMIN_KEY sont lus au moment de l'import.
os.environ.pop("DATABASE_URL", None)                 # force SQLite
os.environ["DB_PATH"] = os.path.join(tempfile.gettempdir(), "tresorerie_test_import.db")
os.environ.setdefault("ADMIN_KEY", "cle-admin-test")

import db                      # noqa: E402
import app as appmod           # noqa: E402

ADMIN_KEY = "cle-admin-test"


@pytest.fixture
def client(tmp_path):
    """Client de test avec une base SQLite vierge propre à ce test."""
    db.USE_PG = False
    db.DB_PATH = str(tmp_path / "test.db")
    with appmod.app.app_context():
        db.init_db()
    appmod.app.config["TESTING"] = True
    return appmod.app.test_client()


def otp_code(c):
    """Récupère le code OTP affiché en mode démo sur l'écran de vérification."""
    html = c.get("/inscription/verification").get_data(as_text=True)
    return re.search(r'otp-demo-code">(\d{6})', html).group(1)


def make_agent(c, phone="0700000001", pin="1234", operators="Wave",
               solde="100000", seuil="0", cash="50000"):
    """Déroule l'inscription complète d'un agent et le laisse connecté."""
    c.post("/signup", data={"nom": "Test", "prenom": "Agent", "cni": "CI001234",
                            "phone": phone, "accept": "1"})
    c.post("/inscription/verification", data={"code": otp_code(c)})
    c.post("/inscription/pin", data={"pin": pin, "pin2": pin})
    data = {"operators": operators, "cash_initial": cash}
    for op in ([operators] if isinstance(operators, str) else operators):
        data[f"solde_{op}"] = solde
        data[f"seuil_{op}"] = seuil
    c.post("/inscription/operateurs", data=data)
    c.post("/inscription/services", data={})


def first_wallet_id(agent_id=1):
    conn = db.get_db()
    row = conn.execute("SELECT id FROM wallet WHERE agent_id=? ORDER BY id LIMIT 1",
                       (agent_id,)).fetchone()
    conn.close()
    return row["id"]


def admin_client():
    """Client authentifié sur le panneau gérant."""
    c = appmod.app.test_client()
    c.post("/admin/connexion", data={"key": ADMIN_KEY})
    return c


@pytest.fixture
def agent(client):
    """Un agent complet (Wave 100 000, caisse 50 000, PIN 1234), connecté."""
    make_agent(client)
    return client
