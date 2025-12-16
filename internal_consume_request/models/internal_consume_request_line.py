# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class InternalConsumeRequestLine(models.Model):
    _name = 'internal.consume.request.line'
    _description = 'Internal Consumable Request Line'
    _order = 'sequence, id'

    sequence = fields.Integer(string='Sequence', default=10)
    
    request_id = fields.Many2one(
        'internal.consume.request',
        string='Request',
        required=True,
        ondelete='cascade',
        index=True
    )
    
    product_id = fields.Many2one(
        'product.product',
        string='Product',
        required=True,
        domain="[('type', 'in', ['consu', 'product'])]"
    )
    
    description = fields.Text(
        string='Description',
        compute='_compute_description',
        store=True,
        readonly=False
    )
    
    product_uom_id = fields.Many2one(
        'uom.uom',
        string='Unit of Measure',
        required=True,
        domain="[('category_id', '=', product_uom_category_id)]"
    )
    
    product_uom_category_id = fields.Many2one(
        related='product_id.uom_id.category_id',
        readonly=True
    )
    
    qty_requested = fields.Float(
        string='Quantity Requested',
        required=True,
        default=1.0,
        digits='Product Unit of Measure'
    )
    
    qty_done = fields.Float(
        string='Quantity Done',
        compute='_compute_qty_done',
        digits='Product Unit of Measure'
    )
    
    available_qty = fields.Float(
        string='Available Quantity',
        compute='_compute_available_qty',
        digits='Product Unit of Measure',
        help='Available quantity in the source location'
    )
    
    location_id = fields.Many2one(
        related='request_id.location_id',
        string='Source Location',
        readonly=True
    )
    
    state = fields.Selection(
        related='request_id.state',
        string='Status',
        store=True,
        readonly=True
    )

    @api.depends('product_id')
    def _compute_description(self):
        for line in self:
            if line.product_id:
                line.description = line.product_id.display_name
            else:
                line.description = ''

    @api.depends('request_id.picking_id', 'request_id.picking_id.move_ids', 
                 'request_id.picking_id.move_ids.quantity', 'product_id')
    def _compute_qty_done(self):
        for line in self:
            qty_done = 0.0
            if line.request_id.picking_id:
                for move in line.request_id.picking_id.move_ids:
                    if move.product_id == line.product_id:
                        qty_done += move.quantity
            line.qty_done = qty_done

    @api.depends('product_id', 'location_id', 'product_uom_id', 'request_id.warehouse_id')
    def _compute_available_qty(self):
        """Compute available quantity from warehouse's stock location and child locations"""
        for line in self:
            if line.product_id and line.location_id:
                # Get available quantity from stock.quant
                # Search in location and all child locations
                quants = self.env['stock.quant'].search([
                    ('product_id', '=', line.product_id.id),
                    ('location_id', 'child_of', line.location_id.id),
                    ('location_id.usage', '=', 'internal'),  # Only internal locations
                ])
                
                # Calculate available = on_hand - reserved
                available_qty = 0.0
                for quant in quants:
                    available_qty += (quant.quantity - quant.reserved_quantity)
                
                # Convert to line UOM if different
                if line.product_uom_id and line.product_uom_id != line.product_id.uom_id:
                    available_qty = line.product_id.uom_id._compute_quantity(
                        available_qty,
                        line.product_uom_id
                    )
                
                line.available_qty = max(0.0, available_qty)  # Never negative
            else:
                line.available_qty = 0.0

    @api.onchange('product_id')
    def _onchange_product_id(self):
        if self.product_id:
            self.product_uom_id = self.product_id.uom_id
            self.description = self.product_id.display_name

    @api.constrains('qty_requested')
    def _check_qty_requested(self):
        for line in self:
            if line.qty_requested <= 0:
                raise ValidationError(_('Quantity requested must be greater than zero.'))

    @api.constrains('product_id')
    def _check_product_type(self):
        for line in self:
            if line.product_id and line.product_id.type not in ('consu', 'product'):
                raise ValidationError(
                    _('Product %s is not a consumable or stockable product.') % line.product_id.display_name
                )

    @api.onchange('qty_requested', 'available_qty')
    def _onchange_qty_check_availability(self):
        """Warning if requested qty > available qty"""
        for line in self:
            if line.qty_requested > 0 and line.available_qty > 0:
                if line.qty_requested > line.available_qty:
                    return {
                        'warning': {
                            'title': _('Insufficient Stock'),
                            'message': _(
                                'Requested quantity (%.2f) exceeds available quantity (%.2f) '
                                'for product %s in location %s'
                            ) % (
                                line.qty_requested,
                                line.available_qty,
                                line.product_id.display_name,
                                line.location_id.complete_name if line.location_id else ''
                            )
                        }
                    }
