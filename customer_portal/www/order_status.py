import frappe


def portal_order_status(order):
	"""
	Map the app's own Sales Order status to a customer-facing label.
	Works with either a full Sales Order document or a dict
	(e.g. from frappe.get_all) that has a `status` field.
	"""
	status = order.get("status") if hasattr(order, "get") else order.status

	if status in (None, "", "Draft"):
		return "Pending Approval"

	return status
