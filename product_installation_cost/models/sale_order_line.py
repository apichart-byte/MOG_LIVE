# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    include_installation = fields.Boolean(
        string='Include Installation',
        default=False,
        help="Check this to include installation cost in the unit price.",
    )
    
    installation_cost = fields.Monetary(
        string='Installation Cost',
        currency_field='currency_id',
        default=0.0,
        readonly=True,
        help="Installation cost from the product. "
             "This will be added to the base price when 'Include Installation' is checked.",
    )
    
    base_price = fields.Monetary(
        string='Base Price',
        currency_field='currency_id',
        default=0.0,
        readonly=True,
        help="Product price without installation cost. "
             "Used for internal calculation.",
    )
    
    state = fields.Selection(
        related='order_id.state',
        string='Order Status',
        readonly=True,
        store=False,
    )

    @api.depends('product_id', 'product_uom', 'product_uom_qty')
    def _compute_price_unit(self):
        """Override to handle installation cost if needed."""
        # Call super first to get standard price computation
        res = super(SaleOrderLine, self)._compute_price_unit()
        
        # Then apply our installation logic if applicable
        for line in self:
            if line.product_id and line.product_template_id.installation_cost:
                # Store base price from product
                if not line.base_price:
                    line.base_price = line.price_unit
                # Store installation cost from product
                if not line.installation_cost:
                    line.installation_cost = line.product_template_id.installation_cost
        
        return res

    @api.onchange('product_id')
    def _onchange_product_id_installation(self):
        """When product changes, load base price and installation cost."""
        if self.product_id:
            # Get the base price (this would be the standard product price)
            self.base_price = self.price_unit
            self.installation_cost = self.product_template_id.installation_cost or 0.0
            # Reset the checkbox if product changes
            if not self.installation_cost:
                self.include_installation = False

    @api.onchange('include_installation')
    def _onchange_include_installation(self):
        """Recalculate price_unit when installation checkbox changes."""
        if self.order_id.state in ['sale', 'done']:
            raise UserError(
                _('Cannot change installation inclusion after the order is confirmed.')
            )
        
        if self.product_id:
            if self.include_installation:
                # Add installation cost to base price
                self.price_unit = self.base_price + self.installation_cost
            else:
                # Use only base price
                self.price_unit = self.base_price

    @api.onchange('price_unit')
    def _onchange_price_unit_manual(self):
        """Handle manual price changes - update base_price accordingly."""
        if self.product_id and self.price_unit:
            if self.include_installation and self.installation_cost:
                # If installation is included, calculate base price
                self.base_price = self.price_unit - self.installation_cost
            else:
                # Otherwise, the price_unit is the base price
                self.base_price = self.price_unit

    @api.model_create_multi
    def create(self, vals_list):
        """Handle installation cost on creation."""
        for vals in vals_list:
            if vals.get('product_id'):
                product = self.env['product.product'].browse(vals['product_id'])
                if product.product_tmpl_id.installation_cost:
                    # Set installation cost if not already set
                    if 'installation_cost' not in vals:
                        vals['installation_cost'] = product.product_tmpl_id.installation_cost
                    # Set base price if not already set
                    if 'base_price' not in vals and 'price_unit' in vals:
                        vals['base_price'] = vals['price_unit']
                    # Apply installation if checkbox is checked
                    if vals.get('include_installation') and vals.get('installation_cost'):
                        if 'price_unit' in vals:
                            vals['price_unit'] = vals.get('base_price', 0.0) + vals.get('installation_cost', 0.0)
        
        return super(SaleOrderLine, self).create(vals_list)

    def write(self, vals):
        """Handle installation cost on write."""
        # Prevent changes after confirmation
        if any(line.order_id.state in ['sale', 'done'] for line in self):
            if 'include_installation' in vals:
                raise UserError(
                    _('Cannot change installation inclusion after the order is confirmed.')
                )
        
        # Handle include_installation toggle
        if 'include_installation' in vals:
            for line in self:
                if vals['include_installation']:
                    vals['price_unit'] = line.base_price + line.installation_cost
                else:
                    vals['price_unit'] = line.base_price
        
        # Handle manual price_unit change
        if 'price_unit' in vals and 'include_installation' not in vals:
            for line in self:
                if line.include_installation and line.installation_cost:
                    vals['base_price'] = vals['price_unit'] - line.installation_cost
                else:
                    vals['base_price'] = vals['price_unit']
        
        return super(SaleOrderLine, self).write(vals)

    def copy_data(self, default=None):
        """Preserve installation fields when copying order lines."""
        data = super(SaleOrderLine, self).copy_data(default=default)
        for line_data, line in zip(data, self):
            line_data['include_installation'] = line.include_installation
            line_data['installation_cost'] = line.installation_cost
            line_data['base_price'] = line.base_price
        return data
