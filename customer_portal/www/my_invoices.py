import frappe
from frappe.utils import formatdate, getdate, nowdate
from .get_base_context import get_base_context

def get_context(context):
    context = get_base_context(context)
    context.title = "Invoices"

    # Filters
    search_q = frappe.form_dict.get("search", "")
    status_filter = frappe.form_dict.get("status", "")
    time_filter = frappe.form_dict.get("time", "all_time")
    
    try:
        limit = int(frappe.form_dict.get("limit", 10))
    except (ValueError, TypeError):
        limit = 10
    
    filters = {"customer": context.customer_id, "docstatus": 1}
    
    if status_filter and status_filter != "All Statuses":
        filters["status"] = status_filter
        
    date_filter = frappe.form_dict.get("date", "")
    
    if date_filter:
        filters["posting_date"] = date_filter
    elif time_filter and time_filter != "all_time":
        from frappe.utils import add_months, get_first_day, get_last_day, today
        if time_filter == "this_month":
            filters["posting_date"] = ["between", [get_first_day(today()), get_last_day(today())]]
        elif time_filter == "last_3_months":
            filters["posting_date"] = ["between", [get_first_day(add_months(today(), -3)), get_last_day(today())]]
        elif time_filter == "this_year":
            from datetime import datetime
            current_year = datetime.now().year
            filters["posting_date"] = ["between", [f"{current_year}-01-01", f"{current_year}-12-31"]]

    context.limit = limit
    context.has_more = False
    context.total_count = frappe.db.count("Sales Invoice", filters=filters)
        
    invoices = frappe.get_all(
        "Sales Invoice",
        filters=filters,
        fields=["name", "posting_date", "due_date", "grand_total", "outstanding_amount", "status", "currency", "po_no", "is_return"],
        order_by="posting_date desc",
        limit_page_length=limit + 1
    )
    
    if len(invoices) > limit:
        context.has_more = True
        invoices = invoices[:limit]
    
    if search_q:
        invoices = [inv for inv in invoices if search_q.lower() in inv.name.lower() or (inv.po_no and search_q.lower() in inv.po_no.lower())]

    today = getdate(nowdate())
    
    # KPI calculations for all filtered invoices, not just the paginated page
    all_kpi_invoices = frappe.get_all("Sales Invoice", filters=filters, fields=["grand_total", "outstanding_amount", "due_date"])
    total_billed = 0
    total_paid = 0
    outstanding = 0
    outstanding_count = 0
    overdue = 0
    
    for inv in all_kpi_invoices:
        total_billed += inv.grand_total
        paid_amt = inv.grand_total - inv.outstanding_amount
        total_paid += paid_amt
        
        if inv.outstanding_amount > 0:
            outstanding += inv.outstanding_amount
            outstanding_count += 1
            if inv.due_date and getdate(inv.due_date) < today:
                overdue += inv.outstanding_amount
                
    for inv in invoices:
        # Formatting for UI
        paid_amt = inv.grand_total - inv.outstanding_amount
        if inv.is_return:
            paid_amt = 0
            
        inv.formatted_date = formatdate(inv.posting_date, "dd MMM yyyy")
        inv.formatted_due_date = formatdate(inv.due_date, "dd MMM yyyy") if inv.due_date else "—"
        inv.is_overdue = inv.due_date and getdate(inv.due_date) < today and inv.outstanding_amount > 0 and not inv.is_return
        inv.paid_amount = paid_amt

        # Map the doctype's raw status ("Submitted", "Paid", "Cancelled", ...)
        # to the portal's own vocabulary that the badge rendering expects.
        if inv.is_return:
            pass  # rendered as "Credit Note" regardless of status
        elif inv.is_overdue:
            inv.status = "Overdue"
        elif inv.outstanding_amount <= 0:
            inv.status = "Paid"
        elif inv.outstanding_amount < inv.grand_total:
            inv.status = "Partly Paid"
        else:
            inv.status = "Unpaid"
        
        # order ref
        if not inv.po_no:
            si_item = frappe.db.get_value("Sales Invoice", inv.name, "sales_order")
            inv.order_ref = si_item if si_item else "—"
        else:
            inv.order_ref = inv.po_no
            
    def format_kpi(amount):
        if amount >= 100000:
            return f"₹{amount/100000:.1f}L"
        return frappe.utils.fmt_money(amount)
        
    context.kpi = {
        "total_billed": format_kpi(total_billed),
        "total_paid": format_kpi(total_paid),
        "outstanding": format_kpi(outstanding),
        "outstanding_count": outstanding_count,
        "overdue": format_kpi(overdue) if overdue >= 100000 else frappe.utils.fmt_money(overdue, precision=0)
    }
    
    context.invoices = invoices
    return context
