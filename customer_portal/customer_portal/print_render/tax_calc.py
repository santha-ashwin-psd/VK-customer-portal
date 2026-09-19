"""
Server-side port of public/js/books_vue/src/composables/useTaxCalc.js.

Sales Invoice Item stores no per-line cgst_rate/sgst_rate/igst_rate/
taxable_amount — those are computed client-side in Books from each item's
tax_code + the invoice's place_of_supply + the company's GST state. To print
an invoice that matches Books, we must recompute the same split here.

Kept as a 1:1 port (same function names/behaviour) so future changes to
useTaxCalc.js are easy to diff against this file.
"""
import re

INTRA_COMPONENTS = {"CGST", "SGST", "UTGST"}
INTER_COMPONENTS = {"IGST"}
# CESS applies to both intra and inter (not filtered either way).

_STATE_PREFIX_RE = re.compile(r"^\s*\d+\s*-\s*")


def _num(v):
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def norm_state(s):
    """'33-Tamil Nadu' and 'Tamil Nadu' must compare equal."""
    if not s:
        return ""
    return _STATE_PREFIX_RE.sub("", str(s)).strip().lower()


def is_intra_state(company_state, place_of_supply):
    a, b = norm_state(company_state), norm_state(place_of_supply)
    return bool(a and b and a == b)


def _applicable_rows(template, intra):
    """template: dict with 'tax_type' and 'taxes' (list of {tax_type, rate, account_head})."""
    ttype = template.get("tax_type") or "GST"
    rows = template.get("taxes") or []

    if rows:
        out = []
        for r in rows:
            rt = str(r.get("tax_type") or "").upper()
            rate = _num(r.get("rate"))
            if not rate:
                continue
            if ttype == "GST":
                if rt in INTER_COMPONENTS and intra:
                    continue
                if rt in INTRA_COMPONENTS and not intra:
                    continue
            out.append({
                "tax_type": r.get("tax_type") or ttype,
                "rate": rate,
                "account_head": r.get("account_head") or "",
            })
        return out

    # Legacy single-summed-rate fallback (Tax Template has no top-level
    # `rate`/`account` field in this app's current schema, so this branch is
    # unreachable today — kept only for parity with useTaxCalc.js).
    total = _num(template.get("rate"))
    if not total:
        return []
    if ttype == "GST":
        if intra:
            return [
                {"tax_type": "CGST", "rate": total / 2, "account_head": ""},
                {"tax_type": "SGST", "rate": total / 2, "account_head": ""},
            ]
        return [{"tax_type": "IGST", "rate": total, "account_head": ""}]
    if ttype == "VAT":
        return [{"tax_type": "VAT", "rate": total, "account_head": template.get("account") or ""}]
    return [{"tax_type": "Other", "rate": total, "account_head": template.get("account") or ""}]


def compute_tax_rows(lines, templates_by_name, ctx=None):
    """
    lines: [{ amount, tax_code }]
    templates_by_name: { tax_code: {tax_type, taxes:[{tax_type,rate,account_head}]} }
    ctx: { companyState, placeOfSupply, defaultAccount }
    returns: [{ tax_type, description, rate, account_head, amount }]
    """
    ctx = ctx or {}
    intra = is_intra_state(ctx.get("companyState"), ctx.get("placeOfSupply"))
    agg = {}
    for line in lines or []:
        base = _num(line.get("amount"))
        tax_code = line.get("tax_code")
        if not tax_code or not base:
            continue
        tmpl = templates_by_name.get(tax_code)
        if not tmpl:
            continue
        for comp in _applicable_rows(tmpl, intra):
            rate = _num(comp["rate"])
            if not rate:
                continue
            acct = comp.get("account_head") or ctx.get("defaultAccount") or ""
            key = f'{comp["tax_type"]}@{rate}@{acct}'
            row = agg.setdefault(key, {
                "tax_type": comp["tax_type"],
                "description": f'{comp["tax_type"]} @ {rate}%',
                "rate": rate,
                "account_head": acct,
                "amount": 0.0,
            })
            row["amount"] += base * rate / 100
    for row in agg.values():
        row["amount"] = round(row["amount"], 2)
    return list(agg.values())