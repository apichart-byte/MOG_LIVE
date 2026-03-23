from odoo import models, fields, api

class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    partner_code = fields.Char(
        string='Partner Code',
        compute='_compute_partner_code',
        inverse='_inverse_partner_code',
        store=True,
        readonly=False,
    )

    @api.depends('partner_id.partner_code')
    def _compute_partner_code(self):
        for record in self:
            record.partner_code = record.partner_id.partner_code or False

    def _inverse_partner_code(self):
        pass  # Allow manual input via onchange below

    @api.onchange('partner_code')
    def _onchange_partner_code(self):
        if self.partner_code:
            partner_code = self.partner_code.strip().upper()
            partner = self.env['res.partner'].search([
                ('partner_code', '=ilike', partner_code),
                ('supplier_rank', '>', 0)
            ], limit=1)
            if partner:
                self.partner_id = partner.id
            else:
                return {
                    'warning': {
                        'title': 'Warning',
                        'message': 'No vendor found with this partner code.'
                    }
                }