#!/usr/bin/env python3
"""Regenerate the curated graphify module wiki at graphify-out/wiki/.

Reads the existing graphify-out/graph.json (run `graphify update .` first to
refresh it from code — AST only, no LLM). Filters to Aira-product communities
(backend/ frontend/ docs/), drops claude-flow harness noise + singletons, and
applies readable labels.

Labels are keyed by each community's DOMINANT SOURCE FILE, not community id, so
they survive re-clustering (community ids shift on every `graphify update`).

Usage:  python scripts/build_wiki.py
"""
import json, os, re
from collections import Counter, defaultdict
from pathlib import Path

import networkx as nx
from networkx.readwrite import json_graph
from graphify.cluster import score_all
from graphify.analyze import god_nodes
from graphify.wiki import to_wiki

ROOT = Path(__file__).resolve().parent.parent
GRAPH = ROOT / "graphify-out" / "graph.json"
OUT = ROOT / "graphify-out" / "wiki"

AIRA = ("backend/", "frontend/", "docs/")
EXCLUDE_BASENAMES = {"package.json", "package-lock.json", "tsconfig.json"}
MIN_NODES = 5

# Nice labels for modules where the auto-derived name is poor or ambiguous.
# Keyed by dominant relative source path; applied to the LARGEST community whose
# dominant file matches (so meta_cloud.py's main client wins over the carousel
# sub-cluster, which falls back to the auto label).
FILE_OVERRIDE = {
    "backend/app/routes/follow_ups.py": "Follow-ups & Callback Scheduling API",
    "backend/app/services/assignment.py": "Telecaller Assignment Engine",
    "backend/app/routes/assignment_log.py": "Assignment Log & Leaderboard",
    "backend/app/routes/calls.py": "Calls API (TeleCMI dialer)",
    "backend/app/routes/callers.py": "Callers CRUD & Coaching",
    "backend/app/services/ai_reply.py": "AI Reply Pipeline (Gemini)",
    "backend/app/services/knowledge_service.py": "Knowledge Base (pgvector RAG)",
    "backend/app/services/automation_engine.py": "Bot Flow / Automation Engine",
    "backend/app/services/scoring_engine.py": "Score Engine v2 & Segmentation",
    "backend/app/services/lead_scorer.py": "Legacy Lead Scorer",
    "backend/app/services/meta_cloud.py": "Meta Cloud API Client",
    "backend/app/routes/webhook.py": "WhatsApp Inbound Webhook",
    "backend/app/routes/facebook.py": "Facebook / Webhook Verification",
    "backend/app/routes/instagram.py": "Instagram Channel",
    "backend/app/routes/telegram.py": "Telegram Channel",
    "backend/app/routes/upload.py": "CSV Upload & Bulk Send",
    "backend/app/services/broadcast_executor.py": "Broadcast Executor & Outbound Router",
    "backend/app/services/delivery_status.py": "Delivery Status Tracking",
    "backend/app/services/failover.py": "Quality Failover",
    "backend/app/services/booking_flow.py": "Booking Flow",
    "backend/app/services/payment_razorpay.py": "Razorpay Payments",
    "backend/app/services/reengagement_service.py": "Reengagement Service",
    "backend/app/services/voice_router.py": "Voice Router (TeleCMI)",
    "backend/app/services/call_digest.py": "Caller Daily Digest",
    "backend/app/services/flow_runtime.py": "Flow Runtime (pause/resume)",
    "backend/app/services/autopilot.py": "Autopilot & AI Agent Runtime",
    "backend/app/routes/automations.py": "Automations API",
    "backend/app/routes/ctwa_leads.py": "CTWA Leads",
    "backend/app/routes/inbound_leads.py": "Inbound Lead Reporting",
    "backend/app/routes/operator.py": "Operator Console & Audit",
    "backend/app/routes/chat_handovers.py": "Chat Handovers (escalation pool)",
    "backend/app/routes/tags.py": "Broadcast Tags",
    "backend/app/routes/numbers.py": "Phone Numbers Pool",
    "backend/app/routes/voice_numbers.py": "Voice Numbers Pool",
    "backend/app/routes/lead_notes.py": "Lead Notes",
    "backend/app/models/schemas.py": "Pydantic Schemas",
    "backend/app/main.py": "App Entry & Schedulers",
    "frontend/lib/api.ts": "API Client (frontend)",
    "frontend/app/dashboard/automations/[id]/flow/Canvas.tsx": "Bot Flow Builder Canvas",
    "frontend/components/lead-details-panel.tsx": "Lead Details Panel",
    "frontend/components/conversation-list.tsx": "Conversation List UI",
}


def title(s: str) -> str:
    return re.sub(r"[_\-]+", " ", s).strip().title()


def auto_label(p: str) -> str:
    base = os.path.basename(p)
    stem = re.sub(r"\.(py|tsx?|jsx?|md|html)$", "", base)
    if "/routes/" in p:
        return f"{title(stem)} API"
    if "/services/" in p:
        return f"{title(stem)} Service"
    if "/tests/" in p:
        return f"Tests: {title(stem.replace('test_', ''))}"
    if "/models/" in p:
        return f"{title(stem)} (Models)"
    if p.endswith("main.py"):
        return "App Entry & Schedulers"
    if "/dashboard/" in p and base.startswith("page"):
        seg = re.search(r"/dashboard/([^/]+)/", p)
        return f"{title(seg.group(1))} Page" if seg else "Dashboard Page"
    if "/flow/" in p:
        return f"Bot Flow UI: {title(stem)}"
    if "/components/" in p:
        return f"{title(stem)} Component"
    if p.startswith("docs/"):
        m = re.search(r"\d{4}-\d{2}-\d{2}-(.+?)(-design)?$", stem)
        return f"Spec: {title(m.group(1))}" if m else f"Doc: {title(stem)}"
    if base.endswith((".tsx", ".ts")):
        return f"{title(stem)} (frontend)"
    return title(stem)


def main() -> None:
    if not GRAPH.exists():
        raise SystemExit(f"missing {GRAPH} — run `graphify update .` first")

    g = json.loads(GRAPH.read_text(encoding="utf-8"))
    G = json_graph.node_link_graph(g, edges="links")

    by_comm = defaultdict(list)
    for n in g["nodes"]:
        by_comm[n.get("community")].append(n)

    def path_of(n):
        return n.get("source_file") or n.get("source") or ""

    rows = []  # (size, cid, node_ids, dominant_path)
    for cid, ns in by_comm.items():
        if cid is None or len(ns) < MIN_NODES:
            continue
        paths = [path_of(n) for n in ns]
        aira = [p for p in paths if p.startswith(AIRA)]
        if len(aira) < len(ns) * 0.5:
            continue
        dom = Counter(aira).most_common(1)[0][0]
        if os.path.basename(dom) in EXCLUDE_BASENAMES:
            continue
        rows.append((len(ns), int(cid), [n["id"] for n in ns], dom))

    rows.sort(reverse=True)  # largest first → override applies to biggest per file
    communities, labels, used_override = {}, {}, set()
    for _size, cid, ids, dom in rows:
        communities[cid] = ids
        if dom in FILE_OVERRIDE and dom not in used_override:
            labels[cid] = FILE_OVERRIDE[dom]
            used_override.add(dom)
        else:
            labels[cid] = auto_label(dom)

    cohesion = score_all(G, communities)
    gods = god_nodes(G)
    count = to_wiki(G, communities, OUT, community_labels=labels,
                    cohesion=cohesion, god_nodes_data=gods)
    print(f"Wiki: {count} articles across {len(communities)} Aira-product "
          f"communities -> {OUT.relative_to(ROOT)}/")


if __name__ == "__main__":
    main()
