# Product Installation Cost

## Overview
This module adds optional installation cost functionality to products and sale orders in Odoo 17. It allows businesses to define installation costs for products and give sales teams the flexibility to include or exclude these costs on a per-order-line basis.

## Features

### Product Level
- **Installation Cost Field**: Add installation cost to any product
- **Security**: Only Sale Managers can edit installation costs
- **Validation**: Automatic constraint ensures installation cost is never negative
- **Multi-Currency Support**: Installation cost respects company currency

### Sale Order Line Level
- **Include Installation Checkbox**: Toggle to include/exclude installation cost
- **Automatic Price Calculation**: Price automatically recalculates when checkbox is toggled
- **Manual Price Protection**: System handles manual price edits correctly
- **Base Price Tracking**: Internal field maintains product base price separately
- **State Protection**: Cannot modify installation inclusion after order confirmation

## How It Works

### Concept
The module maintains three price components for each sale order line:
1. **Base Price**: The product's list price (without installation)
2. **Installation Cost**: The installation cost from the product
3. **Final Price (price_unit)**: Base Price + Installation Cost (if included)

### Pricing Logic
```
When Include Installation = TRUE:
    price_unit = base_price + installation_cost

When Include Installation = FALSE:
    price_unit = base_price
```

### Manual Price Handling
If a user manually edits the `price_unit`:
- The system recalculates `base_price` accordingly
- If installation is included: `base_price = price_unit - installation_cost`
- If installation is excluded: `base_price = price_unit`
- When toggling the checkbox, prices recalculate from the updated base_price

## Usage

### Setting Up Products

1. Navigate to **Sales > Products > Products**
2. Open a product form
3. Go to the **Sales** tab
4. Find the **Installation** section
5. Enter the **Installation Cost** (requires Sale Manager role)
6. Save the product

### Creating Quotations/Orders

1. Create a new quotation
2. Add a product line that has installation cost defined
3. The **Include Installation** checkbox appears (if installation_cost > 0)
4. Check the box to include installation cost in the line price
5. The **price_unit** automatically updates
6. Continue with normal order processing

### Price Modifications

**Scenario 1: Toggle Installation**
- Check/uncheck "Include Installation"
- Price automatically recalculates

**Scenario 2: Manual Price Edit**
- Edit the price_unit directly
- System stores the new base_price
- Toggle still works correctly with the new price

**Scenario 3: Copy Order**
- All installation settings are preserved
- Prices remain consistent

## Business Rules

### Field Visibility
- Installation checkbox only appears when `installation_cost > 0`
- Base price field is hidden (technical use only)
- Installation cost field is read-only on order lines

### State Restrictions
- **Draft/Sent**: Full editing capability
- **Sale/Done**: Cannot change installation inclusion
- Installation cost becomes read-only after confirmation

### Security
- **Sale User**: Can read installation cost, toggle inclusion
- **Sale Manager**: Can edit product installation cost
- Standard sale order line ACLs apply

## Edge Cases & Solutions

### Edge Case 1: Product with Zero Installation Cost
**Solution**: Checkbox is hidden/disabled to prevent confusion

### Edge Case 2: Manual Price Change After Including Installation
**Scenario**: 
- Product price: 100, Installation: 20
- User checks "Include Installation" → price becomes 120
- User manually changes price to 150
- User unchecks "Include Installation"

**Result**: Price becomes 130 (base_price recalculated as 150 - 20 = 130)

### Edge Case 3: Confirmed Order Modification
**Solution**: System prevents changing installation inclusion with UserError

### Edge Case 4: Copy Quotation
**Solution**: All fields (include_installation, base_price, installation_cost) are preserved

### Edge Case 5: Multi-Currency Orders
**Solution**: All monetary fields respect the order's currency

### Edge Case 6: Discount + Installation
**Solution**: Compatible - discount applies to final price_unit (after installation)

### Edge Case 7: Pricelist + Installation
**Solution**: Pricelist determines base_price, then installation is added if included

## Technical Details

### Models Extended
- `product.template`: Added `installation_cost` field
- `sale.order.line`: Added `include_installation`, `installation_cost`, `base_price` fields

### Methods Used
- `@api.onchange`: For real-time UI updates
- `@api.depends`: For computed fields (if needed)
- `@api.constrains`: For validation
- `create()` override: Handle installation on creation
- `write()` override: Handle installation on update
- `copy_data()` override: Preserve fields on copy

### Key Features
- Pure Odoo framework (no custom JavaScript)
- Minimal core method overriding
- Clean separation of concerns
- Production-ready code quality

## Installation

1. Copy module to your Odoo addons directory
2. Update app list: **Apps > Update Apps List**
3. Search for "Product Installation Cost"
4. Click **Install**

## Dependencies
- `sale`: Sale Management
- `product`: Product Management

## Configuration
No additional configuration required. Module works out-of-the-box after installation.

## Compatibility
- **Odoo Version**: 17.0
- **Compatible Modules**: Discounts, Pricelists, Multi-currency
- **Multi-Company**: Yes

## Support & Maintenance
For issues or feature requests, contact your system administrator or module maintainer.

## License
LGPL-3

## Author
Your Company

## Version
1.0.0

---

## Developer Notes

### Future Enhancements (Optional)
- Add installation cost to reports/invoices as separate line
- Track installation separately in analytics
- Add installation cost to product variants
- Create installation product automatically
- Add batch update wizard for installation costs

### Testing Checklist
- [ ] Create product with installation cost
- [ ] Add to quotation and toggle checkbox
- [ ] Verify price calculation
- [ ] Manually edit price and toggle again
- [ ] Confirm order (checkbox should lock)
- [ ] Copy quotation (settings preserved)
- [ ] Test with discounts
- [ ] Test with pricelists
- [ ] Test multi-currency scenario
- [ ] Verify security (sale user vs manager)
- [ ] Test negative installation cost (should fail)
