# Email Organizer Agent

A faculty email triage worklet built through the Agentic AI Worklets 14-lab method. It organizes incoming email by sender and urgency, prepares replies for faculty review, surfaces action items and meeting requests, and keeps the mailbox owner in control of outgoing messages.

## Team

| Name | USN | Division | GitHub username |
|---|---|---|---|
| `Sinchana Hadagali` | `01FE23BCI117` | `B` | `https://github.com/SinchuP` |
| `Manjula Nayak` | `01FE23BCI097` | `B` | `https://github.com/manjulanayak258036` |
| `Tejaswini M. V` | `01FE23BCI044` | `B` | `https://github.com/tejaswini325` |
| `Rakshita R. T` | `01FE23BCI041` | `B` | `https://github.com/RAKSHITART` |


## Project Problem Statement

Faculty inboxes combine administrative deadlines, student questions, meeting requests, collaboration, and routine notices. Manually sorting and prioritizing these messages takes time, can bury important requests, and makes it easy to overlook tasks or follow-ups. Similar questions may also receive inconsistent replies when each response is written from scratch.

This project develops an email-organizing worklet that helps a faculty mailbox owner review incoming messages in a structured queue. It classifies senders, prioritizes messages using deadline and escalation signals, prepares reply drafts, extracts action items, flags follow-ups, and checks meeting requests against calendar events when live calendar data is available. The faculty mailbox owner remains responsible for reviewing drafts and approving any outgoing reply.

## Objectives

- Classify incoming messages by sender category and identify actionable content.
- Rank messages using deadline, urgency, and escalation signals.
- Prepare reply drafts for faculty review.
- Surface tasks, deadlines, commitments, and follow-up items.
- Check candidate meeting times against the connected primary calendar when a complete live calendar response is available.
- Provide a review dashboard and an auditable record of workflow actions.

## Approach and Implementation

The project follows a coordinator-and-workers architecture developed incrementally across 14 labs. A shared connector provides access to Gmail, Calendar, contacts, and stored reference data. A governed runtime records workflow steps, and a node graph coordinates ingestion, planning, triage, validation, assembly, and publication to the review queue.

The main implementation is organized into:

- `core/` - shared authentication, classification, models, and audit support.
- `dashboard/` - Streamlit faculty review dashboard.
- `lab01_agent_loop/` through `lab14_capstone/` - the 14 incremental worklets and demonstrations.
- `CHAPTER_3.md` - the provided problem statement and worklet specification.
- `SUBMISSION.md` - the course submission and lab acceptance matrix.

The dashboard provides views for the triaged inbox, draft replies, action items, follow-ups, calendar, and audit trail. Drafts remain available for review; the send path checks the configured mailbox owner against the authenticated Gmail account before sending.

## Results

The project includes runnable demonstrations for the lab modules and a Streamlit dashboard that can triage live Gmail data when local OAuth configuration is available. The graph validates the triage result before publishing it to the review queue. Calendar suggestions are labeled as calendar-checked only when the live event window is complete and usable; otherwise, the dashboard presents a manual-confirmation message.

## Assignments: 14 Labs

The `Assignments/` folder in the submitted repository contains the lab-wise code for all 14 labs.

| Lab | Topic | Source module |
|---|---|---|
| 01 | Agent vs Chatbot: planning loop | [`lab01_agent_loop/`](./Assignments/lab01_agent_loop/) |
| 02 | Tool-Using Agent | [`lab02_tools/`](./Assignments/lab02_tools/) |
| 03 | Skill Creation | [`lab03_skills/`](./Assignments/lab03_skills/) |
| 04 | Memory and Retrieval | [`lab04_memory/`](./Assignments/lab04_memory/) |
| 05 | MCP-Style Connector | [`lab05_connector/`](./Assignments/lab05_connector/) |
| 06 | Governed Runtime | [`lab06_runtime/`](./Assignments/lab06_runtime/) |
| 07 | Agentic Node Graph | [`lab07_node_graph/`](./Assignments/lab07_node_graph/) |
| 08 | Parallel Swarm | [`lab08_parallel_swarm/`](./Assignments/lab08_parallel_swarm/) |
| 09 | Deep Research and Evidence | [`lab09_grounding/`](./Assignments/lab09_grounding/) |
| 10 | Ops Resilience | [`lab10_self_healing/`](./Assignments/lab10_self_healing/) |
| 11 | SDLC Factory | [`lab11_sdlc_factory/`](./Assignments/lab11_sdlc_factory/) |
| 12 | Safety and Governance | [`lab12_governance/`](./Assignments/lab12_governance/) |
| 13 | Discipline-Specific Agents | [`lab13_specialists/`](./Assignments/lab13_specialists/) |
| 14 | Capstone Integration | [`lab14_capstone/`](./Assignments/lab14_capstone/) |

## Repository Folders and Documents

- [Assignments - all 14 lab folders](./Assignments/)
- [Course Project - complete project folder](./Course%20Project/)
- [Problem statement and worklet details](./Course%20Project/CHAPTER_3.md)
- [Final course project report](./Course%20Project/SUBMISSION.md)

The `Course Project/` folder is intended to contain the complete project folder, including its lab code and supporting files. The `Assignments/` folder separately presents the lab-wise code for grading.

## Running the Project Locally

Install dependencies:

```powershell
python -m pip install -r requirements.txt
```

Run an individual lab demonstration, for example:

```powershell
python lab07_node_graph/demo_lab07.py
```

Run the faculty dashboard:

```powershell
streamlit run dashboard/app.py
```

Live Gmail and Calendar access requires local Google OAuth configuration. Do not commit `credentials.json`, `token.json`, mailbox data, audit logs, or runtime checkpoints.
