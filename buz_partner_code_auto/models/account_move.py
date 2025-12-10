from odoo import models, fields, api

class AccountMove(models.Model):
    _inherit = 'account.move'

    partner_code = fields.Char(
        string='Partner Code',
        help='Enter partner code to auto-fill partner details',
        store=True
    )

    @api.onchange('partner_code')
    def _onchange_partner_code(self):
        if self.partner_code:
            # Convert to uppercase for case-insensitive search
            partner_code = self.partner_code.strip().upper()
            partner = self.env['res.partner'].search([
                ('partner_code', '=ilike', partner_code)
            ], limit=1)
            if partner:
                self.partner_id = partner.id
                return {}
            else:
                return {
                    'warning': {
                        'title': 'Warning',
                        'message': 'No partner found with this partner code.'
                    }
                }

    @api.onchange('partner_id')
    def _onchange_partner_id_code(self):
        if self.partner_id and hasattr(self.partner_id, 'partner_code') and self.partner_id.partner_code:
            self.partner_code = self.partner_id.partner_code