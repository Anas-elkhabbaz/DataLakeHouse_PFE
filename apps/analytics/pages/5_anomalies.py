"""
Page 5 — Anomalies de changelog
Tickets avec des patterns inhabituels : forte rotation, escalades inversées,
outliers de délai de résolution, forte implication collective.
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from analytics_app import query
import streamlit as st
import plotly.express as px
import pandas as pd

st.set_page_config(page_title="Anomalies", layout="wide")
st.title("Anomalies de changelog")
st.caption("Tickets dont les patterns de lifecycle s'écartent significativement de la norme.")
st.divider()


@st.cache_data(ttl=3600)
def load_anomalies() -> pd.DataFrame:
    return query("""
        SELECT
            c.key,
            i.issuetype,
            i.resolution,
            i.priority,
            YEAR(i.created_at)       AS year_created,
            LEAST(i.resolution_days, 5000) AS resolution_days,
            c.n_status_changes,
            c.n_assignee_changes,
            c.n_priority_changes,
            c.n_people_involved,
            c.was_escalated,
            c.was_deescalated,
            LEFT(i.summary, 100)     AS summary_excerpt,
            -- Anomaly flags
            IFF(c.n_status_changes > 5 OR c.n_assignee_changes > 3, 1, 0)   AS flag_high_churn,
            IFF(c.was_escalated = 1 AND c.was_deescalated = 1, 1, 0)         AS flag_escalation_reversed,
            IFF(c.n_people_involved > 5, 1, 0)                               AS flag_many_people
        FROM PFE_SPARK.INTERMEDIATE.INT_CHANGELOG_FEATURES c
        JOIN PFE_SPARK.INTERMEDIATE.INT_ISSUES_CLEANED i USING (key)
    """)


@st.cache_data(ttl=3600)
def load_monthly_anomalies() -> pd.DataFrame:
    return query("""
        SELECT
            DATE_TRUNC('month', i.created_at)                                AS month,
            SUM(IFF(c.n_status_changes > 5 OR c.n_assignee_changes > 3, 1, 0)) AS high_churn,
            SUM(IFF(c.was_escalated = 1 AND c.was_deescalated = 1, 1, 0))      AS escalation_reversed,
            SUM(IFF(c.n_people_involved > 5, 1, 0))                            AS many_people
        FROM PFE_SPARK.INTERMEDIATE.INT_CHANGELOG_FEATURES c
        JOIN PFE_SPARK.INTERMEDIATE.INT_ISSUES_CLEANED i USING (key)
        GROUP BY DATE_TRUNC('month', i.created_at)
        ORDER BY month
    """)


df        = load_anomalies()
monthly   = load_monthly_anomalies()

if df.empty:
    st.warning("No changelog data available.")
    st.stop()

# Outlier resolution: top 1% per issuetype
p99 = df.groupby("issuetype")["resolution_days"].quantile(0.99).rename("p99")
df  = df.join(p99, on="issuetype")
df["flag_outlier_resolution"] = (df["resolution_days"] >= df["p99"]).astype(int)

# Total anomalies
n_high_churn          = df["flag_high_churn"].sum()
n_escalation_reversed = df["flag_escalation_reversed"].sum()
n_many_people         = df["flag_many_people"].sum()
n_outlier_res         = df["flag_outlier_resolution"].sum()
n_any = (df[["flag_high_churn","flag_escalation_reversed","flag_many_people","flag_outlier_resolution"]].max(axis=1)).sum()

# ── KPI row ──────────────────────────────────────────────────────────────────
k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("Total anomalies",         f"{n_any:,}")
k2.metric("Forte rotation",          f"{n_high_churn:,}",
          help="n_status_changes > 5 ou n_assignee_changes > 3")
k3.metric("Escalade puis désescalade", f"{n_escalation_reversed:,}",
          help="Priorité montée puis redescendue")
k4.metric("Outlier délai résolution", f"{n_outlier_res:,}",
          help="Top 1% de resolution_days dans le type d'incident")
k5.metric("Forte implication",        f"{n_many_people:,}",
          help="n_people_involved > 5")

st.divider()

# ── Monthly trend ─────────────────────────────────────────────────────────────
if not monthly.empty:
    monthly["month"] = pd.to_datetime(monthly["month"])
    monthly_long = monthly.melt(
        id_vars="month",
        value_vars=["high_churn", "escalation_reversed", "many_people"],
        var_name="Anomalie", value_name="Nombre",
    )
    monthly_long["Anomalie"] = monthly_long["Anomalie"].map({
        "high_churn":          "Forte rotation",
        "escalation_reversed": "Escalade inversée",
        "many_people":         "Forte implication",
    })
    fig_trend = px.line(
        monthly_long, x="month", y="Nombre", color="Anomalie",
        title="Anomalies par mois",
        labels={"month": "Mois"},
        markers=True,
    )
    st.plotly_chart(fig_trend, use_container_width=True)

st.divider()

# ── Filterable table ──────────────────────────────────────────────────────────
st.subheader("Tickets anomaliques")

anomaly_filter = st.multiselect(
    "Filtrer par type d'anomalie",
    options=["Forte rotation", "Escalade inversée", "Outlier délai", "Forte implication"],
    default=["Forte rotation", "Escalade inversée", "Outlier délai", "Forte implication"],
)

flag_map = {
    "Forte rotation":    "flag_high_churn",
    "Escalade inversée": "flag_escalation_reversed",
    "Outlier délai":     "flag_outlier_resolution",
    "Forte implication": "flag_many_people",
}
selected_flags = [flag_map[a] for a in anomaly_filter if a in flag_map]

if selected_flags:
    mask = df[selected_flags].max(axis=1) == 1
    display = df[mask].copy()
else:
    display = df.copy()

display["Anomalies"] = display.apply(lambda r: ", ".join(
    lbl for lbl, col in [
        ("Churn", "flag_high_churn"),
        ("Esc.Inv.", "flag_escalation_reversed"),
        ("Outlier", "flag_outlier_resolution"),
        ("People",  "flag_many_people"),
    ] if r[col] == 1
), axis=1)

st.dataframe(
    display[["key","issuetype","resolution","priority","year_created",
             "resolution_days","n_status_changes","n_assignee_changes",
             "n_people_involved","Anomalies","summary_excerpt"]]
    .rename(columns={
        "key":               "Ticket",
        "issuetype":         "Type",
        "resolution":        "Résolution",
        "priority":          "Priorité",
        "year_created":      "Année",
        "resolution_days":   "Délai (j)",
        "n_status_changes":  "Status chg.",
        "n_assignee_changes":"Assign. chg.",
        "n_people_involved": "Personnes",
        "summary_excerpt":   "Résumé",
    })
    .sort_values("Délai (j)", ascending=False),
    use_container_width=True,
    hide_index=True,
)
st.caption(f"{len(display):,} tickets anomaliques affichés sur {len(df):,} tickets avec changelog.")
