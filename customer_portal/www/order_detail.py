import frappe
from frappe.utils import formatdate, format_time, get_datetime
from .get_base_context import get_base_context
from .order_status import portal_order_status

def get_context(context):
    context = get_base_context(context)
    order_name = frappe.form_dict.name
    
    if not order_name:
        frappe.redirect_to_message("Order Not Found", "The requested order could not be found.")
        raise frappe.Redirect
        
    try:
        order = frappe.get_doc("Sales Order", order_name)
    except frappe.DoesNotExistError:
        frappe.redirect_to_message("Order Not Found", "The requested order could not be found.")
        raise frappe.Redirect
        
    if order.customer != context.customer_id:
        frappe.redirect_to_message("Not Authorized", "You are not authorized to view this order.")
        raise frappe.Redirect
        
    context.title = f"Order {order.name}"
    
    context.salesman = "—"
    if order.get("territory"):
        current_territory = order.get("territory")
        territory_manager = None
        
        while current_territory:
            # Check User Permission for this territory
            user_with_permission = frappe.db.get_value("User Permission", 
                {"allow": "Territory", "for_value": current_territory}, 
                "user"
            )
            
            if user_with_permission:
                territory_manager = user_with_permission
                break
                
            current_territory = frappe.db.get_value("Territory", current_territory, "parent_territory")
            
        if territory_manager:
            user_full_name = frappe.db.get_value("User", territory_manager, "full_name")
            context.salesman = user_full_name or territory_manager

    
    order.status = portal_order_status(order)

    context.order = order
    
    context.formatted_date = formatdate(order.transaction_date, "dd MMM yyyy")
    
    # Format amount
    context.formatted_grand_total = frappe.utils.fmt_money(order.grand_total, currency=order.currency)
    context.formatted_total_taxes = frappe.utils.fmt_money(order.total_tax, currency=order.currency)
    context.formatted_net_total = frappe.utils.fmt_money(order.net_total, currency=order.currency)

    # Blended tax rate for display next to "GST" — items can carry different
    # tax templates, so this is derived from the actual totals rather than
    # assumed to be a single fixed rate (previously hardcoded as 18%).
    net_total = frappe.utils.flt(order.net_total)
    total_tax = frappe.utils.flt(order.total_tax)
    context.tax_rate_display = f"{(total_tax / net_total * 100):.0f}%" if net_total else "0%"

    # Fetch Invoice
    invoice = frappe.db.get_value("Sales Invoice", {"sales_order": order.name}, "name")
    context.invoice_name = invoice
    context.is_paid = False
    
    if invoice:
        inv_status = frappe.db.get_value("Sales Invoice", invoice, "status")
        if inv_status == "Paid":
            context.is_paid = True
    else:
        if float(order.get("advance_paid") or 0) >= float(order.grand_total):
            context.is_paid = True
    # Fetch Delivery Note
    delivery = frappe.db.get_value("Delivery Note", {"sales_order": order.name}, "name")
    context.delivery_name = delivery
    
    # Transporter Details (from Delivery Note if exists)
    if delivery:
        dn_doc = frappe.get_doc("Delivery Note", delivery)
        context.transporter = dn_doc.transporter_name or "—"
        context.tracking_no = dn_doc.lr_no or "—"
        context.eta = formatdate(dn_doc.get("lr_date") or order.delivery_date, "dd MMM yyyy") if (dn_doc.get("lr_date") or order.delivery_date) else "—"
    else:
        context.transporter = "—"
        context.tracking_no = "—"
        context.eta = formatdate(order.delivery_date, "dd MMM yyyy") if order.delivery_date else "—"

    # Timeline Logic
    creation_dt = get_datetime(order.creation)
    context.timeline = {
        "placed_date": formatdate(creation_dt, "dd MMM yyyy"),
        "placed_time": creation_dt.strftime("%I:%M %p")
    }
    
    if order.status not in ("Pending Approval", "Cancelled"):
        modified_dt = get_datetime(order.modified)
        context.timeline["confirmed_date"] = formatdate(modified_dt, "dd MMM yyyy")
        context.timeline["confirmed_time"] = modified_dt.strftime("%I:%M %p")
        
    if delivery:
        context.timeline["dispatched_date"] = formatdate(dn_doc.posting_date, "dd MMM yyyy")
        
        pt_str = str(dn_doc.posting_time).split('.')[0]
        try:
            import datetime
            time_obj = datetime.datetime.strptime(pt_str, "%H:%M:%S")
            context.timeline["dispatched_time"] = time_obj.strftime("%I:%M %p")
        except Exception:
            context.timeline["dispatched_time"] = pt_str
            
    return context