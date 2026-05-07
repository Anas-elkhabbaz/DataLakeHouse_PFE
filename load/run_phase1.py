"""Phase 1 : Création de l'infrastructure Snowflake."""
import os
from dotenv import load_dotenv
import snowflake.connector

load_dotenv()

conn = snowflake.connector.connect(
    account=os.environ["SNOWFLAKE_ACCOUNT"],
    user=os.environ["SNOWFLAKE_USER"],
    password=os.environ["SNOWFLAKE_PASSWORD"],
    role=os.environ["SNOWFLAKE_ROLE"],
)
cur = conn.cursor()

steps = [
    ("CREATE DATABASE",              "CREATE DATABASE IF NOT EXISTS PFE_SPARK"),
    ("CREATE SCHEMA RAW",            "CREATE SCHEMA IF NOT EXISTS PFE_SPARK.RAW"),
    ("CREATE SCHEMA STAGING",        "CREATE SCHEMA IF NOT EXISTS PFE_SPARK.STAGING"),
    ("CREATE SCHEMA INTERMEDIATE",   "CREATE SCHEMA IF NOT EXISTS PFE_SPARK.INTERMEDIATE"),
    ("CREATE SCHEMA MARTS_ML",       "CREATE SCHEMA IF NOT EXISTS PFE_SPARK.MARTS_ML"),
    ("CREATE SCHEMA MARTS_ANALYTICS","CREATE SCHEMA IF NOT EXISTS PFE_SPARK.MARTS_ANALYTICS"),
    ("CREATE SCHEMA CORTEX",         "CREATE SCHEMA IF NOT EXISTS PFE_SPARK.CORTEX"),
    ("CREATE WAREHOUSE", """
        CREATE WAREHOUSE IF NOT EXISTS PFE_WH
        WAREHOUSE_SIZE = 'X-SMALL'
        AUTO_SUSPEND   = 60
        AUTO_RESUME    = TRUE
        INITIALLY_SUSPENDED = TRUE
    """),
    ("CREATE STAGE", """
        CREATE STAGE IF NOT EXISTS PFE_SPARK.RAW.CSV_STAGE
        FILE_FORMAT = (
            TYPE                         = CSV
            FIELD_OPTIONALLY_ENCLOSED_BY = '"'
            SKIP_HEADER                  = 1
            NULL_IF                      = ('', 'NULL', 'nan', 'NaN')
            EMPTY_FIELD_AS_NULL          = TRUE
            FIELD_DELIMITER              = ','
            ENCODING                     = 'UTF-8'
        )
    """),
]

for label, sql in steps:
    cur.execute(sql)
    print(f"  OK  {label}")

conn.close()
print("\nPhase 1 complete — database, schemas, warehouse, stage created.")
