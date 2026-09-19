import frappe
from frappe.utils import flt, formatdate, getdate, nowdate
from .get_base_context import get_base_context

def get_context(context):
    context = get_base_context(context)
    context.title = "Payments"

    order_param = frappe.form_dict.get("order")
    invoice_param = frappe.form_dict.get("invoice")
    
    today = getdate(nowdate())
    total_outstanding = 0
    invoices = []
    
    if order_param:
        context.payment_type = "Order Advance"
        so = frappe.get_doc("Sales Order", order_param)
        if so.customer != context.customer_id:
            frappe.throw("Not Authorized", frappe.PermissionError)
            
        advance_paid = flt(so.get("advance_paid"))
        outstanding = flt(so.grand_total) - advance_paid
        
        invoices.append(frappe._dict({
            "name": so.name,
            "due_date": so.delivery_date,
            "formatted_due_date": formatdate(so.delivery_date, "dd MMM yyyy") if so.delivery_date else "—",
            "outstanding_amount": outstanding,
            "outstanding_formatted": frappe.utils.fmt_money(outstanding, precision=0),
            "display_status": "Advance Required",
            "status_color": "var(--primary)"
        }))
        total_outstanding = outstanding
    else:
        context.payment_type = "Invoice Payment"
        filters = {"customer": context.customer_id, "docstatus": 1, "status": ["in", ["Unpaid", "Overdue", "Partly Paid"]]}
        
        if invoice_param:
            filters["name"] = invoice_param
            
        # Calculate totals across ALL unpaid invoices
        inv_list = frappe.get_all(
            "Sales Invoice",
            filters=filters,
            fields=["name", "posting_date", "due_date", "grand_total", "outstanding_amount", "status", "currency"],
            order_by="due_date asc"
        )
        
        total_outstanding = sum(flt(i.outstanding_amount) for i in inv_list)
        context.total_invoices_count = len(inv_list)
        
        for inv in inv_list:
            inv.formatted_due_date = formatdate(inv.due_date, "dd MMM yyyy") if inv.due_date else "—"
            inv.is_overdue = inv.due_date and getdate(inv.due_date) < today
            inv.outstanding_formatted = frappe.utils.fmt_money(inv.outstanding_amount, precision=0)
            
            # Format the status label for display
            if inv.is_overdue:
                inv.display_status = "Overdue"
                inv.status_color = "var(--danger)"
            elif inv.status == "Partly Paid":
                inv.display_status = f"Partial — ₹{inv.outstanding_formatted} remaining"
                inv.status_color = "var(--neutral-400)"
            else:
                inv.display_status = f"Due {formatdate(inv.due_date, 'dd MMM')}"
                inv.status_color = "var(--neutral-400)"
                
            invoices.append(inv)
            
    context.unpaid_invoices = invoices
    context.total_outstanding = frappe.utils.fmt_money(total_outstanding, precision=0)
    if context.payment_type == "Order Advance":
        context.total_invoices_count = 1
        
    company = None
    if invoices and context.payment_type == "Invoice Payment":
        first_inv = frappe.get_doc("Sales Invoice", invoices[0].name)
        company = first_inv.company
    elif context.payment_type == "Order Advance" and order_param:
        company = frappe.db.get_value("Sales Order", order_param, "company")
    else:
        invoice_docs = frappe.get_all(
            "Sales Invoice",
            filters={"customer": context.customer_id, "docstatus": 1, "outstanding_amount": [">", 0]},
            limit=1,
            fields=["company"]
        )
        company = invoice_docs[0].company if invoice_docs else None

    context.company = company

    if company:
        bank_accts = frappe.get_all(
            "Bank Account",
            filters={"company": company},
            fields=["name", "account_name", "gl_account", "bank_name", "account_number", "branch", "ifsc_code"]
        )
        for ba in bank_accts:
            ba.account = ba.get("gl_account") or ""
            ba.bank = ba.get("bank_name") or ""
            ba.bank_account_no = ba.get("account_number") or ""
            ba.branch_code = ba.get("branch") or ""
            ba.ifsc_code = ba.get("ifsc_code") or ""

        context.bank_accounts = bank_accts
        context.company_currency = frappe.db.get_single_value("Books Settings", "default_currency") or "INR"

    
    # Also fetch recent Payment Entries for Payment History
    try:
        history_limit = int(frappe.form_dict.get("history_limit", 5))
    except (ValueError, TypeError):
        history_limit = 5

    payment_filters = {"party_type": "Customer", "party": context.customer_id, "docstatus": 1}
    context.total_history_count = frappe.db.count("Payment Entry", filters=payment_filters)
    context.history_limit = history_limit
    context.has_more_history = False
    
    payment_entries = frappe.get_all(
        "Payment Entry",
        filters=payment_filters,
        fields=["name", "payment_date", "reference_no", "paid_amount"],
        order_by="payment_date desc",
        limit_page_length=history_limit + 1
    )
    
    if len(payment_entries) > history_limit:
        context.has_more_history = True
        payment_entries = payment_entries[:history_limit]
    
    for pe in payment_entries:
        pe.formatted_date = formatdate(pe.payment_date, "dd MMM yy")
        pe.amount_formatted = frappe.utils.fmt_money(pe.paid_amount, precision=0)
        pe.ref_label = pe.reference_no if pe.reference_no else pe.name
        pe.status_label = "Cleared"
        
    context.payment_history = payment_entries

    return context
