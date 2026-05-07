"""
Tableau de bord analytique — Apache Spark JIRA
Application Streamlit multi-pages — Path 2

Lancement : streamlit run apps/analytics/analytics_app.py
"""

import os
from dotenv import load_dotenv
import streamlit as st
import snowflake.connector
import pandas as pd
import plotly.express as px

load_dotenv()

st.set_page_config(
    page_title="Analytics Spark — PFE UIR",
    page_icon="📊",
    layout="wide",
)


@st.cache_resource
def get_conn():
    return snowflake.connector.connect(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user=os.environ["SNOWFLAKE_USER"],
        password=os.environ["SNOWFLAKE_PASSWORD"],
        role=os.environ.get("SNOWFLAKE_ROLE", "SYSADMIN"),
        warehouse=os.environ.get("SNOWFLAKE_WAREHOUSE", "PFE_WH"),
        database=os.environ.get("SNOWFLAKE_DATABASE", "PFE_SPARK"),
        schema="MARTS_ANALYTICS",
    )


@st.cache_data(ttl=3600)
def query(sql: str) -> pd.DataFrame:
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute(sql)
        cols = [d[0].lower() for d in cur.description]
        return pd.DataFrame(cur.fetchall(), columns=cols)


# ---------------------------------------------------------------------------
# KPIs globaux
# ---------------------------------------------------------------------------
@st.cache_data(ttl=3600)
def load_kpis() -> dict:
    df = query("""
        SELECT
            SUM(total_issues)                                    AS total_issues,
            SUM(total_resolved)                                  AS total_resolved,
            ROUND(100.0 * SUM(total_resolved) / NULLIF(SUM(total_issues), 0), 1) AS pct_resolved,
            ROUND(AVG(median_resolution_days), 1)                AS avg_median_resolution_days,
            ROUND(100.0 * SUM(CASE WHEN issuetype = 'Bug' THEN total_issues END)
                  / NULLIF(SUM(total_issues), 0), 1)             AS pct_bug,
            ROUND(100.0 * SUM(CASE WHEN issuetype = 'Improvement' THEN total_issues END)
                  / NULLIF(SUM(total_issues), 0), 1)             AS pct_improvement
        FROM PFE_SPARK.MARTS_ANALYTICS.MART_ANALYTICS_OPS
    """)
    return df.iloc[0].to_dict()


# ---------------------------------------------------------------------------
# Série temporelle : issues créées par mois × issuetype
# ---------------------------------------------------------------------------
@st.cache_data(ttl=3600)
def load_monthly_trend() -> pd.DataFrame:
    return query("""
        SELECT
            CAST(month AS DATE) AS month,
            issuetype,
            total_issues
        FROM PFE_SPARK.MARTS_ANALYTICS.MART_ANALYTICS_OPS
        ORDER BY month, issuetype
    """)


# ===========================================================================
# PAGE PRINCIPALE — Accueil
# ===========================================================================
st.title("📊 Tableau de bord analytique — Apache Spark JIRA")
st.caption("Dataset Kaggle (mars 2025) | PFE UIR 2026 — Anas Elkhabbaz")
st.divider()

kpis = load_kpis()

k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("Total incidents",       f"{int(kpis.get('total_issues', 0)):,}")
k2.metric("Total résolus",         f"{int(kpis.get('total_resolved', 0)):,}")
k3.metric("% Bugs",                f"{kpis.get('pct_bug', 0):.1f}%")
k4.metric("% Améliorations",       f"{kpis.get('pct_improvement', 0):.1f}%")
k5.metric("Délai médian (jours)",  f"{kpis.get('avg_median_resolution_days', 0):.1f}")

st.divider()

trend_df = load_monthly_trend()
if not trend_df.empty:
    fig = px.bar(
        trend_df,
        x="month",
        y="total_issues",
        color="issuetype",
        title="Incidents créés par mois (par type)",
        labels={"month": "Mois", "total_issues": "Nombre d'incidents", "issuetype": "Type"},
        barmode="stack",
    )
    fig.update_layout(legend_title_text="Type d'incident")
    st.plotly_chart(fig, use_container_width=True)

st.info(
    "Utilisez le menu de navigation à gauche pour explorer les pages détaillées : "
    "Vue d'ensemble, Dynamique de résolution, Charge de travail, Relations entre tickets."
)
