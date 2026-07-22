from datetime import timedelta

from odoo import fields
from odoo.tests.common import TransactionCase
from odoo.tools.safe_eval import safe_eval


class TestPurchaseOrderLineViews(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.product = cls.env["product.product"].create(
            {
                "name": "Purchase history test product",
            }
        )
        cls.vendor = cls.env["res.partner"].create(
            {"name": "Purchase history test vendor"}
        )

    def _create_order(self, date_order, price_unit, state):
        order = self.env["purchase.order"].create(
            {
                "partner_id": self.vendor.id,
                "date_order": date_order,
                "order_line": [
                    fields.Command.create(
                        {
                            "name": self.product.display_name,
                            "product_id": self.product.id,
                            "product_qty": 1.0,
                            "product_uom": self.product.uom_po_id.id,
                            "price_unit": price_unit,
                            "date_planned": date_order,
                        }
                    )
                ],
            }
        )
        order.state = state
        return order

    def test_last_purchase_price_uses_latest_confirmed_prior_order(self):
        current_date = fields.Datetime.now()
        self._create_order(
            current_date - timedelta(days=10), 100.0, "purchase"
        )
        previous_order = self._create_order(
            current_date - timedelta(days=5), 125.0, "done"
        )
        self._create_order(
            current_date - timedelta(days=1), 999.0, "cancel"
        )
        self._create_order(
            current_date + timedelta(days=1), 999.0, "purchase"
        )
        current_order = self._create_order(current_date, 150.0, "draft")

        line = current_order.order_line
        self.assertEqual(line.last_purchase_price, 125.0)
        self.assertEqual(line.last_purchase_date, previous_order.date_order)

    def test_actions_split_rfq_and_purchase_order_states(self):
        purchase_action = self.env.ref(
            "purchase_line_views.action_purchase_order_line_view"
        )
        rfq_action = self.env.ref("purchase_line_views.action_rfq_order_line_view")

        self.assertEqual(
            safe_eval(purchase_action.domain),
            [("state", "in", ["purchase", "done", "cancel"])],
        )
        self.assertEqual(
            safe_eval(rfq_action.domain),
            [("state", "in", ["draft", "sent", "to approve"])],
        )

    def test_tree_views_include_purchase_context_and_last_price(self):
        required_fields = {
            "purchase_user_id",
            "purchase_company_id",
            "last_purchase_price",
            "last_purchase_date",
        }
        for xmlid in (
            "purchase_line_views.purchase_order_line_tree_view",
            "purchase_line_views.rfq_line_tree_view",
        ):
            view = self.env.ref(xmlid)
            for field_name in required_fields:
                self.assertIn(
                    'name="%s"' % field_name,
                    view.arch_db,
                    "%s is missing from %s" % (field_name, xmlid),
                )
