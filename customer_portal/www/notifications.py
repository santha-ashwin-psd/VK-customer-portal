import frappe
from frappe.utils import format_datetime, get_datetime
from .get_base_context import get_base_context

def get_context(context):
    context = get_base_context(context)
    user = frappe.session.user

    context.pathname = "/notifications"
    context.title = "Notifications"

    all_notifications = []

    # Notification Log (latest, read + unread)
    notification_logs = frappe.get_all("Notification Log",
        filters={"for_user": user, "type": ["not in", ["Email"]]},
        fields=["name", "subject", "email_content", "document_type", "document_name", "read", "creation", "type"],
        order_by="creation desc",
        limit=50
    )
    for n in notification_logs:
        n.time_formatted = format_datetime(n.creation, "dd MMM yyyy, h:mm a")
        n.timestamp = get_datetime(n.creation)
        all_notifications.append(n)

    # Sort all by timestamp desc
    all_notifications = sorted(all_notifications, key=lambda k: k.timestamp, reverse=True)

    context.notifications = all_notifications[:50]
    return context
