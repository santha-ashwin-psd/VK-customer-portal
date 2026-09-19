import frappe
from frappe.utils import formatdate, fmt_money

def get_context(context):
    """
    Get the context for the My Profile page.
    """
    user = frappe.session.user
    # Get the current contact
    contact_name = frappe.db.get_value("Contact", {"user": user}, "name")
    if not contact_name:
        contact_name = frappe.db.get_value("Contact", {"email_id": user}, "name")

    customer_id = None
    if contact_name:
        # Get customer linked to the contact via Dynamic Link
        customer_id = frappe.db.get_value(
            "Dynamic Link",
            {"parenttype": "Contact", "parent": contact_name, "link_doctype": "Customer"},
            "link_name",
        )
        
    if not customer_id:
        customer_id = frappe.db.get_value("Portal User", {"user": user, "parenttype": "Customer"}, "parent")
        
    if not customer_id:
        frappe.throw("Customer not found for the current user.", frappe.DoesNotExistError)
    
    context.customer_id = customer_id
    context.pathname = "/my-profile"
    
    # Fetch customer and contact details
    customer = frappe.get_doc("Customer", customer_id)
    contact = frappe.get_doc("Contact", contact_name) if contact_name else None
    
    context.customer = customer
    context.contact = contact
    
    # Format data for display
    context.customer_since = formatdate(customer.creation, "MMM yyyy")
    credit_limit = customer.credit_limit or 0
    context.credit_limit = fmt_money(credit_limit, currency=customer.default_currency or "INR")
    
    # Get additional details
    if customer.territory:
        current_territory = customer.territory
        territory_manager = None
        
        while current_territory:
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
        else:
            context.salesman = None
    else:
        context.salesman = None
        
    # Get PAN number from customer
    context.pan_number = customer.tax_id or ""

    return context