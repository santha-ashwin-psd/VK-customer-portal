import frappe
from .dashboard import _get_customer

@frappe.whitelist()
def get_invoices(status=None, from_date=None, to_date=None):
    cust = _get_customer()

    filters = {"customer": cust, "docstatus": 1}
    if from_date: filters["posting_date"] = [">=", from_date]
    if to_date:   filters["posting_date"] = ["<=", to_date]
    if status == "Paid":    filters["outstanding_amount"] = 0
    if status == "Unpaid":  filters["outstanding_amount"] = [">", 0]
    if status == "Overdue":
        filters["outstanding_amount"] = [">", 0]
        filters["due_date"] = ["<", frappe.utils.nowdate()]

    return frappe.get_all("Sales Invoice", filters=filters,
        fields=["name", "posting_date", "due_date",
                "po_no", "grand_total", "outstanding_amount",
                "status", "ewaybill"],
        order_by="posting_date desc", page_length=50)

@frappe.whitelist()
def get_invoice_pdf_url(invoice_name):
    # Verify this invoice belongs to the customer
    cust = _get_customer()
    owner = frappe.db.get_value("Sales Invoice", invoice_name, "customer")
    if owner != cust:
        frappe.throw("Not permitted", frappe.PermissionError)
    return f"/api/method/frappe.utils.weasyprint.download_pdf?doctype=Sales Invoice&name={invoice_name}"


@frappe.whitelist(allow_guest=True)
def download_invoice_pdf(invoice_name):
    """
    Render and stream a PDF for a Sales Invoice belonging to the logged-in
    portal customer, using a server-side port of Books' own Classic invoice
    template (print_render/classic_invoice.py, ported from
    useLivePreview.js + useTaxCalc.js) instead of the old, visually-
    different "Tax Invoice" Print Format. See print_render/classic_invoice.py
    for the full rationale — this is Phase 1 of making the portal PDF match
    Books' own invoice preview exactly; Books' own (browser-side) renderer
    is unchanged for now.

    allow_guest=True is kept only because whitelisted portal endpoints in
    this app are consistently declared this way (see orders.py); _get_customer()
    below still throws PermissionError for a Guest session, so this is not
    actually reachable without a logged-in portal user.
    """
    cust = _get_customer()
    owner = frappe.db.get_value("Sales Invoice", invoice_name, "customer")
    if not owner or owner != cust:
        frappe.throw("Not Authorized or Invoice not found", frappe.PermissionError)

    from customer_portal.customer_portal.print_render.classic_invoice import (
        build_print_doc, render_classic_invoice,
    )

    doc, state = build_print_doc(invoice_name)
    cfg = {"title": "Credit Note"} if frappe.db.get_value("Sales Invoice", invoice_name, "is_return") else {}
    html = render_classic_invoice(doc, state, cfg)

    frappe.local.response.filename = f"Invoice-{invoice_name}.pdf"
    frappe.local.response.filecontent = frappe.utils.pdf.get_pdf(html)
    frappe.local.response.type = "pdf"