# -*- coding: utf-8 -*-
{
    'name': 'Product Installation Cost',
    'version': '17.0.1.0.0',
    'category': 'Sales/Sales',
    'summary': 'Add optional installation cost to products and sale orders',
    'description': """
Product Installation Cost
==========================
This module allows you to:
- Define installation cost for products
- Optionally include installation cost in sale order lines
- Automatically calculate prices based on installation selection
- Maintain data integrity with proper constraints and security

Key Features:
- Installation cost field on products (editable by Sale Manager only)
- Checkbox on sale order lines to include/exclude installation
- Automatic price calculation (base price + installation cost)
- Manual price protection and recalculation
- Multi-company and multi-currency support
- State-based field restrictions
- Compatible with discounts and pricelists
    """,
    'author': 'Your Company',
    'website': 'https://www.yourcompany.com',
    'depends': [
        'sale',
        'product',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/product_views.xml',
        'views/sale_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
