from odoo import models, fields, api, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)

class TaxUndueLine(models.Model):
    _name = 'tax.undue.line'
    _description = 'Tax Undue Line'
    _rec_name = 'name'

    name = fields.Char(string="Tax Invoice No")
    move_id = fields.Many2one('account.move', string="Journal Entry", required=True)
    partner_id = fields.Many2one('res.partner', string="Partner", required=True)
    tax_invoice_date = fields.Date(string="Tax Invoice Date")
    tax_id = fields.Many2one('account.tax', string="Tax", required=True)
    account_id = fields.Many2one('account.account', string="VAT Undue Account", required=True)
    
    tax_rate = fields.Float(string="Tax Rate")
    tax_base = fields.Monetary(string="Tax Base", currency_field='currency_id')
    tax_amount = fields.Monetary(string="Tax Amount", currency_field='currency_id')
    
    state = fields.Selection([
        ('undue', 'Undue'),
        ('refund', 'Refund'),
        ('used', 'Used')
    ], string="State", default='undue', compute='_compute_state', store=True)
    
    used_move_id = fields.Many2one('account.move', string="Usage Journal Entry")
    company_id = fields.Many2one('res.company', string="Company", required=True, default=lambda self: self.env.company)
    currency_id = fields.Many2one('res.currency', string="Currency", related='company_id.currency_id', store=True)

    # Partial usage handling
    used_tax_amount = fields.Monetary(string="Used Tax Amount", currency_field='currency_id', default=0.0)
    refunded_tax_amount = fields.Monetary(string="Refunded Tax Amount", currency_field='currency_id', default=0.0)
    remaining_tax_amount = fields.Monetary(string="Remaining Tax Amount", currency_field='currency_id', compute='_compute_remaining_tax_amount', store=True)

    origin_move_type = fields.Selection(related='move_id.move_type', store=True, string="Origin Move Type")
    original_undue_line_id = fields.Many2one('tax.undue.line', string="Original Undue Line")

    @api.depends('tax_amount', 'used_tax_amount', 'refunded_tax_amount')
    def _compute_remaining_tax_amount(self):
        for record in self:
            record.remaining_tax_amount = record.tax_amount - record.used_tax_amount - record.refunded_tax_amount

    @api.depends('remaining_tax_amount')
    def _compute_state(self):
        for record in self:
            # Floating point comparison
            if abs(record.remaining_tax_amount) < 0.001:
                # If it was fully refunded, mark as refund. Otherwise used.
                if record.refunded_tax_amount > 0 and record.used_tax_amount == 0:
                     record.state = 'refund'
                else:
                     record.state = 'used'
            elif record.remaining_tax_amount < 0:
                record.state = 'refund'
            else:
                record.state = 'undue'

    def action_use_vat(self):
        """เปิด Wizard ให้ User เลือกวันที่ลงบัญชี"""
        # Validation ก่อนเปิด wizard
        for rec in self:
            if rec.state == 'used':
                raise UserError(_("Selected lines contain already used VAT."))
            if rec.state == 'refund':
                raise UserError(_("Cannot use VAT for refunded lines. This line was already used and then reversed by a Credit Note."))
            if rec.tax_amount == 0:
                raise UserError(_("Cannot use VAT for amount 0."))
            if rec.tax_amount < 0:
                raise UserError(_("Cannot use VAT for negative amount (Credit Note lines)."))
            if rec.remaining_tax_amount <= 0:
                raise UserError(_("No remaining VAT amount to use."))
            if not rec.tax_id.undue_conversion_tax_id:
                raise UserError(_("Please configure the Target VAT Tax on tax %s.") % rec.tax_id.name)
            if not rec.tax_id.undue_input_vat_account_id:
                raise UserError(_("Please configure the Input VAT Account on tax %s.") % rec.tax_id.name)
            
            # ตรวจสอบว่า account_id (Undue Account) ต้องไม่เหมือนกับ Input VAT Account
            if rec.account_id.id == rec.tax_id.undue_input_vat_account_id.id:
                raise UserError(_("VAT Undue Account and Input VAT Account cannot be the same! Please check tax configuration for %s.") % rec.tax_id.name)
        
        # เปิด wizard
        return {
            'type': 'ir.actions.act_window',
            'name': _('Use VAT - Select Accounting Date'),
            'res_model': 'vat.undue.use.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_undue_line_ids': [(6, 0, self.ids)],
            },
        }

    def _process_use_vat(self):
        """ประมวลผลการใช้ VAT (เรียกจาก wizard)"""
        # รับวันที่ลงบัญชีจาก context
        accounting_date = self.env.context.get('accounting_date', fields.Date.context_today(self))
        
        # Create Journal Entries
        moves = self.env['account.move']
        
        for rec in self:
            amount = rec.remaining_tax_amount
            if amount == 0:
                continue

            # Determine Target Account and Tags
            target_tax = rec.tax_id.undue_conversion_tax_id
            
            # ต้องตรวจสอบว่า undue_input_vat_account_id มีค่าก่อน
            if not rec.tax_id.undue_input_vat_account_id:
                raise UserError(_("Input VAT Account not configured for tax %s. Please check the tax configuration.") % rec.tax_id.name)
                
            target_account_id = rec.tax_id.undue_input_vat_account_id.id
            
            # Debug: แสดงบัญชีที่จะใช้
            _logger.info("=== VAT Undue Usage Debug ===")
            _logger.info(f"Tax Undue Line: {rec.name}")
            _logger.info(f"Undue Account (Credit): {rec.account_id.code} - {rec.account_id.name} (ID: {rec.account_id.id})")
            _logger.info(f"Input VAT Account (Debit): {rec.tax_id.undue_input_vat_account_id.code} - {rec.tax_id.undue_input_vat_account_id.name} (ID: {target_account_id})")
            _logger.info(f"Amount: {amount}")
            
            # Validate accounts
            if rec.account_id.id == target_account_id:
                raise UserError(_(
                    "VAT Undue Account and Input VAT Account cannot be the same!\n"
                    "Current configuration uses account: %s - %s\n"
                    "Please check tax configuration for: %s"
                ) % (rec.account_id.code, rec.account_id.name, rec.tax_id.name))
            
            # Get Tags from Target Tax Repartition
            # If amount > 0 (Purchase), use invoice_repartition_line_ids
            # If amount < 0 (Refund), use refund_repartition_line_ids
            repartition_lines = target_tax.invoice_repartition_line_ids if amount > 0 else target_tax.refund_repartition_line_ids
            
            # Find the tax component line for tags
            rep_line = next((l for l in repartition_lines if l.repartition_type == 'tax'), None)
            
            if not rep_line:
                raise UserError(_("Target Tax %s has no tax repartition line.") % target_tax.name)

            tag_ids = rep_line.tag_ids.ids

            journal = self.env['account.journal'].search([('type', '=', 'general'), ('company_id', '=', rec.company_id.id)], limit=1)
            if not journal:
                 raise UserError(_("Please define a General Journal for this company."))

            # Debit / Credit logic
            # ตอนกด "Use VAT" เราต้องการ:
            # - ลดยอด VAT Undue Account (Credit 116600)
            # - เพิ่มยอด Input VAT Account (Debit 116400)
            
            # amount ปกติจะเป็นบวก (ยอด VAT ที่ต้องการนำไปใช้)
            amount_abs = abs(amount)
            
            # ตรวจสอบว่า amount มีค่าและ accounts ไม่ซ้ำกัน
            if amount_abs <= 0:
                raise UserError(_("Invalid amount for VAT usage: %s") % amount)
            
            if rec.account_id.id == target_account_id:
                raise UserError(_("Source and Target accounts cannot be the same!"))
            
            # สร้าง Journal Lines
            # Line 1: Debit Input VAT Account (116400)
            # Line 2: Credit Undue Account (116600)
            
            if amount > 0:
                # กรณีปกติ: ภาษีซื้อ
                # Dr 116400 Input VAT
                # Cr 116600 VAT Undue
                line_1_debit = amount_abs
                line_1_credit = 0.0
                line_2_debit = 0.0
                line_2_credit = amount_abs
            else:
                # กรณี Refund/Reversal (ถ้ามี)
                # Dr 116600 VAT Undue
                # Cr 116400 Input VAT
                line_1_debit = 0.0
                line_1_credit = amount_abs
                line_2_debit = amount_abs
                line_2_credit = 0.0

            move_vals = {
                'journal_id': journal.id,
                'date': accounting_date,  # ใช้วันที่จาก wizard
                'ref': _("Clear Undue VAT: %s") % rec.name,
                'move_type': 'entry',
                'line_ids': [
                    (0, 0, {
                        'name': _("Input VAT from Undue: %s") % rec.name,
                        'account_id': target_account_id,  # 116400 - Input VAT
                        'debit': line_1_debit,
                        'credit': line_1_credit,
                        'partner_id': rec.partner_id.id,
                        'tax_tag_ids': [(6, 0, tag_ids)],
                        'tax_line_id': target_tax.id,  # เพื่อให้แสดง Originator Tax
                        'tax_base_amount': rec.tax_base,  # เพื่อให้แสดง Tax Base
                    }),
                    (0, 0, {
                        'name': _("Clear Undue VAT: %s") % rec.name,
                        'account_id': rec.account_id.id,  # 116600 - VAT Undue
                        'debit': line_2_debit,
                        'credit': line_2_credit,
                        'partner_id': rec.partner_id.id,
                    }),
                ]
            }
            
            _logger.info("Creating Journal Entry with vals:")
            _logger.info(f"Journal: {journal.name}")
            _logger.info(f"Line 1 (Input VAT): Account={target_account_id}, Dr={line_1_debit}, Cr={line_1_credit}")
            _logger.info(f"Line 2 (VAT Undue): Account={rec.account_id.id}, Dr={line_2_debit}, Cr={line_2_credit}")
            
            # สร้าง move ด้วย with_context เพื่อไม่ให้ auto-compute
            move = self.env['account.move'].with_context(
                check_move_validity=False,
                skip_invoice_sync=True,
                skip_account_move_synchronization=True
            ).create(move_vals)
            
            _logger.info(f"Created move {move.name}, checking lines:")
            for line in move.line_ids:
                _logger.info(f"  Line: {line.account_id.code} - Dr: {line.debit}, Cr: {line.credit}")
            
            # ตรวจสอบความถูกต้องก่อน post
            total_debit = sum(line.debit for line in move.line_ids)
            total_credit = sum(line.credit for line in move.line_ids)
            
            if abs(total_debit - total_credit) > 0.01:
                move.unlink()
                raise UserError(_("Journal Entry is not balanced! Debit=%.2f, Credit=%.2f. Please check the configuration.") % (total_debit, total_credit))
            
            # ตรวจสอบว่ามี 2 lines และใช้บัญชีที่ถูกต้อง
            if len(move.line_ids) != 2:
                move.unlink()
                raise UserError(_("Journal Entry should have exactly 2 lines, but has %d lines.") % len(move.line_ids))
            
            accounts_in_move = set(line.account_id.id for line in move.line_ids)
            expected_accounts = {target_account_id, rec.account_id.id}
            
            if accounts_in_move != expected_accounts:
                # แสดงรายละเอียดบัญชีที่ใช้จริง
                actual_accounts_info = "\n".join([
                    f"  - {line.account_id.code} ({line.account_id.name}): Dr={line.debit:.2f}, Cr={line.credit:.2f}"
                    for line in move.line_ids
                ])
                expected_accounts_info = (
                    f"  - {rec.tax_id.undue_input_vat_account_id.code} ({rec.tax_id.undue_input_vat_account_id.name})\n"
                    f"  - {rec.account_id.code} ({rec.account_id.name})"
                )
                
                _logger.error(f"Account mismatch! Expected: {expected_accounts}, Got: {accounts_in_move}")
                
                move.unlink()
                raise UserError(_(
                    "Journal Entry uses wrong accounts!\n\n"
                    "Expected accounts:\n%s\n\n"
                    "Actual accounts:\n%s\n\n"
                    "Please check:\n"
                    "1. Tax '%s' → Input VAT Account field\n"
                    "2. Tax Undue Line account configuration"
                ) % (expected_accounts_info, actual_accounts_info, rec.tax_id.name))
            
            move.action_post()
            
            # สร้าง Tax Invoice ให้เชื่อมกับ line ของ Input VAT Account (116400)
            # หา line ที่เป็น Input VAT Account
            input_vat_line = move.line_ids.filtered(
                lambda l: l.account_id.id == target_account_id and l.debit > 0
            )
            
            if input_vat_line:
                # สร้าง tax invoice record สำหรับ Tax Report
                # ใช้ accounting_date จาก wizard เป็นวันที่ใน tax invoice
                tax_invoice_vals = {
                    'move_id': move.id,
                    'move_line_id': input_vat_line[0].id,
                    'partner_id': rec.partner_id.id,
                    'tax_invoice_number': rec.name,
                    'tax_invoice_date': accounting_date,  # ใช้วันที่ลงบัญชีที่ User เลือก
                    'tax_base_amount': rec.tax_base,  # เพิ่ม tax base
                    'balance': amount,  # เพิ่ม balance (tax amount)
                }
                
                _logger.info(f"Creating tax invoice record for VAT Undue usage: {rec.name}, Date: {accounting_date}")
                self.env['account.move.tax.invoice'].create(tax_invoice_vals)
            
            rec.write({
                'used_tax_amount': rec.used_tax_amount + amount,
                'used_move_id': move.id,
            })
            moves |= move
        
        return moves
