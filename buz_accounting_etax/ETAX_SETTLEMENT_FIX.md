# E-Tax Settlement Validation Error Fix

## Problem Description

When creating marketplace settlements in the `marketplace_settlement` module, the following validation error occurred:

```
Validation Error
The operation cannot be completed:
- Create/update: a mandatory field is not set.
- Delete: another model requires the record being deleted. If possible, archive it instead.

Model: ธุรกรรม E-Tax (etax.transaction)
Field: ลูกค้า (partner_id)
```

## Root Cause

The `buz_accounting_etax` module overrides the `action_post()` method for ALL `account.move` records and attempts to create `etax.transaction` records automatically. However:

1. **Settlement journal entries** created by `marketplace_settlement` are not invoices - they are general journal entries (`move_type = 'entry'`)
2. Settlement entries don't have a `partner_id` at the move level (only on individual move lines)
3. The `etax.transaction` model requires `partner_id` as a mandatory field
4. The etax module was trying to create etax transactions for ALL moves, including settlements

## Solution Implemented

### File Modified: `/opt/instance1/odoo17/custom-addons/buz_accounting_etax/models/etax_invoice_confirm.py`

#### Change 1: Updated `_create_related_record()` method
Added validation to skip etax transaction creation for non-invoice moves:

```python
def _create_related_record(self, move):
    """
    สร้างรายการที่เกี่ยวข้องหลัง Confirm
    """
    # Skip etax transaction creation for:
    # 1. Journal entries (entry moves) - these don't have partner_id at move level
    # 2. Moves without partner_id (e.g., settlement entries)
    # 3. Only process customer/vendor invoices and credit notes
    if move.move_type not in ['out_invoice', 'out_refund', 'in_invoice', 'in_refund']:
        return
        
    # Additional safety check: ensure partner_id exists
    if not move.partner_id:
        _logger.warning(f'Skipping etax transaction for move {move.name}: no partner_id')
        return
    
    # ... rest of the code continues only for invoices with partner_id
```

**What this does:**
- Only creates etax transactions for actual invoices (`out_invoice`, `out_refund`, `in_invoice`, `in_refund`)
- Skips journal entries, settlements, and other move types
- Adds an additional safety check to verify partner_id exists before creating etax transaction
- Logs a warning if a move without partner_id is encountered

#### Change 2: Updated `_custom_validation_before_confirm()` method
Improved validation to only check invoice_line_ids for actual invoices:

```python
def _custom_validation_before_confirm(self):
    """
    ตรวจสอบเงื่อนไขก่อนการ Confirm Invoice
    """
    for move in self:
        # ตรวจสอบว่ามี Invoice Lines หรือไม่ - เฉพาะสำหรับ invoice เท่านั้น
        # Journal entries จะมี line_ids แทน invoice_line_ids
        if move.move_type in ['out_invoice', 'in_invoice', 'out_refund', 'in_refund']:
            if not move.invoice_line_ids:
                raise ValidationError(_('ไม่สามารถ Confirm ได้: ไม่มีรายการสินค้า'))
            
            # ตรวจสอบ Partner เฉพาะสำหรับ Invoice เท่านั้น (ไม่บังคับสำหรับ Journal Entry)
            if not move.partner_id:
                raise UserError(_('กรุณาระบุลูกค้า'))
        
        # ... rest of validation
```

**What this does:**
- Only validates `invoice_line_ids` for actual invoices
- Allows journal entries (settlements) to have `line_ids` without requiring `invoice_line_ids`
- Prevents unnecessary validation errors for non-invoice moves

## Benefits

1. **Marketplace settlements work correctly** - No more validation errors when creating settlements
2. **E-tax transactions only for invoices** - Cleaner data model, etax records only for actual customer/vendor invoices
3. **Better error handling** - Warning logs instead of crashes for edge cases
4. **Backward compatible** - Existing invoice processing continues to work as before

## Testing Recommendations

1. **Test marketplace settlements** - Create settlements with multiple invoices
2. **Test regular invoices** - Ensure etax transactions are still created for normal invoices
3. **Test credit notes** - Verify etax transactions work for refunds
4. **Test journal entries** - Verify manual journal entries can be posted without errors

## Related Modules

- `buz_accounting_etax` - E-Tax integration module (modified)
- `marketplace_settlement` - Marketplace settlement module (no changes needed)

## Date Fixed
December 15, 2025
