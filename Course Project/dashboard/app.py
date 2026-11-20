"""Review-ready Streamlit dashboard for the Email Organizer Agent.

Run with:
    streamlit run dashboard/app.py
"""

from __future__ import annotations

import calendar
import collections
import datetime
import html
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.audit import AuditLogger
from core.auth import GoogleAuthManager, get_configured_mailbox_owner_email, send_email_guarded
from core.models import ApprovalStatus, DraftReply, TriagedInbox
from lab07_node_graph.graph import AgenticNodeGraph, GraphRunResult


AUDIT_PATH = ROOT / "audit_log.jsonl"
CHECKPOINT_PATH = ROOT / "runtime_checkpoint.jsonl"


def get_google_account_email() -> Optional[str]:
    """Return the connected Gmail address if a valid non-expired token is available."""
    cached_email = st.session_state.get("google_account_email")
    if cached_email:
        return cached_email

    token_path = ROOT / "token.json"
    if not token_path.exists():
        return None

    try:
        auth = GoogleAuthManager(
            credentials_path=str(ROOT / "credentials.json"),
            token_path=str(token_path),
        )
        creds = auth.get_credentials(interactive=False)
        if not creds or not creds.valid:
            return None

        service = auth.get_gmail_service(interactive=False)
        profile = service.users().getProfile(userId="me").execute()
        email = (profile or {}).get("emailAddress")
        if email:
            st.session_state["google_account_email"] = email
        return email
    except Exception:
        return None


def render_google_account_widget() -> None:
    """Render a sidebar Google account status and connect action using the shared OAuth flow."""
    connected_email = get_google_account_email()

    if connected_email:
        st.markdown(
            f"""
            <div class="saas-hero-badge" style="background: rgba(34, 197, 94, 0.12); border-color: rgba(34, 197, 94, 0.45); color: #166534; width: fit-content;">
                <span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:#22C55E;margin-right:8px;"></span>
                Connected as: {html.escape(connected_email)}
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.caption("Only this account's inbox is accessed — nothing else is touched.")
        if st.button("Refresh account status", use_container_width=True, key="refresh_google_account_status"):
            st.session_state.pop("google_account_email", None)
            st.rerun()
        return

    if st.button("Connect Google Account", type="primary", use_container_width=True, key="connect_google_account_button"):
        try:
            auth = GoogleAuthManager(
                credentials_path=str(ROOT / "credentials.json"),
                token_path=str(ROOT / "token.json"),
            )
            creds = auth.get_credentials(interactive=True)
            if not creds or not creds.valid:
                st.warning("Google account connection is not yet valid. Please try again.")
            else:
                service = auth.get_gmail_service(interactive=False)
                profile = service.users().getProfile(userId="me").execute()
                email = (profile or {}).get("emailAddress")
                if email:
                    st.session_state["google_account_email"] = email
                    st.success(f"Connected as: {email}")
                    st.info("Google auth completed. Click the refresh button if the dashboard does not update immediately.")
                    st.rerun()
                else:
                    st.warning("Connected successfully, but the account email could not be read from Gmail profile data.")
        except Exception as exc:
            st.error(f"Google authentication could not be completed: {exc}")

    st.caption("Your Google account must be added as an authorized tester for this app before connecting.")


# =============================================================================
# Custom SaaS Design System & CSS Injection
# =============================================================================

CUSTOM_CSS = """
<style>
/* ---------------- Global & Typography ---------------- */
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

html, body, [class*="css"] {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    color: #0F172A;
    background: #F4F9FF;
}

.block-container {
    padding-top: 1.5rem !important;
    padding-bottom: 2.5rem !important;
    padding-left: 2rem !important;
    padding-right: 2rem !important;
    max-width: 1400px;
}

#MainMenu {visibility: hidden;}
footer {visibility: hidden;}
header[data-testid="stHeader"] {background: rgba(11, 31, 58, 0.96); backdrop-filter: blur(8px);}

/* ---------------- Legend & Theme Palette ---------------- */
.theme-navy { background: #0B1F3A; color: #E2E8F0; }
.theme-agent { background: #EAF5FF; border: 1px solid #BFDBFE; }
.theme-amber { background: #FFF5D6; border: 1px solid #FCD34D; }
.theme-green { background: #E8F8EE; border: 1px solid #A7F3D0; }

/* ---------------- Hero / Header ---------------- */
.saas-hero {
    background: linear-gradient(135deg, #0B1F3A 0%, #132F52 100%);
    border-radius: 12px;
    padding: 0.9rem 1.2rem;
    margin-bottom: 0.9rem;
    color: #F8FAFC;
    box-shadow: 0 4px 12px rgba(11, 31, 58, 0.08);
    display: flex;
    justify-content: space-between;
    align-items: center;
    min-height: 68px;
}

.saas-hero-title {
    font-size: 1.2rem;
    font-weight: 700;
    margin: 0;
    letter-spacing: -0.02em;
    color: #FFFFFF;
}

.saas-hero-subtitle {
    font-size: 0.76rem;
    color: #B9C8DA;
    margin-top: 0.15rem;
    margin-bottom: 0;
    line-height: 1.4;
}

.saas-hero-badge {
    background: rgba(96, 165, 250, 0.18);
    border: 1px solid rgba(147, 197, 253, 0.45);
    color: #DCEEFF;
    padding: 0.4rem 0.7rem;
    border-radius: 9999px;
    font-size: 0.72rem;
    font-weight: 600;
    display: inline-flex;
    align-items: center;
    gap: 6px;
}

/* ---------------- Compact Summary Row ---------------- */
.summary-bar {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem;
    align-items: center;
    margin: 0 0 0.75rem 0;
    padding: 0.55rem 0.8rem;
    background: #F8FBFF;
    border: 1px solid #E2E8F0;
    border-radius: 10px;
    color: #334155;
    font-size: 0.78rem;
    font-weight: 600;
}

.summary-pill {
    display: inline-flex;
    align-items: center;
    padding: 0.32rem 0.62rem;
    border-radius: 999px;
    background: #EAF5FF;
    border: 1px solid #DBEAFE;
    color: #0F172A;
}

.summary-pill strong {
    margin-right: 0.2rem;
}

/* ---------------- High-end review panels ---------------- */
.insight-grid {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 0.75rem;
    margin: 0.85rem 0 1.1rem 0;
}

.insight-card {
    background: linear-gradient(180deg, #FFFFFF 0%, #F8FBFF 100%);
    border: 1px solid #E2E8F0;
    border-radius: 12px;
    padding: 0.8rem 0.9rem;
    box-shadow: 0 2px 8px rgba(15, 23, 42, 0.03);
}

.insight-label {
    display: block;
    font-size: 0.68rem;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: #64748B;
    margin-bottom: 0.35rem;
    font-weight: 700;
}

.insight-card strong {
    display: block;
    font-size: 1rem;
    color: #0F172A;
    margin-bottom: 0.18rem;
}

.insight-card span {
    color: #475569;
    font-size: 0.75rem;
    line-height: 1.5;
}

.review-guide {
    background: #FFFFFF;
    border: 1px solid #E2E8F0;
    border-radius: 12px;
    padding: 0.9rem 1rem 0.75rem 1rem;
    margin: 0.2rem 0 1rem 0;
}

.review-guide h4 {
    margin: 0 0 0.55rem 0;
    color: #0F172A;
    font-size: 0.9rem;
}

.review-guide ul {
    margin: 0;
    padding-left: 1.1rem;
    color: #475569;
    font-size: 0.78rem;
    line-height: 1.7;
}

.labs-grid {
    display: grid;
    grid-template-columns: repeat(5, minmax(0, 1fr));
    gap: 0.7rem;
    margin: 1rem 0 1.4rem 0;
}

.lab-card {
    background: linear-gradient(180deg, #FFFFFF 0%, #F8FBFF 100%);
    border: 1px solid #E2E8F0;
    border-radius: 10px;
    padding: 0.7rem 0.65rem;
    min-height: 112px;
    box-shadow: 0 1px 3px rgba(15, 23, 42, 0.04);
}

.lab-card.pass {
    border-left: 4px solid #22C55E;
}

.lab-card.active {
    border-left: 4px solid #60A5FA;
}

.lab-card.pending {
    border-left: 4px solid #F59E0B;
}

.lab-card .lab-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 0.35rem;
}

.lab-card .lab-no {
    font-size: 0.72rem;
    font-weight: 700;
    color: #0F172A;
}

.lab-card .lab-badge {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    padding: 0.18rem 0.46rem;
    border-radius: 999px;
    font-size: 0.6rem;
    font-weight: 700;
    letter-spacing: 0.04em;
    text-transform: uppercase;
}

.lab-card.pass .lab-badge {
    background: #DCFCE7;
    color: #166534;
}

.lab-card.active .lab-badge {
    background: #DBEAFE;
    color: #1D4ED8;
}

.lab-card.pending .lab-badge {
    background: #FEF3C7;
    color: #92400E;
}

.lab-card .lab-title {
    font-size: 0.8rem;
    font-weight: 700;
    color: #0F172A;
    line-height: 1.35;
    margin-bottom: 0.28rem;
}

.lab-card .lab-desc {
    font-size: 0.68rem;
    line-height: 1.5;
    color: #475569;
}

/* ---------------- Gmail-style list rows ---------------- */
.gmail-list {
    border-top: 1px solid #E2E8F0;
    border-bottom: 1px solid #E2E8F0;
    background: #FFFFFF;
}

.gmail-row {
    display: grid;
    grid-template-columns: minmax(120px, 180px) minmax(240px, 1fr) auto 72px;
    align-items: center;
    gap: 0.65rem;
    min-height: 48px;
    padding: 0.5rem 0.75rem;
    border-bottom: 1px solid #EEF2F7;
    background: #FFFFFF;
    transition: background 0.15s ease;
}

.gmail-item {
    display: block;
    border-bottom: 1px solid #EEF2F7;
    background: #FFFFFF;
}

.gmail-item:last-child {
    border-bottom: none;
}

.gmail-summary {
    display: block;
    list-style: none;
    cursor: pointer;
    margin: 0;
}

.gmail-summary::-webkit-details-marker {
    display: none;
}

.gmail-summary:hover .gmail-row {
    background: #F8FBFF;
}

.gmail-item[open] .gmail-summary {
    background: #F8FBFF;
}

.gmail-sender {
    font-size: 0.8rem;
    color: #1E293B;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}

.gmail-sender.unread {
    font-weight: 700;
    color: #0F172A;
}

.gmail-subject {
    min-width: 0;
    font-size: 0.8rem;
    color: #0F172A;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    font-weight: 600;
}

.gmail-preview {
    color: #64748B;
    font-weight: 400;
    margin-left: 0.35rem;
}

.gmail-details {
    padding: 0.7rem 0.75rem 0.85rem 0.75rem;
    background: #F8FBFF;
    border-top: 1px solid #EEF2F7;
    color: #334155;
    font-size: 0.8rem;
    line-height: 1.65;
}

.gmail-action-check {
    display: inline-flex;
    align-items: center;
    gap: 0.5rem;
    margin-top: 0.5rem;
    color: #0F172A;
    font-weight: 600;
}

.gmail-action-check input {
    width: 16px;
    height: 16px;
    accent-color: #0B1F3A;
}

.gmail-chips {
    display: flex;
    justify-content: flex-end;
    gap: 0.35rem;
    flex-wrap: wrap;
}

.gmail-chip {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    padding: 0.18rem 0.52rem;
    border-radius: 999px;
    font-size: 0.66rem;
    line-height: 1;
    font-weight: 700;
    letter-spacing: 0.02em;
    border: 1px solid transparent;
    white-space: nowrap;
}

.gmail-chip.urgent { background: #FEE2E2; color: #B91C1C; border-color: #FCA5A5; }
.gmail-chip.high { background: #FFEDD5; color: #C2410C; border-color: #FDBA74; }
.gmail-chip.medium { background: #FEF3C7; color: #A16207; border-color: #FCD34D; }
.gmail-chip.low { background: #DBEAFE; color: #1D4ED8; border-color: #93C5FD; }
.gmail-chip.admin { background: #E0F2FE; color: #075985; border-color: #BAE6FD; }
.gmail-chip.student { background: #DCFCE7; color: #166534; border-color: #86EFAC; }
.gmail-chip.collaborator { background: #F3E8FF; color: #7E22CE; border-color: #D8B4FE; }
.gmail-chip.vendor { background: #F1F5F9; color: #475569; border-color: #CBD5E1; }
.gmail-chip.pending { background: #FFF5D6; color: #A16207; border-color: #FCD34D; }
.gmail-chip.approved { background: #DCFCE7; color: #166534; border-color: #86EFAC; }
.gmail-chip.sent { background: #DCFCE7; color: #15803D; border-color: #BBF7D0; }
.gmail-chip.draft { background: #FEF3C7; color: #A16207; border-color: #FCD34D; }
.gmail-chip.neutral { background: #F1F5F9; color: #475569; border-color: #E2E8F0; }
.gmail-chip.tertiary { background: #EAF5FF; color: #1D4ED8; border-color: #BFDBFE; }

.gmail-time {
    font-size: 0.72rem;
    color: #64748B;
    text-align: right;
    white-space: nowrap;
    font-weight: 600;
}

.gmail-details {
    margin-top: 0.2rem;
    background: #F8FBFF;
    border: 1px solid #E2E8F0;
    border-radius: 10px;
    padding: 0.75rem 0.9rem;
    color: #334155;
    font-size: 0.8rem;
    line-height: 1.6;
}

/* ---------------- Action-item detail rows ---------------- */
.gmail-details .detail-metadata {
    display: grid;
    grid-template-columns: repeat(2, minmax(140px, 1fr));
    gap: 0.65rem 1rem;
    margin-top: 0.15rem;
}

.gmail-details .detail-field {
    display: flex;
    flex-direction: column;
    gap: 0.18rem;
    min-width: 0;
}

.gmail-details .detail-field span {
    font-size: 0.66rem;
    font-weight: 700;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    color: #64748B;
}

.gmail-details .detail-field strong {
    font-size: 0.8rem;
    font-weight: 600;
    color: #0F172A;
    line-height: 1.4;
    word-break: break-word;
}

.gmail-confirm-row {
    display: flex;
    justify-content: flex-end;
    align-items: center;
    margin-top: 0.85rem;
    padding-top: 0.7rem;
    border-top: 1px solid #E2E8F0;
}

.gmail-action-check {
    display: inline-flex;
    align-items: center;
    gap: 0.55rem;
    margin: 0;
    padding: 0.28rem 0.6rem;
    border-radius: 999px;
    background: #F8FAFC;
    border: 1px solid #E2E8F0;
    color: #0F172A;
    font-weight: 600;
    font-size: 0.78rem;
    line-height: 1.2;
}

.gmail-action-check input {
    width: 16px;
    height: 16px;
    accent-color: #0B1F3A;
    margin: 0;
}

/* ---------------- Tabs ---------------- */
div[data-testid="stTabs"] button[role="tab"] {
    font-size: 0.88rem;
    font-weight: 600;
    color: #475569;
    padding: 0.72rem 1rem;
    border-radius: 8px 8px 0 0;
    transition: color 0.15s ease;
    background: #F8FBFF;
}

div[data-testid="stTabs"] button[role="tab"][aria-selected="true"] {
    color: #0B1F3A !important;
    border-bottom-color: #0B1F3A !important;
    font-weight: 700;
    background: #EAF5FF;
}

/* ---------------- Sidebar Product Styling ---------------- */
.sidebar-section-header {
    font-size: 0.84rem;
    font-weight: 800;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: #0F172A;
    margin: 0.4rem 0 0.6rem 0;
    display: flex;
    align-items: center;
    gap: 0.5rem;
}

.sidebar-status-card {
    background: linear-gradient(180deg, #F8FBFF 0%, #F0F9FF 100%);
    border: 1px solid #BFDBFE;
    border-radius: 12px;
    padding: 0.8rem 0.85rem;
    margin: 0.25rem 0 0.9rem 0;
    box-shadow: inset 0 1px 0 rgba(255,255,255,0.6);
}

.sidebar-status-row {
    display: flex;
    align-items: center;
    gap: 0.6rem;
    margin-bottom: 0.25rem;
}

.sidebar-status-dot {
    width: 9px;
    height: 9px;
    border-radius: 999px;
    background: #22C55E;
    box-shadow: 0 0 0 4px rgba(34, 197, 94, 0.12);
}

.sidebar-status-text {
    font-size: 0.8rem;
    font-weight: 700;
    color: #0F172A;
}

.sidebar-status-sub {
    font-size: 0.74rem;
    color: #475569;
    line-height: 1.5;
}

.sidebar-help-item {
    display: flex;
    gap: 0.7rem;
    align-items: flex-start;
    margin: 0.6rem 0;
}

.sidebar-help-badge {
    min-width: 26px;
    height: 26px;
    border-radius: 8px;
    background: #EAF5FF;
    color: #0B1F3A;
    border: 1px solid #BFDBFE;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    font-size: 0.7rem;
    font-weight: 800;
}

.sidebar-help-copy {
    font-size: 0.8rem;
    line-height: 1.55;
    color: #334155;
}

.sidebar-help-copy strong {
    font-size: 0.64rem;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    color: #475569;
    display: block;
    margin-bottom: 0.18rem;
}

.sidebar-note {
    color: #475569;
    font-size: 0.75rem;
    line-height: 1.55;
    margin-top: 0.5rem;
}

.sidebar-roadmap {
    margin-top: 0.3rem;
    padding: 0.1rem 0;
}

.sidebar-roadmap h4 {
    margin: 0 0 0.6rem 0;
    font-size: 0.7rem;
    font-weight: 800;
    color: #475569;
    letter-spacing: 0.08em;
    text-transform: uppercase;
}

.sidebar-roadmap-list {
    margin: 0;
    padding-left: 1rem;
    color: #334155;
    font-size: 0.76rem;
    line-height: 1.8;
}

.sidebar-roadmap-list li {
    margin: 0.12rem 0;
}

.sidebar-roadmap-list strong {
    color: #0F172A;
}

/* ---------------- Card Containers ---------------- */
.saas-card {
    background: #EAF5FF;
    border: 1px solid #BFDBFE;
    border-radius: 12px;
    padding: 1.25rem;
    margin-bottom: 1.25rem;
    box-shadow: 0 2px 6px rgba(15, 23, 42, 0.04);
}

.saas-card:hover {
    border-color: #93C5FD;
    box-shadow: 0 4px 12px rgba(15, 23, 42, 0.07);
}

/* ---------------- Status & Urgency Badges ---------------- */
.badge {
    display: inline-block;
    padding: 3px 9px;
    border-radius: 6px;
    font-size: 0.76rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    margin-right: 6px;
}

.badge-urgent { background: #FEE2E2; color: #B91C1C; border: 1px solid #FCA5A5; }
.badge-high   { background: #FFEDD5; color: #C2410C; border: 1px solid #FDBA74; }
.badge-medium { background: #FEF3C7; color: #A16207; border: 1px solid #FCD34D; }
.badge-low    { background: #DBEAFE; color: #1D4ED8; border: 1px solid #93C5FD; }
.badge-admin  { background: #E0F2FE; color: #075985; border: 1px solid #BAE6FD; }
.badge-student { background: #DCFCE7; color: #166534; border: 1px solid #86EFAC; }
.badge-collaborator { background: #F3E8FF; color: #7E22CE; border: 1px solid #D8B4FE; }
.badge-vendor { background: #F1F5F9; color: #475569; border: 1px solid #CBD5E1; }
.badge-draft     { background: #FEF3C7; color: #A16207; border: 1px solid #FCD34D; }
.badge-approved  { background: #DCFCE7; color: #166534; border: 1px solid #86EFAC; }
.badge-pending  { background: #FFF5D6; color: #A16207; border: 1px solid #FCD34D; }
.badge-sent      { background: #DCFCE7; color: #15803D; border: 1px solid #BBF7D0; }
.badge-discarded { background: #FEE2E2; color: #991B1B; border: 1px solid #FECACA; }

.legend-guide {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem;
    align-items: center;
    padding: 0.4rem 0.75rem;
    margin: 0 0 0.75rem 0;
    background: #F8FBFF;
    border: 1px solid #E2E8F0;
    border-radius: 999px;
    max-width: 780px;
    box-shadow: inset 0 1px 0 rgba(255,255,255,0.75);
}

.legend-item {
    display: inline-flex;
    align-items: center;
    gap: 0.45rem;
    color: #475569;
    font-size: 0.72rem;
    font-weight: 700;
    letter-spacing: 0.02em;
}

.legend-swatch {
    width: 10px;
    height: 10px;
    border-radius: 999px;
    display: inline-block;
    border: 1px solid rgba(15, 23, 42, 0.15);
}

.legend-swatch.navy { background: #0B1F3A; }
.legend-swatch.agent { background: #EAF5FF; }
.legend-swatch.amber { background: #FFF5D6; }
.legend-swatch.green { background: #E8F8EE; }

div[data-testid="stCheckbox"] {
    pointer-events: auto !important;
    position: relative;
    z-index: 1;
    display: inline-flex !important;
    align-items: center !important;
}

div[data-testid="stCheckbox"] label {
    display: inline-flex !important;
    align-items: center !important;
    gap: 0.55rem !important;
    pointer-events: auto !important;
    cursor: pointer;
}

div[data-testid="stCheckbox"] input {
    width: 16px !important;
    height: 16px !important;
    margin: 0 !important;
    accent-color: #0B1F3A !important;
    pointer-events: auto !important;
    cursor: pointer;
}

div[data-testid="stCheckbox"] span {
    pointer-events: auto !important;
    cursor: pointer;
}

/* ---------------- Draft Card Typography & Sections ---------------- */
.draft-card-header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    margin-bottom: 0.75rem;
    border-bottom: 1px solid #D6E9FF;
    padding-bottom: 0.75rem;
}

.draft-subject {
    font-size: 1.05rem;
    font-weight: 700;
    color: #0F172A;
    margin: 0 0 0.25rem 0;
}

.draft-meta {
    font-size: 0.82rem;
    color: #475569;
}

.draft-meta strong {
    color: #0F172A;
}

.draft-meta-box {
    background: #F8FBFF;
    border: 1px solid #BFDBFE;
    border-radius: 8px;
    padding: 0.85rem;
    font-size: 0.82rem;
    color: #334155;
    margin-bottom: 0.85rem;
}

/* ---------------- Empty State ---------------- */
.saas-empty-state {
    text-align: center;
    padding: 3rem 1.5rem;
    background: #F8FBFF;
    border: 1.5px dashed #BFDBFE;
    border-radius: 12px;
    color: #475569;
    margin: 1.5rem 0;
}

.saas-empty-icon {
    font-size: 2.2rem;
    margin-bottom: 0.5rem;
    display: block;
}

.saas-empty-title {
    font-size: 1rem;
    font-weight: 700;
    color: #0F172A;
    margin-bottom: 0.25rem;
}

.saas-empty-desc {
    font-size: 0.85rem;
    color: #475569;
}

/* ---------------- Button Polish ---------------- */
div[data-testid="stButton"] button {
    border-radius: 8px;
    font-weight: 600;
    font-size: 0.88rem;
    padding: 0.5rem 1rem;
    transition: all 0.15s ease;
}

div[data-testid="stButton"] button:hover {
    box-shadow: 0 2px 6px rgba(0,0,0,0.08);
}

/* ---------------- Calendar Tab Styles ---------------- */
.cal-section-label {
    font-size: 0.68rem;
    font-weight: 800;
    letter-spacing: 0.09em;
    text-transform: uppercase;
    color: #64748B;
    margin: 1.1rem 0 0.55rem 0;
    padding-bottom: 0.3rem;
    border-bottom: 2px solid #E2E8F0;
}

.cal-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
    gap: 0.75rem;
    margin-bottom: 1.1rem;
}

.cal-card {
    background: #FFFFFF;
    border: 1px solid #E2E8F0;
    border-radius: 12px;
    padding: 0.85rem 1rem;
    box-shadow: 0 2px 6px rgba(15, 23, 42, 0.04);
    position: relative;
    transition: box-shadow 0.15s ease, border-color 0.15s ease;
}

.cal-card:hover {
    border-color: #93C5FD;
    box-shadow: 0 4px 12px rgba(15, 23, 42, 0.08);
}

.cal-card-accent {
    position: absolute;
    left: 0;
    top: 0;
    bottom: 0;
    width: 4px;
    border-radius: 12px 0 0 12px;
}

.cal-card-title {
    font-size: 0.9rem;
    font-weight: 700;
    color: #0F172A;
    margin: 0 0 0.3rem 0;
    padding-left: 0.5rem;
    line-height: 1.35;
}

.cal-card-time {
    font-size: 0.76rem;
    color: #475569;
    font-weight: 600;
    padding-left: 0.5rem;
    margin-bottom: 0.35rem;
}

.cal-card-meta {
    font-size: 0.73rem;
    color: #64748B;
    padding-left: 0.5rem;
    line-height: 1.5;
}

.cal-type-badge {
    display: inline-flex;
    align-items: center;
    padding: 0.15rem 0.5rem;
    border-radius: 999px;
    font-size: 0.62rem;
    font-weight: 700;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    margin-left: 0.4rem;
    vertical-align: middle;
}

.cal-type-meeting   { background:#DBEAFE; color:#1D4ED8; border:1px solid #93C5FD; }
.cal-type-class     { background:#DCFCE7; color:#166534; border:1px solid #86EFAC; }
.cal-type-conference{ background:#F3E8FF; color:#7E22CE; border:1px solid #D8B4FE; }
.cal-type-deadline  { background:#FEE2E2; color:#B91C1C; border:1px solid #FCA5A5; }
.cal-type-placement { background:#FFEDD5; color:#C2410C; border:1px solid #FDBA74; }
.cal-type-test      { background:#FEF3C7; color:#A16207; border:1px solid #FCD34D; }
.cal-type-hackathon { background:#EDE9FE; color:#6D28D9; border:1px solid #C4B5FD; }
.cal-type-event     { background:#F0FDF4; color:#15803D; border:1px solid #BBF7D0; }
.cal-type-zoom      { background:#EAF5FF; color:#0369A1; border:1px solid #BAE6FD; }
.cal-type-other     { background:#F1F5F9; color:#475569; border:1px solid #CBD5E1; }

.cal-free-slot {
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    background: #F0FDF4;
    border: 1px solid #BBF7D0;
    border-radius: 8px;
    padding: 0.38rem 0.75rem;
    font-size: 0.8rem;
    color: #166534;
    font-weight: 600;
    margin: 0.3rem 0.3rem 0.3rem 0;
    display: inline-block;
}

.cal-free-dot {
    display: inline-block;
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: #22C55E;
    margin-right: 4px;
    vertical-align: middle;
}
</style>
"""


# =============================================================================
# Helper Utilities
# =============================================================================

def safe_audit_dataframe(entries: List[Dict[str, Any]]) -> pd.DataFrame:
    """Format audit entries safely for PyArrow by normalizing all complex fields to strings."""
    if not entries:
        return pd.DataFrame()

    safe_rows = []
    for e in entries:
        row = {}
        for k, v in e.items():
            if isinstance(v, (dict, list)):
                try:
                    row[k] = json.dumps(v, default=str)
                except Exception:
                    row[k] = str(v)
            elif v is None:
                row[k] = ""
            else:
                row[k] = str(v) if not isinstance(v, (int, float, bool)) else v
        safe_rows.append(row)

    df = pd.DataFrame(safe_rows)
    # Reorder columns logically if present
    desired_order = [
        "timestamp",
        "agent",
        "action",
        "guardrail_passed",
        "input_summary",
        "result_summary",
        "intent",
        "metadata",
    ]
    present_order = [col for col in desired_order if col in df.columns]
    remaining = [col for col in df.columns if col not in present_order]
    return df[present_order + remaining]


@st.cache_data(ttl=300, show_spinner=False)
def build_graph_result(max_results: int) -> GraphRunResult:
    """Run the full triage pipeline. Results are cached for 5 minutes to avoid
    re-hitting the Gmail API on every Streamlit rerender."""
    graph = AgenticNodeGraph(max_retries=2)
    return graph.run(max_results=max_results)


def ensure_state(result: GraphRunResult) -> None:
    if "draft_states" not in st.session_state:
        st.session_state.draft_states = {}
    if "draft_bodies" not in st.session_state:
        st.session_state.draft_bodies = {}

    inbox = result.triaged_inbox
    if not inbox:
        return
    for item in inbox.items:
        if not item.draft_reply:
            continue
        draft = item.draft_reply
        st.session_state.draft_states.setdefault(
            draft.draft_id,
            {
                "status": draft.status.value,
                "sent_message_id": None,
                "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            },
        )
        st.session_state.draft_bodies.setdefault(draft.draft_id, draft.body)


def audit_logger() -> AuditLogger:
    return AuditLogger(log_path=str(AUDIT_PATH))


def triaged_rows(inbox: TriagedInbox) -> List[Dict[str, Any]]:
    rows = []
    for item in sorted(inbox.items, key=lambda i: i.urgency_score, reverse=True):
        full_body = getattr(item, "body_preview", None) or (item.rationale if item.rationale else item.subject)
        preview = full_body[:80] + ("..." if len(full_body) > 80 else "")
        rows.append(
            {
                "Score": item.urgency_score,
                "Urgency": item.urgency.value.upper(),
                "Category": item.category.value.capitalize(),
                "Sender": item.sender,
                "Subject": item.subject,
                "Preview": preview,
                "Full Body": full_body,
                "Draft Generated": "Yes" if item.draft_reply else "No",
                "Action Items": len(item.action_items),
                "Reply Later": "Yes" if item.reply_later else "No",
            }
        )
    return rows


def action_rows(inbox: TriagedInbox) -> List[Dict[str, Any]]:
    rows = []
    for item in inbox.items:
        for action in item.action_items:
            rows.append(
                {
                    "Thread ID": action.thread_id,
                    "Task Description": action.task,
                    "Deadline": action.deadline or "None specified",
                    "Assigned Owner": action.owner,
                    "Confirmed by Faculty": "Yes" if action.confirmed else "No",
                }
            )
    return rows


def followup_rows(inbox: TriagedInbox) -> List[Dict[str, Any]]:
    rows = []
    for item in inbox.items:
        if item.reply_later:
            rows.append(
                {
                    "Follow-up Type": "Reply Later",
                    "Thread ID": item.thread_id,
                    "Subject": item.subject,
                    "Resurface Timing": item.resurface_date or "Next scheduled triage cycle",
                    "Triage Status": "Scheduled for review",
                }
            )
        if item.meeting_request:
            rows.append(
                {
                    "Follow-up Type": "Meeting Request",
                    "Thread ID": item.thread_id,
                    "Subject": item.subject,
                    "Resurface Timing": "; ".join(item.meeting_request.proposed_slots),
                    "Triage Status": "Pending faculty slot approval",
                }
            )
    return rows


# =============================================================================
# Calendar helpers
# =============================================================================

# Accent colors (CSS border accent) keyed by detected event type
_CAL_ACCENT = {
    "meeting":    "#60A5FA",
    "class":      "#34D399",
    "conference": "#A78BFA",
    "deadline":   "#F87171",
    "placement":  "#FB923C",
    "test":       "#FBBF24",
    "hackathon":  "#8B5CF6",
    "event":      "#4ADE80",
    "zoom":       "#38BDF8",
    "other":      "#94A3B8",
}


def _classify_cal_event(summary: str) -> str:
    s = summary.lower()
    if any(k in s for k in ["zoom", "google meet", "teams", "webex", "meet.google"]):
        return "zoom"
    if any(k in s for k in ["deadline", "submission", "due", "approval", "review due"]):
        return "deadline"
    if any(k in s for k in ["placement", "recruitment", "drive", "aptitude", "pre-placement", "ppt", "campus hiring"]):
        return "placement"
    if any(k in s for k in ["hackathon", "hack ", "sprint", "ideathon", "buildathon"]):
        return "hackathon"
    if any(k in s for k in ["test", "quiz", "exam", "assessment", "coding round"]):
        return "test"
    if any(k in s for k in ["conference", "symposium", "workshop", "seminar", "colloquium"]):
        return "conference"
    if any(k in s for k in ["lecture", "tutorial", "lab session", "course", "class "]):
        return "class"
    if any(k in s for k in ["meeting", "meet", "discussion", "sync ", "call", "interview"]):
        return "meeting"
    if any(k in s for k in ["event", "talk", "session", "fest", "day"]):
        return "event"
    return "other"


CAL_TYPE_COLORS = {
    "zoom":       {"bg": "#E0F2FE", "fg": "#0369A1", "border": "#38BDF8"},
    "deadline":   {"bg": "#FEE2E2", "fg": "#B91C1C", "border": "#F87171"},
    "placement":  {"bg": "#FFEDD5", "fg": "#C2410C", "border": "#FB923C"},
    "hackathon":  {"bg": "#EDE9FE", "fg": "#6D28D9", "border": "#A78BFA"},
    "test":       {"bg": "#FEF3C7", "fg": "#A16207", "border": "#FBBF24"},
    "conference": {"bg": "#F3E8FF", "fg": "#7E22CE", "border": "#C084FC"},
    "class":      {"bg": "#DCFCE7", "fg": "#166534", "border": "#4ADE80"},
    "meeting":    {"bg": "#DBEAFE", "fg": "#1D4ED8", "border": "#60A5FA"},
    "event":      {"bg": "#F0FDF4", "fg": "#15803D", "border": "#86EFAC"},
    "other":      {"bg": "#F1F5F9", "fg": "#475569", "border": "#94A3B8"},
}

_MONTH_NAME_TO_INT = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3,
    "april": 4, "apr": 4, "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7,
    "august": 8, "aug": 8, "september": 9, "sep": 9, "october": 10, "oct": 10,
    "november": 11, "nov": 11, "december": 12, "dec": 12,
}


@st.cache_data(ttl=300, show_spinner=False)
def fetch_calendar_events_for_month(year: int, month: int) -> List[Dict[str, Any]]:
    """Fetch Google Calendar events for the given year and month.

    Returns a list of simplified event dicts. Falls back to an empty list if auth is unavailable.
    """
    token_path = ROOT / "token.json"
    creds_path = ROOT / "credentials.json"
    if not (token_path.exists() and creds_path.exists()):
        return []
    try:
        auth = GoogleAuthManager(
            credentials_path=str(creds_path),
            token_path=str(token_path),
        )
        service = auth.get_calendar_service(interactive=False)
        num_days = calendar.monthrange(year, month)[1]
        start_dt = datetime.datetime(year, month, 1, 0, 0, 0, tzinfo=datetime.timezone.utc)
        end_dt = datetime.datetime(year, month, num_days, 23, 59, 59, tzinfo=datetime.timezone.utc)
        resp = (
            service.events()
            .list(
                calendarId="primary",
                maxResults=100,
                singleEvents=True,
                orderBy="startTime",
                timeMin=start_dt.isoformat(),
                timeMax=end_dt.isoformat(),
            )
            .execute()
        )
        events = []
        for e in resp.get("items", []):
            raw_start = e.get("start", {}).get("dateTime") or e.get("start", {}).get("date", "")
            raw_end = e.get("end", {}).get("dateTime") or e.get("end", {}).get("date", "")
            summary = e.get("summary", "(No Title)")
            events.append({
                "summary": summary,
                "start_raw": raw_start,
                "end_raw": raw_end,
                "location": e.get("location", ""),
                "description": (e.get("description") or "")[:200],
                "status": e.get("status", ""),
                "organizer": (e.get("organizer") or {}).get("email", ""),
                "event_type": _classify_cal_event(summary),
                "source": "Google Calendar",
                "event_id": e.get("id", ""),
            })
        return events
    except Exception:
        return []


_STUDENT_PATTERNS = [
    (["placement", "campus recruitment", "hiring drive", "company visit", "pre-placement", "ppt"], "placement"),
    (["aptitude test", "online test", "coding test", "written test", "assessment test"], "test"),
    (["hackathon", "hack event", "buildathon", "ideathon", "code sprint"], "hackathon"),
    (["register", "registration deadline", "last date to register", "registration closes"], "deadline"),
    (["talk", "guest lecture", "expert session", "keynote", "seminar", "workshop"], "event"),
    (["zoom", "google meet", "ms teams", "webex", "online session", "virtual meeting"], "zoom"),
    (["exam", "quiz", "test", "mid-term", "end-term", "internal assessment"], "test"),
]


def extract_calendar_events_for_month(
    inbox: Optional[TriagedInbox],
    year: int,
    month: int,
) -> Dict[int, List[Dict[str, Any]]]:
    """Collect all scheduled events (Google Calendar + Inbox emails) for a given month.

    Returns a dict mapping day_of_month (1..31) -> list of event dicts.
    """
    events_by_day: Dict[int, List[Dict[str, Any]]] = collections.defaultdict(list)
    num_days = calendar.monthrange(year, month)[1]

    # 1. Pull Google Calendar events for this month
    gcal_events = fetch_calendar_events_for_month(year, month)
    for gev in gcal_events:
        raw_start = gev.get("start_raw", "")
        try:
            ev_date = datetime.date.fromisoformat(raw_start[:10])
            if ev_date.year == year and ev_date.month == month and 1 <= ev_date.day <= num_days:
                events_by_day[ev_date.day].append({
                    "summary": gev.get("summary", "Calendar Event"),
                    "event_type": gev.get("event_type", "meeting"),
                    "source": "Google Calendar",
                    "time": raw_start[11:16] if "T" in raw_start else "All Day",
                    "detail": gev.get("location") or gev.get("description") or "",
                })
        except Exception:
            pass

    # 2. Extract events detected from inbox threads
    if inbox and inbox.items:
        for item in inbox.items:
            full_text = item.subject + " " + (item.body_preview or "")
            for msg in getattr(item, "messages", []) or []:
                full_text += " " + (msg.body or msg.snippet or "")
            lower_text = full_text.lower()

            etype = _classify_cal_event(item.subject)
            if etype == "other":
                for keywords, stype in _STUDENT_PATTERNS:
                    if any(kw in lower_text for kw in keywords):
                        etype = stype
                        break
            if etype == "other":
                if any(w in lower_text for w in ["deadline", "last date", "submission", "due", "final list"]):
                    etype = "deadline"
                elif any(w in lower_text for w in ["meeting", "zoom", "meet", "teams"]):
                    etype = "meeting"

            matched_days = set()

            # Pattern A: e.g. "29th september", "29 sep", "september 29"
            for m in re.finditer(r'(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?([a-z]+)', lower_text):
                d_val = int(m.group(1))
                m_word = m.group(2)
                if m_word in _MONTH_NAME_TO_INT and _MONTH_NAME_TO_INT[m_word] == month:
                    if 1 <= d_val <= num_days:
                        matched_days.add(d_val)

            for m in re.finditer(r'([a-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?', lower_text):
                m_word = m.group(1)
                d_val = int(m.group(2))
                if m_word in _MONTH_NAME_TO_INT and _MONTH_NAME_TO_INT[m_word] == month:
                    if 1 <= d_val <= num_days:
                        matched_days.add(d_val)

            # Pattern B: comma-separated list e.g. "3, 6, 7th" or "20, 27, 29th" or "20, 27"
            for m in re.finditer(r'(\d{1,2}(?:\s*,\s*\d{1,2})+)(?:st|nd|rd|th)?', lower_text):
                for part in re.split(r'\s*,\s*', m.group(1)):
                    if part.isdigit():
                        d_val = int(part)
                        if 1 <= d_val <= num_days:
                            matched_days.add(d_val)

            # Pattern C: standalone day mention if the month name is present in subject/text
            month_word = datetime.date(year, month, 1).strftime("%B").lower()
            month_abbr = datetime.date(year, month, 1).strftime("%b").lower()
            if (month_word in lower_text or month_abbr in lower_text) and not matched_days:
                for m in re.finditer(r'\b(\d{1,2})(?:st|nd|rd|th)\b', lower_text):
                    d_val = int(m.group(1))
                    if 1 <= d_val <= num_days:
                        matched_days.add(d_val)

            # If "today" is mentioned and current date matches this month
            today = datetime.date.today()
            if today.year == year and today.month == month and "today" in lower_text:
                if 1 <= today.day <= num_days:
                    matched_days.add(today.day)

            for d in sorted(matched_days):
                existing_titles = [x["summary"] for x in events_by_day[d]]
                if item.subject not in existing_titles:
                    events_by_day[d].append({
                        "summary": item.subject,
                        "event_type": etype,
                        "source": "Inbox",
                        "time": "",
                        "detail": f"Sender: {item.sender}",
                    })

    return events_by_day


def _fmt_cal_datetime(raw: str) -> str:
    """Format a raw ISO datetime/date string into a human-readable label."""
    if not raw:
        return "Time not specified"
    try:
        normalized = raw.replace("Z", "+00:00")
        dt = datetime.datetime.fromisoformat(normalized)
        return dt.strftime("%a, %d %b %Y  %I:%M %p UTC")
    except Exception:
        pass
    # All-day event (date-only)
    try:
        d = datetime.date.fromisoformat(raw[:10])
        return d.strftime("%a, %d %b %Y  (All Day)")
    except Exception:
        return raw


def response_time_metrics(entries: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute lightweight response metrics from audit_log.jsonl timestamps."""
    approval_entries = [
        e for e in entries
        if "approve" in str(e.get("intent", "")).lower()
        or "send" in str(e.get("action", "")).lower()
    ]
    timestamps = []
    for entry in approval_entries:
        try:
            timestamps.append(datetime.datetime.fromisoformat(entry["timestamp"]))
        except Exception:
            pass

    if len(timestamps) < 2:
        return {
            "approved_reply_events": len(timestamps),
            "average_time_to_response_minutes": None,
            "metric_basis": "audit_log.jsonl approval/send timestamps (historical data accumulating)",
        }

    timestamps.sort()
    gaps = [
        (later - earlier).total_seconds() / 60.0
        for earlier, later in zip(timestamps, timestamps[1:])
    ]
    return {
        "approved_reply_events": len(timestamps),
        "average_time_to_response_minutes": round(sum(gaps) / len(gaps), 2),
        "metric_basis": "Average gap between approval/send audit events across runs",
    }


def render_empty_state(icon: str, title: str, description: str) -> None:
    st.markdown(
        f"""
        <div class="saas-empty-state">
            <span class="saas-empty-icon">{icon}</span>
            <div class="saas-empty-title">{html.escape(title)}</div>
            <div class="saas-empty-desc">{html.escape(description)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def gmail_chip(label: str, tone: str = "neutral") -> str:
    color_class = tone if tone in {"urgent", "high", "medium", "low", "admin", "student", "collaborator", "vendor", "pending", "approved", "sent", "draft", "neutral", "tertiary"} else "neutral"

    tooltip_map = {
        "urgent": "Urgent — action is likely time-sensitive and should be reviewed first.",
        "high": "High — important and should be reviewed soon.",
        "medium": "Medium — normal priority within the regular workflow.",
        "low": "Low — informational or lower urgency; can wait.",
        "admin": "Admin — communication from university or administration.",
        "student": "Student — email originated from a student.",
        "collaborator": "Collaborator — academic or internal partner email.",
        "vendor": "Vendor — external partner or recruitment/vendor communication.",
        "pending": "Pending — this item is waiting for review or follow-up.",
        "approved": "Approved — this action has been accepted and is ready.",
        "sent": "Sent — this message was already dispatched.",
        "draft": "Draft — a response is prepared but not yet finalized.",
        "neutral": "Neutral — informational label without a special priority signal.",
        "tertiary": "Tertiary — supporting metadata or context label.",
    }
    tooltip = tooltip_map.get(color_class, "Status label")
    return (
        f'<span class="gmail-chip {color_class}" title="{html.escape(tooltip)}">{html.escape(str(label))}</span>'
    )


def dedupe_chips(chips: List[str]) -> List[str]:
    seen = set()
    unique: List[str] = []
    for chip in chips:
        if not chip:
            continue
        normalized = chip.strip()
        if normalized.lower() in seen:
            continue
        seen.add(normalized.lower())
        unique.append(chip)
    return unique


def render_gmail_row(sender: str, subject: str, preview: str, chips: List[str], timestamp: str, unread: bool = False, details_html: Optional[str] = None, show_checkbox: bool = False) -> None:
    sender_class = "gmail-sender unread" if unread else "gmail-sender"
    clean_chips = dedupe_chips(chips)
    row_html = (
        f'<div class="gmail-row {"unread" if unread else ""}">'
        f'<div class="{sender_class}">{html.escape(sender)}</div>'
        f'<div class="gmail-subject">{html.escape(subject)}<span class="gmail-preview">{html.escape(preview)}</span></div>'
        f'<div class="gmail-chips">{"".join(clean_chips)}</div>'
        f'<div class="gmail-time">{html.escape(timestamp)}</div>'
        '</div>'
    )
    details_block = ""
    if details_html:
        details_block = f'<div class="gmail-details">{details_html}'
        if show_checkbox:
            details_block += (
                '<div class="gmail-confirm-row">'
                '<label class="gmail-action-check"><input type="checkbox" /> Mark Confirmed</label>'
                '</div>'
            )
        details_block += '</div>'
    st.markdown(
        f'<details class="gmail-item"><summary class="gmail-summary">{row_html}</summary>{details_block}</details>',
        unsafe_allow_html=True,
    )


# =============================================================================
# Card-Based Draft Reply Renderer
# =============================================================================

def render_draft_card(item, audit: AuditLogger) -> None:
    draft: DraftReply = item.draft_reply
    state = st.session_state.draft_states[draft.draft_id]
    current_status = state["status"]

    urgency_val = item.urgency.value.lower()
    status_val = current_status.lower()

    if status_val in ["draft", "pending_review", "edited"]:
        status_badge_class = "badge-pending"
        card_class = "saas-card theme-amber"
    elif status_val in ["approved", "sent"]:
        status_badge_class = "badge-approved"
        card_class = "saas-card theme-green"
    elif status_val == "discarded":
        status_badge_class = "badge-discarded"
        card_class = "saas-card"
    else:
        status_badge_class = "badge-draft"
        card_class = "saas-card"

    urgency_badge_class = f"badge-{urgency_val}" if urgency_val in ["urgent", "high", "medium", "low"] else "badge-low"

    with st.container():
        st.markdown(
            f"""
            <div class="{card_class}">
                <div class="draft-card-header">
                    <div>
                        <div class="draft-subject">{html.escape(draft.subject)}</div>
                        <div class="draft-meta">
                            <strong>From:</strong> {html.escape(item.sender)} &nbsp;|&nbsp;
                            <strong>To:</strong> {html.escape(draft.recipient)} &nbsp;|&nbsp;
                            <strong>Thread:</strong> <code>{html.escape(draft.thread_id)}</code>
                        </div>
                    </div>
                    <div>
                        <span class="badge {urgency_badge_class}">{html.escape(item.urgency.value.upper())}</span>
                        <span class="badge {status_badge_class}">{html.escape(current_status.upper())}</span>
                    </div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        col_editor, col_meta = st.columns([7, 3])

        with col_editor:
            edited_body = st.text_area(
                "Proposed Draft Reply (Editable)",
                value=st.session_state.draft_bodies[draft.draft_id],
                key=f"body_{draft.draft_id}",
                height=190,
                label_visibility="visible",
            )
            st.session_state.draft_bodies[draft.draft_id] = edited_body

            # Intent-colored action buttons
            btn_col1, btn_col2, btn_col3 = st.columns([1.2, 1, 1])

            with btn_col1:
                if st.button("Approve & Send", key=f"approve_{draft.draft_id}", type="primary"):
                    try:
                        auth = GoogleAuthManager(
                            credentials_path=str(ROOT / "credentials.json"),
                            token_path=str(ROOT / "token.json"),
                        )
                        gmail = auth.get_gmail_service(interactive=False)
                        authenticated_email = (
                            gmail.users().getProfile(userId="me").execute().get("emailAddress", "").strip().lower()
                        )
                        configured_owner = get_configured_mailbox_owner_email()
                        if not configured_owner or authenticated_email != configured_owner:
                            raise PermissionError(
                                "The connected Google account is not the configured mailbox owner."
                            )
                        guarded = draft.model_copy(
                            update={
                                "body": edited_body,
                                "status": ApprovalStatus.APPROVED,
                                "approved_by": authenticated_email,
                            }
                        )
                        sent = send_email_guarded(
                            gmail_service=gmail,
                            draft=guarded,
                            approver=authenticated_email,
                        )
                        state.update(
                            {
                                "status": "sent",
                                "sent_message_id": sent.get("id"),
                                "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                            }
                        )
                        audit.log(
                            agent="Dashboard",
                            intent="approve_and_send_draft",
                            action="send_email_guarded",
                            input_data={
                                "draft_id": draft.draft_id,
                                "thread_id": draft.thread_id,
                                "approved_by": authenticated_email,
                            },
                            result={"status": "sent", "message_id": sent.get("id")},
                        )
                        st.success(f"Dispatched via guarded approval. Message ID: {sent.get('id')}")
                        st.rerun()
                    except Exception as exc:
                        audit.log(
                            agent="Dashboard",
                            intent="approve_and_send_draft",
                            action="send_email_guarded_failed",
                            input_data={"draft_id": draft.draft_id, "thread_id": draft.thread_id},
                            result={"error": str(exc)},
                            guardrail_passed=False,
                        )
                        st.error(f"Send blocked by guardrail: {exc}")

            with btn_col2:
                if st.button("Save Changes", key=f"edit_{draft.draft_id}"):
                    state.update(
                        {
                            "status": "draft",
                            "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                        }
                    )
                    audit.log(
                        agent="Dashboard",
                        intent="edit_draft",
                        action="save_edit",
                        input_data={"draft_id": draft.draft_id},
                        result={"status": "draft"},
                    )
                    st.info("Draft modifications saved to session.")

            with btn_col3:
                if st.button("Discard", key=f"discard_{draft.draft_id}"):
                    state.update(
                        {
                            "status": "discarded",
                            "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                        }
                    )
                    audit.log(
                        agent="Dashboard",
                        intent="discard_draft",
                        action="discard",
                        input_data={"draft_id": draft.draft_id},
                        result={"status": "discarded"},
                    )
                    st.warning("Draft marked discarded.")
                    st.rerun()

        with col_meta:
            citations_list = "<br>".join([f"• {html.escape(c)}" for c in draft.citations]) if draft.citations else "None"
            st.markdown(
                f"""
                <div class="draft-meta-box">
                    <strong>Category:</strong> {html.escape(item.category.value.capitalize())}<br>
                    <strong>Template:</strong> <code>{html.escape(str(draft.template_used))}</code><br>
                    <strong>Urgency Score:</strong> {item.urgency_score}/100<br>
                    <strong>Rationale:</strong> {html.escape(item.rationale)}<br><br>
                    <strong>Evidence Citations:</strong><br>
                    {citations_list}
                </div>
                """,
                unsafe_allow_html=True,
            )

        st.markdown("<hr style='margin: 1.5rem 0; border: none; border-top: 1px dashed #E2E8F0;'>", unsafe_allow_html=True)


# =============================================================================
# Main Application
# =============================================================================

def main() -> None:
    st.set_page_config(
        page_title="Email Organizer Agent | Faculty Review",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    # Inject SaaS Custom CSS
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

    # ---------------- Sidebar Controls ----------------
    with st.sidebar:
        st.markdown('<div class="sidebar-section-header"><span>⚙️</span>Pipeline Configuration</div>', unsafe_allow_html=True)
        st.markdown(
            '<div class="sidebar-note">Every email is checked, prioritized, and reviewed by you before anything is sent.</div>',
            unsafe_allow_html=True,
        )

        render_google_account_widget()

        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown('<div class="sidebar-section-header"><span>📥</span>Inbox Settings</div>', unsafe_allow_html=True)
        max_results = st.slider(
            "Number of threads to fetch",
            min_value=5,
            max_value=50,
            value=10,
            step=5,
            help="Controls how many recent email threads are pulled in for this triage run. Higher numbers consume more Gmail API quota. Keep at 10 for normal use.",
        )
        if max_results > 15:
            st.caption(f"Fetching {max_results} threads uses ~{max_results + 1} Gmail API calls. If you hit quota limits, lower this value and wait 60 seconds.")
        else:
            st.caption("Keep at 10 for normal use. Higher values consume more Gmail API quota.")

        st.markdown("<br>", unsafe_allow_html=True)
        run_btn = st.button("Run Full Triage Pass", type="primary", use_container_width=True)

        if run_btn:
            with st.spinner(f"Ingesting {max_results} threads, evaluating domain metrics, running graph..."):
                st.session_state.graph_result = build_graph_result(max_results=max_results)

        st.markdown("<br>", unsafe_allow_html=True)

        st.markdown('<div class="sidebar-section-header"><span>🧭</span>How this works</div>', unsafe_allow_html=True)
        workflow_items = [
            ("Connector", "One secure connection reads your inbox, history, and calendar"),
            ("State Machine", "Each email is classified, prioritized, drafted, and validated before you ever see it"),
            ("Guardrails", "Nothing is sent without your explicit approval"),
            ("Audit", "Every action is logged for a full audit trail"),
        ]
        for label, copy in workflow_items:
            st.markdown(
                f"""
                <div class="sidebar-help-item">
                    <div class="sidebar-help-badge">{html.escape(label[:2].upper())}</div>
                    <div class="sidebar-help-copy"><strong>{html.escape(label)}</strong>{html.escape(copy)}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

        st.markdown("<br>", unsafe_allow_html=True)
        with st.expander("View build progress", expanded=False):
            st.markdown("#### PHASE A — Foundations (Labs 1-6) ✓ Complete")
            st.markdown(
                "- Lab 1: Planning loop — clarify, plan, revise\n"
                "- Lab 2: Typed tools — verified data, not guesses\n"
                "- Lab 3: Reusable skills — plan + format, case-agnostic\n"
                "- Lab 4: Memory — session state vs. long-term knowledge\n"
                "- Lab 5: Unified connector — one governed data source\n"
                "- Lab 6: Governed runtime — budgets, audit, checkpoints"
            )

            st.markdown("#### PHASE B — Orchestration (Labs 7-8) ✓ Complete")
            st.markdown(
                "- Lab 7: Full pipeline graph — bounded validation retry\n"
                "- Lab 8: Parallel processing — faster, merged by plan fit"
            )

            st.markdown("#### PHASE C — Reliability (Labs 9-11) ✓ Complete")
            st.markdown(
                "- Lab 9: Evidence grounding — every claim cites a real source\n"
                "- Lab 10: Self-healing — diagnoses and fixes only what failed\n"
                "- Lab 11: Tested builds — nothing advances without passing checks"
            )

            st.markdown("#### PHASE D — Governance & Capstone (Labs 12-14) ✓ Complete")
            st.markdown(
                "- Lab 12: Approval, rollback, and access control\n"
                "- Lab 13: Domain specialists — placement & scheduling handling\n"
                "- Lab 14: Full integrated system (what you're using right now)"
            )

        st.markdown("<br>", unsafe_allow_html=True)
        with st.expander("Learn more", expanded=False):
            st.markdown(
                """
                Technical summary:
                - Connector: unified Gmail/Calendar access layer
                - State Machine: ingest → plan → validate → assemble → approve
                - Guardrails: approval gate required before send
                - Audit: append-only JSONL runtime trail
                """
            )

    # Ensure baseline run exists
    if "graph_result" not in st.session_state:
        with st.spinner("Initializing pipeline and fetching initial inbox snapshot..."):
            st.session_state.graph_result = build_graph_result(max_results=max_results)

    result: GraphRunResult = st.session_state.graph_result
    ensure_state(result)

    audit = audit_logger()
    audit.log(
        agent="Dashboard",
        intent="dashboard_view",
        action="render",
        input_data={"run_id": result.run_id},
        result={"status": result.status, "source_backend": result.source_backend},
    )

    # ---------------- Hero Header ----------------
    backend_label = "Live Gmail API" if result.source_backend == "live_api" else "Benchmark Fixture"

    st.markdown(
        f"""
        <div class="saas-hero">
            <div>
                <h1 class="saas-hero-title">Email Organizer Agent</h1>
                <p class="saas-hero-subtitle">
                    Faculty Mailbox Review & Governed Approval Console &nbsp;•&nbsp; Run ID: <code>{html.escape(result.run_id)}</code>
                </p>
            </div>
            <div>
                <span class="saas-hero-badge">
                    Connected: {backend_label}
                </span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if not result.triaged_inbox:
        st.error(result.error or "Pipeline error: No triaged inbox produced.")
        return

    st.markdown(
        """
        <div class="review-guide">
            <h4>How to review this queue</h4>
            <ul>
                <li>Use the triaged inbox to see which threads matter most by urgency and sender category.</li>
                <li>Review draft replies in the queue as faculty-approved output only; no content sends without the human gate.</li>
                <li>Check action items and follow-ups to capture concrete work, deadlines, and meeting requests.</li>
                <li>Use the audit trail to confirm the pipeline decisions and governance checks for every run.</li>
            </ul>
        </div>
        """,
        unsafe_allow_html=True,
    )

    inbox = result.triaged_inbox
    drafts = [item for item in inbox.items if item.draft_reply]
    actions = action_rows(inbox)
    urgent_count = sum(1 for item in inbox.items if item.urgency.value in ["urgent", "high"])
    pending_approvals = sum(
        1 for d in drafts
        if d.draft_reply and st.session_state.draft_states.get(d.draft_reply.draft_id, {}).get("status") == "draft"
    )

    specialist_summary = getattr(result, "specialist_registry_summary", {}) or {}
    checked_live_items = specialist_summary.get("checked_live_items", 0)
    matched_specialist_items = specialist_summary.get("matched_specialist_items", 0)
    specialist_note = specialist_summary.get("note", "specialist registry not checked")

    st.markdown(
        f"""
        <div class="summary-bar">
            <span class="summary-pill"><strong>{len(inbox.items)}</strong> threads</span>
            <span class="summary-pill"><strong>{urgent_count}</strong> urgent</span>
            <span class="summary-pill"><strong>{pending_approvals}</strong> pending approval</span>
            <span class="summary-pill"><strong>{len(actions)}</strong> actions</span>
            <span class="summary-pill"><strong>Specialists</strong> checked {checked_live_items} / matched {matched_specialist_items}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.caption(specialist_note)

    st.markdown(
        """
        <div class="insight-grid">
            <div class="insight-card">
                <span class="insight-label">Source</span>
                <strong>Live mailbox data</strong>
                <span>Inbox thread fetches and urgent content checks are driven from the connected source.</span>
            </div>
            <div class="insight-card">
                <span class="insight-label">Draft output</span>
                <strong>Faculty review queue</strong>
                <span>Drafts remain in review until the mailbox owner approves or edits them.</span>
            </div>
            <div class="insight-card">
                <span class="insight-label">Action tracking</span>
                <strong>Task + deadline list</strong>
                <span>Concrete action items and commitments are surfaced for the faculty owner.</span>
            </div>
            <div class="insight-card">
                <span class="insight-label">Governance</span>
                <strong>Audit + guardrail</strong>
                <span>Every run remains auditable and blocked from a silent send path.</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.expander("Color guide", expanded=False):
        st.markdown(
            """
            <div class="legend-guide">
                <span class="legend-item"><span class="legend-swatch navy"></span>Coordinator</span>
                <span class="legend-item"><span class="legend-swatch agent"></span>Agent</span>
                <span class="legend-item"><span class="legend-swatch amber"></span>Awaiting Approval</span>
                <span class="legend-item"><span class="legend-swatch green"></span>Published</span>
            </div>
            """,
            unsafe_allow_html=True,
        )

    # ---------------- Tab Navigation ----------------
    tabs = st.tabs([
        "Triaged Inbox",
        "Draft-Reply Queue",
        "Action-Item List",
        "Follow-up Digest",
        "Calendar",
        "Live Audit Trail",
    ])

    # 1. Triaged Inbox Panel
    with tabs[0]:
        st.markdown("### Ranked Inbox Triage")
        st.caption("Prioritized threads with sender category, urgency, and actionability surfaced in a Gmail-like stack.")

        rows = triaged_rows(inbox)
        if rows:
            for row in rows:
                sender = row["Sender"]
                subject = row["Subject"]
                preview = row.get("Preview") or row["Subject"]
                full_body = row.get("Full Body") or row["Subject"]
                chips = [
                    gmail_chip(row["Urgency"].title(), tone=row["Urgency"].lower() if row["Urgency"].lower() in {"urgent", "high", "medium", "low"} else "neutral"),
                    gmail_chip(row["Category"], tone="tertiary" if row["Category"].lower() == "student" else "neutral"),
                ]
                details = (
                    f"<strong>Sender:</strong> {html.escape(sender)}<br>"
                    f"<strong>Subject:</strong> {html.escape(subject)}<br><br>"
                    f"<div style='white-space: pre-wrap;'>{html.escape(full_body)}</div>"
                )
                render_gmail_row(sender, subject, preview, chips, "Today", unread=True, details_html=details)
        else:
            render_empty_state("-", "Inbox Empty", "No threads found matching the search criteria.")

    # 2. Draft-Reply Queue Panel
    with tabs[1]:
        st.markdown("### Draft-Reply Approval Queue")
        st.caption("Draft responses stay in the queue until a faculty owner approves or edits them.")
        if not drafts:
            render_empty_state("-", "No Draft Replies Pending", "All actionable threads have been addressed or no vendor replies needed.")
        else:
            for item in drafts:
                render_draft_card(item, audit)

    # 3. Action-Item List Panel
    with tabs[2]:
        st.markdown("### Action Items & Commitments")
        st.caption("Concrete tasks, deadlines, and ownership extracted from the mailbox threads.")
        if actions:
            for row in actions:
                chips = [gmail_chip("Action", tone="pending")]
                deadline = row["Deadline"] if row["Deadline"] and row["Deadline"] != "None specified" else None
                if deadline:
                    chips.append(gmail_chip(deadline, tone="tertiary"))
                details = (
                    "<div class='detail-metadata'>"
                    f"<div class='detail-field'><span>Thread ID</span><strong>{html.escape(row['Thread ID'])}</strong></div>"
                    f"<div class='detail-field'><span>Task</span><strong>{html.escape(row['Task Description'])}</strong></div>"
                    f"<div class='detail-field'><span>Owner</span><strong>{html.escape(row['Assigned Owner'])}</strong></div>"
                    f"<div class='detail-field'><span>Confirmed</span><strong>{html.escape(row['Confirmed by Faculty'])}</strong></div>"
                    "</div>"
                )
                render_gmail_row(
                    "Faculty Mailbox Owner",
                    row["Task Description"],
                    "Confirm action required",
                    chips,
                    "",
                    unread=False,
                    details_html=details,
                    show_checkbox=True,
                )
        else:
            render_empty_state("-", "No Action Items", "No pending tasks or deadlines detected in current inbox threads.")

    # 4. Follow-up Digest Panel
    with tabs[3]:
        st.markdown("### Follow-up Digest & Response SLA Metrics")
        st.caption("Deferred replies and scheduling requests are grouped into a single review list.")

        rows_followup = followup_rows(inbox)
        if rows_followup:
            st.markdown('<div class="gmail-list">', unsafe_allow_html=True)
            for row in rows_followup:
                chips = [
                    gmail_chip(row["Follow-up Type"], tone="pending"),
                    gmail_chip("Review", tone="neutral"),
                ]
                details = (
                    f"<strong>Follow-up Type:</strong> {html.escape(row['Follow-up Type'])}<br>"
                    f"<strong>Resurface Timing:</strong> {html.escape(row['Resurface Timing'])}<br>"
                    f"<strong>Triage Status:</strong> {html.escape(row['Triage Status'])}"
                )
                render_gmail_row("Follow-up Review", row["Subject"], row["Resurface Timing"], chips, "Scheduled", unread=True, details_html=details)
            st.markdown('</div>', unsafe_allow_html=True)
        else:
            render_empty_state("-", "No Follow-up Items", "No reply-later flags or proposed meeting requests present.")

        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown("#### Historical Response Timing Metrics")
        entries = audit.read_all()
        metrics = response_time_metrics(entries)

        c1, c2 = st.columns(2)
        with c1:
            st.metric("Total Approved/Dispatched Events", metrics["approved_reply_events"])
        with c2:
            avg = metrics["average_time_to_response_minutes"]
            st.metric("Average Turnaround Time", "N/A" if avg is None else f"{avg} min")
        st.caption(f"Basis: {metrics['metric_basis']}")

    # 5. Calendar Panel
    with tabs[4]:
        st.markdown("### 📅 Monthly Schedule & Events Calendar")
        st.caption(
            "Unified monthly calendar combining Google Calendar schedule and events detected from your inbox. "
            "Days with upcoming events are marked; empty days remain unmarked."
        )

        today = datetime.date.today()
        if "cal_year" not in st.session_state:
            st.session_state.cal_year = today.year
        if "cal_month" not in st.session_state:
            st.session_state.cal_month = today.month

        # Month Navigation Row
        nav_col1, nav_col2, nav_col3, nav_col4 = st.columns([1.2, 3.6, 1.2, 1.0])
        with nav_col1:
            if st.button("◀ Previous Month", key="cal_btn_prev", use_container_width=True):
                if st.session_state.cal_month == 1:
                    st.session_state.cal_month = 12
                    st.session_state.cal_year -= 1
                else:
                    st.session_state.cal_month -= 1
                st.rerun()

        with nav_col2:
            current_month_dt = datetime.date(st.session_state.cal_year, st.session_state.cal_month, 1)
            st.markdown(
                f"<div style='text-align:center; font-size:1.25rem; font-weight:700; color:#0F172A; padding-top:4px;'>"
                f"{current_month_dt.strftime('%B %Y')}</div>",
                unsafe_allow_html=True,
            )

        with nav_col3:
            if st.button("Next Month ▶", key="cal_btn_next", use_container_width=True):
                if st.session_state.cal_month == 12:
                    st.session_state.cal_month = 1
                    st.session_state.cal_year += 1
                else:
                    st.session_state.cal_month += 1
                st.rerun()

        with nav_col4:
            if (st.session_state.cal_year, st.session_state.cal_month) != (today.year, today.month):
                if st.button("Today", key="cal_btn_today", use_container_width=True):
                    st.session_state.cal_year = today.year
                    st.session_state.cal_month = today.month
                    st.rerun()

        # Extract events for selected month
        year = st.session_state.cal_year
        month = st.session_state.cal_month
        events_by_day = extract_calendar_events_for_month(inbox, year, month)
        total_events = sum(len(evs) for evs in events_by_day.values())

        # Connection status badge
        acct_email = st.session_state.get("google_account_email") or "Connected Account"
        st.caption(
            f"✅ **Google Calendar Active** ({html.escape(acct_email)}) · "
            f"**{total_events}** event(s) marked for {current_month_dt.strftime('%B %Y')}"
        )

        st.markdown("<div style='margin-bottom:8px;'></div>", unsafe_allow_html=True)

        # Build full month calendar
        cal_matrix = calendar.monthcalendar(year, month)
        weekdays = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

        # Header row
        hcols = st.columns(7)
        for hidx, wname in enumerate(weekdays):
            hcols[hidx].markdown(
                f"<div style='text-align:center; font-weight:700; color:#475569; font-size:0.85rem; padding:4px 0; background:#F8FAFC; border-radius:4px; border:1px solid #E2E8F0;'>"
                f"{wname}</div>",
                unsafe_allow_html=True,
            )

        st.markdown("<div style='margin-bottom:6px;'></div>", unsafe_allow_html=True)

        # Weeks and Days
        for week in cal_matrix:
            wcols = st.columns(7)
            for widx, day in enumerate(week):
                with wcols[widx]:
                    if day == 0:
                        # Blank cell outside month
                        st.markdown(
                            "<div style='min-height:92px; background:#F8FAFC; border:1px dashed #E2E8F0; border-radius:6px; margin-bottom:6px;'></div>",
                            unsafe_allow_html=True,
                        )
                    else:
                        day_events = events_by_day.get(day, [])
                        is_today = (today.year == year and today.month == month and today.day == day)

                        if day_events:
                            # MARKED DAY
                            if is_today:
                                day_badge = f"<span style='background:#2563EB; color:#fff; border-radius:50%; width:22px; height:22px; display:inline-block; text-align:center; line-height:22px; font-size:0.75rem; font-weight:700;'>{day}</span> <span style='font-size:0.65rem; color:#2563EB; font-weight:700;'>TODAY</span>"
                                cell_bg = "#EFF6FF"
                                cell_border = "2px solid #3B82F6"
                            else:
                                day_badge = f"<span style='font-size:0.85rem; font-weight:700; color:#0F172A;'>{day}</span> <span style='display:inline-block; width:8px; height:8px; border-radius:50%; background:#EF4444; margin-left:4px;' title='{len(day_events)} marked event(s)'></span>"
                                cell_bg = "#FEF2F2"
                                cell_border = "1.5px solid #F87171"

                            pills = []
                            for ev in day_events[:2]:
                                etype = ev.get("event_type", "other")
                                col_info = CAL_TYPE_COLORS.get(etype, CAL_TYPE_COLORS["other"])
                                ev_sum = ev.get("summary", "")
                                short_title = html.escape(ev_sum[:24]) + ("..." if len(ev_sum) > 24 else "")
                                full_title = html.escape(ev_sum)
                                bg_c = col_info["bg"]
                                fg_c = col_info["fg"]
                                bd_c = col_info["border"]
                                pills.append(
                                    f"<div style='background:{bg_c}; color:{fg_c}; border-left:3px solid {bd_c}; padding:2px 4px; border-radius:3px; margin-top:3px; font-size:0.68rem; line-height:1.2; font-weight:600; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;' title='{full_title}'>"
                                    f"{short_title}</div>"
                                )
                            if len(day_events) > 2:
                                pills.append(
                                    f"<div style='font-size:0.65rem; color:#B91C1C; font-weight:600; margin-top:2px;'>+{len(day_events)-2} more</div>"
                                )

                            pills_html = "".join(pills)
                            st.markdown(
                                f"<div style='min-height:92px; background:{cell_bg}; border:{cell_border}; border-radius:6px; padding:6px 6px; margin-bottom:6px; box-shadow:0 1px 3px rgba(0,0,0,0.03);'>"
                                f"<div style='margin-bottom:3px;'>{day_badge}</div>{pills_html}</div>",
                                unsafe_allow_html=True,
                            )
                        else:
                            # UNMARKED DAY (Leave clean without cards)
                            if is_today:
                                day_badge = f"<span style='background:#2563EB; color:#fff; border-radius:50%; width:22px; height:22px; display:inline-block; text-align:center; line-height:22px; font-size:0.75rem; font-weight:700;'>{day}</span> <span style='font-size:0.65rem; color:#2563EB; font-weight:700;'>TODAY</span>"
                                st.markdown(
                                    f"<div style='min-height:92px; background:#F8FAFC; border:1.5px solid #93C5FD; border-radius:6px; padding:6px 6px; margin-bottom:6px;'>"
                                    f"<div>{day_badge}</div></div>",
                                    unsafe_allow_html=True,
                                )
                            else:
                                st.markdown(
                                    f"<div style='min-height:92px; background:#FFFFFF; border:1px solid #E2E8F0; border-radius:6px; padding:6px 6px; margin-bottom:6px;'>"
                                    f"<span style='font-size:0.85rem; font-weight:500; color:#94A3B8;'>{day}</span></div>",
                                    unsafe_allow_html=True,
                                )

        # Clean chronological schedule list of marked events below the calendar
        st.markdown("---")
        st.markdown(f"#### 📋 Marked Events for {current_month_dt.strftime('%B %Y')}")
        if total_events > 0:
            marked_rows = []
            for d in sorted(events_by_day.keys()):
                for ev in events_by_day[d]:
                    d_obj = datetime.date(year, month, d)
                    marked_rows.append({
                        "Date": d_obj.strftime("%d %b %Y (%a)"),
                        "Day": d,
                        "Event": ev["summary"],
                        "Type": ev["event_type"].capitalize(),
                        "Source": ev["source"],
                        "Details": ev.get("detail", ""),
                    })
            st.dataframe(
                marked_rows,
                column_config={
                    "Date": st.column_config.TextColumn("Date", width="small"),
                    "Day": None,
                    "Event": st.column_config.TextColumn("Event Title", width="large"),
                    "Type": st.column_config.TextColumn("Category", width="small"),
                    "Source": st.column_config.TextColumn("Source", width="small"),
                    "Details": st.column_config.TextColumn("Details", width="medium"),
                },
                hide_index=True,
                use_container_width=True,
            )
        else:
            st.info(f"No events scheduled or detected for {current_month_dt.strftime('%B %Y')}. All days in this month are currently unmarked.")

    # 6. Live Audit Trail Panel
    with tabs[5]:
        st.markdown("### Live Governed Audit Trail")
        st.caption("This log records the runtime decisions, payloads, checkpoints, and guardrail checks that keep the mailbox-owner approval model auditable.")

        entries = audit.read_all()
        if entries:
            display_entries = list(reversed(entries[-150:]))
            safe_df = safe_audit_dataframe(display_entries)
            st.dataframe(safe_df, width="stretch", hide_index=True)
        else:
            render_empty_state("-", "Audit Log Empty", "No runtime events recorded yet.")


if __name__ == "__main__":
    main()
