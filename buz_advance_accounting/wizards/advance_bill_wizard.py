# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo import Command
from odoo.exceptions import UserError


class PurchaseAdvanceBillWizard(models.TransientModel):
    _name = 'purchase.advance.bill.wizard'
    _description = 'Create Advance Accrual from PO'

    purchase_id = fields.Many2one('purchase.order', required=True)
    journal_id = fields.Many2one('account.journal', string='Journal', required=True, domain="[('type', '=', 'general')]")
    accrual_account_id = fields.Many2one('account.account', string='Accrual Account', required=True, domain="[('deprecated', '=', False)]")
    amount = fields.Monetary(required=True)
    currency_id = fields.Many2one('res.currency', required=True, default=lambda self: self.env.company.currency_id)
    date = fields.Date(default=fields.Date.context_today)
    ref = fields.Char(string='Reference')
    
    # Exchange rate fields
    exchange_rate = fields.Float(string='Exchange Rate (USD→THB)', digits=(12, 6), default=1.0, 
                                  help='Exchange rate from USD to THB. For example, 35.50 means 1 USD = 35.50 THB')
    amount_thb = fields.Monetary(string='Amount in THB', currency_field='company_currency_id', compute='_compute_amount_thb', store=True)
    company_currency_id = fields.Many2one('res.currency', related='purchase_id.company_id.currency_id', store=False)
    diff_account_id = fields.Many2one('account.account', string='Currency Difference Account', 
                                       domain="[('deprecated', '=', False)]",
                                       help='Account for posting currency exchange rate differences')

    preview_line_ids = fields.One2many('purchase.advance.bill.preview.line', 'wizard_id', string='Preview Lines', readonly=True)

    @api.depends('amount', 'exchange_rate')
    def _compute_amount_thb(self):
        for wizard in self:
            wizard.amount_thb = wizard.amount * wizard.exchange_rate
    
    @api.onchange('purchase_id')
    def _onchange_purchase(self):
        if self.purchase_id:
            po = self.purchase_id
            # Set currency first
            self.currency_id = po.currency_id or self.env.company.currency_id
            # Set amount in original currency (USD)
            # Use amount_total directly without conversion
            self.amount = po.amount_total
            
            # Get exchange rate from system
            usd_currency = self.env['res.currency'].search([('name', '=', 'USD')], limit=1)
            thb_currency = self.env['res.currency'].search([('name', '=', 'THB')], limit=1)
            
            if usd_currency and thb_currency and self.currency_id == usd_currency:
                # Get exchange rate from currency rate table for today
                rate = usd_currency._convert(1.0, thb_currency, self.env.company, self.date or fields.Date.today())
                self.exchange_rate = rate
            else:
                self.exchange_rate = 1.0
                
            self._recompute_preview()

    @api.onchange('amount', 'accrual_account_id', 'journal_id', 'date', 'ref', 'exchange_rate')
    def _onchange_recompute_preview(self):
        self._recompute_preview()

    def _get_payable_account_from_partner(self, partner):
        return partner.property_account_payable_id

    def _get_expense_account_from_po(self, po):
        """Get expense account from products in PO lines"""
        expense_account = False
        for line in po.order_line:
            if line.product_id:
                # Get expense account from product category
                if line.product_id.categ_id.property_account_expense_categ_id:
                    expense_account = line.product_id.categ_id.property_account_expense_categ_id
                    break
                # Fallback to product's own expense account
                elif line.product_id.property_account_expense_id:
                    expense_account = line.product_id.property_account_expense_id
                    break
        
        # If no expense account found from products, use company's default
        if not expense_account:
            expense_account = po.company_id.account_journal_purchase_id.default_account_id
            
        return expense_account

    def _get_tax_input_account(self, po):
        """Get tax input account for purchase taxes"""
        tax_account = False
        
        # Get tax account from purchase order lines
        for line in po.order_line:
            for tax in line.taxes_id:
                if tax.type_tax_use == 'purchase':
                    # Get the input tax account
                    tax_account = tax.invoice_repartition_line_ids.filtered(
                        lambda r: r.repartition_type == 'tax'
                    ).account_id
                    if tax_account:
                        break
            if tax_account:
                break
        
        # Fallback: search for typical input tax account
        if not tax_account:
            tax_account = self.env['account.account'].search([
                ('code', 'like', '15%'),  # Common input tax account code
                ('company_id', '=', po.company_id.id)
            ], limit=1)
            
        # Another fallback: search for any input tax related account
        if not tax_account:
            tax_account = self.env['account.account'].search([
                ('name', 'ilike', 'input'),
                ('name', 'ilike', 'tax'),
                ('company_id', '=', po.company_id.id)
            ], limit=1)
            
        return tax_account

    def _recompute_preview(self):
        for wizard in self:
            lines = []
            if not wizard.purchase_id or not wizard.accrual_account_id or wizard.amount <= 0:
                wizard.preview_line_ids = [Command.clear()]
                continue
            po = wizard.purchase_id
            company = po.company_id
            company_currency = company.currency_id
            src_currency = wizard.currency_id or po.currency_id or company_currency
            
            # Use the amount from wizard (which is the total amount including tax in USD)
            total_amount_usd = wizard.amount
            
            # Calculate tax rate from PO to split the amount
            if po.amount_total > 0:
                tax_rate = po.amount_tax / po.amount_total
                untaxed_rate = po.amount_untaxed / po.amount_total
            else:
                tax_rate = 0
                untaxed_rate = 1
            
            # Split the USD amount
            amount_untaxed_usd = total_amount_usd * untaxed_rate
            amount_tax_usd = total_amount_usd * tax_rate
            
            # Convert DEBIT side using USER's exchange rate
            if wizard.exchange_rate and wizard.exchange_rate > 0:
                amount_untaxed_thb_debit = amount_untaxed_usd * wizard.exchange_rate
                amount_tax_thb_debit = amount_tax_usd * wizard.exchange_rate
                total_debit = amount_untaxed_thb_debit + amount_tax_thb_debit
            else:
                amount_untaxed_thb_debit = src_currency._convert(amount_untaxed_usd, company_currency, company, wizard.date or fields.Date.context_today(wizard))
                amount_tax_thb_debit = src_currency._convert(amount_tax_usd, company_currency, company, wizard.date or fields.Date.context_today(wizard))
                total_debit = amount_untaxed_thb_debit + amount_tax_thb_debit
            
            # Convert CREDIT side using SYSTEM rate (accrual account)
            total_amount_thb_credit = src_currency._convert(total_amount_usd, company_currency, company, wizard.date or fields.Date.context_today(wizard))
            
            # Calculate currency difference
            currency_diff = total_debit - total_amount_thb_credit
            
            payable_account = wizard._get_payable_account_from_partner(po.partner_id)
            expense_account = wizard._get_expense_account_from_po(po)
            
            # Get tax input account
            tax_input_account = wizard._get_tax_input_account(po)
            
            label = wizard.ref or _('Advance Accrual')
            label_tax = wizard.ref or _('Input Tax')
            
            if amount_untaxed_thb_debit > 0 and expense_account and wizard.accrual_account_id:
                # Expense line (Debit) - using USER's exchange rate
                lines.append((0, 0, {
                    'account_id': expense_account.id,
                    'name': label + ' (Rate: %.6f)' % wizard.exchange_rate,
                    'debit': amount_untaxed_thb_debit,
                    'credit': 0.0,
                }))
                
                # Tax line (Debit) - if there's tax, using USER's exchange rate
                if amount_tax_thb_debit > 0 and tax_input_account:
                    lines.append((0, 0, {
                        'account_id': tax_input_account.id,
                        'name': label_tax + ' (Rate: %.6f)' % wizard.exchange_rate,
                        'debit': amount_tax_thb_debit,
                        'credit': 0.0,
                    }))
                
                # Accrual account (Credit) - using SYSTEM rate
                system_rate = total_amount_thb_credit / total_amount_usd if total_amount_usd > 0 else 0
                lines.append((0, 0, {
                    'account_id': wizard.accrual_account_id.id,
                    'name': label + ' (System Rate: %.6f)' % system_rate,
                    'debit': 0.0,
                    'credit': total_amount_thb_credit,
                }))
                
                # Currency difference line (if exists and diff account is set)
                if abs(currency_diff) > 0.01 and wizard.diff_account_id:
                    if currency_diff > 0:
                        # Debit > Credit: need to credit diff account
                        lines.append((0, 0, {
                            'account_id': wizard.diff_account_id.id,
                            'name': _('Currency Difference'),
                            'debit': 0.0,
                            'credit': abs(currency_diff),
                        }))
                    else:
                        # Credit > Debit: need to debit diff account
                        lines.append((0, 0, {
                            'account_id': wizard.diff_account_id.id,
                            'name': _('Currency Difference'),
                            'debit': abs(currency_diff),
                            'credit': 0.0,
                        }))
            
            wizard.preview_line_ids = [Command.clear()] + [Command.create(vals[2]) for vals in lines]

    def action_create(self):
        self.ensure_one()
        po = self.purchase_id
        if not po:
            raise UserError(_('No Purchase Order provided.'))
        if self.amount <= 0:
            raise UserError(_('Amount must be positive.'))
        if not self.accrual_account_id:
            raise UserError(_('Please select an Accrual Account.'))

        expense_account = self._get_expense_account_from_po(po)
        if not expense_account:
            raise UserError(_('No expense account found for products in this Purchase Order.'))
        
        tax_input_account = self._get_tax_input_account(po)
            
        company = po.company_id
        company_currency = company.currency_id
        src_currency = self.currency_id or po.currency_id or company_currency
        
        # Use the amount from wizard (total amount including tax in USD)
        total_amount_usd = self.amount
        
        # Calculate tax rate from PO to split the amount
        if po.amount_total > 0:
            tax_rate = po.amount_tax / po.amount_total
            untaxed_rate = po.amount_untaxed / po.amount_total
        else:
            tax_rate = 0
            untaxed_rate = 1
        
        # Split the USD amount
        amount_untaxed_usd = total_amount_usd * untaxed_rate
        amount_tax_usd = total_amount_usd * tax_rate
        
        # Convert DEBIT side using USER's exchange rate
        if self.exchange_rate and self.exchange_rate > 0:
            amount_untaxed_thb_debit = amount_untaxed_usd * self.exchange_rate
            amount_tax_thb_debit = amount_tax_usd * self.exchange_rate
            total_debit = amount_untaxed_thb_debit + amount_tax_thb_debit
        else:
            # Fallback to system rate
            amount_untaxed_thb_debit = src_currency._convert(amount_untaxed_usd, company_currency, company, self.date or fields.Date.context_today(self))
            amount_tax_thb_debit = src_currency._convert(amount_tax_usd, company_currency, company, self.date or fields.Date.context_today(self))
            total_debit = amount_untaxed_thb_debit + amount_tax_thb_debit
        
        # Convert CREDIT side using SYSTEM rate (accrual account)
        total_amount_thb_credit = src_currency._convert(total_amount_usd, company_currency, company, self.date or fields.Date.context_today(self))
        
        # Calculate currency difference
        currency_diff = total_debit - total_amount_thb_credit

        # Prepare journal entry lines
        journal_lines = []
        
        # Expense line (Debit) - using USER's exchange rate
        journal_lines.append((0, 0, {
            'name': (self.ref or _('Advance Accrual')) + (' (Rate: %.6f)' % self.exchange_rate if self.exchange_rate else ''),
            'debit': amount_untaxed_thb_debit if amount_untaxed_thb_debit > 0 else 0.0,
            'credit': 0.0,
            'account_id': expense_account.id,
            'partner_id': po.partner_id.id,
            'currency_id': src_currency.id,
            'amount_currency': amount_untaxed_usd if src_currency != company_currency else amount_untaxed_thb_debit,
        }))
        
        # Tax line (Debit) - if there's tax and tax account, using USER's exchange rate
        if amount_tax_thb_debit > 0 and tax_input_account:
            journal_lines.append((0, 0, {
                'name': (self.ref or _('Input Tax')) + (' (Rate: %.6f)' % self.exchange_rate if self.exchange_rate else ''),
                'debit': amount_tax_thb_debit,
                'credit': 0.0,
                'account_id': tax_input_account.id,
                'partner_id': po.partner_id.id,
                'currency_id': src_currency.id,
                'amount_currency': amount_tax_usd if src_currency != company_currency else amount_tax_thb_debit,
            }))
        
        # Accrual account (Credit) - using SYSTEM rate
        system_rate = total_amount_thb_credit / total_amount_usd if total_amount_usd > 0 else 0
        journal_lines.append((0, 0, {
            'name': (self.ref or _('Advance Accrual')) + (' (System Rate: %.6f)' % system_rate),
            'debit': 0.0,
            'credit': total_amount_thb_credit if total_amount_thb_credit > 0 else 0.0,
            'account_id': self.accrual_account_id.id,
            'partner_id': po.partner_id.id,
            'currency_id': src_currency.id,
            'amount_currency': -total_amount_usd if src_currency != company_currency else -total_amount_thb_credit,
        }))
        
        # Currency difference line (if exists and diff account is set)
        if abs(currency_diff) > 0.01 and self.diff_account_id:
            if currency_diff > 0:
                # Total Debit > Total Credit: need to credit diff account to balance
                journal_lines.append((0, 0, {
                    'name': _('Currency Difference (%.6f - %.6f)') % (self.exchange_rate or 0, system_rate),
                    'debit': 0.0,
                    'credit': abs(currency_diff),
                    'account_id': self.diff_account_id.id,
                    'partner_id': po.partner_id.id,
                    'currency_id': company_currency.id,
                }))
            else:
                # Total Credit > Total Debit: need to debit diff account to balance
                journal_lines.append((0, 0, {
                    'name': _('Currency Difference (%.6f - %.6f)') % (self.exchange_rate or 0, system_rate),
                    'debit': abs(currency_diff),
                    'credit': 0.0,
                    'account_id': self.diff_account_id.id,
                    'partner_id': po.partner_id.id,
                    'currency_id': company_currency.id,
                }))
        elif abs(currency_diff) > 0.01 and not self.diff_account_id:
            raise UserError(_('Currency difference detected (%.2f THB) but no Currency Difference Account is selected. Please select an account to post the difference.') % currency_diff)

        move_vals = {
            'move_type': 'entry',
            'date': self.date or fields.Date.context_today(self),
            'journal_id': self.journal_id.id,
            'ref': self.ref or (po.name + ' - ' + _('Advance Accrual')),
            'partner_id': po.partner_id.id,
            'currency_id': company_currency.id,
            'line_ids': journal_lines,
            'purchase_id': po.id,
        }
        move = self.env['account.move'].create(move_vals)
        move.action_post()
        accrual = self.env['purchase.advance.accrual'].create({
            'purchase_id': po.id,
            'move_id': move.id,
            'amount': total_amount_usd,  # Store USD amount
            'currency_id': self.currency_id.id,
            'date': self.date,
            'exchange_rate': self.exchange_rate,
            'amount_thb': total_debit,  # Store THB amount calculated with user's rate
            'diff_account_id': self.diff_account_id.id if self.diff_account_id else False,
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'res_id': move.id,
            'view_mode': 'form',
            'target': 'current',
        }


class PurchaseAdvanceBillPreviewLine(models.TransientModel):
    _name = 'purchase.advance.bill.preview.line'
    _description = 'Preview Lines for Advance Accrual Wizard'

    wizard_id = fields.Many2one('purchase.advance.bill.wizard', required=True, ondelete='cascade')
    account_id = fields.Many2one('account.account', string='Account', required=True)
    name = fields.Char(string='Label')
    debit = fields.Monetary(currency_field='currency_id')
    credit = fields.Monetary(currency_field='currency_id')
    currency_id = fields.Many2one(related='wizard_id.purchase_id.company_id.currency_id', store=False)
