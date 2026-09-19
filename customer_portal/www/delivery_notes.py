import frappe
from frappe.utils import formatdate
from .get_base_context import get_base_context

def get_context(context):
    context = get_base_context(context)
    context.title = "Delivery Notes"
    
    # Filters
    search_q = frappe.form_dict.get("search", "")
    status_filter = frappe.form_dict.get("status", "")
    time_filter = frappe.form_dict.get("time", "all_time")
    date_filter = frappe.form_dict.get("date", "")
    
    try:
        limit = int(frappe.form_dict.get("limit", 10))
    except (ValueError, TypeError):
        limit = 10

    filters = {"customer": context.customer_id, "docstatus": 1}
    
    if status_filter and status_filter != "All Statuses":
        filters["status"] = status_filter
        
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
    if search_q:
        or_filters = [
            ["name", "like", f"%{search_q}%"],
            ["lr_no", "like", f"%{search_q}%"]
        ]
        context.total_count = len(frappe.get_all("Delivery Note", filters=filters, or_filters=or_filters, pluck="name"))
        delivery_notes = frappe.get_all(
            "Delivery Note",
            filters=filters,
            or_filters=or_filters,
            fields=["name", "posting_date", "transporter_name", "lr_no", "status", "sales_order"],
            order_by="posting_date desc",
            limit_page_length=limit + 1
        )
    else:
        context.total_count = frappe.db.count("Delivery Note", filters=filters)
        delivery_notes = frappe.get_all(
            "Delivery Note",
            filters=filters,
            fields=["name", "posting_date", "transporter_name", "lr_no", "status", "sales_order"],
            order_by="posting_date desc",
            limit_page_length=limit + 1
        )
    
    if len(delivery_notes) > limit:
        context.has_more = True
        delivery_notes = delivery_notes[:limit]

    for dn in delivery_notes:
        dn.date = formatdate(dn.posting_date, "dd MMM yyyy")
        
        # Count items
        items_count = frappe.db.count("Delivery Note Item", {"parent": dn.name})
        dn.total_items = f"{items_count} items"

        # Alias for template compatibility
        dn.transporter = dn.get("transporter_name") or ""

        # Get Sales Order reference
        so_ref = dn.get("sales_order")
        dn.order_ref = so_ref if so_ref else "—"

        # Set ETA based on Sales Order delivery_date
        if so_ref:
            so_delivery_date = frappe.db.get_value("Sales Order", so_ref, "delivery_date")
            dn.eta = formatdate(so_delivery_date, "dd MMM yyyy") if so_delivery_date else "—"
        else:
            dn.eta = "—"
        
        # Map status to a user-friendly format
        if dn.status == "Completed":
            dn.status_badge = "Delivered"
        elif dn.status in ["To Bill", "In Transit", "Partially Billed"]:
            dn.status_badge = "Shipped"
        elif dn.status == "Return":
            dn.status_badge = "Returned"
        else:
            dn.status_badge = "Pending"
    
    context.delivery_notes = delivery_notes
    return context