"""
Page 1 — Vue d'ensemble
Distribution des types d'incidents et des résolutions
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from analytics_app import get_conn, query
import streamlit as st
import plotly.express as px
import pandas as pd

st.set_page_config(page_title="Vue d'ensemble", page_icon="🔍", layout="wide")
st.title("🔍 Vue d'ensemble — Distribution des incidents")
st.divider()


@st.cache_data(ttl=3600)
def load_issuetype_dist() -> pd.DataFrame:
    return query("""
        SELECT issuetype, SUM(total_issues) AS n
        FROM PFE_SPARK.MARTS_ANALYTICS.MART_ANALYTICS_OPS
        GROUP BY issuetype
        ORDER BY n DESC
    """)


@st.cache_data(ttl=3600)
def load_resolution_dist() -> pd.DataFrame:
    return query("""
        SELECT
            SUM(pct_fixed * total_issues / 100)            AS fixed,
            SUM(pct_wontfix * total_issues / 100)          AS wontfix,
            SUM(pct_duplicate * total_issues / 100)        AS duplicate,
            SUM(pct_cannot_reproduce * total_issues / 100) AS cannot_reproduce,
            SUM(total_issues)                              AS total
        FROM PFE_SPARK.MARTS_ANALYTICS.MART_ANALYTICS_OPS
    """)


@st.cache_data(ttl=3600)
def load_issuetype_x_resolution() -> pd.DataFrame:
    return query("""
        SELECT
            i.issuetype,
            i.resolution,
            COUNT(*) AS n
        FROM PFE_SPARK.INTERMEDIATE.INT_ISSUES_CLEANED i
        GROUP BY i.issuetype, i.resolution
        ORDER BY i.issuetype, n DESC
    """)


col1, col2 = st.columns(2)

it_df = load_issuetype_dist()
if not it_df.empty:
    fig_it = px.pie(
        it_df, names="issuetype", values="n",
        title="Distribution par type d'incident",
        hole=0.4,
    )
    fig_it.update_traces(textposition="inside", textinfo="percent+label")
    col1.plotly_chart(fig_it, use_container_width=True)

re_raw = load_resolution_dist()
if not re_raw.empty:
    row = re_raw.iloc[0]
    total = float(row["total"]) or 1
    re_data = pd.DataFrame([
        {"resolution": "Fixed",             "n": float(row["fixed"])},
        {"resolution": "Won't Fix",         "n": float(row["wontfix"])},
        {"resolution": "Duplicate",         "n": float(row["duplicate"])},
        {"resolution": "Cannot Reproduce",  "n": float(row["cannot_reproduce"])},
    ])
    fig_re = px.pie(
        re_data, names="resolution", values="n",
        title="Distribution par résolution (principales)",
        hole=0.4,
    )
    fig_re.update_traces(textposition="inside", textinfo="percent+label")
    col2.plotly_chart(fig_re, use_container_width=True)

st.divider()
st.subheader("Heatmap type × résolution")

hm_df = load_issuetype_x_resolution()
if not hm_df.empty:
    pivot = hm_df.pivot_table(
        index="issuetype", columns="resolution", values="n", fill_value=0
    )
    fig_hm = px.imshow(
        pivot,
        text_auto=True,
        aspect="auto",
        title="Nombre d'incidents par type et résolution",
        labels={"x": "Résolution", "y": "Type d'incident", "color": "Nombre"},
        color_continuous_scale="Blues",
    )
    st.plotly_chart(fig_hm, use_container_width=True)
