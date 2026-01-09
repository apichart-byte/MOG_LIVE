# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
from odoo.exceptions import UserError
from odoo.tools.misc import clean_context


class SaleOrder(models.Model):
    _inherit = 'sale.order'
    
    # Approval fields
    approval_state = fields.Selection([
        ('not_required', 'Not Required'),
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ], string='Approval Status', default='not_required', copy=False)
    
    # Confirm flow fields
    confirm_flow_state = fields.Selection([
        ('draft', 'Quotation'),
        ('confirm_to_so', 'Confirm To SO'),
        ('sale', 'Sales Order'),
    ], string='Confirm Flow State', default='draft', copy=False)
    
    margin_percentage = fields.Float(
        string='Margin %', 
        compute='_compute_margin_percentage', 
        store=True
    )
    margin_rule_id = fields.Many2one(
        'margin.approval.rule', 
        string='Applied Margin Rule', 
        compute='_compute_margin_rule', 
        store=True
    )
    margin_rule_line_id = fields.Many2one(
        'margin.approval.rule.line',
        string='Applied Margin Line',
        compute='_compute_margin_rule',
        store=True
    )
    margin_approval_user_ids = fields.Many2many(
        'res.users',
        'sale_order_margin_approver_rel',
        'order_id',
        'user_id', 
        string='Margin Approvers', 
        compute='_compute_margin_rule', 
        store=True
    )
    approval_type = fields.Selection(
        related='margin_rule_line_id.approval_type',
        string='Approval Type',
        readonly=True
    )
    approved_user_ids = fields.Many2many(
        'res.users',
        'sale_order_approved_user_rel',
        'order_id',
        'user_id',
        string='Users Who Approved',
        copy=False
    )
    
    @api.depends('margin', 'amount_untaxed')
    def _compute_margin_percentage(self):
        for order in self:
            if order.amount_untaxed:
                # Use margin from sale_margin module
                order.margin_percentage = (order.margin / order.amount_untaxed) * 100.0
            else:
                order.margin_percentage = 0.0
    
    @api.depends('user_id', 'company_id', 'margin_percentage')
    def _compute_margin_rule(self):
        for order in self:
            rule = self.env['margin.approval.rule'].get_applicable_rule_for_user(
                order.user_id.id, 
                order.company_id.id
            )
            order.margin_rule_id = rule.id if rule else False
            
            if rule and rule.line_ids:
                # Find applicable line for this margin
                line = False
                for rule_line in rule.line_ids:
                    if rule_line.min_margin <= order.margin_percentage <= rule_line.max_margin:
                        line = rule_line
                        break
                
                order.margin_rule_line_id = line.id if line else False
                order.margin_approval_user_ids = line.approver_ids if line else False
                
                # Update approval state
                if line and order.approval_state == 'not_required':
                    order.approval_state = 'pending'
                elif not line and order.approval_state in ('pending', False):
                    order.approval_state = 'not_required'
            else:
                order.margin_rule_line_id = False
                order.margin_approval_user_ids = False
                if order.approval_state in ('pending', False):
                    order.approval_state = 'not_required'
    
    def _can_approve_margin(self):
        """Check if current user can approve this order's margin"""
        self.ensure_one()
        if self.env.user.has_group('buz_margin_approval.group_margin_approval'):
            return True
        return self.env.user in self.margin_approval_user_ids
    
    def action_confirm(self):
        """Override to enforce Confirm To SO flow for sales users"""
        for order in self:
            # Check if user is in sales margin approver user group
            is_sales_user = self.env.user.has_group('buz_margin_approval.group_sales_margin_approver_user')
            
            # If user is sales user and hasn't gone through Confirm To SO
            if is_sales_user and order.confirm_flow_state != 'confirm_to_so':
                raise UserError(_(
                    "You must use 'Confirm To SO' button instead of 'Confirm Sale'. "
                    "Please click 'Confirm To SO' first."
                ))
            
            # Check margin approval
            if order.approval_state == 'pending':
                raise UserError(_(
                    "Cannot confirm! This order has a margin of %.2f%% which requires approval. "
                    "Please wait for approval from an authorized person."
                ) % order.margin_percentage)
            
            if order.approval_state == 'rejected':
                raise UserError(_(
                    "Cannot confirm! This order's margin has been rejected. "
                    "Please revise the order."
                ))
        
        result = super(SaleOrder, self).action_confirm()
        
        # Update confirm_flow_state to sale after confirmation
        for order in self:
            order.confirm_flow_state = 'sale'
        
        return result
    
    def action_request_margin_approval(self):
        """Request margin approval from approvers"""
        self.ensure_one()
        
        if self.approval_state not in ('not_required', 'pending', 'rejected', False):
            raise UserError(_("This order does not require new approval request."))
        
        if not self.margin_approval_user_ids:
            raise UserError(_("No approvers defined for this margin range."))
        
        self.approval_state = 'pending'
        self.approved_user_ids = [(5, 0, 0)]  # Clear previous approvals
        
        # Create a record in mail thread for traceability
        body = _("Margin Approval Requested. Order margin: %.2f%%") % self.margin_percentage
        self.message_post(body=body)
        
        # Create mail activities for approvers
        self._create_margin_approval_activities()
        
        # Send email notification
        self._send_margin_approval_email()
        
        return True
    
    def action_approve_margin(self):
        """Approve margin by authorized user"""
        self.ensure_one()
        
        if not self._can_approve_margin():
            raise UserError(_("You are not authorized to approve this order's margin."))
        
        if self.approval_state != 'pending':
            raise UserError(_("This order is not pending approval."))
        
        # Add current user to approved users
        self.approved_user_ids = [(4, self.env.user.id)]
        
        # Check if approval is complete based on approval_type
        if self.approval_type == 'any':
            # Any one approver is enough
            self.approval_state = 'approved'
            self._mark_margin_approval_activities_done()
        elif self.approval_type == 'all':
            # Check if all approvers have approved
            if set(self.approved_user_ids.ids) >= set(self.margin_approval_user_ids.ids):
                self.approval_state = 'approved'
                self._mark_margin_approval_activities_done()
        
        body = _("Margin Approved by %s") % self.env.user.name
        if self.approval_state == 'approved':
            body += _(" - All required approvals obtained")
        self.message_post(body=body)
        
        return True
    
    def action_reject_margin(self):
        """Reject margin - opens wizard for reason"""
        self.ensure_one()
        
        if not self._can_approve_margin():
            raise UserError(_("You are not authorized to reject this order's margin."))
        
        return {
            'name': _('Reject Margin'),
            'view_mode': 'form',
            'res_model': 'margin.rejection.wizard',
            'type': 'ir.actions.act_window',
            'target': 'new',
            'context': {'default_sale_order_id': self.id}
        }
    
    def action_confirm_to_so(self):
        """Confirm To SO - for Sales users (does NOT call action_confirm)"""
        self.ensure_one()
        
        # Check approval
        if self.approval_state not in ('approved', 'not_required'):
            raise UserError(_(
                "Cannot proceed! This order requires margin approval. "
                "Current approval status: %s"
            ) % dict(self._fields['approval_state'].selection).get(self.approval_state))
        
        # Update state
        self.confirm_flow_state = 'confirm_to_so'
        
        # Log in chatter
        body = _("Order moved to 'Confirm To SO' state by %s") % self.env.user.name
        self.message_post(body=body)
        
        return True
    
    def write(self, vals):
        """Reset approval when price/discount changes"""
        reset_approval = False
        
        # Check if order lines are being modified
        if 'order_line' in vals:
            for command in vals['order_line']:
                # command[0]: 0=create, 1=update, 2=delete, 3=unlink, 4=link, 5=clear, 6=replace
                if command[0] in (0, 1, 2):
                    line_vals = command[2] if len(command) > 2 else {}
                    if command[0] == 2 or any(field in line_vals for field in ['price_unit', 'discount', 'product_uom_qty', 'product_id']):
                        reset_approval = True
                        break
        
        # Reset approval if order was approved and prices changed
        if reset_approval:
            for order in self:
                if order.approval_state == 'approved':
                    vals['approval_state'] = 'pending'
                    vals['approved_user_ids'] = [(5, 0, 0)]  # Clear approvals
                    # Recreate activities
                    order._mark_margin_approval_activities_done()
                    order._create_margin_approval_activities()
                    order.message_post(body=_("Order modified - Approval reset to pending"))
        
        return super(SaleOrder, self).write(vals)
    
    def _send_margin_approval_email(self):
        """Send email notification to approvers (in Thai)"""
        self.ensure_one()
        
        for user in self.margin_approval_user_ids:
            if not user.email:
                continue
                
            mail_values = {
                'subject': _('ขออนุมัติ Margin: %s') % self.name,
                'email_from': self.company_id.email or self.env.user.email_formatted,
                'email_to': user.email,
                'body_html': f"""
                    <p>เรียน {user.name},</p>
                    <p>มีคำขออนุมัติ margin สำหรับใบเสนอราคาเลขที่ <strong>{self.name}</strong></p>
                    <ul>
                        <li>ลูกค้า: {self.partner_id.name}</li>
                        <li>ยอดรวม: {self.amount_total:,.2f} {self.currency_id.symbol}</li>
                        <li>Margin: <strong>{self.margin_percentage:.2f}%</strong></li>
                        <li>พนักงานขาย: {self.user_id.name}</li>
                        <li>ประเภทการอนุมัติ: {'ต้องอนุมัติทุกคน' if self.approval_type == 'all' else 'อนุมัติคนใดคนหนึ่ง' if self.approval_type == 'any' else '-'}</li>
                    </ul>
                    <p>กรุณาเข้าสู่ระบบเพื่อทำการอนุมัติหรือปฏิเสธคำขอนี้</p>
                    <p>ขอบคุณครับ/ค่ะ</p>
                """,
                'auto_delete': True,
                'model': 'sale.order',
                'res_id': self.id,
            }
            
            self.env['mail.mail'].sudo().create(mail_values).send()
    
    def _create_margin_approval_activities(self):
        """Create mail activity for each margin approver"""
        self.ensure_one()
        mail_activity = self.env['mail.activity']
        
        activity_type = self.env.ref('mail.mail_activity_data_todo', raise_if_not_found=False)
        if not activity_type:
            return
        
        for approver in self.margin_approval_user_ids:
            # Delete old pending activities first
            old_activities = mail_activity.search([
                ('res_model', '=', 'sale.order'),
                ('res_id', '=', self.id),
                ('user_id', '=', approver.id),
                ('activity_type_id', '=', activity_type.id),
            ])
            old_activities.unlink()
            
            # Create new activity
            mail_activity.create({
                'activity_type_id': activity_type.id,
                'user_id': approver.id,
                'res_id': self.id,
                'res_model_id': self.env['ir.model'].sudo().search([('model', '=', 'sale.order')], limit=1).id,
                'summary': _('อนุมัติ Margin ของใบสั่งขาย: %s') % self.name,
                'note': f"""
                    <p>Sales Order: <strong>{self.name}</strong></p>
                    <p>ลูกค้า: {self.partner_id.name}</p>
                    <p>Margin: <strong>{self.margin_percentage:.2f}%</strong></p>
                    <p>ยอดรวม: {self.amount_total:,.2f} {self.currency_id.symbol}</p>
                    <p>พนักงานขาย: {self.user_id.name}</p>
                    <p>กรุณาตรวจสอบและอนุมัติหรือปฏิเสธคำขอนี้</p>
                """,
                'date_deadline': fields.Date.context_today(self),
            })
    
    def _mark_margin_approval_activities_done(self):
        """Mark margin approval activities as done"""
        self.ensure_one()
        mail_activity = self.env['mail.activity']
        
        activity_type = self.env.ref('mail.mail_activity_data_todo', raise_if_not_found=False)
        if not activity_type:
            return
        
        activities = mail_activity.search([
            ('res_model', '=', 'sale.order'),
            ('res_id', '=', self.id),
            ('activity_type_id', '=', activity_type.id),
            ('user_id', 'in', self.margin_approval_user_ids.ids),
        ])
        
        for activity in activities:
            activity.action_feedback(feedback=_('Margin Approved'))
    
    def _mark_margin_approval_activities_rejected(self, rejection_reason=''):
        """Mark margin approval activities as rejected"""
        self.ensure_one()
        mail_activity = self.env['mail.activity']
        
        activity_type = self.env.ref('mail.mail_activity_data_todo', raise_if_not_found=False)
        if not activity_type:
            return
        
        activities = mail_activity.search([
            ('res_model', '=', 'sale.order'),
            ('res_id', '=', self.id),
            ('activity_type_id', '=', activity_type.id),
            ('user_id', 'in', self.margin_approval_user_ids.ids),
        ])
        
        feedback_msg = _('Margin Rejected')
        if rejection_reason:
            feedback_msg = _('Margin Rejected - เหตุผล: %s') % rejection_reason
        
        for activity in activities:
            activity.action_feedback(feedback=feedback_msg)
