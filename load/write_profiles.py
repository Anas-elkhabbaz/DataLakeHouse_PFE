"""Écrit ~/.dbt/profiles.yml en lisant les credentials depuis .env."""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

content = (
    "pfe_spark_triage:\n"
    "  target: dev\n"
    "  outputs:\n"
    "    dev:\n"
    "      type: snowflake\n"
    f"      account: {os.environ['SNOWFLAKE_ACCOUNT']}\n"
    f"      user: {os.environ['SNOWFLAKE_USER']}\n"
    f"      password: \"{os.environ['SNOWFLAKE_PASSWORD']}\"\n"
    f"      role: {os.environ['SNOWFLAKE_ROLE']}\n"
    "      database: PFE_SPARK\n"
    "      warehouse: PFE_WH\n"
    "      schema: public\n"
    "      threads: 4\n"
    "      client_session_keep_alive: false\n"
    "      query_tag: dbt_pfe_spark\n"
)

dbt_dir = Path.home() / ".dbt"
dbt_dir.mkdir(exist_ok=True)
profile_path = dbt_dir / "profiles.yml"
profile_path.write_text(content, encoding="utf-8")
print(f"profiles.yml written to {profile_path}")
