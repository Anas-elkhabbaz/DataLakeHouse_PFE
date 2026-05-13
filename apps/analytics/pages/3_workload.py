"""
Page 3 — Charge de travail
Analyse par assignataire et indicateurs d'escalade
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from analytics_app import query
import streamlit as st
import plotly.express as px
import pandas as pd

st.set_page_config(page_title="Charge de travail", page_icon="👤", layout="wide")
st.title("👤 Charge de travail par assignataire")
st.divider()


@st.cache_data(ttl=3600)
def load_assignee_data() -> pd.DataFrame:
    return query("""
        SELECT
            assignee,
            n_assigned,
            n_fixed,
            avg_resolution_days,
            top_issuetype AS dominant_issuetype
        FROM PFE_SPARK.MARTS_ANALYTICS.MART_ANALYTICS_WORKLOAD
        WHERE n_assigned >= 5
        ORDER BY n_assigned DESC
        LIMIT 20
    """)


@st.cache_data(ttl=3600)
def load_assignee_changes_dist() -> pd.DataFrame:
    return query("""
        SELECT
            n_assignee_changes,
            COUNT(*) AS n_tickets
        FROM PFE_SPARK.INTERMEDIATE.INT_CHANGELOG_FEATURES
        GROUP BY n_assignee_changes
        ORDER BY n_assignee_changes
    """)


assignee_df = load_assignee_data()

if not assignee_df.empty:
    top20 = assignee_df.head(20)

    fig_bar = px.bar(
        top20, x="assignee", y="n_assigned",
        title="Top 20 assignataires — nombre d'incidents assignés",
        labels={"assignee": "Assignataire", "n_assigned": "Incidents assignés"},
        color="n_fixed",
        color_continuous_scale="Greens",
        text="n_assigned",
    )
    fig_bar.update_layout(xaxis_tickangle=-45)
    st.plotly_chart(fig_bar, use_container_width=True)

    st.subheader("Détail par assignataire (top 20)")
    display_df = top20.rename(columns={
        "assignee":           "Assignataire",
        "n_assigned":         "Incidents assignés",
        "n_fixed":            "Résolus (Fixed)",
        "avg_resolution_days": "Délai moyen (j)",
        "dominant_issuetype": "Type dominant",
    })
    st.dataframe(display_df.set_index("Assignataire"), use_container_width=True)

st.divider()
st.subheader("Distribution des changements d'assignataire par ticket")
st.caption("Indicateur d'escalade — un ticket passé entre plusieurs personnes suggère une difficulté accrue")

changes_df = load_assignee_changes_dist()
if not changes_df.empty:
    fig_changes = px.bar(
        changes_df[changes_df["n_assignee_changes"] <= 10],
        x="n_assignee_changes",
        y="n_tickets",
        title="Nombre de changements d'assignataire par ticket (plafonné à 10)",
        labels={
            "n_assignee_changes": "Nombre de changements d'assignataire",
            "n_tickets":          "Nombre de tickets",
        },
        color_discrete_sequence=["#636EFA"],
    )
    st.plotly_chart(fig_changes, use_container_width=True)
