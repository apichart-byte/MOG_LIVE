from odoo import models, fields, api

class AccountMove(models.Model):
    _inherit = 'account.move'

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
            domain = [('partner_code', '=ilike', partner_code)]
            if self.move_type in ('out_invoice', 'out_refund', 'out_receipt'):
                domain.append(('customer_rank', '>', 0))
            elif self.move_type in ('in_invoice', 'in_refund', 'in_receipt'):
                domain.append(('supplier_rank', '>', 0))
            partner = self.env['res.partner'].search(domain, limit=1)
            if partner:
                self.partner_id = partner.id
            else:
                message = 'No customer found with this partner code.' if self.move_type in ('out_invoice', 'out_refund', 'out_receipt') else 'No vendor found with this partner code.'
                return {
                    'warning': {
                        'title': 'Warning',
                        'message': message
                    }
                }