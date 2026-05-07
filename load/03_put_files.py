"""
Étape 1 : Inspecte les en-têtes CSV et affiche les positions de colonnes.
Étape 2 : Upload (PUT) les 4 fichiers CSV vers le stage Snowflake @RAW.CSV_STAGE.

Usage :
    python load/03_put_files.py

Variables d'environnement requises (.env) :
    SNOWFLAKE_ACCOUNT, SNOWFLAKE_USER, SNOWFLAKE_PASSWORD,
    SNOWFLAKE_ROLE, SNOWFLAKE_WAREHOUSE, SNOWFLAKE_DATABASE
"""

import os
import csv
from pathlib import Path
from dotenv import load_dotenv
import snowflake.connector

load_dotenv()

DATA_DIR = Path(__file__).parent.parent / "data"
STAGE = "@PFE_SPARK.RAW.CSV_STAGE"

CSV_FILES = {
    "issues.csv":     "issues",
    "comments.csv":   "comments",
    "changelog.csv":  "changelog",
    "issuelinks.csv": "issuelinks",
}


def inspect_headers(csv_path: Path) -> list[str]:
    """Lit la première ligne du CSV et retourne les noms de colonnes."""
    with open(csv_path, encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        return next(reader)


def print_column_positions(filename: str, headers: list[str]) -> None:
    print(f"\n{'='*60}")
    print(f"  {filename}  ({len(headers)} colonnes)")
    print(f"{'='*60}")
    for i, col in enumerate(headers, start=1):
        print(f"  ${i:>2}  {col}")


def get_connection():
    return snowflake.connector.connect(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user=os.environ["SNOWFLAKE_USER"],
        password=os.environ["SNOWFLAKE_PASSWORD"],
        role=os.environ.get("SNOWFLAKE_ROLE", "SYSADMIN"),
        warehouse=os.environ.get("SNOWFLAKE_WAREHOUSE", "PFE_WH"),
        database=os.environ.get("SNOWFLAKE_DATABASE", "PFE_SPARK"),
        schema="RAW",
    )


def put_file(cursor, local_path: Path) -> None:
    cmd = f"PUT 'file://{local_path.as_posix()}' {STAGE} AUTO_COMPRESS=TRUE OVERWRITE=TRUE"
    print(f"\n  PUT {local_path.name} ...", end=" ", flush=True)
    cursor.execute(cmd)
    rows = cursor.fetchall()
    for row in rows:
        status = row[6] if len(row) > 6 else "?"
        print(f"[{status}]")


def main():
    print("\n=== Inspection des en-têtes CSV ===")
    for filename in CSV_FILES:
        path = DATA_DIR / filename
        if not path.exists():
            print(f"[ERREUR] Fichier introuvable : {path}")
            continue
        headers = inspect_headers(path)
        print_column_positions(filename, headers)

    print("\n\n=== Upload vers Snowflake ===")
    try:
        conn = get_connection()
    except Exception as e:
        print(f"\n[ERREUR] Connexion Snowflake impossible : {e}")
        print("Vérifiez votre fichier .env et réessayez.")
        return

    with conn.cursor() as cur:
        for filename in CSV_FILES:
            path = DATA_DIR / filename
            if not path.exists():
                print(f"  [SKIP] {filename} introuvable")
                continue
            try:
                put_file(cur, path)
            except Exception as e:
                print(f"  [ERREUR] {filename} : {e}")

    conn.close()
    print("\n=== Upload terminé ===")
    print("\nProchaine étape : exécuter load/04_copy_into_raw.sql dans Snowflake.")
    print("Vérifier d'abord que les positions $N ci-dessus correspondent")
    print("aux colonnes attendues dans ce fichier SQL.\n")


if __name__ == "__main__":
    main()
