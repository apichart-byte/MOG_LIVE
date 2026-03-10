# -*- coding: utf-8 -*-
from odoo import models, api, fields

class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    @api.depends('currency_id', 'company_id', 'move_id.date', 'move_id.move_type')
    def _compute_currency_rate(self):
        """
        Override _compute_currency_rate to inject the rate_type context.
        """
        for line in self:
            if line.currency_id:
                # Determine rate_type based on move_type
                rate_type = 'standard'
                if line.move_id:
                    if line.move_id.is_sale_document():
                        rate_type = 'sell'
                    elif line.move_id.is_purchase_document():
                        rate_type = 'buy'
                
                # Inject context into both currencies so _get_rates receives the context properly
                from_currency = line.company_currency_id.with_context(
                    rate_type=rate_type, 
                    move_type=line.move_id.move_type if line.move_id else False
                )
                to_currency = line.currency_id.with_context(
                    rate_type=rate_type, 
                    move_type=line.move_id.move_type if line.move_id else False
                )

                line.currency_rate = self.env['res.currency']._get_conversion_rate(
                    from_currency=from_currency,
                    to_currency=to_currency,
                    company=line.company_id,
                    date=line._get_rate_date(),
                )
            else:
                line.currency_rate = 1.0
