from odoo import models, fields, api
from odoo.exceptions import ValidationError

class ResPartner(models.Model):
    _inherit = 'res.partner'

    partner_code = fields.Char(
        string='Partner Code',
        help='Unique code for this partner',
        index=True,
        copy=False,
        size=50,
        tracking=True  # เพิ่ม tracking เพื่อติดตามการเปลี่ยนแปลง
    )

    _sql_constraints = [
        ('partner_code_unique', 'UNIQUE(partner_code)', 'Partner Code must be unique!')
    ]

    @api.constrains('partner_code')
    def _check_partner_code_unique(self):
        for record in self:
            if record.partner_code:
                # ตรวจสอบว่ามี partner code ซ้ำหรือไม่ (case-insensitive)
                existing = self.search([
                    ('partner_code', '=ilike', record.partner_code),
                    ('id', '!=', record.id)
                ])
                if existing:
                    raise ValidationError(f'Partner code "{record.partner_code}" already exists for {existing.name}!')
