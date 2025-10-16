# DB_supabase.py
import os
import psycopg2


def get_config():
    return {
        "HOST": os.getenv("PGHOST", "aws-1-us-east-2.pooler.supabase.com"),        # ex: db.abcd.supabase.co
        "PORT": os.getenv("PGPORT", "6543"),
        "DBNAME": os.getenv("PGDATABASE", "postgres"),
        "USER": os.getenv("PGUSER", "postgres.xxjiossrswqsjkaaeewe"),
        "PASSWORD": os.getenv("PGPASSWORD", "projetosazzas"),
        "SSLMODE": os.getenv("PGSSLMODE", "require"),  # manter "require" no Supabase
        "CONNECT_TIMEOUT": int(os.getenv("PGCONNECT_TIMEOUT", "10")),
    }

def get_conn():
    cfg = get_config()
    conn = psycopg2.connect(
        host=cfg["HOST"],
        port=cfg["PORT"],
        dbname=cfg["DBNAME"],
        user=cfg["USER"],
        password=cfg["PASSWORD"],
        sslmode=cfg["SSLMODE"],
        connect_timeout=cfg["CONNECT_TIMEOUT"],
        
    )
    return conn

def test_connection():
    with get_conn() as cn, cn.cursor() as cur:
        cur.execute("SELECT 1;")
        cur.fetchone()
        return True
