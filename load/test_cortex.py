"""Test which Cortex functions are available on this account."""
import os
from dotenv import load_dotenv
import snowflake.connector

load_dotenv()

conn = snowflake.connector.connect(
    account=os.environ["SNOWFLAKE_ACCOUNT"],
    user=os.environ["SNOWFLAKE_USER"],
    password=os.environ["SNOWFLAKE_PASSWORD"],
    role=os.environ["SNOWFLAKE_ROLE"],
    warehouse="PFE_WH",
    database="PFE_SPARK",
    schema="CORTEX",
)
cur = conn.cursor()

print("Testing EMBED_TEXT_1024...")
try:
    cur.execute("""
        SELECT SNOWFLAKE.CORTEX.EMBED_TEXT_1024('voyage-multilingual-2', 'test ticket bug')
    """)
    r = cur.fetchone()
    print(f"  EMBED_TEXT_1024: OK (vector length={len(r[0])})")
except Exception as e:
    print(f"  EMBED_TEXT_1024: BLOCKED — {e}")

print("Testing COMPLETE...")
try:
    cur.execute("""
        SELECT SNOWFLAKE.CORTEX.COMPLETE('mistral-large2', 'Say OK.')
    """)
    r = cur.fetchone()
    print(f"  COMPLETE: OK — {r[0][:50]}")
except Exception as e:
    print(f"  COMPLETE: BLOCKED — {e}")

conn.close()
