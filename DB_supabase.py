import os
import psycopg2
import streamlit as st

@st.cache_resource(show_spinner=False)
def get_config():
    s = st.secrets
    return dict(
        HOST=s.get("PGHOST", os.getenv("PGHOST","")),
        PORT=int(s.get("PGPORT", os.getenv("PGPORT","6543"))),
        DBNAME=s.get("PGDATABASE", os.getenv("PGDATABASE","postgres")),
        USER=s.get("PGUSER", os.getenv("PGUSER","")),
        PASSWORD=s.get("PGPASSWORD", os.getenv("PGPASSWORD","")),
        SSLMODE=s.get("PGSSLMODE", os.getenv("PGSSLMODE","require")),
        CONNECT_TIMEOUT=int(s.get("PGCONNECT_TIMEOUT", os.getenv("PGCONNECT_TIMEOUT","10"))),
    )

def get_conn():
    cfg = get_config()
    # conexão NOVA a cada chamada (SEM cache)
    return psycopg2.connect(
        host=cfg["HOST"],
        port=cfg["PORT"],
        dbname=cfg["DBNAME"],
        user=cfg["USER"],
        password=cfg["PASSWORD"],
        sslmode=cfg["SSLMODE"],
        connect_timeout=cfg["CONNECT_TIMEOUT"],
        keepalives=1, keepalives_idle=30, keepalives_interval=10, keepalives_count=5,
    )

def test_connection():
    with get_conn() as cn, cn.cursor() as cur:
        cur.execute("SELECT 1")
        return cur.fetchone()[0] == 1
