from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, Request

from app.api.deps import get_current_user
from app.api.tickets import staff_role
from app.schemas.auth import UserRole

router = APIRouter(prefix="/analytics", tags=["analytics"])


def _group_counts(tickets: Any, query: dict[str, Any], field: str) -> dict[str, int]:
    grouped = tickets.aggregate([
        {"$match": query},
        {"$group": {"_id": f"${field}", "count": {"$sum": 1}}},
    ])
    return {str(row["_id"] or "unassigned"): row["count"] for row in grouped}


def _group_counts_by_day(tickets: Any, query: dict[str, Any]) -> list[dict[str, Any]]:
    grouped = tickets.aggregate([
        {"$match": query},
        {"$group": {
            "_id": {"$dateToString": {"format": "%Y-%m-%d", "date": "$created_at"}},
            "count": {"$sum": 1},
        }},
        {"$sort": {"_id": 1}},
    ])
    values = {row["_id"]: row["count"] for row in grouped}
    today = datetime.now(timezone.utc).date()
    return [
        {"date": (today - timedelta(days=offset)).isoformat(), "count": values.get((today - timedelta(days=offset)).isoformat(), 0)}
        for offset in range(13, -1, -1)
    ]


def _average_resolution_hours(tickets: Any, query: dict[str, Any]) -> float | None:
    rows = list(tickets.aggregate([
        {"$match": {**query, "resolved_at": {"$ne": None}}},
        {"$group": {
            "_id": None,
            "average_milliseconds": {
                "$avg": {"$subtract": ["$resolved_at", "$created_at"]},
            },
            "resolved_count": {"$sum": 1},
        }},
    ]))
    if not rows or rows[0]["resolved_count"] == 0:
        return None
    return round(rows[0]["average_milliseconds"] / 3_600_000, 2)


def _recent_tickets(tickets: Any, query: dict[str, Any], limit: int = 5) -> list[dict[str, Any]]:
    return [
        {
            "id": str(ticket["_id"]),
            "ticket_number": ticket["ticket_number"],
            "subject": ticket["subject"],
            "status": ticket["status"],
            "priority": ticket["priority"],
            "updated_at": ticket["updated_at"],
            "customer_name": ticket["customer_name"],
        }
        for ticket in tickets.find(query).sort("updated_at", -1).limit(limit)
    ]


@router.get("/dashboard")
def dashboard_analytics(
    request: Request,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    database = request.app.state.mongo_client[request.app.state.settings.mongodb_database]
    tickets = database["tickets"]
    users = database["users"]
    user_id = current_user["_id"]

    if current_user["role"] == UserRole.CUSTOMER.value:
        query = {"customer_id": user_id}
        status_counts = _group_counts(tickets, query, "status")
        recent = _recent_tickets(tickets, query)
        total = tickets.count_documents(query)
        return {
            "role": "customer",
            "metrics": {
                "total_tickets": total,
                "open_tickets": sum(status_counts.get(key, 0) for key in ("open", "in_progress", "pending_customer")),
                "resolved_tickets": status_counts.get("resolved", 0) + status_counts.get("closed", 0),
            },
            "status_distribution": status_counts,
            "recent_tickets": recent,
        }

    if current_user["role"] == UserRole.AGENT.value:
        assigned_query = {"assigned_agent_id": user_id}
        available_query = {"$or": [{"assigned_agent_id": user_id}, {"assigned_agent_id": None}]}
        assigned_status = _group_counts(tickets, assigned_query, "status")
        visible_status = _group_counts(tickets, available_query, "status")
        priorities = _group_counts(tickets, available_query, "priority")
        visible_total = tickets.count_documents(available_query)
        open_count = sum(assigned_status.get(key, 0) for key in ("open", "in_progress"))
        pending_count = assigned_status.get("pending_customer", 0)
        resolved_count = assigned_status.get("resolved", 0) + assigned_status.get("closed", 0)
        return {
            "role": "agent",
            "metrics": {
                "assigned_tickets": tickets.count_documents(assigned_query),
                "unassigned_tickets": tickets.count_documents({"assigned_agent_id": None}),
                "open_tickets": open_count,
                "pending_customer": pending_count,
                "resolved_tickets": resolved_count,
            },
            "priority_distribution": priorities,
            "status_distribution": visible_status,
            "recent_tickets": _recent_tickets(tickets, available_query),
            "workload": {
                "visible_ticket_count": visible_total,
                "assigned_ticket_count": tickets.count_documents(assigned_query),
            },
        }

    all_tickets: dict[str, Any] = {}
    statuses = _group_counts(tickets, all_tickets, "status")
    priorities = _group_counts(tickets, all_tickets, "priority")
    workload_rows = list(tickets.aggregate([
        {"$match": {"assigned_agent_id": {"$ne": None}}},
        {"$group": {
            "_id": "$assigned_agent_id",
            "agent_name": {"$first": "$assigned_agent_name"},
            "ticket_count": {"$sum": 1},
            "open_count": {"$sum": {"$cond": [{"$in": ["$status", ["open", "in_progress"]]}, 1, 0]}},
        }},
        {"$sort": {"ticket_count": -1}},
        {"$limit": 20},
    ]))
    trends = _group_counts_by_day(tickets, {
        "created_at": {"$gte": datetime.now(timezone.utc) - timedelta(days=13)},
    })
    return {
        "role": "admin",
        "metrics": {
            "total_tickets": tickets.count_documents({}),
            "open_tickets": sum(statuses.get(key, 0) for key in ("open", "in_progress")),
            "pending_customer": statuses.get("pending_customer", 0),
            "resolved_tickets": statuses.get("resolved", 0) + statuses.get("closed", 0),
            "critical_tickets": priorities.get("critical", 0),
            "total_customers": users.count_documents({"role": UserRole.CUSTOMER.value, "is_active": True}),
            "total_agents": users.count_documents({"role": UserRole.AGENT.value, "is_active": True}),
            "average_resolution_hours": _average_resolution_hours(tickets, all_tickets),
        },
        "status_distribution": statuses,
        "priority_distribution": priorities,
        "ticket_trends": trends,
        "agent_workload": [
            {
                "agent_id": str(row["_id"]),
                "agent_name": row.get("agent_name") or "Support agent",
                "ticket_count": row["ticket_count"],
                "open_count": row["open_count"],
            }
            for row in workload_rows
        ],
        "recent_tickets": _recent_tickets(tickets, all_tickets),
    }
