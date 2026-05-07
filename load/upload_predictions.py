"""Uploads results/mart_predictions.csv to Snowflake CORTEX.MART_PREDICTIONS."""
import os
from pathlib import Path
from dotenv import load_dotenv
import pandas as pd
import snowflake.connector
from snowflake.connector.pandas_tools import write_pandas

load_dotenv()

preds = pd.read_csv(Path(__file__).parent.parent / "results" / "mart_predictions.csv")
preds.columns = [c.upper() for c in preds.columns]
preds["FIX_SUMMARY"] = preds["FIX_SUMMARY"].fillna("")

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
cur.execute("""
    CREATE OR REPLACE TABLE CORTEX.MART_PREDICTIONS (
        key               VARCHAR,
        true_issuetype    VARCHAR,
        true_resolution   VARCHAR,
        pred_issuetype    VARCHAR,
        pred_resolution   VARCHAR,
        conf_issuetype    FLOAT,
        conf_resolution   FLOAT,
        method            VARCHAR,
        fix_summary       VARCHAR
    )
""")
print(f"Uploading {len(preds):,} rows via executemany …")
rows = [tuple(r) for r in preds.itertuples(index=False)]
cur.executemany("""
    INSERT INTO CORTEX.MART_PREDICTIONS
        (key, true_issuetype, true_resolution, pred_issuetype, pred_resolution,
         conf_issuetype, conf_resolution, method, fix_summary)
    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
""", rows)
cur.execute("SELECT COUNT(*) FROM CORTEX.MART_PREDICTIONS")
n = cur.fetchone()[0]
print(f"Done — {n:,} rows in CORTEX.MART_PREDICTIONS")
conn.close()
