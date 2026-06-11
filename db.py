"""
Couche d'accès aux données — SQLite (fonctionnement 100 % local, hors-ligne).

Modèle de données minimal (cahier des charges, section 5) :
  agent, wallet (portefeuille), caisse, transaction, cloture (+ lignes).

Principe clé : les soldes sont recalculés à partir des transactions ; les
colonnes opening_balance ne mémorisent que le point de départ de la JOURNÉE
courante (mis à jour à chaque clôture).
"""
import sqlite3
import os
from datetime import datetime

# Chemin de la base : surchargeable par la variable d'environnement DB_PATH
# (utile en hébergement cloud pour pointer vers un disque persistant).
DB_PATH = os.environ.get("DB_PATH") or os.path.join(os.path.dirname(__file__), "data.db")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def today_str():
    return datetime.now().strftime("%Y-%m-%d")


def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


SCHEMA = """
CREATE TABLE IF NOT EXISTS agent (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    phone               TEXT NOT NULL,
    nom                 TEXT,                   -- nom de famille
    prenom              TEXT,                   -- prénom
    cni                 TEXT,                   -- numéro de carte d'identité (CNI)
    shop_name           TEXT,                   -- nom de la boutique
    subscription_status TEXT NOT NULL DEFAULT 'Essai gratuit',
    business_day        TEXT NOT NULL,          -- journée comptable ouverte
    pin_hash            TEXT,                   -- code de connexion (haché)
    created_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS wallet (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id        INTEGER NOT NULL REFERENCES agent(id),
    operator        TEXT NOT NULL,
    opening_balance REAL NOT NULL DEFAULT 0,
    alert_threshold REAL NOT NULL DEFAULT 0,
    active          INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS caisse (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id        INTEGER NOT NULL REFERENCES agent(id),
    opening_balance REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS "transaction" (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id     INTEGER NOT NULL REFERENCES agent(id),
    business_day TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    type         TEXT NOT NULL,
    wallet_id    INTEGER REFERENCES wallet(id),   -- NULL pour les opérations cash seules
    amount       REAL NOT NULL,
    commission   REAL NOT NULL DEFAULT 0,
    deleted      INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS cloture (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id   INTEGER NOT NULL REFERENCES agent(id),
    date       TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cloture_line (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    cloture_id INTEGER NOT NULL REFERENCES cloture(id),
    label      TEXT NOT NULL,         -- nom opérateur ou « Caisse »
    kind       TEXT NOT NULL,         -- 'wallet' ou 'cash'
    ref_id     INTEGER,               -- id du wallet (NULL pour la caisse)
    theorique  REAL NOT NULL,
    reel       REAL NOT NULL,
    ecart      REAL NOT NULL,
    commission REAL NOT NULL DEFAULT 0  -- commissions du jour pour cet opérateur
);
"""


def _migrate(conn):
    """Migrations légères pour les bases déjà créées avant l'ajout de colonnes."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(cloture_line)").fetchall()}
    if "commission" not in cols:
        conn.execute("ALTER TABLE cloture_line ADD COLUMN commission REAL NOT NULL DEFAULT 0")
    acols = {r["name"] for r in conn.execute("PRAGMA table_info(agent)").fetchall()}
    if "pin_hash" not in acols:
        conn.execute("ALTER TABLE agent ADD COLUMN pin_hash TEXT")
    if "shop_name" not in acols:
        conn.execute("ALTER TABLE agent ADD COLUMN shop_name TEXT")
    for col in ("nom", "prenom", "cni"):
        if col not in acols:
            conn.execute(f"ALTER TABLE agent ADD COLUMN {col} TEXT")


def init_db():
    conn = get_db()
    conn.executescript(SCHEMA)
    _migrate(conn)
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Helpers de haut niveau
# ---------------------------------------------------------------------------

def get_agent():
    """Retourne l'agent unique du MVP (ou None s'il n'existe pas encore)."""
    conn = get_db()
    row = conn.execute("SELECT * FROM agent LIMIT 1").fetchone()
    conn.close()
    return row


def is_onboarded():
    return get_agent() is not None


def current_transactions(conn, agent_id, business_day):
    """Transactions non supprimées de la journée comptable courante."""
    return conn.execute(
        'SELECT * FROM "transaction" '
        "WHERE agent_id=? AND business_day=? AND deleted=0 "
        "ORDER BY created_at DESC",
        (agent_id, business_day),
    ).fetchall()
