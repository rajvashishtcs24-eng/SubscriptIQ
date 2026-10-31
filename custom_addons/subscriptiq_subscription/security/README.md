# SubscriptIQ Security Policy — Phase 2 (Subscription Plans)

## Access Control Model

In Phase 2, `subscriptiq_subscription` introduces two custom business models:
* `subscriptiq.plan`
* `subscriptiq.plan.line`

### Access Control Rules (`ir.model.access.csv`):
1. **Internal Users (`base.group_user`)**:
   * Granted **Read-only** permissions (`perm_read=1, perm_write=0, perm_create=0, perm_unlink=0`).
   * Allows sales and customer support staff to consult subscription plans when preparing quotations and advising customers.
2. **Product Managers (`product.group_product_manager`)**:
   * Granted **Full CRUD** permissions (`perm_read=1, perm_write=1, perm_create=1, perm_unlink=1`).
   * Allows product and catalog administrators to create, edit, activate, archive, and delete subscription plans and plan lines.

### Underlying Product Security:
* Native product models (`product.template` and `product.product`) continue to reuse Odoo core ACLs from the `product` addon (`product.group_product_user`, `product.group_product_manager`).
