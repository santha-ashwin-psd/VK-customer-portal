"""Portal notifications: creates Notification Log entries for customer portal users."""
import frappe
from frappe.utils import flt, fmt_money, nowdate, add_days, getdate


def get_portal_users(customer):
    """All users who can log in to the portal for this customer."""
    users = set(frappe.get_all(
        "Portal User", filters={"parent": customer, "parenttype": "Customer"}, pluck="user"))
    contacts = frappe.get_all(
        "Dynamic Link",
        filters={"link_doctype": "Customer", "link_name": customer, "parenttype": "Contact"},
        pluck="parent")
    for c in contacts:
        email = frappe.db.get_value("Contact", c, "email_id")
        if email and frappe.db.exists("User", email):
            users.add(email)
    return [u for u in users if u not in ("Guest", "Administrator")]


def _send(customer, subject, doctype, name, content=None, dedupe=False):
    if not customer:
        return
    for user in get_portal_users(customer):
        if dedupe and frappe.db.exists("Notification Log", {
                "for_user": user, "document_type": doctype,
                "document_name": name, "subject": subject}):
            continue
        try:
            frappe.get_doc({
                "doctype": "Notification Log",
                "for_user": user,
                "type": "Alert",
                "document_type": doctype,
                "document_name": name,
                "subject": subject,
                "email_content": content,
            }).insert(ignore_permissions=True)
        except Exception:
            frappe.log_error(frappe.get_traceback(), "Portal notification failed")


def _amt(doc):
    return fmt_money(flt(doc.grand_total), currency=doc.get("currency") or "INR")


# ---------- Sales Order ----------
def so_after_insert(doc, method=None):
    # Only notify on insert if the order is being held (credit limit / advance)
    if doc.docstatus == 0 and (doc.get("requires_advance_payment") or doc.get("credit_limit_breached")):
        _send(doc.customer, f"Order {doc.name} received and is pending approval", "Sales Order", doc.name,
              f"Amount: {_amt(doc)}")

def so_on_submit(doc, method=None):
    _send(doc.customer, f"Order {doc.name} placed successfully", "Sales Order", doc.name,
          f"Amount: {_amt(doc)}", dedupe=True)

def so_on_cancel(doc, method=None):
    _send(doc.customer, f"Order {doc.name} has been cancelled", "Sales Order", doc.name, dedupe=True)

def so_on_update_after_submit(doc, method=None):
    before = doc.get_doc_before_save()
    if before and before.status != doc.status and doc.status in ("Completed", "Closed", "On Hold"):
        _send(doc.customer, f"Order {doc.name} is now {doc.status}", "Sales Order", doc.name)


# ---------- Delivery Note ----------
def dn_on_submit(doc, method=None):
    extra = f" via {doc.transporter_name}" if doc.get("transporter_name") else ""
    lr = f" (LR: {doc.lr_no})" if doc.get("lr_no") else ""
    _send(doc.customer, f"Delivery Note {doc.name} created — your order is dispatched{extra}{lr}",
          "Delivery Note", doc.name)

def dn_on_cancel(doc, method=None):
    _send(doc.customer, f"Delivery Note {doc.name} has been cancelled", "Delivery Note", doc.name)


# ---------- Sales Invoice ----------
def inv_on_submit(doc, method=None):
    due = f", due {frappe.utils.formatdate(doc.due_date)}" if doc.get("due_date") else ""
    _send(doc.customer, f"Invoice {doc.name} generated for {_amt(doc)}{due}", "Sales Invoice", doc.name)

def inv_on_cancel(doc, method=None):
    _send(doc.customer, f"Invoice {doc.name} has been cancelled", "Sales Invoice", doc.name)

def inv_on_update_after_submit(doc, method=None):
    before = doc.get_doc_before_save()
    if before and flt(before.outstanding_amount) > 0 and flt(doc.outstanding_amount) <= 0:
        _send(doc.customer, f"Invoice {doc.name} is fully paid", "Sales Invoice", doc.name)


# ---------- Payment Entry ----------
def pe_on_submit(doc, method=None):
    if doc.get("party_type") == "Customer" and doc.get("payment_type") == "Receive":
        amt = fmt_money(flt(doc.paid_amount), currency=doc.get("paid_from_account_currency") or "INR")
        _send(doc.party, f"Payment {doc.name} of {amt} received. Thank you!", "Payment Entry", doc.name)


# ---------- Support ----------
def support_on_update(doc, method=None):
    before = doc.get_doc_before_save()
    if before and before.status != doc.status:
        _send(doc.customer, f"Your ticket {doc.name} is now {doc.status}", "Customer Support Request", doc.name)


# ---------- Scheduler: due soon / overdue ----------
def daily_invoice_reminders():
    today = nowdate()
    rows = frappe.get_all(
        "Sales Invoice",
        filters={"docstatus": 1, "outstanding_amount": [">", 0], "due_date": ["<=", add_days(today, 3)]},
        fields=["name", "customer", "due_date", "outstanding_amount", "currency"])
    for r in rows:
        amt = fmt_money(flt(r.outstanding_amount), currency=r.currency or "INR")
        if getdate(r.due_date) < getdate(today):
            subj = f"Invoice {r.name} is overdue — {amt} outstanding"
        else:
            subj = f"Invoice {r.name} is due on {frappe.utils.formatdate(r.due_date)} — {amt}"
        _send(r.customer, subj, "Sales Invoice", r.name, dedupe=True)