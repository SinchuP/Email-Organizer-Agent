"""Google OAuth 2.0 and API Service Manager for Gmail and Google Calendar.

Enforces:
1. Real OAuth2 Desktop Installed-App Flow (browser consent, token.json caching).
2. Hard Guardrails in code:
   - gmail.send is NEVER invoked without explicit human approval (status == APPROVED and approver named).
   - Inbox access is strictly scoped to the authenticated mailbox (userId='me').
"""

from __future__ import annotations
import os
import json
import datetime
from pathlib import Path
from typing import Optional, Dict, Any

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

from core.models import DraftReply, ApprovalStatus

# Full required OAuth scopes
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events",
]

DEFAULT_CREDENTIALS_PATH = "credentials.json"
DEFAULT_TOKEN_PATH = "token.json"
DEFAULT_INSTITUTION_CONFIG_PATH = Path(__file__).resolve().parent.parent / "institution_config.json"


def get_configured_mailbox_owner_email() -> str:
    """Return the configured mailbox owner identity, failing closed if absent."""
    try:
        with DEFAULT_INSTITUTION_CONFIG_PATH.open("r", encoding="utf-8") as config_file:
            owner_email = json.load(config_file).get("mailbox_owner_email", "")
    except (OSError, json.JSONDecodeError):
        return ""
    return str(owner_email).strip().lower()


class GoogleAuthManager:
    def __init__(
        self,
        credentials_path: str = DEFAULT_CREDENTIALS_PATH,
        token_path: str = DEFAULT_TOKEN_PATH,
    ):
        self.credentials_path = Path(credentials_path)
        self.token_path = Path(token_path)
        self.creds: Optional[Credentials] = None

    def get_credentials(self, interactive: bool = True) -> Credentials:
        """Load or refresh credentials; opens browser flow if token.json is absent."""
        if self.token_path.exists():
            try:
                self.creds = Credentials.from_authorized_user_file(str(self.token_path), SCOPES)
            except Exception as e:
                print(f"[Auth] Notice: Existing token.json could not be parsed: {e}")
                self.creds = None

        # If there are no valid credentials available, let the user log in.
        if not self.creds or not self.creds.valid:
            if self.creds and self.creds.expired and self.creds.refresh_token:
                try:
                    self.creds.refresh(Request())
                    print("[Auth] Credentials refreshed successfully.")
                except Exception as e:
                    print(f"[Auth] Refresh token failed: {e}. Requesting re-authorization...")
                    self.creds = None

            if not self.creds:
                if not self.credentials_path.exists():
                    raise FileNotFoundError(
                        f"OAuth credentials file '{self.credentials_path}' not found in project root. "
                        "Please place credentials.json in the project root."
                    )
                if not interactive:
                    raise RuntimeError("Authentication required but interactive browser flow is disabled.")

                print("[Auth] Opening browser window for Google OAuth 2.0 authorization...")
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(self.credentials_path), SCOPES
                )
                self.creds = flow.run_local_server(port=0)

            # Save the credentials for the next run
            with open(self.token_path, "w", encoding="utf-8") as token_file:
                token_file.write(self.creds.to_json())
            print(f"[Auth] Token saved securely to {self.token_path}")

        return self.creds

    def get_gmail_service(self, interactive: bool = True):
        creds = self.get_credentials(interactive=interactive)
        return build("gmail", "v1", credentials=creds)

    def get_calendar_service(self, interactive: bool = True):
        creds = self.get_credentials(interactive=interactive)
        return build("calendar", "v3", credentials=creds)


def create_calendar_event_guarded(
    calendar_service,
    gmail_service,
    summary: str,
    start_datetime: datetime.datetime,
    end_datetime: datetime.datetime,
    timezone_name: str,
    description: str = "",
) -> Dict[str, Any]:
    """Create a primary-calendar event only for the authenticated mailbox owner."""
    if not summary or not start_datetime or not end_datetime:
        raise ValueError("Calendar event summary and start/end times are required.")
    if end_datetime <= start_datetime:
        raise ValueError("Calendar event end time must be after its start time.")

    expected_owner = get_configured_mailbox_owner_email()
    if not expected_owner:
        raise PermissionError("GUARDRAIL VIOLATION: The configured mailbox owner is missing.")

    actual_account = (
        gmail_service.users()
        .getProfile(userId="me")
        .execute()
        .get("emailAddress", "")
        .strip()
        .lower()
    )
    if not actual_account or actual_account != expected_owner:
        raise PermissionError(
            "GUARDRAIL VIOLATION: The authenticated account does not match the configured mailbox owner."
        )

    event = {
        "summary": summary,
        "description": description,
        "start": {
            "dateTime": start_datetime.isoformat(),
            "timeZone": timezone_name,
        },
        "end": {
            "dateTime": end_datetime.isoformat(),
            "timeZone": timezone_name,
        },
    }
    return (
        calendar_service.events()
        .insert(calendarId="primary", body=event)
        .execute()
    )


def create_calendar_reminder_guarded(
    calendar_service,
    gmail_service,
    summary: str,
    due_datetime: datetime.datetime,
    timezone_name: str,
    reminder_minutes: int = 15,
    description: str = "",
) -> Dict[str, Any]:
    """Create a short primary-calendar reminder for the authenticated mailbox owner."""
    if not summary or not due_datetime:
        raise ValueError("Reminder summary and due time are required.")
    if reminder_minutes not in {15, 30, 60}:
        raise ValueError("Reminder must be 15, 30, or 60 minutes before due time.")

    expected_owner = get_configured_mailbox_owner_email()
    if not expected_owner:
        raise PermissionError("GUARDRAIL VIOLATION: The configured mailbox owner is missing.")

    actual_account = (
        gmail_service.users()
        .getProfile(userId="me")
        .execute()
        .get("emailAddress", "")
        .strip()
        .lower()
    )
    if not actual_account or actual_account != expected_owner:
        raise PermissionError(
            "GUARDRAIL VIOLATION: The authenticated account does not match the configured mailbox owner."
        )

    event = {
        "summary": f"Reminder: {summary}",
        "description": description,
        "start": {
            "dateTime": due_datetime.isoformat(),
            "timeZone": timezone_name,
        },
        "end": {
            "dateTime": (due_datetime + datetime.timedelta(minutes=15)).isoformat(),
            "timeZone": timezone_name,
        },
        "reminders": {
            "useDefault": False,
            "overrides": [
                {"method": "popup", "minutes": reminder_minutes},
                {"method": "email", "minutes": reminder_minutes},
            ],
        },
    }
    return (
        calendar_service.events()
        .insert(calendarId="primary", body=event)
        .execute()
    )


def send_email_guarded(
    gmail_service,
    draft: DraftReply,
    approver: str,
    override_token: Optional[str] = None,
) -> Dict[str, Any]:
    """Strictly guarded email sending function.

    GUARDRAIL ENFORCEMENT IN CODE:
    - Never send an email without explicit faculty (human) approval.
    - Status MUST be ApprovalStatus.APPROVED.
    - Approver MUST match the authenticated Gmail profile and configured mailbox owner.
    """
    if draft.status != ApprovalStatus.APPROVED:
        raise PermissionError(
            f"GUARDRAIL VIOLATION: Attempted to send email draft '{draft.draft_id}' with status '{draft.status}'. "
            "Emails can only be dispatched after explicit Faculty Approval."
        )

    expected_owner = get_configured_mailbox_owner_email()
    if not expected_owner or not approver:
        raise PermissionError(
            "GUARDRAIL VIOLATION: The configured mailbox owner and verified approver are required."
        )

    if approver.strip().lower() != expected_owner or (draft.approved_by or "").strip().lower() != expected_owner:
        raise PermissionError(
            "GUARDRAIL VIOLATION: The approved-by identity must match the configured mailbox owner."
        )

    actual_account = (
        gmail_service.users()
        .getProfile(userId="me")
        .execute()
        .get("emailAddress", "")
        .strip()
        .lower()
    )
    if not actual_account or actual_account != expected_owner:
        raise PermissionError(
            "GUARDRAIL VIOLATION: The authenticated Gmail account does not match the configured mailbox owner."
        )

    import base64
    from email.mime.text import MIMEText

    message = MIMEText(draft.body)
    message["to"] = draft.recipient
    message["subject"] = draft.subject
    raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")

    result = (
        gmail_service.users()
        .messages()
        .send(userId="me", body={"raw": raw_message, "threadId": draft.thread_id})
        .execute()
    )
    return result
