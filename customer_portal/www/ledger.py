import frappe
from frappe.utils import fmt_money, getdate
from datetime import datetime

def get_context(context):
    """Get context for ledger page"""
    from .get_base_context import get_base_context
    context = get_base_context(context)
    
    if not context.get('customer_id') or context.customer_id == "Not Linked":
        frappe.throw("No customer linked to this user")
        
    customer = context.customer_id
    
    context.title = "Ledger"
    context.pathname = "/ledger"
    
    # Get filter parameters
    from_date = frappe.form_dict.get('from_date')
    to_date = frappe.form_dict.get('to_date')
    
    try:
        limit = int(frappe.form_dict.get("limit", 10))
    except (ValueError, TypeError):
        limit = 10

    context.limit = limit
    context.has_more = False

    filters = {
        "party_type": "Customer",
        "party": customer,
        "is_cancelled": 0
    }
    if from_date and to_date:
        filters["posting_date"] = ["between", [from_date, to_date]]
    elif from_date:
        filters["posting_date"] = [">=", from_date]
    elif to_date:
        filters["posting_date"] = ["<=", to_date]
        
    context.total_count = frappe.db.count("General Ledger Entry", filters=filters)
    
    # Get ledger data
    ledger_entries = get_ledger_entries(customer, from_date, to_date, limit=limit + 1)
    
    if len(ledger_entries) > limit:
        context.has_more = True
        ledger_entries = ledger_entries[:limit]
    
    # Calculate totals
    total_debit = sum(entry['debit'] for entry in ledger_entries)
    total_credit = sum(entry['credit'] for entry in ledger_entries)
    closing_balance = total_debit - total_credit
    
    # Format data for display
    context.kpi = {
        'total_debits': fmt_money(total_debit, currency='INR'),
        'total_credits': fmt_money(total_credit, currency='INR'),
        'closing_balance': fmt_money(closing_balance, currency='INR'),
        'closing_balance_raw': closing_balance,
    }
    
    # Format ledger entries
    formatted_entries = []
    running_balance = 0
    
    for entry in ledger_entries:
        running_balance += entry['debit'] - entry['credit']
        formatted_entries.append({
            'date': frappe.utils.formatdate(entry['posting_date']),
            'posting_date': entry['posting_date'],
            'document': entry['voucher_no'],
            'description': get_document_description(entry),
            'debit': fmt_money(entry['debit'], currency='INR') if entry['debit'] else '—',
            'debit_raw': entry['debit'],
            'credit': fmt_money(entry['credit'], currency='INR') if entry['credit'] else '—',
            'credit_raw': entry['credit'],
            'balance': fmt_money(running_balance, currency='INR'),
            'balance_raw': running_balance,
        })
    
    context.ledger_entries = formatted_entries
    context.from_date = from_date or ''
    context.to_date = to_date or ''
    
    return context

def get_customer():
    """Get customer linked to current user"""
    try:
        customer = frappe.db.get_value("Customer (Portal)", 
            filters={"user": frappe.session.user},
            fieldname="customer_name")
        return customer
    except:
        return None

def get_customer_id():
    """Get customer ID"""
    try:
        customer = get_customer()
        if customer:
            return customer
        return None
    except:
        return None

def get_ledger_entries(customer, from_date=None, to_date=None, limit=50):
    """Get GL entries for customer"""
    filters = {
        "party_type": "Customer",
        "party": customer,
        "is_cancelled": 0
    }
    
    if from_date and to_date:
        filters["posting_date"] = ["between", [from_date, to_date]]
    elif from_date:
        filters["posting_date"] = [">=", from_date]
    elif to_date:
        filters["posting_date"] = ["<=", to_date]
    
    entries = frappe.get_all("General Ledger Entry",
        filters=filters,
        fields=["name", "posting_date", "account", "debit", "credit", "voucher_no", "voucher_type"],
        order_by="posting_date desc, name desc",
        limit_page_length=limit)
    
    return entries

def get_document_description(entry):
    """Get description for document"""
    voucher_type = entry.get('voucher_type', '')
    voucher_no = entry.get('voucher_no', '')
    
    type_map = {
        'Sales Invoice': 'Invoice',
        'Payment Entry': 'Payment',
        'Journal Entry': 'Journal Entry',
        'Stock Transfer': 'Transfer'
    }
    
    type_label = type_map.get(voucher_type, voucher_type)
    
    if type_label and voucher_no:
        return f"{type_label} — {voucher_no}"
    return voucher_no or '—'
