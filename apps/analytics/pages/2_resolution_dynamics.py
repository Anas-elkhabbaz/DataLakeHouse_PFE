"""
Page 2 — Dynamique de résolution
Délais de résolution par type et par priorité
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from analytics_app import query
import streamlit as st
import plotly.express as px
import pandas as pd

st.set_page_config(page_title="Dynamique de résolution", page_icon="⏱️", layout="wide")
st.title("⏱️ Dynamique de résolution")
st.divider()


@st.cache_data(ttl=3600)
def load_resolution_data() -> pd.DataFrame:
    return query("""
        SELECT
            key,
            issuetype,
            priority,
            resolution,
            YEAR(created_at) AS year_created,
            LEAST(resolution_days, 365) AS resolution_days_clipped
        FROM PFE_SPARK.INTERMEDIATE.INT_ISSUES_CLEANED
        WHERE resolution_days IS NOT NULL
          AND resolved_at IS NOT NULL
    """)


# Sidebar filters
st.sidebar.header("Filtres")
df_all = load_resolution_data()

issuetypes = sorted(df_all["issuetype"].dropna().unique().tolist())
selected_types = st.sidebar.multiselect(
    "Types d'incidents", issuetypes, default=issuetypes
)

priorities = sorted(df_all["priority"].dropna().unique().tolist())
selected_priorities = st.sidebar.multiselect(
    "Priorités", priorities, default=priorities
)

year_min = int(df_all["year_created"].min())
year_max = int(df_all["year_created"].max())
year_range = st.sidebar.slider(
    "Années", year_min, year_max, (year_min, year_max)
)

df = df_all[
    df_all["issuetype"].isin(selected_types) &
    df_all["priority"].isin(selected_priorities) &
    df_all["year_created"].between(year_range[0], year_range[1])
]

st.caption(f"{len(df):,} incidents affichés après filtres")

col1, col2 = st.columns(2)

if not df.empty:
    fig_it = px.box(
        df, x="issuetype", y="resolution_days_clipped",
        title="Délai de résolution par type (plafonné à 365 jours)",
        labels={"issuetype": "Type", "resolution_days_clipped": "Jours (plafonné 365)"},
        color="issuetype",
    )
    fig_it.update_layout(showlegend=False)
    col1.plotly_chart(fig_it, use_container_width=True)

    fig_pri = px.box(
        df, x="priority", y="resolution_days_clipped",
        title="Délai de résolution par priorité",
        labels={"priority": "Priorité", "resolution_days_clipped": "Jours (plafonné 365)"},
        color="priority",
        category_orders={"priority": ["Blocker", "Critical", "Major", "Minor", "Trivial"]},
    )
    fig_pri.update_layout(showlegend=False)
    col2.plotly_chart(fig_pri, use_container_width=True)

st.divider()

bugs_df = df[df["issuetype"] == "Bug"]
if not bugs_df.empty:
    fig_hist = px.histogram(
        bugs_df, x="resolution_days_clipped", nbins=50,
        title="Distribution du délai de résolution — Bugs uniquement",
        labels={"resolution_days_clipped": "Jours jusqu'à résolution (plafonné 365)"},
        color_discrete_sequence=["#EF553B"],
    )
    fig_hist.update_layout(bargap=0.1)
    st.plotly_chart(fig_hist, use_container_width=True)
else:
    st.info("Aucun bug dans la sélection courante.")
