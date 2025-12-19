# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    installation_cost = fields.Monetary(
        string='Installation Cost',
        currency_field='currency_id',
        default=0.0,
        help="Additional cost for product installation. "
             "This can be optionally included in sale orders.",
        groups='sales_team.group_sale_manager',  # Only Sale Manager can edit
    )

    @api.constrains('installation_cost')
    def _check_installation_cost(self):
        """Ensure installation cost is not negative."""
        for record in self:
            if record.installation_cost < 0:
                raise ValidationError(
                    _('Installation cost cannot be negative for product "%s".')
                    % record.name
                )
