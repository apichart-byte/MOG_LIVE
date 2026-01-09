# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from datetime import datetime


class BuzClearingPaymentWizard(models.TransientModel):
    _name = 'buz.clearing.payment.wizard'
    _description = 'Inter-Customer Clearing Payment Wizard'
    
    # Step 1: Payment Header
    paying_partner_id = fields.Many2one(
        'res.partner', string='Paying Customer', required=True,
        domain=[('is_company', '=', True), ('vat', '!=', False)]
    )
    paying_partner_tax_id = fields.Char(
        string='Tax ID', compute='_compute_paying_partner_tax_id', readonly=True,
        help='Tax ID of the selected paying customer'
    )
    journal_id = fields.Many2one(
        'account.journal', string='Payment Journal', required=True,
        domain=[('type', 'in', ['bank', 'cash'])]
    )
    payment_date = fields.Date(
        string='Payment Date', required=True, default=fields.Date.today
    )
    currency_id = fields.Many2one(
        'res.currency', string='Currency', required=True,
        default=lambda self: self.env.company.currency_id
    )
    amount = fields.Monetary(
        string='Payment Amount', required=True, currency_field='currency_id'
    )
    reference = fields.Char(
        string='Reference'
    )
    
    # Step 2: Allocation
    allocation_line_ids = fields.One2many(
        'buz.clearing.payment.line', 'wizard_id', string='Allocations'
    )
    
    # Computed fields
    total_allocated = fields.Monetary(
        string='Total Allocated', compute='_compute_totals', 
        currency_field='currency_id'
    )
    remaining_amount = fields.Monetary(
        string='Remaining Amount', compute='_compute_totals', 
        currency_field='currency_id'
    )
    state = fields.Selection([
        ('header', 'Payment Header'),
        ('allocate', 'Allocate Invoices'),
        ('review', 'Review & Confirm'),
    ], string='State', default='header')
    
    @api.depends('paying_partner_id')
    def _compute_paying_partner_tax_id(self):
        """Compute tax ID of paying customer"""
        for wizard in self:
            wizard.paying_partner_tax_id = wizard.paying_partner_id.vat or ''
    
    @api.depends('amount', 'allocation_line_ids.allocate_amount')
    def _compute_totals(self):
        for wizard in self:
            wizard.total_allocated = sum(wizard.allocation_line_ids.mapped('allocate_amount'))
            wizard.remaining_amount = wizard.amount - wizard.total_allocated
    
    @api.onchange('journal_id')
    def onchange_journal_id(self):
        """Set currency based on journal"""
        if self.journal_id:
            self.currency_id = self.journal_id.currency_id or self.env.company.currency_id
    
    @api.onchange('paying_partner_id')
    def onchange_paying_partner_id(self):
        """Clear allocation lines when paying partner changes"""
        self.allocation_line_ids = [(5, 0, 0)]
    
    def action_next(self):
        """Move to next step"""
        if self.state == 'header':
            # Validate header
            if not self.paying_partner_id:
                raise ValidationError(_('Please select a paying customer.'))
            if not self.journal_id:
                raise ValidationError(_('Please select a payment journal.'))
            if not self.amount or self.amount <= 0:
                raise ValidationError(_('Payment amount must be greater than 0.'))
            
            # Load available invoices
            self._load_available_invoices()
            
            self.state = 'allocate'
            return {
                'type': 'ir.actions.act_window',
                'res_model': self._name,
                'res_id': self.id,
                'view_mode': 'form',
                'view_id': self.env.ref('buz_inter_customer_clearing_payment.view_clearing_payment_wizard_form').id,
                'target': 'new',
                'context': self.env.context,
            }
        
        elif self.state == 'allocate':
            # Validate allocations
            if not any(line.selected for line in self.allocation_line_ids):
                raise ValidationError(_('Please select at least one invoice to allocate.'))
            
            self.state = 'review'
            return {
                'type': 'ir.actions.act_window',
                'res_model': self._name,
                'res_id': self.id,
                'view_mode': 'form',
                'view_id': self.env.ref('buz_inter_customer_clearing_payment.view_clearing_payment_wizard_review').id,
                'target': 'new',
                'context': self.env.context,
            }
        
        return {'type': 'ir.actions.act_window_close'}
    
    def action_previous(self):
        """Move to previous step"""
        if self.state == 'allocate':
            self.state = 'header'
        elif self.state == 'review':
            self.state = 'allocate'
        
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'view_id': self.env.ref('buz_inter_customer_clearing_payment.view_clearing_payment_wizard_form').id,
            'target': 'new',
            'context': self.env.context,
        }
    
    def action_auto_fill_fifo(self):
        """Auto-fill allocations using FIFO logic filtered by Tax ID"""
        if not self.paying_partner_id or not self.paying_partner_id.vat:
            raise ValidationError(
                _('Paying customer must have a Tax ID to use auto-fill feature.')
            )
        
        # Get all customers with the same Tax ID
        partner_with_same_tax = self.env['res.partner'].search([
            ('vat', '=', self.paying_partner_id.vat),
        ])
        
        # Get all unpaid invoices from customers with same Tax ID, sorted by date
        invoices = self.env['account.move'].search([
            ('partner_id', 'in', partner_with_same_tax.ids),
            ('state', '=', 'posted'),
            ('move_type', '=', 'out_invoice'),
            ('payment_state', 'in', ['not_paid', 'partial']),
        ], order='invoice_date asc')
        
        remaining = self.amount
        allocation_lines = []
        
        for invoice in invoices:
            if remaining <= 0:
                break
            
            residual = invoice.amount_residual
            allocate = min(residual, remaining)
            
            allocation_lines.append((0, 0, {
                'invoice_id': invoice.id,
                'selected': True,
                'allocate_amount': allocate,
            }))
            
            remaining -= allocate
        
        self.allocation_line_ids = allocation_lines
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'view_id': self.env.ref('buz_inter_customer_clearing_payment.view_clearing_payment_wizard_form').id,
            'target': 'new',
            'context': self.env.context,
        }
    
    def action_clear_allocation(self):
        """Clear all allocations"""
        self.allocation_line_ids = [(5, 0, 0)]
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'view_id': self.env.ref('buz_inter_customer_clearing_payment.view_clearing_payment_wizard_form').id,
            'target': 'new',
            'context': self.env.context,
        }
    
    def action_confirm_and_post(self):
        """Create payment and clearing entries"""
        # Validate total allocation
        if self.total_allocated > self.amount:
            raise ValidationError(_('Total allocated amount cannot exceed payment amount.'))
        
        # Validate that we have allocations
        selected_lines = self.allocation_line_ids.filtered(lambda l: l.selected and l.allocate_amount > 0)
        if not selected_lines:
            raise ValidationError(_('Please select at least one invoice to allocate payment.'))
        
        # Create payment
        payment_vals = {
            'partner_id': self.paying_partner_id.id,
            'journal_id': self.journal_id.id,
            'date': self.payment_date,
            'amount': self.amount,
            'currency_id': self.currency_id.id,
            'payment_type': 'inbound',
            'partner_type': 'customer',
            'ref': self.reference,
            'is_clearing_payment': True,
            'clearing_advance_amount': self.remaining_amount,
        }
        
        payment = self.env['account.payment'].create(payment_vals)
        payment.action_post()
        
        import logging
        _logger = logging.getLogger(__name__)
        _logger.info('='*80)
        _logger.info('Payment created: %s', payment.name)
        _logger.info('Selected lines count: %s', len(selected_lines))
        
        # Process allocations
        for line in selected_lines:
            _logger.info('---')
            _logger.info('Processing line - Invoice: %s', line.invoice_id.name)
            _logger.info('Invoice Partner: %s (ID: %s)', line.invoice_partner_id.name, line.invoice_partner_id.id)
            _logger.info('Paying Partner: %s (ID: %s)', self.paying_partner_id.name, self.paying_partner_id.id)
            _logger.info('Same partner? %s', line.invoice_partner_id == self.paying_partner_id)
            _logger.info('Allocate amount: %s', line.allocate_amount)
            
            # Skip if paying customer is the same as invoice customer
            if line.invoice_partner_id == self.paying_partner_id:
                _logger.info('-> Calling _reconcile_same_customer')
                # Direct reconciliation for same customer
                self._reconcile_same_customer(payment, line)
            else:
                _logger.info('-> Calling _create_clearing_entry')
                # Create clearing entry for different customer
                self._create_clearing_entry(payment, line)
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Success'),
                'message': _('Payment and allocations have been processed successfully.'),
                'type': 'success',
                'sticky': False,
            }
        }
    
    def _load_available_invoices(self):
        """Load all available invoices filtered by same Tax ID as paying customer"""
        if not self.paying_partner_id or not self.paying_partner_id.vat:
            raise ValidationError(
                _('Paying customer must have a Tax ID (VAT) to proceed with clearing payment.')
            )
        
        # Get all customers with the same Tax ID
        partner_with_same_tax = self.env['res.partner'].search([
            ('vat', '=', self.paying_partner_id.vat),
        ])
        
        # Load invoices from customers with same Tax ID
        invoices = self.env['account.move'].search([
            ('partner_id', 'in', partner_with_same_tax.ids),
            ('state', '=', 'posted'),
            ('move_type', '=', 'out_invoice'),
            ('payment_state', 'in', ['not_paid', 'partial']),
        ])
        
        allocation_lines = []
        for invoice in invoices:
            allocation_lines.append((0, 0, {
                'invoice_id': invoice.id,
                'selected': False,
                'allocate_amount': 0.0,
            }))
        
        self.allocation_line_ids = allocation_lines
    
    def _reconcile_same_customer(self, payment, line):
        """Reconcile payment with invoice for same customer"""
        # Find the receivable lines
        payment_line = payment.move_id.line_ids.filtered(
            lambda l: l.account_id.account_type == 'asset_receivable'
        )
        invoice_line = line.invoice_id.line_ids.filtered(
            lambda l: l.account_id.account_type == 'asset_receivable'
        )
        
        if payment_line and invoice_line:
            # Auto reconcile to mark invoice as paid
            lines_to_reconcile = payment_line | invoice_line
            lines_to_reconcile.reconcile()
            
            # Mark reconciliation as clearing reconcile
            partial_reconciles = payment_line.matched_debit_ids | payment_line.matched_credit_ids
            partial_reconciles |= invoice_line.matched_debit_ids | invoice_line.matched_credit_ids
            partial_reconciles.filtered(lambda r: not r.is_clearing_reconcile).write({
                'is_clearing_reconcile': True,
                'clearing_payment_id': payment.id,
            })
            
            # Create clearing link
            self.env['buz.clearing.link'].create({
                'payment_id': payment.id,
                'invoice_id': line.invoice_id.id,
                'amount': line.allocate_amount,
                'date': self.payment_date,
            })
    
    def _create_clearing_entry(self, payment, line):
        """Create clearing journal entry for different customer"""
        # Read and store values before they potentially get lost
        invoice = line.invoice_id
        invoice_partner = line.invoice_partner_id
        allocate_amount = line.allocate_amount
        currency = line.currency_id
        
        import logging
        _logger = logging.getLogger(__name__)
        _logger.info('='*80)
        _logger.info('_create_clearing_entry called')
        _logger.info('Invoice: %s', invoice.name)
        _logger.info('Invoice Partner: %s (ID: %s)', invoice_partner.name, invoice_partner.id)
        _logger.info('Allocate Amount: %s (type: %s)', allocate_amount, type(allocate_amount))
        _logger.info('Currency: %s (ID: %s)', currency.name if currency else 'None', currency.id if currency else 'None')
        _logger.info('Company Currency: %s', self.env.company.currency_id.name)
        
        # Validate allocation amount
        if not allocate_amount or allocate_amount <= 0:
            raise UserError(_('Allocation amount must be greater than 0 for invoice %s') % invoice.name)
        
        # Get accounts
        receivable_account = invoice.line_ids.filtered(
            lambda l: l.account_id.account_type == 'asset_receivable'
        ).account_id
        
        if not receivable_account:
            raise UserError(_('Cannot find receivable account for invoice %s') % invoice.name)
        
        # Determine if we're using foreign currency
        company_currency = self.env.company.currency_id
        is_foreign_currency = currency != company_currency
        
        # Calculate amounts in company currency
        if is_foreign_currency:
            # Convert foreign currency to company currency
            amount_company_currency = currency._convert(
                allocate_amount,
                company_currency,
                self.env.company,
                self.payment_date or fields.Date.today()
            )
        else:
            # Already in company currency
            amount_company_currency = allocate_amount
        
        # Ensure we have valid amounts
        if not amount_company_currency or amount_company_currency <= 0:
            raise UserError(_('Invalid amount calculation for invoice %s. Amount: %s') % (invoice.name, amount_company_currency))
        
        _logger.info('Amount Company Currency: %s', amount_company_currency)
        _logger.info('Is Foreign Currency: %s', is_foreign_currency)
        
        # Prepare line values based on currency
        if is_foreign_currency:
            debit_line_vals = {
                'account_id': receivable_account.id,
                'partner_id': self.paying_partner_id.id,  # Paying customer gets the debt
                'debit': amount_company_currency,
                'credit': 0.0,
                'amount_currency': allocate_amount,
                'currency_id': currency.id,
            }
            credit_line_vals = {
                'account_id': receivable_account.id,
                'partner_id': invoice_partner.id,  # Invoice customer debt is cleared
                'debit': 0.0,
                'credit': amount_company_currency,
                'amount_currency': -allocate_amount,
                'currency_id': currency.id,
            }
        else:
            # For company currency, don't use amount_currency
            debit_line_vals = {
                'account_id': receivable_account.id,
                'partner_id': self.paying_partner_id.id,  # Paying customer gets the debt
                'debit': amount_company_currency,
                'credit': 0.0,
            }
            credit_line_vals = {
                'account_id': receivable_account.id,
                'partner_id': invoice_partner.id,  # Invoice customer debt is cleared
                'debit': 0.0,
                'credit': amount_company_currency,
            }
        
        # Create clearing journal entry
        move_vals = {
            'journal_id': self.journal_id.id,
            'date': self.payment_date,
            'ref': _('Clearing: %s - %s') % (self.paying_partner_id.name, invoice_partner.name),
            'is_clearing_entry': True,
            'clearing_payment_id': payment.id,
            'line_ids': [
                (0, 0, debit_line_vals),
                (0, 0, credit_line_vals),
            ],
        }
        
        _logger.info('Move Vals: %s', move_vals)
        _logger.info('Debit Line: %s', debit_line_vals)
        _logger.info('Credit Line: %s', credit_line_vals)
        
        clearing_move = self.env['account.move'].create(move_vals)
        clearing_move.action_post()
        
        # Reconcile invoice with clearing entry
        # Invoice has debit AR (customer owes us)
        # Clearing has credit AR (customer debt is cleared)
        invoice_line = invoice.line_ids.filtered(
            lambda l: l.account_id.account_type == 'asset_receivable'
        )
        clearing_credit_line = clearing_move.line_ids.filtered(
            lambda l: l.partner_id == invoice_partner and l.credit > 0
        )
        
        _logger.info('Invoice line: %s (debit: %s, credit: %s, partner: %s)', 
                     invoice_line.ids if invoice_line else None,
                     sum(invoice_line.mapped('debit')) if invoice_line else 0,
                     sum(invoice_line.mapped('credit')) if invoice_line else 0,
                     invoice_line.mapped('partner_id.name') if invoice_line else None)
        _logger.info('Clearing credit line: %s (debit: %s, credit: %s, partner: %s)',
                     clearing_credit_line.ids if clearing_credit_line else None,
                     sum(clearing_credit_line.mapped('debit')) if clearing_credit_line else 0,
                     sum(clearing_credit_line.mapped('credit')) if clearing_credit_line else 0,
                     clearing_credit_line.mapped('partner_id.name') if clearing_credit_line else None)
        
        if invoice_line and clearing_credit_line:
            # Auto reconcile invoice with clearing entry to mark as paid
            lines_to_reconcile = invoice_line | clearing_credit_line
            lines_to_reconcile.reconcile()
            
            # Mark as clearing reconcile
            partial_reconciles = invoice_line.matched_debit_ids | invoice_line.matched_credit_ids
            partial_reconciles |= clearing_credit_line.matched_debit_ids | clearing_credit_line.matched_credit_ids
            partial_reconciles.filtered(lambda r: not r.is_clearing_reconcile).write({
                'is_clearing_reconcile': True,
                'clearing_payment_id': payment.id,
            })
        
        # Reconcile payment with clearing entry
        # Payment has debit AR (we received money, customer debt increases)
        # Clearing has debit AR (paying customer takes on the debt)
        payment_line = payment.move_id.line_ids.filtered(
            lambda l: l.account_id.account_type == 'asset_receivable'
        )
        clearing_debit_line = clearing_move.line_ids.filtered(
            lambda l: l.partner_id == self.paying_partner_id and l.debit > 0
        )
        
        _logger.info('Payment line: %s (debit: %s, credit: %s, partner: %s)',
                     payment_line.ids if payment_line else None,
                     sum(payment_line.mapped('debit')) if payment_line else 0,
                     sum(payment_line.mapped('credit')) if payment_line else 0,
                     payment_line.mapped('partner_id.name') if payment_line else None)
        _logger.info('Clearing debit line: %s (debit: %s, credit: %s, partner: %s)',
                     clearing_debit_line.ids if clearing_debit_line else None,
                     sum(clearing_debit_line.mapped('debit')) if clearing_debit_line else 0,
                     sum(clearing_debit_line.mapped('credit')) if clearing_debit_line else 0,
                     clearing_debit_line.mapped('partner_id.name') if clearing_debit_line else None)
        
        if payment_line and clearing_debit_line:
            # Auto reconcile payment with clearing entry
            lines_to_reconcile = payment_line | clearing_debit_line
            lines_to_reconcile.reconcile()
            
            # Mark as clearing reconcile
            partial_reconciles = payment_line.matched_debit_ids | payment_line.matched_credit_ids
            partial_reconciles |= clearing_debit_line.matched_debit_ids | clearing_debit_line.matched_credit_ids
            partial_reconciles.filtered(lambda r: not r.is_clearing_reconcile).write({
                'is_clearing_reconcile': True,
                'clearing_payment_id': payment.id,
            })
        
        # Create clearing link
        self.env['buz.clearing.link'].create({
            'payment_id': payment.id,
            'clearing_move_id': clearing_move.id,
            'invoice_id': invoice.id,
            'amount': allocate_amount,
            'date': self.payment_date,
        })