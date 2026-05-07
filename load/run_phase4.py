"""Phase 4 : CREATE raw tables + COPY INTO depuis le stage."""
import os, time
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
    schema="RAW",
)
cur = conn.cursor()

# Redimensionner le warehouse pour COPY INTO rapide
cur.execute("ALTER WAREHOUSE PFE_WH SET WAREHOUSE_SIZE = 'MEDIUM'")
print("Warehouse → MEDIUM")

tables = [
    ("RAW.ISSUES", """
        CREATE OR REPLACE TABLE RAW.ISSUES (
            id VARCHAR, key VARCHAR, summary VARCHAR, description VARCHAR,
            created VARCHAR, resolutiondate VARCHAR, issuetype_name VARCHAR,
            resolution_name VARCHAR, resolution_description VARCHAR,
            priority_name VARCHAR, status_name VARCHAR, project_key VARCHAR,
            assignee VARCHAR, reporter VARCHAR, creator VARCHAR,
            votes_votes VARCHAR, watches_watchcount VARCHAR
        )""",
     """
        COPY INTO RAW.ISSUES (
            id, key, summary, description, created, resolutiondate,
            issuetype_name, resolution_name, resolution_description,
            priority_name, status_name, project_key,
            assignee, reporter, creator, votes_votes, watches_watchcount
        )
        FROM (
            SELECT $1,$2,$3,$37,$35,$33,$25,$6,$5,$8,$13,$28,$10,$21,$19,$22,$34
            FROM @RAW.CSV_STAGE/issues.csv.gz
        )
        ON_ERROR = 'CONTINUE'
     """),

    ("RAW.COMMENTS", """
        CREATE OR REPLACE TABLE RAW.COMMENTS (
            key VARCHAR, comment_id VARCHAR, comment_author VARCHAR,
            comment_body VARCHAR, comment_created VARCHAR, comment_updated VARCHAR
        )""",
     """
        COPY INTO RAW.COMMENTS
        FROM (SELECT $1,$2,$3,$4,$5,$6 FROM @RAW.CSV_STAGE/comments.csv.gz)
        ON_ERROR = 'CONTINUE'
     """),

    ("RAW.CHANGELOG", """
        CREATE OR REPLACE TABLE RAW.CHANGELOG (
            key VARCHAR, author VARCHAR, created VARCHAR,
            field VARCHAR, fromstring VARCHAR, tostring VARCHAR
        )""",
     """
        COPY INTO RAW.CHANGELOG (key, author, created, field, fromstring, tostring)
        FROM (SELECT $2,$4,$5,$6,$9,$11 FROM @RAW.CSV_STAGE/changelog.csv.gz)
        ON_ERROR = 'CONTINUE'
     """),

    ("RAW.ISSUELINKS", """
        CREATE OR REPLACE TABLE RAW.ISSUELINKS (
            key VARCHAR, type_name VARCHAR,
            inwardissue_key VARCHAR, outwardissue_key VARCHAR
        )""",
     """
        COPY INTO RAW.ISSUELINKS (key, type_name, inwardissue_key, outwardissue_key)
        FROM (SELECT $1,$4,$8,$23 FROM @RAW.CSV_STAGE/issuelinks.csv.gz)
        ON_ERROR = 'CONTINUE'
     """),
]

for name, ddl, copy_sql in tables:
    print(f"\n  CREATE {name}...", end=" ", flush=True)
    cur.execute(ddl)
    print("OK")
    print(f"  COPY INTO {name}...", end=" ", flush=True)
    t0 = time.time()
    cur.execute(copy_sql)
    rows = cur.fetchall()
    loaded = sum(r[3] for r in rows if r[3] is not None) if rows else 0
    elapsed = time.time() - t0
    print(f"{loaded:,} lignes chargées en {elapsed:.0f}s")

# Vérification des comptes
print("\n=== Vérification des comptes ===")
expected = {"RAW.ISSUES": 18_552_208, "RAW.COMMENTS": 62_356_265,
            "RAW.CHANGELOG": 40_490_946, "RAW.ISSUELINKS": 390_068}
for tbl, exp in expected.items():
    cur.execute(f"SELECT COUNT(*) FROM {tbl}")
    n = cur.fetchone()[0]
    status = "OK" if abs(n - exp) / exp < 0.01 else "VERIFIER"
    print(f"  {status}  {tbl}: {n:,} (attendu ~{exp:,})")

# SPARK subset
cur.execute("SELECT COUNT(*) FROM RAW.ISSUES WHERE project_key = 'SPARK'")
n_spark = cur.fetchone()[0]
print(f"\n  SPARK issues : {n_spark:,} (attendu ~49 833)")

cur.execute("ALTER WAREHOUSE PFE_WH SET WAREHOUSE_SIZE = 'X-SMALL'")
print("\nWarehouse → X-SMALL")
conn.close()
print("Phase 4 complete.")
