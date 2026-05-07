"""Executes cortex/ SQL scripts via snowflake-connector-python.
Usage: python run_cortex.py <01|02|03|04>
"""
import os, sys, time, re
from pathlib import Path
from dotenv import load_dotenv
import snowflake.connector

load_dotenv()

SCRIPT_MAP = {
    "01": Path(__file__).parent.parent / "cortex" / "01_train_enriched.sql",
    "02": Path(__file__).parent.parent / "cortex" / "02_train_embeddings.sql",
    "03": Path(__file__).parent.parent / "cortex" / "03_predict.sql",
    "04": Path(__file__).parent.parent / "cortex" / "04_evaluate.sql",
}

phase = sys.argv[1] if len(sys.argv) > 1 else "01"
sql_file = SCRIPT_MAP[phase]
print(f"=== Cortex Phase {phase}: {sql_file.name} ===\n")

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

raw = sql_file.read_text(encoding="utf-8")

# Split on semicolons, skip blank / comment-only blocks
statements = [s.strip() for s in raw.split(";") if s.strip()]

for stmt in statements:
    # Skip comment-only blocks
    lines = [l for l in stmt.splitlines() if not l.strip().startswith("--")]
    code = "\n".join(lines).strip()
    if not code:
        continue

    # Print first meaningful line as label
    first_line = next((l.strip() for l in code.splitlines() if l.strip()), "")
    print(f"  >> {first_line[:80]}")
    t0 = time.time()
    try:
        cur.execute(stmt)
        rows = cur.fetchall()
        elapsed = time.time() - t0
        if rows:
            print(f"     {rows}  ({elapsed:.0f}s)")
        else:
            print(f"     OK ({elapsed:.0f}s)")
    except Exception as e:
        print(f"     ERROR: {e}")

conn.close()
print(f"\n=== Phase {phase} complete ===")
