import frappe
from frappe.utils import flt, fmt_money, formatdate, format_datetime


def _row(label, value):
    return {"label": label, "value": value if value not in (None, "") else "—"}


def _details(doctype, name):
    """Returns (rows, link, link_label) for the document behind a notification."""
    if doctype == "Sales Order":
        d = frappe.db.get_value("Sales Order", name,
            ["status", "transaction_date", "delivery_date", "grand_total", "currency", "per_delivered", "per_billed"], as_dict=True)
        if not d:
            return [], None, None
        items = frappe.get_all("Sales Order Item", filters={"parent": name},
            fields=["item_name", "qty"], order_by="idx", limit=5)
        rows = [
            _row("Order Date", formatdate(d.transaction_date)),
            _row("Status", d.status),
            _row("Delivery Date", formatdate(d.delivery_date) if d.delivery_date else None),
            _row("Amount", fmt_money(flt(d.grand_total), currency=d.currency or "INR")),
            _row("Items", ", ".join(f"{i.item_name} × {flt(i.qty):g}" for i in items)),
            _row("Delivered", f"{flt(d.per_delivered):g}%"),
            _row("Billed", f"{flt(d.per_billed):g}%"),
        ]
        return rows, f"/portal/sales-orders/{name}", "View Order"

    if doctype == "Delivery Note":
        d = frappe.db.get_value("Delivery Note", name,
            ["posting_date", "status", "transporter_name", "lr_no", "grand_total", "currency"], as_dict=True)
        if not d:
            return [], None, None
        so = frappe.db.get_value("Delivery Note Item", {"parent": name}, "against_sales_order")
        rows = [
            _row("Date", formatdate(d.posting_date)),
            _row("Status", d.status),
            _row("Order", so),
            _row("Transporter", d.transporter_name),
            _row("LR No.", d.lr_no),
        ]
        return rows, f"/delivery-notes/{name}", "View Delivery Note"

    if doctype == "Sales Invoice":
        d = frappe.db.get_value("Sales Invoice", name,
            ["posting_date", "due_date", "status", "grand_total", "outstanding_amount", "currency"], as_dict=True)
        if not d:
            return [], None, None
        cur = d.currency or "INR"
        rows = [
            _row("Invoice Date", formatdate(d.posting_date)),
            _row("Due Date", formatdate(d.due_date) if d.due_date else None),
            _row("Status", d.status),
            _row("Total", fmt_money(flt(d.grand_total), currency=cur)),
            _row("Outstanding", fmt_money(flt(d.outstanding_amount), currency=cur)),
        ]
        return rows, f"/api/method/customer_portal.api.invoices.download_invoice_pdf?invoice_name={name}", "View Invoice PDF"

    if doctype == "Payment Entry":
        d = frappe.db.get_value("Payment Entry", name,
            ["posting_date", "paid_amount", "mode_of_payment", "reference_no"], as_dict=True)
        if not d:
            return [], None, None
        rows = [
            _row("Date", formatdate(d.posting_date)),
            _row("Amount", fmt_money(flt(d.paid_amount), currency="INR")),
            _row("Mode", d.mode_of_payment),
            _row("Reference", d.reference_no),
        ]
        return rows, "/portal/payments", "View Payments"

    if doctype == "Customer Support Request":
        d = frappe.db.get_value("Customer Support Request", name,
            ["subject", "category", "status", "posting_date"], as_dict=True)
        if not d:
            return [], None, None
        rows = [
            _row("Subject", d.subject),
            _row("Category", d.category),
            _row("Status", d.status),
            _row("Raised On", formatdate(d.posting_date) if d.posting_date else None),
        ]
        return rows, "/support", "View Support"

    return [], None, None


@frappe.whitelist()
def open_notification(name):
    """Mark one notification as read and return its details. Only the owner may open it."""
    log = frappe.db.get_value("Notification Log", name,
        ["name", "for_user", "subject", "email_content", "document_type", "document_name", "creation", "read"],
        as_dict=True)
    if not log or log.for_user != frappe.session.user:
        frappe.throw("Not Authorized", frappe.PermissionError)

    if not log.read:
        frappe.db.set_value("Notification Log", name, "read", 1, update_modified=False)
        frappe.db.commit()

    rows, link, link_label = ([], None, None)
    if log.document_type and log.document_name:
        try:
            rows, link, link_label = _details(log.document_type, log.document_name)
        except Exception:
            frappe.log_error(frappe.get_traceback(), "Portal notification detail failed")

    unread = frappe.db.count("Notification Log", {
        "for_user": frappe.session.user, "read": 0, "type": ["not in", ["Email"]]})

    return {
        "subject": log.subject,
        "message": frappe.utils.strip_html(log.email_content or ""),
        "time": format_datetime(log.creation, "dd MMM yyyy, h:mm a"),
        "doctype": log.document_type,
        "docname": log.document_name,
        "rows": rows,
        "link": link,
        "link_label": link_label,
        "new_tab": bool(link and link.startswith("/api/")),
        "unread_count": unread,
    }


@frappe.whitelist()
def delete_notification(name):
    """Delete one notification. Only the owner can delete it, and only after it has been read."""
    log = frappe.db.get_value("Notification Log", name, ["for_user", "read"], as_dict=True)
    if not log or log.for_user != frappe.session.user:
        frappe.throw("Not Authorized", frappe.PermissionError)
    if not log.read:
        frappe.throw("Open the notification before deleting it")
    frappe.db.delete("Notification Log", {"name": name})
    frappe.db.commit()
    return 1


@frappe.whitelist()
def delete_read_notifications():
    """Delete all read notifications of the current user."""
    names = frappe.get_all("Notification Log", pluck="name", filters={
        "for_user": frappe.session.user, "read": 1, "type": ["not in", ["Email"]]})
    for n in names:
        frappe.db.delete("Notification Log", {"name": n})
    frappe.db.commit()
    return len(names)
