"""Margin tests: POS Lite must pull standard cost from Standard Cost Pricelist
the same way Sales Orders compute margin.

Covers:
* standard_cost_price / margin on pos.lite.order.line
* margin / margin_percent on pos.lite.order
* parity with sale.order.line + sale.order ("เหมือนกับ SO")
* no-cost-pricelist edge case
* return-order edge case
"""

from odoo.tests import common, tagged
from odoo import fields


@tagged('-at_install', 'post_install')
class MarginTestBase(common.TransactionCase):
    """Setup: Standard Cost Pricelist priced at 60 per product."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.company = cls.env.company
        cls.currency = cls.company.currency_id

        cls.category = cls.env['product.category'].create({
            'name': 'Margin Cat',
        })
        cls.product = cls.env['product.product'].create({
            'name': 'Margin Widget',
            'type': 'service',
            'categ_id': cls.category.id,
            'sale_ok': True,
            'list_price': 100.0,
            'taxes_id': [(5, 0, 0)],  # no tax → predictable subtotals
        })

        cls.partner = cls.env['res.partner'].create({
            'name': 'Margin Customer',
            'customer_rank': 1,
        })

        # Sales pricelist — explicit fixed price so both SO and POS get 100
        cls.sales_pricelist = cls.env['product.pricelist'].create({
            'name': 'Margin Sales PL',
            'company_id': cls.company.id,
        })
        cls.env['product.pricelist.item'].create({
            'pricelist_id': cls.sales_pricelist.id,
            'applied_on': '1_product',
            'product_tmpl_id': cls.product.product_tmpl_id.id,
            'compute_price': 'fixed',
            'fixed_price': 100.0,
        })

        # Standard Cost Pricelist — single source of truth for standard cost
        # Ensure no pre-existing standard cost pricelist
        existing = cls.env['product.pricelist'].search([
            ('is_standard_cost_pricelist', '=', True),
            ('company_id', '=', cls.company.id),
        ])
        if existing:
            existing.sudo().write({'is_standard_cost_pricelist': False})

        cls.cost_pricelist = cls.env['product.pricelist'].create({
            'name': 'Margin Standard Cost PL',
            'company_id': cls.company.id,
        })
        cls.env['product.pricelist.item'].create({
            'pricelist_id': cls.cost_pricelist.id,
            'applied_on': '1_product',
            'product_tmpl_id': cls.product.product_tmpl_id.id,
            'compute_price': 'fixed',
            'fixed_price': 60.0,
        })
        cls.cost_pricelist.sudo().write({'is_standard_cost_pricelist': True})

        cls.warehouse = cls.env['stock.warehouse'].search([
            ('company_id', '=', cls.company.id),
        ], limit=1)

        cls.cash_journal = cls.env['account.journal'].create({
            'name': 'Margin Cash',
            'type': 'cash',
            'code': 'MCSH',
            'company_id': cls.company.id,
        })

        cls.employee = cls.env['hr.employee'].create({
            'name': 'Margin Emp',
            'company_id': cls.company.id,
        })

        cls.config = cls.env['pos.lite.config'].create({
            'name': 'Margin Cfg',
            'company_id': cls.company.id,
            'warehouse_id': cls.warehouse.id,
            'pricelist_id': cls.sales_pricelist.id,
            'journal_id': cls.cash_journal.id,
        })

        # Ensure sequences start high to avoid conflicts
        cls.env.cr.execute(
            "UPDATE ir_sequence SET number_next = 100000 "
            "WHERE code IN ('pos.lite.session', 'pos.lite.order') AND number_next < 100000"
        )
        cls.env.invalidate_all()

        cls.session = cls.env['pos.lite.session'].create({
            'config_id': cls.config.id,
            'employee_id': cls.employee.id,
            'company_id': cls.company.id,
        })

    # ── helpers ────────────────────────────────────────────────

    def _draft_pos_order(self, lines):
        line_cmds = [(0, 0, {
            'product_id': pid, 'qty': qty, 'price_unit': price,
        }) for pid, qty, price in lines]
        return self.env['pos.lite.order'].create({
            'company_id': self.company.id,
            'channel': 'phone',
            'partner_id': self.partner.id,
            'warehouse_id': self.warehouse.id,
            'pricelist_id': self.sales_pricelist.id,
            'session_id': self.session.id,
            'line_ids': line_cmds,
        })

    def _sale_order(self, lines):
        line_cmds = [(0, 0, {
            'product_id': pid, 'product_uom_qty': qty, 'price_unit': price,
        }) for pid, qty, price in lines]
        so = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'pricelist_id': self.sales_pricelist.id,
            'company_id': self.company.id,
            'order_line': line_cmds,
        })
        so.flush_recordset()
        so.order_line.flush_recordset()
        return so


@tagged('-at_install', 'post_install')
class TestStandardCostMargin(MarginTestBase):

    def test_cost_from_standard_pricelist(self):
        """qty=2, unit=100 → subtotal=200, cost=60*2=120, margin=80."""
        order = self._draft_pos_order([(self.product.id, 2, 100.0)])
        line = order.line_ids[0]
        self.assertAlmostEqual(line.standard_cost_price, 60.0, places=2)
        margin = 200.0 - 120.0  # subtotal=200, cost=60*2=120 → margin=80
        self.assertAlmostEqual(line.margin, margin, places=2)

    def test_order_margin_and_percent(self):
        """order.margin=80, order.margin_percent=80/200=0.4."""
        order = self._draft_pos_order([(self.product.id, 2, 100.0)])
        order.invalidate_recordset()
        self.assertAlmostEqual(order.margin, 80.0, places=2)
        if order.amount_untaxed:
            self.assertAlmostEqual(order.margin_percent, 80.0 / 200.0, places=4)
        else:
            self.assertAlmostEqual(order.margin_percent, 0.0, places=4)

    def test_pos_matches_so(self):
        """POS margin == SO margin (เหมือนกับ SO)."""
        order = self._draft_pos_order([(self.product.id, 2, 100.0)])
        order.invalidate_recordset()
        so = self._sale_order([(self.product.id, 2, 100.0)])

        self.assertAlmostEqual(
            order.line_ids[0].standard_cost_price,
            so.order_line[0].purchase_price, places=2,
        )
        self.assertAlmostEqual(so.order_line[0].purchase_price, 60.0, places=2)

        self.assertAlmostEqual(
            order.line_ids[0].margin, so.order_line[0].margin, places=2,
        )
        # order-level
        self.assertAlmostEqual(order.margin, so.margin, places=2)
        self.assertAlmostEqual(so.margin, 80.0, places=2)

    def test_discount_reduces_margin(self):
        """10% discount cuts revenue but not cost → margin drops."""
        order = self._draft_pos_order([(self.product.id, 1, 100.0)])
        line = order.line_ids[0]
        line.discount = 10.0  # percent → 10% off
        line.discount_type = 'percent'
        order.invalidate_recordset()
        # subtotal = 100 * 0.9 = 90; cost = 60; margin = 30
        self.assertAlmostEqual(line.price_subtotal, 90.0, places=2)
        self.assertAlmostEqual(line.standard_cost_price, 60.0, places=2)
        self.assertAlmostEqual(line.margin, 30.0, places=2)
        self.assertAlmostEqual(order.margin, 30.0, places=2)

    def test_no_standard_cost_pricelist_means_zero_cost(self):
        """Without cost pricelist, cost=0 and margin=full subtotal."""
        self.cost_pricelist.sudo().write({'is_standard_cost_pricelist': False})
        order = self._draft_pos_order([(self.product.id, 1, 100.0)])
        order.invalidate_recordset()
        self.assertAlmostEqual(order.line_ids[0].standard_cost_price, 0.0, places=2)
        self.assertAlmostEqual(order.line_ids[0].margin, 100.0, places=2)
        self.assertAlmostEqual(order.margin, 100.0, places=2)
        # Restore for other tests in same TransactionCase (they'd rollback,
        # but explicit restore avoids bleed if cursor reused).
        self.cost_pricelist.sudo().write({'is_standard_cost_pricelist': True})

    def test_product_without_cost_rule_matches_so(self):
        """Product with no rule on cost pricelist behaves identically.
        Odoo falls back to list_price, so cost=50 matches SO."""
        other = self.env['product.product'].create({
            'name': 'Other Widget',
            'type': 'service',
            'categ_id': self.category.id,
            'sale_ok': True,
            'list_price': 50.0,
            'taxes_id': [(5, 0, 0)],
        })
        order = self._draft_pos_order([(other.id, 1, 50.0)])
        order.invalidate_recordset()
        so = self._sale_order([(other.id, 1, 50.0)])

        self.assertAlmostEqual(
            order.line_ids[0].standard_cost_price,
            so.order_line[0].purchase_price, places=2,
        )
        self.assertAlmostEqual(order.margin, so.margin, places=2)

    def test_return_order_margin_negative(self):
        """Return order negates margin to match negative amount_untaxed."""
        order = self._draft_pos_order([(self.product.id, 1, 100.0)])
        order.invalidate_recordset()
        self.assertAlmostEqual(order.margin, 40.0, places=2)  # 100 - 60 = 40

        return_order = self.env['pos.lite.order'].create({
            'company_id': self.company.id,
            'channel': 'phone',
            'partner_id': self.partner.id,
            'warehouse_id': self.warehouse.id,
            'pricelist_id': self.sales_pricelist.id,
            'session_id': self.session.id,
            'return_of_order_id': order.id,
            'line_ids': [(0, 0, {
                'product_id': self.product.id,
                'qty': 1,
                'price_unit': 100.0,
                'returned_from_line_id': order.line_ids[0].id,
            })],
        })
        return_order.invalidate_recordset()

        # Line margin stays positive (subtotal=100, cost=60, margin=40).
        # Order-level negates it → margin=-40. amount_untaxed=-100 → rate=0.4.
        self.assertAlmostEqual(return_order.line_ids[0].margin, 40.0, places=2)
        self.assertAlmostEqual(return_order.margin, -40.0, places=2)
        self.assertAlmostEqual(return_order.margin_percent, 0.4, places=4)
