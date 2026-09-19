"""
Server-side port of the "Classic" invoice template in
public/js/books_vue/src/composables/useLivePreview.js (_renderClassic),
so the customer portal's invoice PDF matches Books' own invoice preview
exactly instead of using the separate "Tax Invoice" Print Format.

Phase 1 of the agreed plan: this renderer is used by the portal only for
now. Books' own browser-side renderer is untouched. Only Classic is ported
(Modern/Minimal can follow later) — Books Company.pdf_template is read for
future use but any non-"classic" value still falls back to Classic here.

HTML/CSS below is transcribed 1:1 from _renderClassic so a PDF from this
file should be pixel-equivalent to Books' Classic PDF for the same data.
Diff this file against useLivePreview.js if that template ever changes.
"""
import html
import re
from datetime import datetime

import frappe
from frappe.utils import flt, get_url

from .tax_calc import compute_tax_rows

DEFAULT_BRAND_COLOR = "#1a6ef7"


# ── small formatting helpers (ports of the _xxx helpers in useLivePreview.js) ──

def _esc(s):
    return html.escape(str(s if s is not None else ""), quote=True)


def _currency_symbol(currency):
    return currency if (currency and currency != "INR") else "₹"


def _fmt(v, currency):
    symbol = (currency + " ") if (currency and currency != "INR") else "₹"
    return symbol + "{:,.2f}".format(flt(v))


def _fmt_num(v):
    return "{:,.2f}".format(flt(v))


def _js_num(v):
    """Mirrors JS `String(Number(v))` — used for Qty, which the JS template
    prints as a bare number (1, not 1.00; 1.5, not 1.50)."""
    n = flt(v)
    return str(int(n)) if n == int(n) else str(n)


def _fmt_doc_date(d):
    if not d:
        return ""
    dt = d if isinstance(d, datetime) else frappe.utils.get_datetime(d)
    return dt.strftime("%d-%b-%Y")


def _fmt_expiry(d):
    if not d:
        return ""
    dt = d if isinstance(d, datetime) else frappe.utils.get_datetime(d)
    return dt.strftime("%d-%b-%y")


_ONES = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten",
         "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen",
         "Eighteen", "Nineteen"]
_TENS = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]


def _two(x):
    if x < 20:
        return _ONES[x]
    return _TENS[x // 10] + (" " + _ONES[x % 10] if x % 10 else "")


def _three(x):
    if x >= 100:
        return _ONES[x // 100] + " Hundred" + (" " + _two(x % 100) if x % 100 else "")
    return _two(x)


def _number_to_words(n):
    n = round(flt(n))
    if n == 0:
        return "Rupees Zero Only"
    parts = []
    crore, n = divmod(n, 10000000)
    lakh, n = divmod(n, 100000)
    thousand, n = divmod(n, 1000)
    rest = n
    if crore:
        parts.append(_three(int(crore)) + " Crore")
    if lakh:
        parts.append(_three(int(lakh)) + " Lakh")
    if thousand:
        parts.append(_three(int(thousand)) + " Thousand")
    if rest:
        parts.append(_three(int(rest)))
    return "Rupees " + " ".join(parts) + " Only"


def _today():
    return frappe.utils.now_datetime().strftime("%d-%b-%Y")


def _bullet_list(text):
    lines = [ln.strip() for ln in str(text or "").split("\n") if ln.strip()]
    if not lines:
        return ""
    return "<ul>" + "".join(f"<li>{_esc(l)}</li>" for l in lines) + "</ul>"


def _hsn_summary(items):
    """Group line items by HSN code for the tax-rate summary table."""
    order, agg = [], {}
    for it in items or []:
        hsn = it.get("hsn_code") or ""
        if not hsn:
            continue
        taxable = flt(it.get("taxable_amount") if it.get("taxable_amount") is not None else it.get("amount"))
        cgst_rate, sgst_rate, igst_rate = flt(it.get("cgst_rate")), flt(it.get("sgst_rate")), flt(it.get("igst_rate"))
        row = agg.get(hsn)
        if not row:
            row = {"hsn": hsn, "taxable": 0.0, "cgstRate": cgst_rate, "sgstRate": sgst_rate,
                   "igstRate": igst_rate, "cgstAmt": 0.0, "sgstAmt": 0.0, "igstAmt": 0.0}
            agg[hsn] = row
            order.append(hsn)
        row["taxable"] += taxable
        row["cgstAmt"] += taxable * cgst_rate / 100
        row["sgstAmt"] += taxable * sgst_rate / 100
        row["igstAmt"] += taxable * igst_rate / 100
    return [agg[h] for h in order]


def _logo_src(url):
    if not url:
        return ""
    if url.startswith("data:") or url.startswith("http"):
        return url
    return get_url(url)


_TRAILING_INDIA_RE = re.compile(r"^india$", re.IGNORECASE)
_PINCODE_RE = re.compile(r"^\d{4,8}$")
# Strips a trailing "@9%" / "(9%)" rate suffix off a tax description, e.g.
# "CGST @ 9%" -> "CGST" — same as the JS: /[@(]?\s*[\d.]+\s*%\)?/g then /\(\s*\)/g
_TAX_LABEL_RATE_RE = re.compile(r"[@(]?\s*[\d.]+\s*%\)?")
_EMPTY_PARENS_RE = re.compile(r"\(\s*\)")


def _tax_label(description):
    label = _TAX_LABEL_RATE_RE.sub("", description or "Tax")
    label = _EMPTY_PARENS_RE.sub("", label)
    return label.strip()


def _format_addr_lines(raw):
    """Reflow formatAddress()'s '\\n'-joined text into two print lines:
    'street[, street2]' / 'City, State - Pincode' — same order as
    Invoices.vue's formatAddress(): line1, [line2], city, state, pincode, [country].
    """
    lines = [ln.strip() for ln in str(raw or "").split("\n") if ln.strip()]
    if not lines:
        return []
    if len(lines) > 1 and _TRAILING_INDIA_RE.match(lines[-1]):
        lines.pop()
    if len(lines) <= 1:
        return lines
    pincode = ""
    if _PINCODE_RE.match(lines[-1]):
        pincode = lines.pop()
    state = lines.pop() if lines else ""
    city = lines.pop() if lines else ""
    street_line = ", ".join(lines)
    city_state_line = ", ".join(x for x in (city, state) if x) + (f" - {pincode}" if pincode else "")
    return [x for x in (street_line, city_state_line) if x]


# ── data assembly: mirrors withItemTaxRates() + the `data` object built in
#    Invoices.vue's downloadInvoicePdf() ──────────────────────────────────────

def _with_item_tax_rates(items, place_of_supply, company_state, templates_by_name):
    out = []
    for it in items:
        rows = []
        if it.get("tax_code") and flt(it.get("amount")):
            rows = compute_tax_rows(
                [{"amount": flt(it.get("amount")), "tax_code": it.get("tax_code")}],
                templates_by_name,
                {"companyState": company_state, "placeOfSupply": place_of_supply},
            )

        def rate(tax_type):
            return next((r["rate"] for r in rows if r["tax_type"] == tax_type), 0)

        merged = dict(it)
        merged["taxable_amount"] = flt(it.get("amount"))
        merged["cgst_rate"] = rate("CGST")
        merged["sgst_rate"] = rate("SGST")
        merged["igst_rate"] = rate("IGST")
        out.append(merged)
    return out


def _resolve_shipping_address(invoice):
    addr_name = invoice.get("shipping_address_name")
    if addr_name and frappe.db.exists("Address", addr_name):
        addr = frappe.get_doc("Address", addr_name)
        parts = [addr.address_line1, addr.address_line2, addr.city, addr.state, addr.pincode, addr.country]
        return "\n".join(p for p in parts if p)
    return invoice.get("shipping_address") or ""


def _default_bank_account():
    """Same fallback as api.admin.get_company_settings(): Bank Account isn't
    linked back to a company here, so just take the flagged-default one, or
    the oldest, if any exist."""
    name = frappe.db.get_value("Bank Account", {"is_default": 1}, "name")
    if not name:
        name = frappe.db.get_value("Bank Account", {}, "name", order_by="creation asc")
    if not name:
        return {}
    bank = frappe.get_doc("Bank Account", name)
    return {
        "bank_name": bank.bank_name or "",
        "bank_branch": bank.branch or "",
        "bank_account_no": bank.account_number or "",
        "bank_ifsc": bank.ifsc_code or "",
    }


def _load_tax_templates(tax_codes):
    templates = {}
    for code in {c for c in tax_codes if c}:
        if not frappe.db.exists("Tax Template", code):
            continue
        tmpl = frappe.get_doc("Tax Template", code)
        templates[code] = {
            "tax_type": tmpl.tax_type,
            "taxes": [{"tax_type": r.tax_type, "rate": r.rate, "account_head": r.account_head}
                      for r in tmpl.taxes],
        }
    return templates


def build_print_doc(invoice_name):
    """Assemble the doc dict this renderer needs, straight from the DB —
    the server-side equivalent of the `data` object Invoices.vue builds in
    downloadInvoicePdf()/previewData before handing it to renderDocument()."""
    invoice = frappe.get_doc("Sales Invoice", invoice_name)

    company_doc = None
    if invoice.company and frappe.db.exists("Books Company", invoice.company):
        company_doc = frappe.get_doc("Books Company", invoice.company)

    customer_doc = None
    if invoice.customer and frappe.db.exists("Customer", invoice.customer):
        customer_doc = frappe.get_doc("Customer", invoice.customer)

    tax_codes = [it.tax_code for it in invoice.items]
    templates_by_name = _load_tax_templates(tax_codes)

    items = [{
        "item_name": it.item_name, "item_code": it.item_code, "description": it.description,
        "batch_no": it.batch_no, "batch_expiry_date": it.batch_expiry_date,
        "hsn_code": it.hsn_code, "qty": it.qty, "uom": it.uom, "mrp": it.mrp, "rate": it.rate,
        "discount_percentage": it.discount_percentage, "amount": it.amount, "tax_code": it.tax_code,
    } for it in invoice.items]
    items = _with_item_tax_rates(
        items, invoice.place_of_supply,
        company_doc.gst_state if company_doc else "",
        templates_by_name,
    )

    taxes = [{"description": t.description or t.account_head or "", "tax_amount": t.tax_amount}
             for t in invoice.taxes]

    doc = {
        "name": invoice.name,
        "company": invoice.company or "",
        "customer": invoice.customer,
        "customer_name": invoice.customer_name,
        "customer_company_name": (customer_doc.get("company_name") if customer_doc else "") or "",
        "posting_date": invoice.posting_date,
        "due_date": invoice.due_date,
        "currency": invoice.currency or "INR",
        "net_total": flt(invoice.net_total),
        "total_taxes_and_charges": flt(invoice.total_tax),
        "grand_total": flt(invoice.grand_total),
        "place_of_supply": invoice.place_of_supply or "",
        "billing_address": invoice.billing_address or "",
        "shipping_address": _resolve_shipping_address(invoice),
        "customer_gstin": invoice.customer_gstin or (customer_doc.get("tax_id") if customer_doc else "") or "",
        "customer_mobile": invoice.customer_mobile or "",
        "company_gstin": (company_doc.gstin if company_doc else "") or "",
        "dispatched_through": (customer_doc.get("dispatched_through") if customer_doc else "") or "",
        "destination": (customer_doc.get("destination") if customer_doc else "") or "",
        "items": items,
        "taxes": taxes,
        "discount_amount": flt(invoice.get("additional_discount_amount")),
        "remarks": invoice.get("remarks") or "",
        "terms": invoice.terms or "",
        "po_no": invoice.po_no or "",
        "in_words": invoice.get("in_words") or "",
    }

    state = {
        "brandColor": (company_doc.brand_color if company_doc else "") or DEFAULT_BRAND_COLOR,
        "logo": _logo_src((company_doc.company_logo if company_doc else "") or ""),
        "companyAddress": (company_doc.address_line if company_doc else "") or "",
        "companyCity": (company_doc.city if company_doc else "") or "",
        "companyPincode": (company_doc.pincode if company_doc else "") or "",
        "companyPhone": (company_doc.phone if company_doc else "") or "",
        "companyEmail": (company_doc.email if company_doc else "") or "",
    }
    state.update(_default_bank_account())

    return doc, state


# ── the template itself: a line-for-line port of _renderClassic() ──────────

_CSS = """
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:Arial,Helvetica,sans-serif;color:#1a1a1a;background:#fff;font-size:12.5px;line-height:1.55;-webkit-print-color-adjust:exact;print-color-adjust:exact}
.sheet{max-width:980px;margin:0 auto;padding:40px}
.frame{padding:28px 30px}
.hdr{display:flex;justify-content:space-between;align-items:flex-start;gap:20px;font-family:Arial,Helvetica,sans-serif}
.hdr-l .co{font-size:32px;font-weight:700;color:#111;letter-spacing:-.01em;font-family:Arial,Helvetica,sans-serif}
.hdr-l .addr{font-size:11px;font-weight:600;color:#111;margin-top:8px;line-height:1.55}
.hdr-l .contact{margin-top:8px;font-size:11px;color:{brand};display:flex;flex-direction:row;flex-wrap:wrap;gap:16px}
.hdr-l .contact .ci{display:flex;align-items:center;gap:6px}
.hdr-l .contact svg{width:12px;height:12px;flex-shrink:0}
.hdr-r{flex-shrink:0}
.hdr-r img{max-height:110px;max-width:170px;object-fit:contain;display:block}
.title{text-align:center;font-size:20px;font-weight:800;letter-spacing:.05em;color:#111;margin:28px 0 20px;font-family:Arial,Helvetica,sans-serif}
.hdr-bot{display:flex;justify-content:space-between;align-items:flex-end;font-family:Arial,sans-serif;font-size:11.5px;color:#111;padding-bottom:16px;margin-bottom:18px;border-bottom:1px solid #1c1c1c}
.hdr-bot .hb-r{text-align:right}
.hdr-bot .hb-r div+div{margin-top:3px}
.hdr-bot b{font-weight:700}
.hdr-bot .inv-no{font-size:20px;font-weight:800;color:#111}
.hdr-bot .inv-no b{font-size:11.5px;font-weight:700}
.pr{display:flex;justify-content:space-between;gap:24px;margin-bottom:6px;font-family:Arial,sans-serif}
.pr .blk{font-size:12px}
.pr .blk.r{text-align:right}
.pr .l{font-size:9.5px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:{brand};margin-bottom:3px}
.pr .nm{font-weight:700;font-size:13.5px;color:#111;font-family:Arial,Helvetica,sans-serif}
.pr .sub{color:#555;font-size:11px;margin-top:2px;white-space:pre-line;line-height:1.45}
.pr .kv{margin-top:6px}
hr.sep{border:none;border-top:1px solid #1c1c1c;margin:16px 0}
.addr-table{display:flex;width:100%;border:1.3px solid #1c1c1c;margin:10px 0 16px;font-family:Arial,sans-serif}
.addr-table.has-dispatch{margin-bottom:0}
.addr-col{flex:1;min-width:0;width:50%}
.addr-col+.addr-col{border-left:1.3px solid #1c1c1c}
.addr-h{font-size:12px;font-weight:700;color:#111;padding:8px 12px;border-bottom:1.3px solid #1c1c1c}
.addr-body{padding:10px 12px}
.addr-ct{font-size:12px;color:#111;margin-bottom:2px}
.addr-nm{font-size:12px;font-weight:700;color:#111;margin-bottom:4px}
.addr-ln{font-size:12px;color:#111;line-height:1.6}
.addr-body-split{display:flex}
.addr-body-left{flex:1;min-width:0;padding:10px 12px}
.addr-body-right{flex:1;min-width:0;padding:10px 12px;border-left:1.3px solid #1c1c1c}
.dispatch-table{display:flex;width:100%;border:1.3px solid #1c1c1c;border-top:none;margin:0 0 16px;font-family:Arial,sans-serif}
.dispatch-cell{flex:1;min-width:0;padding:8px 12px}
.dispatch-cell+.dispatch-cell{border-left:1.3px solid #1c1c1c}
.dispatch-lbl{font-size:9.5px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:#555;margin-bottom:2px}
.dispatch-val{font-size:12px;color:#111;font-weight:600}
table.it{width:100%;border-collapse:collapse;font-size:12px;font-family:Arial,sans-serif;margin-top:4px;border:1.3px solid #1c1c1c}
table.it th{background:#fff;color:#111;padding:8px 9px;font-size:11.5px;font-weight:700;letter-spacing:0;text-transform:none;text-align:left;border:none;border-bottom:1.5px solid #1c1c1c;border-right:1px solid #1c1c1c;white-space:nowrap}
table.it th.r{text-align:right}table.it th.c{text-align:center}
table.it th:last-child{border-right:none}
table.it td{padding:6px 9px;font-size:11.5px;line-height:1.35;border:none;border-bottom:1px solid #1c1c1c;border-right:1px solid #1c1c1c;vertical-align:top;word-break:break-word;overflow-wrap:anywhere}
table.it td:last-child{border-right:none}
table.it tr:last-child td{border-bottom:none}
table.it td.nw{white-space:nowrap}
.it .inm{font-weight:700;color:#1a1a1a;font-family:Arial,Helvetica,sans-serif;line-height:1.3}
.it .ids{font-size:10px;color:#666;margin-top:1px;line-height:1.3}
.it .r{text-align:right}.it .c{text-align:center}.it .b{font-weight:700}
.bottom-frame{margin-top:16px;border:1.3px solid #1c1c1c;font-family:Arial,sans-serif}
.bf-row{display:flex}
.bf-row+.bf-row{border-top:1.3px solid #1c1c1c}
.bf-cell{flex:1;min-width:0;padding:10px 14px;font-size:11.5px;color:#333;line-height:1.7}
.bf-cell+.bf-cell{border-left:1.3px solid #1c1c1c}
.bf-cell .h{font-weight:700;color:#111;font-size:12px;margin-bottom:5px}
.bf-cell .val{font-weight:700;color:#111;font-size:12px;line-height:1.5}
.bf-cell ul{margin:0;padding-left:18px}
.bf-cell li{margin:0 0 2px}
.bf-cell-totals{padding:0}
.tot-figs{display:table;width:100%;border-collapse:collapse}
.tot-figs .row{display:table-row}
.tot-figs .row>span{display:table-cell;padding:6px 8px;font-size:11px;color:#333;border-bottom:1px solid #1c1c1c;vertical-align:middle;white-space:nowrap}
.tot-figs .row>span:first-child{border-right:1px solid #1c1c1c}
.tot-figs .row>span:last-child{text-align:right;color:#111;width:1%}
.tot-figs .row:last-child>span{border-bottom:none}
.tot-figs .row.grand>span{font-weight:700;color:#111;border-top:1.3px solid #1c1c1c;border-bottom:none;padding-top:9px}
.bf-row-sign .bf-cell{display:flex;align-items:center}
.sign-note-cell{flex:2.2;font-size:11px;color:#333}
.sign-qr-cell{flex:0 0 130px;justify-content:center}
.sign-qr-cell img{width:76px;height:76px;object-fit:contain}
.sign-for-cell{flex:1.4;flex-direction:column;align-items:flex-end;text-align:right;font-size:11.5px;color:#333;gap:22px}
.sign-for-cell b{font-weight:700;color:#111}
.hsn-tbl{margin-top:14px;border-collapse:collapse;font-family:Arial,sans-serif;font-size:11px}
.hsn-tbl th,.hsn-tbl td{border:1px solid #1c1c1c;padding:6px 10px}
.hsn-tbl th{background:#fff;font-weight:700;color:#111;text-align:left}
.hsn-tbl td.r{text-align:right}
table.it tr{page-break-inside:avoid;break-inside:avoid}
.addr-table,.bf-row,.hsn-tbl{page-break-inside:avoid;break-inside:avoid}
@media print{.sheet{padding:0;max-width:none}@page{margin:22mm 15mm}}
"""

_SYNC_ADDR_WIDTH_JS = """
(function () {
  function syncAddrWidth() {
    var tbl = document.querySelector('table.it');
    var addr = document.querySelector('.addr-table');
    if (!tbl || !addr) return;
    var w = tbl.getBoundingClientRect().width;
    if (w > 0) addr.style.width = w + 'px';
  }
  document.addEventListener('DOMContentLoaded', syncAddrWidth);
  window.addEventListener('load', function () {
    syncAddrWidth();
    requestAnimationFrame(syncAddrWidth);
  });
})();
"""


def render_classic_invoice(doc, state, cfg=None):
    """doc/state: the dicts from build_print_doc(). cfg mirrors Invoices.vue's
    INV_PRINT_CFG (title/partyField/includeHsn/includeDiscount/includeMrp)."""
    cfg = {
        "title": "INVOICE", "partyField": "customer_name",
        "includeHsn": True, "includeDiscount": True, "includeMrp": True,
        "copyText": "",
        **(cfg or {}),
    }
    brand = state.get("brandColor") or DEFAULT_BRAND_COLOR
    logo = state.get("logo") or ""
    currency = doc.get("currency") or "INR"
    net_total = flt(doc.get("net_total"))
    party = doc.get(cfg["partyField"]) or doc.get("customer") or ""
    doc_date = doc.get("posting_date")
    items_in = doc.get("items") or []
    include_mrp = cfg["includeMrp"] and any(flt(it.get("mrp")) > 0 for it in items_in)
    has_igst = any(flt(it.get("igst_rate")) > 0 for it in items_in)
    has_cgst = any(flt(it.get("cgst_rate")) > 0 or flt(it.get("sgst_rate")) > 0 for it in items_in)
    include_gst = has_igst or has_cgst
    total_tax = flt(doc.get("total_taxes_and_charges"))
    round_off = round(flt(doc.get("grand_total")) - (net_total + total_tax), 2) if doc.get("grand_total") is not None else 0
    amount_words = doc.get("in_words") or _number_to_words(round(flt(doc.get("grand_total"))))

    item_rows = []
    for i, it in enumerate(items_in):
        desc = f'<div class="ids">{_esc(it["description"])}</div>' \
            if it.get("description") and it.get("description") != it.get("item_name") else ""
        batch = ""
        if it.get("batch_no"):
            exp = f' (exp {_fmt_expiry(it.get("batch_expiry_date"))})' if it.get("batch_expiry_date") else ""
            batch = f'<div class="ids">Batch: {_esc(it["batch_no"])} ({_js_num(it.get("qty"))}){exp}</div>'
        hsn_td = f'<td class="c nw">{_esc(it.get("hsn_code") or "—")}</td>' if cfg["includeHsn"] else ""
        mrp_td = f'<td class="r nw">{_fmt_num(it["mrp"]) if it.get("mrp") else "—"}</td>' if include_mrp else ""
        disc_td = f'<td class="c nw">{flt(it.get("discount_percentage")):.2f}%</td>' if cfg["includeDiscount"] else ""
        taxable_td = f'<td class="r nw">{_fmt_num(it.get("taxable_amount", it.get("amount")))}</td>' if include_gst else ""
        if include_gst:
            if has_igst:
                gst_td = f'<td class="c nw">{flt(it.get("igst_rate")):.2f}%</td>'
            else:
                gst_td = f'<td class="c nw">{flt(it.get("cgst_rate")):.2f}%</td><td class="c nw">{flt(it.get("sgst_rate")):.2f}%</td>'
        else:
            gst_td = ""
        item_rows.append(f"""
    <tr>
      <td class="c">{i + 1}</td>
      <td>
        <div class="inm">{_esc(it.get("item_name") or it.get("item_code"))}</div>
        {desc}{batch}
      </td>
      {hsn_td}
      <td class="r nw">{_js_num(it.get("qty"))}</td>
      <td class="c nw">{_esc(it.get("uom") or "Nos")}</td>
      {mrp_td}
      <td class="r nw">{_fmt_num(it.get("rate"))}</td>
      {disc_td}
      {taxable_td}
      {gst_td}
      <td class="r b nw">{_fmt_num(it.get("amount"))}</td>
    </tr>""")
    items_html = "".join(item_rows)

    tax_rows_html = "".join(
        f'<div class="row"><span>Add {_esc(_tax_label(t.get("description")))} (₹)</span>'
        f'<span>{_fmt_num(t.get("tax_amount"))}</span></div>'
        for t in (doc.get("taxes") or [])
    )
    hsn_rows = _hsn_summary(items_in) if include_gst else []

    # Header (letterhead)
    addr_bits = []
    if state.get("companyAddress"):
        city_pin = ""
        if state.get("companyCity") or state.get("companyPincode"):
            city_pin = f',<br/>{_esc(state.get("companyCity") or "")}' + \
                       (f', {_esc(state["companyPincode"])}' if state.get("companyPincode") else "")
        addr_bits.append(f'<div class="addr">{_esc(state["companyAddress"])}{city_pin}</div>')
    contact_bits = []
    if state.get("companyPhone") or state.get("companyEmail"):
        phone_html = (f'<span class="ci"><svg viewBox="0 0 24 24" fill="{_esc(brand)}">'
                      f'<path d="M6.62 10.79c1.44 2.83 3.76 5.14 6.59 6.59l2.2-2.2a1 1 0 0 1 1.02-.24c1.12.37 2.33.57 3.57.57a1 1 0 0 1 1 1V20a1 1 0 0 1-1 1C10.61 21 3 13.39 3 4a1 1 0 0 1 1-1h3.5a1 1 0 0 1 1 1c0 1.24.2 2.45.57 3.57a1 1 0 0 1-.25 1.02z"/></svg>'
                      f'{_esc(state["companyPhone"])}</span>') if state.get("companyPhone") else ""
        email_html = (f'<span class="ci"><svg viewBox="0 0 24 24" fill="{_esc(brand)}">'
                      f'<path d="M2 5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2zm2.4.2 7.1 6.2a.8.8 0 0 0 1 0l7.1-6.2a.6.6 0 0 0-.4-1H4.8a.6.6 0 0 0-.4 1"/></svg>'
                      f'{_esc(state["companyEmail"])}</span>') if state.get("companyEmail") else ""
        contact_bits.append(f'<div class="contact">{phone_html}{email_html}</div>')

    hdr_html = f"""
  <div class="hdr">
    <div class="hdr-l">
      <div class="co">{_esc(doc.get("company") or "")}</div>
      {"".join(addr_bits)}
      {"".join(contact_bits)}
    </div>
    <div class="hdr-r">
      <div class="print-copy-text" style="font-size:11.5px;font-weight:800;letter-spacing:.05em;text-transform:uppercase;color:#111;text-align:right;margin-bottom:8px">{_esc(cfg.get("copyText") or "")}</div>
      {f'<img src="{_esc(logo)}"/>' if logo else ""}
    </div>
  </div>
  <div class="title">{_esc(cfg["title"])}</div>
  <div class="hdr-bot" style="border-bottom:none">
    <div class="hb-l">{f'<b>GSTIN :</b> {_esc(doc.get("company_gstin"))}' if doc.get("company_gstin") else ""}</div>
    <div class="hb-r">
      <div class="inv-no"><b>{_esc(cfg["title"].capitalize())} No. :</b> {_esc(doc.get("name") or "")}</div>
      <div><b>Date :</b> {_esc(_fmt_doc_date(doc_date))}</div>
      {f'<div><b>Due Date :</b> {_esc(_fmt_doc_date(doc.get("due_date")))}</div>' if doc.get("due_date") else ""}
    </div>
  </div>"""

    # Billing / shipping address block
    bill_lines = _format_addr_lines(doc.get("billing_address") or "")
    ship_lines = _format_addr_lines(doc.get("shipping_address") or doc.get("billing_address") or "")
    gstin = doc.get("customer_gstin") or ""
    phone = doc.get("customer_mobile") or ""
    company_nm = doc.get("customer_company_name") or ""
    dispatched_through = doc.get("dispatched_through") or ""
    destination = doc.get("destination") or ""
    has_dispatch = bool(dispatched_through or destination)

    def _addr_col(label, lines):
        company_nm_html = f'<div class="addr-nm">{_esc(company_nm)}</div>' if company_nm else ""
        body = (
            f'<div class="addr-nm">{_esc(party)}</div>'
            + company_nm_html
            + "".join(f'<div class="addr-ln">{_esc(l)}</div>' for l in lines)
            + (f'<div class="addr-ln"><b>GSTIN :</b> {_esc(gstin)}</div>' if gstin else "")
            + (f'<div class="addr-ln"><b>Phone :</b> {_esc(phone)}</div>' if phone else "")
        )
        return f'<div class="addr-col"><div class="addr-h">{label}</div><div class="addr-body">{body}</div></div>'

    addr_block = ""
    if bill_lines or ship_lines or gstin or phone or company_nm:
        dispatch_table = ""
        if has_dispatch:
            dispatch_table = f"""
      <div class="dispatch-table">
        <div class="dispatch-cell"><div class="dispatch-lbl">Dispatched Through</div><div class="dispatch-val">{_esc(dispatched_through) if dispatched_through else "&mdash;"}</div></div>
        <div class="dispatch-cell"><div class="dispatch-lbl">Destination</div><div class="dispatch-val">{_esc(destination) if destination else "&mdash;"}</div></div>
      </div>"""
        addr_block = (
            f'<div class="addr-table{" has-dispatch" if has_dispatch else ""}">'
            f'{_addr_col("Billing Address", bill_lines)}{_addr_col("Shipping Address", ship_lines)}</div>{dispatch_table}'
        )

    # Item table header
    colspan = 6 + (1 if cfg["includeHsn"] else 0) + (1 if cfg["includeDiscount"] else 0) + \
        (1 if include_mrp else 0) + ((2 if has_igst else 3) if include_gst else 0)
    gst_th = ""
    if include_gst:
        gst_th = (f'<th class="r" style="width:88px">Taxable ({_esc(_currency_symbol(currency))})</th>'
                  + (f'<th class="c" style="width:58px">IGST</th>' if has_igst else
                     f'<th class="c" style="width:58px">CGST</th><th class="c" style="width:58px">SGST</th>'))
    table_html = f"""
  <table class="it">
    <thead><tr>
      <th class="c" style="width:30px">No.</th><th>Item &amp; Description</th>
      {f'<th class="c" style="width:78px">HSN / SAC</th>' if cfg["includeHsn"] else ""}
      <th class="r" style="width:44px">Qty</th><th class="c" style="width:50px">Unit</th>
      {f'<th class="r" style="width:82px">MRP ({_esc(_currency_symbol(currency))})</th>' if include_mrp else ""}
      <th class="r" style="width:82px">Rate ({_esc(_currency_symbol(currency))})</th>
      {f'<th class="c" style="width:64px">Discount</th>' if cfg["includeDiscount"] else ""}
      {gst_th}
      <th class="r" style="width:104px">Amount ({_esc(_currency_symbol(currency))})</th>
    </tr></thead>
    <tbody>{items_html or f'<tr><td colspan="{colspan}" style="text-align:center;color:#999;padding:24px">No items</td></tr>'}</tbody>
  </table>"""

    # Notes + bottom frame (bank / amount-in-words / totals / signature)
    notes_bits = []
    if doc.get("terms"):
        notes_bits.append(f'<div><div class="h">Terms &amp; Conditions :</div>{_bullet_list(doc["terms"])}</div>')
    if doc.get("remarks"):
        margin = "10px" if doc.get("terms") else "0"
        notes_bits.append(f'<div style="margin-top:{margin}"><div class="h">Remarks :</div>{_bullet_list(doc["remarks"])}</div>')
    notes_html = "".join(notes_bits)

    bank_html = ""
    if state.get("bank_name") or state.get("bank_account_no"):
        bank_html = '<div class="h">Bank Details :</div>'
        if state.get("bank_name"):
            bank_html += f'Bank Name: {_esc(state["bank_name"])}<br/>'
        if state.get("bank_branch"):
            bank_html += f'Branch: {_esc(state["bank_branch"])}<br/>'
        if state.get("bank_account_no"):
            bank_html += f'Account No.: {_esc(state["bank_account_no"])}<br/>'
        if state.get("bank_ifsc"):
            bank_html += f'IFSC: {_esc(state["bank_ifsc"])}'

    discount_row = ""
    if doc.get("discount_amount"):
        discount_row = (f'<div class="row"><span style="color:#b91c1c">Discount (₹)</span>'
                         f'<span style="color:#b91c1c">− {_fmt_num(doc["discount_amount"])}</span></div>')
    round_off_row = ""
    if round_off:
        sign = "" if round_off > 0 else "− "
        round_off_row = f'<div class="row"><span>Round Off (₹)</span><span>{sign}{_fmt_num(abs(round_off))}</span></div>'

    qr_url = _logo_src("/assets/zoho_books_clone/img/upi.png")
    bottom_html = f"""
  <div class="bottom-frame">
  <div class="bf-row">
    <div class="bf-cell">{bank_html}</div>
    <div class="bf-cell">
      <div class="h">Total Invoice Amount in Words :</div>
      <div class="val">{_esc(amount_words)}</div>
    </div>
    <div class="bf-cell bf-cell-totals">
      <div class="tot-figs">
        <div class="row"><span>Total Amount before Tax (₹)</span><span>{_fmt_num(net_total)}</span></div>
        {tax_rows_html}
        {discount_row}
        {round_off_row}
        <div class="row grand"><span>Grand Total (₹)</span><span>{_fmt_num(doc.get("grand_total"))}</span></div>
      </div>
    </div>
  </div>
  {f'<div class="bf-row"><div class="bf-cell">{notes_html}</div></div>' if notes_html else ""}
  <div class="bf-row bf-row-sign">
    <div class="bf-cell sign-note-cell">This is a computer-generated invoice. E. &amp; O. E.</div>
    <div class="bf-cell sign-qr-cell"><img src="{_esc(qr_url)}" alt="UPI QR Code"/></div>
    <div class="bf-cell sign-for-cell">
      <div>For, {_esc(doc.get("company") or "")}</div>
      <b>Authorised Signatory</b>
    </div>
  </div>
  </div>"""

    hsn_table_html = ""
    if hsn_rows:
        if has_igst:
            head_extra = '<th class="r">IGST %</th><th class="r">IGST (₹)</th>'
        else:
            head_extra = '<th class="r">CGST %</th><th class="r">CGST (₹)</th><th class="r">SGST %</th><th class="r">SGST (₹)</th>'
        body_rows = []
        for r in hsn_rows:
            if has_igst:
                extra = f'<td class="r">{r["igstRate"]:.2f}%</td><td class="r">{_fmt_num(r["igstAmt"])}</td>'
            else:
                extra = (f'<td class="r">{r["cgstRate"]:.2f}%</td><td class="r">{_fmt_num(r["cgstAmt"])}</td>'
                         f'<td class="r">{r["sgstRate"]:.2f}%</td><td class="r">{_fmt_num(r["sgstAmt"])}</td>')
            body_rows.append(f'<tr><td>{_esc(r["hsn"])}</td><td class="r">{_fmt_num(r["taxable"])}</td>{extra}</tr>')
        hsn_table_html = (f'<table class="hsn-tbl"><thead><tr><th>HSN/SAC Code</th><th class="r">Taxable (₹)</th>'
                           f'{head_extra}</tr></thead><tbody>{"".join(body_rows)}</tbody></table>')

    css = _CSS.replace("{brand}", _esc(brand))
    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"/>
<title>{_esc(cfg["title"])} — {_esc(doc.get("name"))}</title>
<style>{css}</style></head><body><div class="sheet"><div class="frame">
{hdr_html}
{addr_block}
{table_html}
{bottom_html}
{hsn_table_html}
</div></div>
<script>{_SYNC_ADDR_WIDTH_JS}</script>
</body></html>"""