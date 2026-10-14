"""Interactive front end for the heat pump pinch toolkit (Streamlit).

Run locally:
    pip install -r requirements.txt
    streamlit run app.py

Three pages in a top navigation bar (no sidebar):
* Workflow: step-by-step wizard (streams, targets, ΔTmin, heat pumps, retrofit,
  economics), inputs next to the results they drive;
* Dashboard: RQ1-RQ3 with the consolidated sensitivities;
* Sources: provenance, assumptions register, downloads.

The app does no calculation of its own: see app_pages.py.
"""

import streamlit as st

import app_pages

st.set_page_config(page_title="Heat pump pinch analysis", layout="wide", initial_sidebar_state="collapsed")
page = st.navigation([st.Page(app_pages.workflow_page, title="Workflow", icon=":material/account_tree:", default=True),
                      st.Page(app_pages.dashboard_page, title="Dashboard", icon=":material/dashboard:",
                              url_path="dashboard"),
                      st.Page(app_pages.sources_page, title="Sources", icon=":material/menu_book:",
                              url_path="sources")],
                     position="top")
page.run()
