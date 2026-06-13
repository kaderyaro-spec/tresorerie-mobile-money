"""
Couche d'accès aux données — compatible SQLite (local) et PostgreSQL (en ligne).

- En local : SQLite (fichier data.db), aucun réglage nécessaire.
- En ligne : si la variable d'environnement DATABASE_URL est définie (ex. Supabase),
  l'application utilise PostgreSQL → les données sont conservées durablement.

Le reste de l'application n'a pas à savoir quel moteur est utilisé : un petit
adaptateur traduit les requêtes (placeholders « ? », identifiant auto, etc.).

Modèle de données minimal (cahier des charges, section 5) :
  agent, wallet (portefeuille), caisse, transaction, cloture (+ lignes).
"""
import sqlite3
import os
from datetime import datetime

DATABASE_URL = os.environ.get("DATABASE_URL")  # défini = PostgreSQL ; sinon SQLite
USE_PG = bool(DATABASE_URL)

DB_PATH = os.environ.get("DB_PATH") or os.path.join(os.path.dirname(__file__), "data.db")

if USE_PG:
    import psycopg
    from psycopg.rows import dict_row


class _Cursor:
    """Uniformise l'accès au résultat (fetchone/fetchall/lastrowid)."""
    def __init__(self, cur, lastrowid=None):
        self._cur = cur
        self.lastrowid = lastrowid

    def fetchone(self):
        return self._cur.fetchone()

    def fetchall(self):
        return self._cur.fetchall()


class _Conn:
    """
    Adaptateur de connexion. Expose l'API utilisée par l'application
    (execute / executescript / commit / close) quel que soit le moteur.
    """
    def __init__(self, raw, pg):
        self._raw = raw
        self.pg = pg

    def execute(self, sql, params=()):
        if self.pg:
            sql = sql.replace("?", "%s")
            head = sql.lstrip()[:6].upper()
            if head == "INSERT" and "RETURNING" not in sql.upper():
                sql = sql.rstrip().rstrip(";") + " RETURNING id"
                cur = self._raw.execute(sql, params)
                row = cur.fetchone()
                return _Cursor(cur, row["id"] if row else None)
            cur = self._raw.execute(sql, params)
            return _Cursor(cur)
        cur = self._raw.execute(sql, params)
        return _Cursor(cur, cur.lastrowid)

    def executescript(self, sql):
        if self.pg:
            # Retirer les commentaires « -- ... » AVANT de découper sur « ; » :
            # un point-virgule dans un commentaire casserait le découpage.
            import re
            clean = re.sub(r"--[^\n]*", "", sql)
            for stmt in clean.split(";"):
                if stmt.strip():
                    self._raw.execute(stmt)
        else:
            self._raw.executescript(sql)

    def column_names(self, table):
        table = table.strip('"')  # « transaction » est un mot réservé SQL
        if self.pg:
            cur = self._raw.execute(
                "SELECT column_name AS name FROM information_schema.columns "
                "WHERE table_name = %s", (table,))
        else:
            cur = self._raw.execute(f'PRAGMA table_info("{table}")')
        return {r["name"] for r in cur.fetchall()}

    def commit(self):
        self._raw.commit()

    def close(self):
        self._raw.close()


def get_db():
    if USE_PG:
        raw = psycopg.connect(DATABASE_URL, row_factory=dict_row)
        # Désactive les requêtes préparées côté serveur : compatible avec le
        # « transaction pooler » de Supabase (sinon erreurs de prepared statements).
        raw.prepare_threshold = None
        return _Conn(raw, pg=True)
    raw = sqlite3.connect(DB_PATH)
    raw.row_factory = sqlite3.Row
    raw.execute("PRAGMA foreign_keys = ON")
    return _Conn(raw, pg=False)


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
    recovery_hash       TEXT,                   -- code de récupération du PIN (haché)
    sms_token           TEXT,                   -- jeton de l'API de lecture des SMS
    sms_auto            INTEGER NOT NULL DEFAULT 1,  -- créer les transactions auto depuis SMS
    phone_verified      INTEGER NOT NULL DEFAULT 0,
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
    deleted      INTEGER NOT NULL DEFAULT 0,
    client_uid   TEXT,                             -- id généré côté téléphone (sync hors-ligne)
    employee_id  INTEGER                           -- employé qui a saisi (NULL = gérant)
);

CREATE TABLE IF NOT EXISTS cloture (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id   INTEGER NOT NULL REFERENCES agent(id),
    date       TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS employee (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id   INTEGER NOT NULL REFERENCES agent(id),
    name       TEXT NOT NULL,
    pin_hash   TEXT NOT NULL,
    active     INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sms_inbox (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id     INTEGER NOT NULL REFERENCES agent(id),
    sender       TEXT,
    body         TEXT NOT NULL,
    received_at  TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'pending',  -- pending / confirmed / rejected
    parsed_type  TEXT,
    parsed_operator TEXT,
    parsed_amount REAL,
    tx_id        INTEGER
);

CREATE TABLE IF NOT EXISTS sms_device (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id    INTEGER NOT NULL REFERENCES agent(id),
    name        TEXT NOT NULL,
    token       TEXT NOT NULL,
    active      INTEGER NOT NULL DEFAULT 1,
    last_seen   TEXT,
    nb_recus    INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS dette (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id    INTEGER NOT NULL REFERENCES agent(id),
    client_name  TEXT NOT NULL,
    client_phone TEXT,
    amount      REAL NOT NULL,
    note        TEXT,
    op_type     TEXT,                     -- depot_client / retrait_client / retrait_caisse
    wallet_id   INTEGER,                  -- poste UV concerné (NULL = caisse)
    accounted   INTEGER NOT NULL DEFAULT 0,  -- 1 = déjà imputée à une clôture
    cloture_id  INTEGER,                  -- clôture qui l'a imputée
    created_at  TEXT NOT NULL,
    settled_at  TEXT                      -- NULL = en cours, sinon date de règlement
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
    commission REAL NOT NULL DEFAULT 0,  -- commissions du jour pour cet opérateur
    dette      REAL NOT NULL DEFAULT 0   -- dettes clients imputées à ce poste
);
"""


def _migrate(conn):
    """Migrations légères pour les bases déjà créées avant l'ajout de colonnes."""
    cols = conn.column_names("cloture_line")
    if "commission" not in cols:
        conn.execute("ALTER TABLE cloture_line ADD COLUMN commission REAL NOT NULL DEFAULT 0")
    acols = conn.column_names("agent")
    if "pin_hash" not in acols:
        conn.execute("ALTER TABLE agent ADD COLUMN pin_hash TEXT")
    if "shop_name" not in acols:
        conn.execute("ALTER TABLE agent ADD COLUMN shop_name TEXT")
    for col in ("nom", "prenom", "cni", "recovery_hash", "sms_token"):
        if col not in acols:
            conn.execute(f"ALTER TABLE agent ADD COLUMN {col} TEXT")
    if "phone_verified" not in acols:
        conn.execute("ALTER TABLE agent ADD COLUMN phone_verified INTEGER NOT NULL DEFAULT 0")
    if "sms_auto" not in acols:
        conn.execute("ALTER TABLE agent ADD COLUMN sms_auto INTEGER NOT NULL DEFAULT 1")
    tcols = conn.column_names("transaction")
    if "client_uid" not in tcols:
        conn.execute('ALTER TABLE "transaction" ADD COLUMN client_uid TEXT')
    if "employee_id" not in tcols:
        conn.execute('ALTER TABLE "transaction" ADD COLUMN employee_id INTEGER')
    # L'index se crée APRÈS l'ajout de la colonne (bases existantes incluses).
    conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_tx_client_uid '
                 'ON "transaction"(client_uid)')
    if "dette" not in cols:
        conn.execute("ALTER TABLE cloture_line ADD COLUMN dette REAL NOT NULL DEFAULT 0")
    dcols = conn.column_names("dette")
    if "op_type" not in dcols:
        conn.execute("ALTER TABLE dette ADD COLUMN op_type TEXT")
    if "wallet_id" not in dcols:
        conn.execute("ALTER TABLE dette ADD COLUMN wallet_id INTEGER")
    if "accounted" not in dcols:
        conn.execute("ALTER TABLE dette ADD COLUMN accounted INTEGER NOT NULL DEFAULT 0")
    if "cloture_id" not in dcols:
        conn.execute("ALTER TABLE dette ADD COLUMN cloture_id INTEGER")


def init_db():
    conn = get_db()
    schema = SCHEMA
    if USE_PG:
        # Adapter la syntaxe d'auto-incrément pour PostgreSQL.
        schema = schema.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY")
    conn.executescript(schema)
    _migrate(conn)
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Helpers de haut niveau
# ---------------------------------------------------------------------------

def get_agent():
    """Retourne le premier agent (compat ; en multi-comptes, préférer get_agent_by_id)."""
    conn = get_db()
    row = conn.execute("SELECT * FROM agent LIMIT 1").fetchone()
    conn.close()
    return row


def get_agent_by_id(agent_id):
    if not agent_id:
        return None
    conn = get_db()
    row = conn.execute("SELECT * FROM agent WHERE id=?", (agent_id,)).fetchone()
    conn.close()
    return row


def get_agent_by_phone(phone):
    conn = get_db()
    row = conn.execute("SELECT * FROM agent WHERE phone=?", (phone,)).fetchone()
    conn.close()
    return row


def get_agent_by_sms_token(token):
    if not token:
        return None
    conn = get_db()
    row = conn.execute("SELECT * FROM agent WHERE sms_token=?", (token,)).fetchone()
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
