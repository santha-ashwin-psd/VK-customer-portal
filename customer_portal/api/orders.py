import frappe
from frappe.utils import flt
from .dashboard import _get_customer

@frappe.whitelist()
def get_orders(status=None, from_date=None, to_date=None):
    cust = _get_customer()

    filters = {"customer": cust, "docstatus": 1}
    if from_date: filters["transaction_date"] = [">=", from_date]
    if to_date:   filters["transaction_date"] = ["<=", to_date]
    if status:    filters["status"] = status

    return frappe.get_all("Sales Order", filters=filters,
        fields=["name", "transaction_date", "status",
                "grand_total", "total_qty"],
        order_by="transaction_date desc", page_length=50)

import json

@frappe.whitelist()
def search_items(query=""):
    _get_customer() # Security check
    filters = {"disabled": 0, "is_sales_item": 1, "portal_item": 1}
    if query:
        filters["item_code"] = ["like", f"%{query}%"]
        
    items = frappe.get_all("Item", filters=filters, fields=["item_code", "item_name"], limit=20)
    if query and not items:
        # Also try by item name
        items = frappe.get_all("Item", filters={"disabled": 0, "is_sales_item": 1, "portal_item": 1, "item_name": ["like", f"%{query}%"]}, fields=["item_code", "item_name"], limit=20)
    return items

@frappe.whitelist()
def get_item_details(item_code):
    _get_customer() # Security check

    item_code, item_name, description, uom, rate, tax_code = frappe.db.get_value(
        "Item", item_code, ["item_code", "item_name", "description", "stock_uom", "standard_rate", "tax_code"]
    )

    tax_rate = 0
    if tax_code:
        tmpl = frappe.get_doc("Tax Template", tax_code)
        tax_rate = _tax_template_headline_rate(tmpl.taxes)

    return {
        "item_code": item_code,
        "description": description or item_name,
        "uom": uom,
        "rate": flt(rate),
        "tax_rate": flt(tax_rate),
    }
def _tax_type_from_code(tax_code):
    """Best-effort Tax Line tax_type, guessed from the template name — same
    heuristic SalesOrders.vue uses (taxMap) since Tax Template names carry no
    separate structured type of their own beyond CGST/SGST/IGST/CESS/Other."""
    up = (tax_code or "").upper()
    if up.startswith("CGST"): return "CGST"
    if up.startswith("SGST"): return "SGST"
    if up.startswith("IGST"): return "IGST"
    if up.startswith("CESS"): return "Cess"
    return "Other"


def _tax_template_headline_rate(rows):
    """Mirrors templateHeadlineRate() in useTaxCalc.js: same-state
    (CGST+SGST+UTGST+CESS) total if present, else inter-state (IGST+CESS)
    total, else the sum of every row the template defines."""
    def _sum(components):
        return round(sum(flt(r.rate) for r in rows if (r.tax_type or "").upper() in components), 2)
    intra = _sum({"CGST", "SGST", "UTGST", "CESS"})
    if intra:
        return intra
    inter = _sum({"IGST", "CESS"})
    if inter:
        return inter
    return round(sum(flt(r.rate) for r in rows), 2)


@frappe.whitelist()
def place_order(order_data, save_draft=0):
    cust = _get_customer() # Security check
    
    customer_doc = frappe.get_doc("Customer", cust)
    if customer_doc.get("is_account_locked"):
        frappe.throw(f"Your account is currently locked ({customer_doc.get('lock_reason') or 'Policy Violation'}). Please contact support to place new orders.")
        
    # Check if the customer has a credit limit set. If not, force save as
    # draft for commercial credit check. Customer only has a single
    # `credit_limit` Currency field in this app — there's no
    # "credit_limits" child table (that was a leftover from a different
    # schema and returned None here, not an empty list, so the old loop
    # over customer_doc.get("credit_limits", []) crashed with a TypeError).
    has_credit_limit = flt(customer_doc.get("credit_limit")) > 0

    if not has_credit_limit:
        save_draft = 1
    
    if isinstance(order_data, str):
        order_data = json.loads(order_data)
        
    so = frappe.new_doc("Sales Order")
    so.customer = cust

    # Sales Order.company is a required field, but Customer has no native
    # "company" link — this app scopes Customer/Supplier/Item/Contact to a
    # Books Company via the custom `books_company` field (seeded in
    # install.py, see utils/tenancy.py). Records created before that field
    # existed can legitimately have it blank (tenancy.py's own permission
    # queries tolerate NULL/legacy Customers for the same reason), so we
    # can't hard-fail here — fall back to the site's default/sole Books
    # Company exactly like auto_stamp_books_company does, and backfill the
    # Customer so this only needs resolving once per legacy record.
    company = customer_doc.get("books_company")
    if not company:
        from zoho_books_clone.utils.tenancy import _default_books_company
        company = _default_books_company()
        if company:
            customer_doc.db_set("books_company", company, update_modified=False)
    if not company:
        frappe.throw(
            "Your account isn't linked to a company yet. Please contact support."
        )
    so.company = company

    so.transaction_date = order_data.get("order_date")
    so.delivery_date = order_data.get("expected_delivery")
    so.customer_address = order_data.get("billing_address")
    so.shipping_address_name = order_data.get("shipping_address")

    for item in order_data.get("items", []):
        if not item.get("item_code") or not float(item.get("qty", 0)):
            continue
        so.append("items", {
            "item_code": item.get("item_code"),
            "qty": item.get("qty"),
            "uom": item.get("uom"),
            "rate": item.get("rate")
        })
        
    if not so.get("items"):
        frappe.throw("Please add at least one valid item.")

    # Sales Order has no "taxes_and_charges" template field — that's an
    # ERPNext concept and "Sales Taxes and Charges Template" isn't a doctype
    # in this app at all. Tax instead comes from directly-appended `taxes`
    # (Tax Line) rows, whose `rate` the Sales Order controller applies to the
    # net total (see sales_order.py). Build one Tax Line per distinct Tax
    # Template used by the ordered items' Item.tax_code, exactly the way the
    # internal Books Sales Order screen does it (SalesOrders.vue: taxMap /
    # templateHeadlineRate) — same-state (CGST+SGST) total when the template
    # has those components, else the inter-state (IGST) total, else the sum
    # of whatever rows it defines.
    tax_codes = {frappe.db.get_value("Item", row.item_code, "tax_code") for row in so.items}
    tax_codes.discard(None)
    tax_codes.discard("")

    for tax_code in tax_codes:
        tmpl = frappe.get_doc("Tax Template", tax_code)
        if tmpl.disabled:
            continue
        rate = _tax_template_headline_rate(tmpl.taxes)
        if not rate:
            continue
        so.append("taxes", {
            "tax_type": _tax_type_from_code(tax_code),
            "description": tax_code,
            "rate": rate,
            "account_head": tmpl.taxes[0].account_head if tmpl.taxes else None,
        })
        
    so.insert(ignore_permissions=True)
    
    # Add notes if provided
    notes = order_data.get("notes")
    if notes:
        so.add_comment("Comment", text=notes)
        
    no_credit_limit = not has_credit_limit
        
    if not int(save_draft) and not no_credit_limit:
        # If it breaches credit limit, hold off on submitting it
        if so.get("requires_advance_payment") or so.get("credit_limit_breached"):
            return {
                "name": so.name,
                "requires_advance_payment": so.get("requires_advance_payment", 0),
                "credit_limit_breached": so.get("credit_limit_breached", 0),
                "credit_breach_reason": so.get("credit_breach_reason", ""),
                "no_credit_limit": no_credit_limit,
                "status": "Draft"
            }
        else:
            so.submit()
            so.reload()
            
    return {
        "name": so.name,
        "requires_advance_payment": so.get("requires_advance_payment", 0),
        "credit_limit_breached": so.get("credit_limit_breached", 0),
        "no_credit_limit": no_credit_limit,
        "status": "Submitted" if not int(save_draft) and not no_credit_limit else "Draft"
    }

@frappe.whitelist()
def approve_order(order_name):
    cust = _get_customer()
    
    so = frappe.get_doc("Sales Order", order_name)
    if so.customer != cust:
        frappe.throw("Not Authorized", frappe.PermissionError)
        
    if so.docstatus != 0:
        frappe.throw("Order is not in Pending Approval state")
        
    so.customer_approval_status = "Approved"
    so.flags.ignore_permissions = True
    so.submit()
    return "Success"
    
@frappe.whitelist()
def reject_order(order_name, reason=""):
    cust = _get_customer()
    
    so = frappe.get_doc("Sales Order", order_name)
    if so.customer != cust:
        frappe.throw("Not Authorized", frappe.PermissionError)
        
    if so.docstatus != 0:
        frappe.throw("Order is not in Pending Approval state")
        
    frappe.delete_doc("Sales Order", order_name, ignore_permissions=True)
    return "Success"

@frappe.whitelist(allow_guest=True)
def download_neat_pdf(order_name):
    # Authenticate via custom portal login logic if needed, 
    # but frappe web handles session if user is logged in
    from customer_portal.www.order_detail import get_context
    context = frappe._dict()
    
    # Temporarily set form_dict name so get_context can read it
    frappe.form_dict.name = order_name
    
    try:
        context = get_context(context)
    except Exception:
        frappe.throw("Not Authorized or Order not found", frappe.PermissionError)
        
    html = frappe.render_template("customer_portal/templates/order_print_format.html", context)
    
    frappe.local.response.filename = f"Order-{order_name}.pdf"
    frappe.local.response.filecontent = frappe.utils.pdf.get_pdf(html)
    frappe.local.response.type = "pdf"

@frappe.whitelist(allow_guest=True)
def download_dn_pdf(dn_name):
    # Authenticate via custom portal login logic if needed, 
    # but frappe web handles session if user is logged in
    from customer_portal.www.dn_detail import get_context
    context = frappe._dict()
    
    # Temporarily set form_dict name so get_context can read it
    frappe.form_dict.name = dn_name
    
    try:
        context = get_context(context)
    except Exception:
        frappe.throw("Not Authorized or Delivery Note not found", frappe.PermissionError)
        
    html = frappe.render_template("customer_portal/templates/dn_print_format.html", context)
    
    frappe.local.response.filename = f"DeliveryNote-{dn_name}.pdf"
    frappe.local.response.filecontent = frappe.utils.pdf.get_pdf(html)
    frappe.local.response.type = "pdf"