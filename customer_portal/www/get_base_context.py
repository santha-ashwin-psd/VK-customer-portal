import frappe
from frappe.utils import nowdate, flt

def get_base_context(context):
    user = frappe.session.user
    if user == "Guest":
        frappe.local.flags.redirect_location = "/login?redirect-to=/portal"
        raise frappe.Redirect

    context.no_cache = 1
    context.title = "Customer Portal - VK Herbals"
    
    user_doc = frappe.get_doc("User", user)
    context.user_name = user_doc.full_name
    context.customer_id = "Not Linked"

    # 1. Fetch Contact & Customer
    contact = frappe.db.get_value("Contact", {"email_id": user}, ["name", "first_name", "last_name"], as_dict=True)
    cust = None
    if contact:
        cust = frappe.db.get_value("Dynamic Link", 
            {"parent": contact.name, "parenttype": "Contact", "link_doctype": "Customer"}, 
            "link_name"
        )
    
    if not cust:
        cust = frappe.db.get_value("Portal User", {"user": user, "parenttype": "Customer"}, "parent")
        
    if not cust:
        context.error = "No customer linked to this account."
        return context
        
    import re
    # Fetch Customer Document
    customer_doc = frappe.get_doc("Customer", cust)
    context.customer_id = cust
    context.display_customer_id = re.sub(r"CUST-\d{4}-", "CUST-", cust) if cust else cust
    context.customer_name = customer_doc.customer_name
    if user_doc.last_login:
        context.last_login = "Today, " + frappe.utils.format_datetime(user_doc.last_login, "h:mm a")
    else:
        context.last_login = ""
        
    context.is_account_locked = customer_doc.get("is_account_locked")
    context.lock_reason = customer_doc.get("lock_reason")
    
    # 2. Fetch KPIs
    inv = frappe.db.sql("""
        SELECT
            SUM(outstanding_amount)                                  AS total_outstanding,
            SUM(CASE WHEN due_date < %s THEN outstanding_amount ELSE 0 END) AS overdue_amount,
            COUNT(*)                                                 AS inv_count,
            SUM(CASE WHEN due_date < %s THEN 1 ELSE 0 END)           AS overdue_count
        FROM `tabSales Invoice`
        WHERE customer = %s AND docstatus = 1 AND outstanding_amount > 0
    """, (nowdate(), nowdate(), cust), as_dict=True)[0]
    company = frappe.db.get_single_value("Books Settings", "default_company")
    
    try:
        limit_info = frappe.db.get_value("Customer Credit Limit", {"parent": cust, "company": company}, ["credit_limit", "bypass_credit_limit_check"], as_dict=True) or {}
    except Exception:
        limit_info = {}
    
    credit_limit = flt(limit_info.get("credit_limit"))
    ignore_so = limit_info.get("bypass_credit_limit_check", 0)
    
    try:
        from erpnext.selling.doctype.customer.customer import get_customer_outstanding
        outstanding = get_customer_outstanding(cust, company, ignore_outstanding_sales_order=ignore_so)
    except ImportError:
        outstanding = flt(inv.total_outstanding)
        
    avail_credit = max(credit_limit - outstanding, 0)
    util_pct = (outstanding / credit_limit * 100) if credit_limit else 0
    
    sales = frappe.db.sql("""
        SELECT SUM(grand_total)
        FROM `tabSales Order`
        WHERE customer = %s AND docstatus = 1
          AND MONTH(transaction_date) = MONTH(CURDATE())
          AND YEAR(transaction_date)  = YEAR(CURDATE())
    """, cust)[0][0] or 0
    
    # Fetch sales target from a custom field on Customer, fallback to 500000 if not set
    sales_target = flt(frappe.db.get_value("Customer", cust, "dealer_monthly_target")) if frappe.db.has_column("Customer", "dealer_monthly_target") else 500000
    achievement_pct = min((sales / sales_target * 100) if sales_target else 0, 100)
    
    context.total_outstanding = outstanding
    context.invoice_outstanding = flt(inv.total_outstanding)
    context.unbilled_orders_amount = max(0, outstanding - flt(inv.total_outstanding))
    context.overdue_amount = flt(inv.overdue_amount)
    
    # Fetch specific overdue invoices for the alert banner
    overdue_invoices = frappe.get_all("Sales Invoice",
        filters={"customer": cust, "docstatus": 1, "outstanding_amount": [">", 0], "due_date": ["<", nowdate()]},
        fields=["name", "outstanding_amount", "due_date"],
        order_by="due_date asc", limit=3
    )
    context.overdue_invoices = overdue_invoices

    context.credit_limit = credit_limit
    context.available_credit = avail_credit
    context.utilisation_pct = round(util_pct, 2)
    context.current_sales = flt(sales)
    context.sales_target = sales_target
    context.achievement_pct = round(achievement_pct, 2)
    context.inv_count = inv.inv_count or 0
    context.overdue_count = inv.overdue_count or 0
    
    # Fetch "Bills crossing credit days" (invoices past their due date)
    credit_days_date = nowdate()
    context.bills_crossing_credit_days = frappe.db.count("Sales Invoice", filters={
        "customer": cust, "docstatus": 1, "outstanding_amount": [">", 0], "due_date": ["<", credit_days_date]
    })
    
    crossing_invoices = frappe.get_all("Sales Invoice", 
        filters={"customer": cust, "docstatus": 1, "outstanding_amount": [">", 0], "due_date": ["<", credit_days_date]}, 
        order_by="due_date asc", limit=3, fields=["name"]
    )
    context.crossing_invoices = [inv.name for inv in crossing_invoices]
    
    oldest = frappe.get_all("Sales Invoice", filters={"customer": cust, "docstatus": 1, "outstanding_amount": [">", 0]}, order_by="posting_date asc", limit=1, fields=["name", "posting_date"])
    context.oldest_bill = f"{oldest[0].name} ({frappe.utils.date_diff(nowdate(), oldest[0].posting_date)} days)" if oldest else "-"
    
    # Pending Invoices
    context.pending_invoices = frappe.get_all("Sales Invoice", 
        filters={"customer": cust, "docstatus": 1, "outstanding_amount": [">", 0]},
        fields=["name", "po_no", "posting_date", "due_date", "grand_total", "outstanding_amount", "status"],
        order_by="posting_date desc", limit=5)
        
    # Recent Orders
    context.recent_orders = frappe.get_all("Sales Order", 
        filters={"customer": cust, "docstatus": 1},
        fields=["name", "transaction_date", "grand_total", "status"],
        order_by="transaction_date desc, name desc", limit=5, ignore_permissions=True)

    # Unread Notifications Count
    context.notification_count = frappe.db.count("Notification Log", filters={
        "for_user": user,
        "read": 0,
        "type": ["not in", ["Email"]]
    })

    # All Sales Items for dropdown
    context.available_items = frappe.get_all("Item", 
        filters={"disabled": 0, "is_sales_item": 1}, 
        fields=["item_code", "item_name"])

    return context