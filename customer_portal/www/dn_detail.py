import frappe
from frappe.utils import formatdate
from .get_base_context import get_base_context

def get_context(context):
    context = get_base_context(context)
    dn_name = frappe.form_dict.name
    
    if not dn_name:
        frappe.redirect_to_message("Delivery Note Not Found", "The requested delivery note could not be found.")
        raise frappe.Redirect
        
    try:
        dn = frappe.get_doc("Delivery Note", dn_name)
    except frappe.DoesNotExistError:
        frappe.redirect_to_message("Delivery Note Not Found", "The requested delivery note could not be found.")
        raise frappe.Redirect
        
    if dn.customer != context.customer_id:
        frappe.redirect_to_message("Not Authorized", "You are not authorized to view this delivery note.")
        raise frappe.Redirect
        
    context.title = f"Delivery Note {dn.name}"
    
    if dn.status == "Completed":
        dn.status_badge = "Delivered"
    elif dn.status in ["To Bill", "In Transit", "Partially Billed"]:
        dn.status_badge = "Shipped"
    elif dn.status == "Return":
        dn.status_badge = "Returned"
    else:
        dn.status_badge = "Pending"
        
    context.dn = dn
    context.formatted_date = formatdate(dn.posting_date, "dd MMM yyyy")
    
    so_ref = dn.get("sales_order")
    context.so_ref = so_ref or "—"
    
    if so_ref:
        so_delivery_date = frappe.db.get_value("Sales Order", so_ref, "delivery_date")
        context.eta = formatdate(so_delivery_date, "dd MMM yyyy") if so_delivery_date else "—"
    else:
        context.eta = "—"
        
    return context
