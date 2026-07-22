# -*- coding: utf-8 -*-
#############################################################################
#
#    Cybrosys Technologies Pvt. Ltd.
#
#    Copyright (C) 2024-TODAY Cybrosys Technologies(<https://www.cybrosys.com>)
#    Author: ASWIN A K (odoo@cybrosys.com)
#
#    You can modify it under the terms of the GNU LESSER
#    GENERAL PUBLIC LICENSE (LGPL v3), Version 3.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU LESSER GENERAL PUBLIC LICENSE (LGPL v3) for more details.
#
#    You should have received a copy of the GNU LESSER GENERAL PUBLIC LICENSE
#    (LGPL v3) along with this program.
#    If not, see <http://www.gnu.org/licenses/>.
#
#############################################################################
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class PurchaseOrderLine(models.Model):
    """ For adding product image directly
    to purchase order line from product"""

    _inherit = 'purchase.order.line'

    product_image = fields.Binary(
        related="product_id.image_1920",
        string="Image",
        help='For getting product image '
             'to purchase order line')

    purchase_user_id = fields.Many2one(
        related="order_id.user_id",
        string="Buyer",
        store=True,
        readonly=True,
    )
    purchase_company_id = fields.Many2one(
        related="order_id.company_id",
        string="Company",
        store=True,
        readonly=True,
    )
    last_purchase_price = fields.Monetary(
        string="Last Purchase Price",
        currency_field="currency_id",
        compute="_compute_last_purchase_info",
    )
    last_purchase_date = fields.Datetime(
        string="Last Purchase Date",
        compute="_compute_last_purchase_info",
    )

    @api.depends("product_id", "order_id", "order_id.date_order", "currency_id")
    def _compute_last_purchase_info(self):
        for line in self:
            line.last_purchase_price = False
            line.last_purchase_date = False
            if not line.product_id or not line.order_id.date_order:
                continue

            previous_order = self.env["purchase.order"].search(
                [
                    ("order_line.product_id", "=", line.product_id.id),
                    ("id", "!=", line.order_id.id),
                    ("state", "in", ("purchase", "done")),
                    ("date_order", "<", line.order_id.date_order),
                ],
                order="date_order desc, id desc",
                limit=1,
            )
            if not previous_order:
                continue

            previous_line = previous_order.order_line.filtered(
                lambda purchase_line: purchase_line.product_id == line.product_id
            )[:1]
            if not previous_line:
                continue

            line.last_purchase_price = previous_order.currency_id._convert(
                previous_line.price_unit,
                line.currency_id,
                line.order_id.company_id,
                fields.Date.to_date(previous_order.date_order),
            )
            line.last_purchase_date = previous_order.date_order

    @api.onchange('order_id')
    def onchange_order_id(self):
        """ Restrict creating purchase order line for purchase order
                in locked,cancel and purchase order states"""
        
        if self.order_id.state in ['cancel', 'done', 'purchase']:
            raise UserError(_("You cannot select purchase order in "
                              "cancel or locked or purchase order state"))
