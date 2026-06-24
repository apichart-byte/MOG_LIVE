# project.md

## Repo structure

- Odoo 17 custom addons directory — not standalone; served via `/opt/instance1/odoo17/odoo-bin --addons-path=...`
- 210+ modules: `buz_*` (~63 custom biz), `l10n_th_*` (Thai localization), OCA imports, and community modules
- Main branch: `main`; stale `master` exists, do not use

## Module conventions

- Prefix custom business modules `buz_` — some modules (e.g. `stock_valuation_location`) use `buz` in display name but not in directory name
- Module manifests use Odoo 17.0 version format: `17.0.X.X.X` or plain `1.0`
- Default license for custom modules: `LGPL-3`; OCA modules: `AGPL-3`
- Dependencies commonly: `account`, `base`, `sale_management`, `purchase`, `stock`
- Mixed code styles (no enforced linter) — match the module you're editing

## Testing

- No central test runner — run per-module: `odoo-bin -u <module> --test-enable --stop-after-init`
- Tests live in `tests/` within each module (present in ~20% of modules)
- Requires a running PostgreSQL instance and Odoo config

## Tooling gaps

- No `.gitignore` — be careful not to commit secrets, caches, or IDE files
- No pre-commit, no linter config (flake8 config at Odoo root `/opt/instance1/odoo17/setup.cfg` is minimal, for rst mostly)
- VS Code: `python.languageServer` set to `None` — no IDE type-checking
- No CI config in this directory

## Files of note

- `prompt.md` — detailed spec for `buz_inter_customer_clearing_payment` module
- `check_tz.py` — one-off timezone debug script, not part of any module

#database and log
Database MOG_LIVE
read /etc/instance1.conf

## Known issues & fixes

### "Cannot create an invoice. No items are available to invoice."

**Error:** Clicking "Create Invoice" on a sale order raises `UserError: Cannot create an invoice. No items are available to invoice.`

**Root cause:** Stored computed field `sale.order.line.qty_to_invoice` is stale (shows `0`) even though the product has `invoice_policy = 'order'` (or `'delivery'` with delivered qty), `state = 'sale'`, and `qty_invoiced = 0`. This happens because the field was computed when the order was in `draft` and was not recomputed after confirmation. The `invoice_bill_select_orderlines` module's `_get_invoiceable_lines()` filters by `qty_to_invoice > 0`, so lines with stale `0` are skipped → empty invoice → error.

**Check (SQL):**
```sql
SELECT id, product_uom_qty, qty_delivered, qty_invoiced, qty_to_invoice, invoice_status
FROM sale_order_line WHERE order_id = <SO_ID>;
```

**Fix (Odoo shell):**
```bash
cd /opt/instance1/odoo17 && /opt/instance1/odoo17-venv/bin/python3 odoo-bin shell -c /etc/instance1.conf -d MOG_LIVE --no-http <<'EOF'
# Replace with actual line IDs from the SO
lines = env['sale.order.line'].browse([LINE_ID_1, LINE_ID_2])
lines.invalidate_recordset(['qty_to_invoice'])
lines._compute_qty_to_invoice()
env.cr.commit()
EOF
```

**Prevention for service products:** Ensure `invoice_policy = 'order'` on product template (Prepaid/Fixed Price). All service products were bulk-updated on 2026-06-08. For new products, set this in the product form.

**Permanent fix:** Create a Server Action (Settings → Technical → Server Actions):
- Model: `sale.order`
- Action Type: `Execute Python Code`
- Python Code:
  ```python
  for line in records.order_line:
      line.invalidate_recordset(['qty_to_invoice'])
  records.order_line._compute_qty_to_invoice()
  ```