"""Lab 7: Agentic Node Graph - the full pipeline.

The graph layer wires the Phase-A components into the Chapter 3 topology:

    ingest -> plan -> workers -> validate
                        ^          |
                        | fail     | pass
                        +----------+
                                   -> assemble -> gate -> publish

Execution, audit, budget, approval, and checkpoint behavior stays inside
Lab 6's GovernedRuntime. This module only owns graph topology and the bounded
validation retry edge.
"""

from __future__ import annotations

import datetime
import uuid
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field

from core.classifier import classify_sender
from core.models import (
    ActionItem,
    ApprovalStatus,
    DraftReply,
    EmailThread,
    MeetingRequest,
    SenderCategory,
    TriagedEmail,
    TriagedInbox,
    UrgencyLevel,
)
from lab02_tools.tools import UrgencyDomainCalculatorTool
from lab03_skills.skills import PlanningSkill, PlanSkillInput, FormattingSkill, TemplateSpec
from lab05_connector.connector import MCPStyleConnector, build_connector
from lab06_runtime.runtime import GovernedRuntime, RuntimeNode, StepStatus
from lab13_specialists.registry import registry
from lab13_specialists.specialists import GenerationAgent
from lab09_grounding.agent import GroundingAgent


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _parse_iso(value: str, default_timezone: datetime.tzinfo = datetime.timezone.utc) -> Optional[datetime.datetime]:
    """Parse an ISO 8601 datetime or date string into a UTC-aware datetime.

    Handles:
    - Full datetime with timezone offset: "2025-10-01T09:00:00+05:30"
    - Full datetime without timezone (assumed UTC): "2025-10-01T09:00:00"
    - Date-only strings (all-day events): "2025-10-01"  → 00:00 UTC that day
    """
    if not value:
        return None
    try:
        # Python 3.7+ fromisoformat doesn't handle trailing Z in older versions
        normalized = value.replace("Z", "+00:00")
        dt = datetime.datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=default_timezone)
        return dt
    except ValueError:
        pass
    try:
        # Fallback: date-only string
        d = datetime.date.fromisoformat(value[:10])
        return datetime.datetime(d.year, d.month, d.day, tzinfo=default_timezone)
    except ValueError:
        return None


class ValidationReport(BaseModel):
    """Validation output for the graph hard gate."""

    passed: bool
    attempt: int
    errors: List[str] = Field(default_factory=list)
    item_count: int = 0
    draft_count: int = 0


class GraphRunResult(BaseModel):
    """Serializable summary of a graph run."""

    run_id: str
    status: str
    triaged_inbox: Optional[TriagedInbox] = None
    validation_report: Optional[ValidationReport] = None
    attempts_used: int = 0
    max_retries: int = 0
    retry_events: List[str] = Field(default_factory=list)
    graph_trace: List[Dict[str, Any]] = Field(default_factory=list)
    formatted_preview: Optional[str] = None
    source_backend: str = "unknown"
    specialist_registry_summary: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None


class AgenticNodeGraph:
    """Explicit Lab 7 graph runner backed by GovernedRuntime."""

    def __init__(
        self,
        connector: Optional[MCPStyleConnector] = None,
        runtime: Optional[GovernedRuntime] = None,
        max_retries: int = 2,
    ):
        self.connector = connector or build_connector()
        self.runtime = runtime or GovernedRuntime(
            run_id=f"lab07-{uuid.uuid4().hex[:8]}",
            audit_path="audit_log.jsonl",
            checkpoint_path="runtime_checkpoint.jsonl",
            total_budget=150.0,
            auto_approve=True,
            approver="Faculty Mailbox Owner",
        )
        self.max_retries = max_retries
        self.state: Dict[str, Any] = {}
        self.retry_events: List[str] = []
        self._registered = False

        self.ingest_node = RuntimeNode(node_id="ingest", name="IngestionClassificationAgent", fn=self._ingest, budget_limit=25.0)
        self.plan_node = RuntimeNode(node_id="plan", name="CoordinatorPlanNode", fn=self._plan, budget_limit=15.0)
        self.workers_node = RuntimeNode(node_id="workers", name="WorkerAgents", fn=self._workers, budget_limit=40.0)
        self.validate_node = RuntimeNode(node_id="validate", name="ValidationGate", fn=self._validate, budget_limit=20.0)
        self.assemble_node = RuntimeNode(node_id="assemble", name="AssemblyNode", fn=self._assemble, budget_limit=20.0)
        self.gate_node = RuntimeNode(
            node_id="gate",
            name="MailboxOwnerGate",
            fn=self._gate_summary,
            requires_approval=True,
            budget_limit=10.0,
        )
        self.publish_node = RuntimeNode(node_id="publish", name="GovernedPublishNode", fn=self._publish, budget_limit=10.0)

    def run(
        self,
        max_results: int = 5,
        query: str = "label:INBOX",
        inject_validation_failure_once: bool = False,
        force_validation_failure: bool = False,
    ) -> GraphRunResult:
        """Run the graph once, including the bounded validation retry edge."""
        self._register_nodes()
        self.state = {
            "query": query,
            "max_results": max_results,
            "inject_validation_failure_once": inject_validation_failure_once,
            "force_validation_failure": force_validation_failure,
            "failure_injected": False,
        }
        self.retry_events = []

        self._run_node(self.ingest_node, {"query": query, "max_results": max_results})
        self._run_node(self.plan_node, {"case_name": "Lab 7 Full Pipeline"})

        validation_report: Optional[ValidationReport] = None
        attempts_used = 0
        max_attempts = self.max_retries + 1

        for attempt in range(1, max_attempts + 1):
            attempts_used = attempt
            self.state["attempt"] = attempt
            self._run_node(self.workers_node, {"attempt": attempt})
            self._run_node(self.validate_node, {"attempt": attempt})
            validation_report = self.state["validation_report"]

            if validation_report.passed:
                break

            if attempt <= self.max_retries:
                event = f"validate --fail--> workers (attempt {attempt}/{max_attempts})"
                self.retry_events.append(event)
                continue

            event = f"bounded retry exhausted after {attempt} attempts"
            self.retry_events.append(event)
            return self._result(
                status="failed_validation",
                attempts_used=attempts_used,
                validation_report=validation_report,
                error="Validation failed after bounded retry budget.",
            )

        self._run_node(self.assemble_node, {})
        gate_result = self._run_node(self.gate_node, {})
        if gate_result.status not in (StepStatus.COMPLETED, StepStatus.APPROVED):
            return self._result(
                status="blocked_at_gate",
                attempts_used=attempts_used,
                validation_report=validation_report,
                error="Mailbox owner gate did not approve the review artifact.",
            )
        self._run_node(self.publish_node, {})

        return self._result(
            status="published_review_artifact",
            attempts_used=attempts_used,
            validation_report=validation_report,
        )

    def _register_nodes(self) -> None:
        if not self._registered:
            self.runtime.register(
                self.ingest_node,
                self.plan_node,
                self.workers_node,
                self.validate_node,
                self.assemble_node,
                self.gate_node,
                self.publish_node,
            )
            self._registered = True

    def _run_node(self, node: RuntimeNode, inputs: Dict[str, Any]) -> Any:
        result = self.runtime.run(step=node, inputs=inputs, cost=5.0)
        if result.status == StepStatus.FAILED:
            raise RuntimeError(f"Graph node {node.node_id} failed: {result.error}")
        return result

    def _ingest(self, query: str, max_results: int) -> Dict[str, Any]:
        inbox_resp = self.connector.read("inbox", query=query, max_results=max_results)
        contacts_resp = self.connector.read("contacts")
        calendar_resp = self.connector.read("calendar", max_results=10)
        sent_resp = self.connector.read("inbox", query="in:sent", max_results=50)
        owner_email = str(sent_resp.metadata.get("authenticated_user", "")).strip().lower()
        owner_replies = []
        if sent_resp.source_backend == "live_api" and owner_email:
            for sent_thread in sent_resp.items:
                for message in sent_thread.messages:
                    if owner_email in message.sender.lower() and message.body.strip():
                        owner_replies.append(
                            {
                                "thread_id": sent_thread.thread_id,
                                "message_id": message.message_id,
                                "subject": message.subject,
                                "recipient": message.recipient,
                                "body": message.body,
                            }
                        )
        self.state["threads"] = inbox_resp.items
        self.state["contacts"] = contacts_resp.items
        self.state["calendar"] = calendar_resp.items
        self.state["owner_replies"] = owner_replies
        self.state["owner_reply_source_backend"] = sent_resp.source_backend
        self.state["source_backend"] = inbox_resp.source_backend
        return {
            "threads": inbox_resp.item_count,
            "contacts": contacts_resp.item_count,
            "calendar_events": calendar_resp.item_count,
            "owner_replies": len(owner_replies),
            "owner_reply_source_backend": sent_resp.source_backend,
            "source_backend": inbox_resp.source_backend,
        }

    def _plan(self, case_name: str) -> Dict[str, Any]:
        plan = PlanningSkill().plan(
            PlanSkillInput(
                case_name=case_name,
                time_window="current connector query",
                scope_filter=self.state.get("query", "label:INBOX"),
                priority_sender_categories=["student", "admin"],
                include_draft_replies=True,
                include_action_item_extraction=True,
                include_calendar_sync=True,
                standard_template_focus="standard_faculty_response",
                custom_rules=["Never send without mailbox owner approval", "Bound validation retries"],
            )
        )
        self.state["plan"] = plan
        return {"plan_id": plan.plan_id, "locked": plan.locked, "steps": len(plan.steps)}

    def _workers(self, attempt: int) -> Dict[str, Any]:
        threads: List[EmailThread] = self.state["threads"]
        contacts: List[Dict[str, Any]] = self.state["contacts"]
        metrics = UrgencyDomainCalculatorTool().compute(threads, contacts)
        if not metrics.valid:
            raise ValueError(f"Domain metrics invalid: {metrics.validation_notes}")

        items = self._build_triaged_items(threads, contacts, metrics.per_thread_scores)
        should_inject = (
            self.state.get("inject_validation_failure_once")
            and not self.state.get("failure_injected")
            and attempt == 1
        )
        if should_inject:
            self.state["failure_injected"] = True

        inbox = TriagedInbox(
            run_id=f"lab07_{uuid.uuid4().hex[:8]}",
            timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            items=items,
            version=1,
            status=ApprovalStatus.DRAFT,
        )
        self.state["triaged_inbox"] = inbox
        self.state["specialist_registry_summary"] = self._specialist_registry_summary(threads)
        return {
            "attempt": attempt,
            "items": len(items),
            "drafts": sum(1 for item in items if item.draft_reply),
            "injected_failure": should_inject,
            "specialist_registry_summary": self.state["specialist_registry_summary"],
        }

    def _validate(self, attempt: int) -> Dict[str, Any]:
        inbox: TriagedInbox = self.state["triaged_inbox"]
        errors: List[str] = []

        if not inbox.items:
            errors.append("Triaged inbox contains no items.")

        for item in inbox.items:
            if item.draft_status_note == "No reply needed — informational":
                continue
            if item.category != SenderCategory.VENDOR and item.draft_reply is None:
                errors.append(f"Missing draft reply for actionable non-vendor thread {item.thread_id}.")
            for action in item.action_items:
                if action.confirmed:
                    errors.append(f"Action item {action.item_id} is incorrectly marked complete.")
            if item.meeting_request and item.meeting_request.confirmed_by_faculty:
                errors.append(f"Meeting request {item.meeting_request.request_id} was confirmed without approval.")

        if self.state.get("force_validation_failure"):
            errors.append("Forced validation failure for bounded retry demonstration.")
        if self.state.get("failure_injected") and attempt == 1:
            errors.append("Injected validation failure for bounded retry demonstration.")

        report = ValidationReport(
            passed=not errors,
            attempt=attempt,
            errors=errors,
            item_count=len(inbox.items),
            draft_count=sum(1 for item in inbox.items if item.draft_reply),
        )
        self.state["validation_report"] = report
        return report.model_dump()

    def _assemble(self) -> Dict[str, Any]:
        inbox: TriagedInbox = self.state["triaged_inbox"]
        template = TemplateSpec(
            template_name="Lab 7 Assembly Preview",
            output_format="markdown",
            header_title="Lab 7 Triaged Inbox with Draft Replies",
        )
        doc = FormattingSkill().format_triaged(inbox, template)
        self.state["formatted_doc"] = doc
        return {"document_id": doc.document_id, "panels": list(doc.panels.keys()), "items": doc.item_count}

    def _gate_summary(self) -> Dict[str, Any]:
        inbox: TriagedInbox = self.state["triaged_inbox"]
        return {
            "pending_review_items": len(inbox.items),
            "draft_replies": sum(1 for item in inbox.items if item.draft_reply),
            "human_gate": "mailbox owner approval required before any send",
        }

    def _publish(self) -> Dict[str, Any]:
        inbox: TriagedInbox = self.state["triaged_inbox"]
        inbox.status = ApprovalStatus.PENDING_REVIEW
        self.state["triaged_inbox"] = inbox
        return {
            "published_artifact": inbox.run_id,
            "status": inbox.status.value,
            "note": "Published to mailbox-owner review queue only; no email sent.",
        }

    def _build_triaged_items(
        self,
        threads: List[EmailThread],
        contacts: List[Dict[str, Any]],
        per_thread_scores: Dict[str, int],
    ) -> List[TriagedEmail]:
        contact_map = {c["contact"].lower(): c for c in contacts}
        items: List[TriagedEmail] = []

        for thread in threads:
            category = self._category_for(thread, contact_map)
            score = per_thread_scores.get(thread.thread_id, 20)
            urgency = self._urgency_for(score)
            body = " ".join(message.body for message in thread.messages)
            lower = f"{thread.subject} {thread.snippet} {body}".lower()
            body_preview = self._body_preview(thread, body)

            action_items = self._action_items(thread, lower)
            meeting_request = self._meeting_request(thread, lower)
            should_reply = UrgencyDomainCalculatorTool.should_generate_reply(thread, category)
            draft_status_note = None
            draft_reply = None
            if category != SenderCategory.VENDOR and should_reply:
                draft_reply = self._draft_reply(thread, category, contact_map)
                draft_reply.evidence_record = self._ground_draft(thread, draft_reply)
            elif category != SenderCategory.VENDOR:
                draft_status_note = "No reply needed — informational"

            items.append(
                TriagedEmail(
                    thread_id=thread.thread_id,
                    subject=thread.subject,
                    sender=thread.sender,
                    category=category,
                    urgency=urgency,
                    urgency_score=score,
                    rationale=f"Score {score}/100 from typed calculator; category={category.value}.",
                    body_preview=body_preview,
                    action_items=action_items,
                    meeting_request=meeting_request,
                    draft_reply=draft_reply,
                    draft_status_note=draft_status_note,
                    reply_later=urgency in (UrgencyLevel.LOW, UrgencyLevel.MEDIUM),
                    resurface_date="Next scheduled triage cycle" if urgency in (UrgencyLevel.LOW, UrgencyLevel.MEDIUM) else None,
                )
            )

        items.sort(key=lambda item: item.urgency_score, reverse=True)
        return items

    def _body_preview(self, thread: EmailThread, body: str) -> str:
        raw = (thread.snippet or body or thread.subject).strip()
        return " ".join(raw.split())

    def _ground_draft(self, thread: EmailThread, draft: DraftReply) -> Dict[str, Any]:
        opening = draft.subject.removeprefix("Re:").strip() or thread.subject
        thread_sender = thread.sender.lower()
        if "<" in thread_sender and ">" in thread_sender:
            thread_sender = thread_sender.split("<", 1)[1].split(">", 1)[0].strip()
        owner_replies = [
            reply
            for reply in self.state.get("owner_replies", [])
            if reply["thread_id"] == thread.thread_id
            or thread_sender in reply.get("recipient", "").lower()
        ]
        prior_reply_texts = [f"{reply['subject']}\n{reply['body']}" for reply in owner_replies]
        grounder = GroundingAgent()
        thread_record = grounder.ground_candidate(
            candidate_id=f"{draft.draft_id}:thread",
            candidate_text=opening,
            threads=[thread],
        )
        owner_reply_record = grounder.ground_candidate(
            candidate_id=f"{draft.draft_id}:owner_reply",
            candidate_text=opening,
            threads=[],
            prior_replies=prior_reply_texts,
        )
        owner_reply_data = owner_reply_record.model_dump()
        if owner_reply_record.source == "prior_reply":
            try:
                reply_index = int(owner_reply_record.source_id.rsplit("_", 1)[1])
                source = owner_replies[reply_index]
                owner_reply_data["source_id"] = source["message_id"]
                owner_reply_data["gmail_thread_id"] = source["thread_id"]
            except (IndexError, ValueError, KeyError):
                owner_reply_data["in_scope"] = False
        evidence = {
            "status": "grounded" if thread_record.in_scope and owner_reply_record.in_scope else "rejected",
            "grounding_text": opening,
            "thread_evidence": thread_record.model_dump(),
            "owner_reply_evidence": owner_reply_data,
            "thread_source_backend": self.state.get("source_backend", "unavailable"),
            "owner_reply_source_backend": self.state.get("owner_reply_source_backend", "unavailable"),
        }
        if evidence["status"] == "grounded":
            draft.citations.extend(
                [
                    f"Grounded in Gmail thread {thread.thread_id}",
                    f"Grounded in mailbox-owner sent message {owner_reply_data['source_id']}",
                ]
            )
        return evidence

    def _category_for(self, thread: EmailThread, contact_map: Dict[str, Dict[str, Any]]) -> SenderCategory:
        sender = thread.sender.lower()
        matched = contact_map.get(sender)
        if matched:
            try:
                return SenderCategory(matched.get("category", "other"))
            except ValueError:
                pass

        # Always route through the same configurable institutional classifier used elsewhere.
        category = classify_sender(thread.sender, contact_map)
        if category != SenderCategory.OTHER:
            return category

        if "student" in sender or ("cs" in sender and ".edu" in sender):
            return SenderCategory.STUDENT
        if "sales" in sender or "promo" in sender or "marketing" in sender:
            return SenderCategory.VENDOR
        return SenderCategory.COLLABORATOR

    def _urgency_for(self, score: int) -> UrgencyLevel:
        if score >= 70:
            return UrgencyLevel.URGENT
        if score >= 45:
            return UrgencyLevel.HIGH
        if score >= 20:
            return UrgencyLevel.MEDIUM
        return UrgencyLevel.LOW

    def _action_items(self, thread: EmailThread, lower_text: str) -> List[ActionItem]:
        action_terms = ["deadline", "due", "submit", "sign", "review", "verify", "approval", "today", "tomorrow"]
        if not any(term in lower_text for term in action_terms):
            return []
        deadline = None
        if "today" in lower_text:
            deadline = "Today"
        elif "tomorrow" in lower_text:
            deadline = "Tomorrow"
        elif "friday" in lower_text:
            deadline = "Friday"
        return [
            ActionItem(
                item_id=f"act_{thread.thread_id[:12]}",
                thread_id=thread.thread_id,
                task=f"Review required action for '{thread.subject}'",
                deadline=deadline,
                owner="Faculty Mailbox Owner",
                confirmed=False,
            )
        ]

    def _meeting_request(self, thread: EmailThread, lower_text: str) -> Optional[MeetingRequest]:
        if not any(term in lower_text for term in ["meeting", "meet", "schedule", "office hours", "slot"]):
            return None

        proposed_slots = self._find_free_slots()
        return MeetingRequest(
            request_id=f"mtg_{thread.thread_id[:12]}",
            thread_id=thread.thread_id,
            sender=thread.sender,
            subject=thread.subject,
            proposed_slots=proposed_slots,
            confirmed_by_faculty=False,
        )

    def _find_free_slots(self) -> List[str]:
        """Query the connector's calendar source and return up to 3 free 1-hour slots.

        Candidate slots are generated for the next 7 working days at 09:00, 11:00,
        and 14:00 in the primary calendar's timezone. Only a complete live event
        response for the candidate window can produce availability proposals.
        """
        cached_slots = self.state.get("calendar_slot_cache")
        if cached_slots is not None:
            return list(cached_slots)

        def fallback(message: str) -> List[str]:
            self.state["calendar_slot_cache"] = [message]
            return [message]

        # Fetch one upcoming event to verify live access and obtain the calendar timezone.
        cal_response = None
        try:
            time_min = datetime.datetime.now(datetime.timezone.utc).isoformat()
            cal_response = self.connector.read("calendar", max_results=1, time_min=time_min)
        except Exception:
            cal_response = None

        if cal_response is None or cal_response.source_backend != "live_api":
            return fallback("Calendar unavailable — no availability was verified; please propose a time manually.")
        if not cal_response.items:
            return fallback("Calendar has no upcoming events — no availability was verified; please propose a time manually.")

        timezone_name = cal_response.metadata.get("time_zone")
        try:
            if not timezone_name:
                raise ZoneInfoNotFoundError("Calendar timezone missing")
            calendar_timezone = ZoneInfo(timezone_name)
        except (ZoneInfoNotFoundError, ValueError):
            return fallback("Calendar timezone unavailable — no availability was verified; please propose a time manually.")

        # Generate the candidate window first, using local calendar dates and hours.
        SLOT_HOURS = [9, 11, 14]  # 9 AM, 11 AM, 2 PM
        now = datetime.datetime.now(calendar_timezone).replace(
            minute=0, second=0, microsecond=0
        )
        candidates: List[datetime.datetime] = []
        day = now.date()
        working_days = 0
        while working_days < 7:
            day += datetime.timedelta(days=1)
            if day.weekday() >= 5:  # skip Saturday/Sunday
                continue
            working_days += 1
            for hour in SLOT_HOURS:
                slot_start = datetime.datetime(
                    day.year, day.month, day.day, hour, 0, 0,
                    tzinfo=calendar_timezone,
                )
                candidates.append(slot_start)

        # Read all pages within the exact proposed window; a truncated response is not trusted.
        window_start = candidates[0].isoformat()
        window_end = (candidates[-1] + datetime.timedelta(hours=1)).isoformat()
        try:
            window_response = self.connector.read(
                "calendar",
                max_results=2500,
                time_min=window_start,
                time_max=window_end,
            )
        except Exception:
            window_response = None
        if window_response is None or window_response.source_backend != "live_api":
            return fallback("Calendar unavailable — no availability was verified; please propose a time manually.")
        if window_response.metadata.get("time_zone") != timezone_name:
            return fallback("Calendar timezone changed during the check — no availability was verified; please propose a time manually.")
        if not window_response.metadata.get("complete", False):
            return fallback("Calendar results were incomplete — no availability was verified; please propose a time manually.")
        if not window_response.items:
            return fallback("No calendar events were returned for the candidate window — availability was not verified; please propose a time manually.")

        # Convert event intervals to UTC so offset/DST transitions compare correctly.
        busy: List[tuple] = []
        for event in window_response.items:
            if event.get("status") == "cancelled" or event.get("transparency") == "transparent":
                continue
            evt_start = _parse_iso(event.get("start", ""), calendar_timezone)
            evt_end = _parse_iso(event.get("end", ""), calendar_timezone)
            if not evt_start or not evt_end or evt_end <= evt_start:
                return fallback("Calendar data could not be verified — please propose a time manually.")
            busy.append((evt_start.astimezone(datetime.timezone.utc), evt_end.astimezone(datetime.timezone.utc)))
        if not busy:
            return fallback("No active busy events were returned — availability was not verified; please propose a time manually.")

        # Filter candidate slots against the complete busy windows.
        free_slots: List[str] = []
        for slot_start in candidates:
            slot_start_utc = slot_start.astimezone(datetime.timezone.utc)
            slot_end_utc = (slot_start + datetime.timedelta(hours=1)).astimezone(datetime.timezone.utc)
            conflict = any(
                s < slot_end_utc and e > slot_start_utc
                for s, e in busy
            )
            if not conflict:
                label = slot_start.strftime("%A %d %b · %I:%M %p")
                free_slots.append(f"Calendar-checked ({timezone_name}): {label}")
            if len(free_slots) == 3:
                break

        # ── 5. Fallback when the queried calendar has no free candidates ──────
        if not free_slots:
            return fallback(
                f"Calendar checked ({timezone_name}) — no free 1-hour slot found in the next 7 working days; "
                "please propose a time manually."
            )
        self.state["calendar_slot_cache"] = free_slots
        return free_slots

    def _specialist_draft_for_thread(self, thread: EmailThread) -> Optional[DraftReply]:
        payload = {
            "sender": thread.sender,
            "subject": thread.subject,
            "body": " ".join(message.body for message in thread.messages),
        }
        for domain_name in registry.domains():
            specialist = registry.get(domain_name)
            if not specialist.detect(payload):
                continue
            try:
                output = GenerationAgent(registry).use(specialist, payload)
            except Exception:
                continue
            return DraftReply(
                draft_id=f"drf_{thread.thread_id[:12]}_{domain_name}",
                thread_id=thread.thread_id,
                recipient=thread.sender,
                subject=f"Re: {thread.subject}",
                body=output.body,
                template_used=output.template_name,
                citations=[f"Thread {thread.thread_id}", f"Live specialist route: {domain_name}"],
                status=ApprovalStatus.DRAFT,
                approved_by=None,
            )
        return None

    def _specialist_registry_summary(self, threads: List[EmailThread]) -> Dict[str, Any]:
        checked_live_items = 0
        matched_domains: List[str] = []
        matched_thread_ids: List[str] = []

        for thread in threads:
            checked_live_items += 1
            matched = self._specialist_draft_for_thread(thread)
            if matched is not None:
                matched_thread_ids.append(thread.thread_id)
                if matched.template_used:
                    matched_domains.append(matched.template_used)

        return {
            "checked_live_items": checked_live_items,
            "matched_specialist_items": len(matched_thread_ids),
            "matched_domains": matched_domains,
            "matched_thread_ids": matched_thread_ids,
            "note": f"checked {checked_live_items} live items against specialist registry, {len(matched_thread_ids)} matched this run",
        }

    def _draft_reply(
        self,
        thread: EmailThread,
        category: SenderCategory,
        contact_map: Dict[str, Dict[str, Any]],
    ) -> DraftReply:
        specialist_draft = self._specialist_draft_for_thread(thread)
        if specialist_draft is not None:
            return specialist_draft

        matched = contact_map.get(thread.sender.lower())
        template = (matched or {}).get("standard_template") or f"{category.value}_standard_response"
        salutation = thread.sender.split("@")[0].replace(".", " ").replace("_", " ").title()
        body = (
            f"Dear {salutation},\n\n"
            f"Thank you for your message regarding '{thread.subject}'. I have reviewed the thread "
            "and will follow up on the relevant action items after checking the supporting context.\n\n"
            "Best regards,\nFaculty Mailbox Owner"
        )
        return DraftReply(
            draft_id=f"drf_{thread.thread_id[:12]}",
            thread_id=thread.thread_id,
            recipient=thread.sender,
            subject=f"Re: {thread.subject}",
            body=body,
            template_used=template,
            citations=[f"Thread {thread.thread_id}", f"Sender {thread.sender}"],
            status=ApprovalStatus.DRAFT,
            approved_by=None,
        )

    def _result(
        self,
        status: str,
        attempts_used: int,
        validation_report: Optional[ValidationReport],
        error: Optional[str] = None,
    ) -> GraphRunResult:
        doc = self.state.get("formatted_doc")
        return GraphRunResult(
            run_id=self.runtime.run_id,
            status=status,
            triaged_inbox=(
                self.state.get("triaged_inbox")
                if status == "published_review_artifact"
                else None
            ),
            validation_report=validation_report,
            attempts_used=attempts_used,
            max_retries=self.max_retries,
            retry_events=self.retry_events,
            graph_trace=self.runtime.step_summary(),
            formatted_preview=(doc.rendered_content[:1200] if doc else None),
            source_backend=self.state.get("source_backend", "unknown"),
            specialist_registry_summary=self.state.get("specialist_registry_summary", {}),
            error=error,
        )


def run_lab07_graph(**kwargs: Any) -> GraphRunResult:
    """Convenience function for demos and the Streamlit dashboard."""
    graph = AgenticNodeGraph(max_retries=kwargs.pop("max_retries", 2))
    return graph.run(**kwargs)
