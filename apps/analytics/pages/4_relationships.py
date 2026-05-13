"""
Page 4 — Relations entre tickets
Analyse des liens : duplicates, blocages, relations
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from analytics_app import query
import streamlit as st
import plotly.express as px
import pandas as pd

st.set_page_config(page_title="Relations entre tickets", page_icon="🔗", layout="wide")
st.title("🔗 Relations entre tickets")
st.divider()


@st.cache_data(ttl=3600)
def load_top_duplicated() -> pd.DataFrame:
    return query("""
        SELECT
            l.key,
            l.n_duplicates,
            i.issuetype,
            i.resolution,
            LEFT(i.summary, 80) AS summary_excerpt
        FROM PFE_SPARK.MARTS_ANALYTICS.MART_ANALYTICS_LINKS l
        JOIN PFE_SPARK.INTERMEDIATE.INT_ISSUES_CLEANED i USING (key)
        WHERE l.n_duplicates > 0
        ORDER BY l.n_duplicates DESC
        LIMIT 20
    """)


@st.cache_data(ttl=3600)
def load_top_blocked() -> pd.DataFrame:
    return query("""
        SELECT
            l.key,
            l.n_blocked_by,
            i.issuetype,
            i.resolution,
            LEFT(i.summary, 80) AS summary_excerpt
        FROM PFE_SPARK.MARTS_ANALYTICS.MART_ANALYTICS_LINKS l
        JOIN PFE_SPARK.INTERMEDIATE.INT_ISSUES_CLEANED i USING (key)
        WHERE l.n_blocked_by > 0
        ORDER BY l.n_blocked_by DESC
        LIMIT 20
    """)


@st.cache_data(ttl=3600)
def load_link_type_dist() -> pd.DataFrame:
    """Breakdown of link categories from the flat mart (no raw STG dependency)."""
    return query("""
        SELECT
            'Duplicate'  AS type_name, SUM(n_duplicates)  AS n_links
        FROM PFE_SPARK.MARTS_ANALYTICS.MART_ANALYTICS_LINKS
        UNION ALL
        SELECT 'Blocks',    SUM(n_blocks)    FROM PFE_SPARK.MARTS_ANALYTICS.MART_ANALYTICS_LINKS
        UNION ALL
        SELECT 'Blocked By', SUM(n_blocked_by) FROM PFE_SPARK.MARTS_ANALYTICS.MART_ANALYTICS_LINKS
        UNION ALL
        SELECT 'Relates',   SUM(n_relates)   FROM PFE_SPARK.MARTS_ANALYTICS.MART_ANALYTICS_LINKS
        ORDER BY n_links DESC
    """)


col1, col2 = st.columns(2)

dup_df = load_top_duplicated()
if not dup_df.empty:
    fig_dup = px.bar(
        dup_df, x="key", y="n_duplicates",
        title="Top 20 tickets les plus dupliqués",
        labels={"key": "Ticket", "n_duplicates": "Nombre de doublons signalés"},
        color="issuetype",
        text="n_duplicates",
    )
    fig_dup.update_layout(xaxis_tickangle=-45)
    col1.plotly_chart(fig_dup, use_container_width=True)

blocked_df = load_top_blocked()
if not blocked_df.empty:
    fig_blocked = px.bar(
        blocked_df, x="key", y="n_blocked_by",
        title="Top 20 tickets les plus bloqués",
        labels={"key": "Ticket", "n_blocked_by": "Bloqué par N tickets"},
        color="issuetype",
        text="n_blocked_by",
    )
    fig_blocked.update_layout(xaxis_tickangle=-45)
    col2.plotly_chart(fig_blocked, use_container_width=True)

st.divider()

link_df = load_link_type_dist()
if not link_df.empty:
    fig_link = px.bar(
        link_df, x="type_name", y="n_links",
        title="Distribution des types de liens entre tickets (top 15)",
        labels={"type_name": "Type de lien", "n_links": "Nombre de liens"},
        color="n_links",
        color_continuous_scale="Viridis",
        text="n_links",
    )
    fig_link.update_layout(xaxis_tickangle=-30)
    st.plotly_chart(fig_link, use_container_width=True)

st.divider()

if not dup_df.empty:
    st.subheader("Détail — Tickets les plus dupliqués")
    st.dataframe(
        dup_df.rename(columns={
            "key":             "Ticket",
            "n_duplicates":    "Doublons",
            "issuetype":       "Type",
            "resolution":      "Résolution",
            "summary_excerpt": "Résumé",
        }),
        use_container_width=True,
        hide_index=True,
    )
