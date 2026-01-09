# PROMPT: Odoo 17 Inter-Customer Clearing Payment Module (UX + Accounting Grade)

You are a senior Odoo 17 Accounting & ERP developer.
Create a full custom module for Odoo 17 (Community/Enterprise compatible).

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MODULE PURPOSE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Create a new user-friendly wizard to receive a customer payment
and allocate that payment to invoices of multiple customers
(using inter-customer clearing logic), while remaining
100% accounting-correct and audit-safe.

This module MUST support:
- Partial payment
- Multi-currency (FX)
- Cancel (undo)
- Reverse (period closed)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MODULE NAME
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
buz_inter_customer_clearing_payment

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BUSINESS SCENARIO
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- Customers are separated by branch (each branch = different customer record)
- One branch/customer sends a lump-sum payment
- That payment must be used to settle invoices of other customers/branches
- Master data CANNOT be changed
- AR Aging and audit trail must remain correct

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
USER EXPERIENCE (UX FLOW)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Menu:
Accounting → Customers → Receive Clearing Payment

Wizard Steps:
1. Payment Header
2. Allocate Invoices
3. Review & Confirm

The user must NOT manually reconcile journal items.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 1: PAYMENT HEADER
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Fields:
- paying_partner_id (Many2one res.partner, required)
- journal_id (Many2one account.journal, bank/cash)
- payment_date (Date, required)
- currency_id (related to journal)
- amount (Monetary, required)
- reference (Char)

Behavior:
- Similar look & feel to standard Register Payment
- No invoice selection in this step

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 2: ALLOCATE INVOICES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Show a selectable, editable table with:
- Select (Boolean)
- Customer
- Branch (analytic account or branch_id)
- Invoice Number
- Invoice Date
- Residual Amount
- Allocation Amount (editable)

Invoice domain:
- state = 'posted'
- move_type = 'out_invoice'
- payment_state in ('not_paid', 'partial')

Allow:
- Allocating to invoices of different customers
- Partial allocation per invoice

Show summary bar:
- Amount Received
- Total Allocated
- Remaining Amount (advance for paying customer)

Optional helper buttons:
- Auto-fill FIFO
- Clear allocation
- Filter by customer / branch

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 3: REVIEW & CONFIRM
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Show:
- Payment summary
- Allocation summary by customer & invoice
- Remaining advance amount
- Read-only accounting preview

Confirm button:
- "Confirm & Post"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ACCOUNTING LOGIC (CRITICAL)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. Create and post ONE payment:
   - Partner = paying customer
   - Debit bank / credit AR (paying customer)

2. For each allocation line where:
   invoice.partner_id != paying_partner_id

   Create a CLEARING journal entry:
   - Debit AR (invoice customer)
   - Credit AR (paying customer)
   - Amount = allocated amount
   - Currency = invoice currency
   - Let Odoo handle FX differences automatically

3. Reconcile:
   - Invoice receivable line ↔ Clearing AR line (invoice customer)
   - Payment AR line ↔ Invoice AR line (paying customer, if any)

4. Do NOT:
   - Reconcile across different partners directly
   - Modify journal entries manually
   - Calculate FX manually
   - Use SQL

Use account.partial.reconcile for all reconciliations.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CANCEL & REVERSE SUPPORT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Cancel (period open):
- Unreconcile all related lines
- Cancel clearing journal entries
- Cancel payment safely

Reverse (period closed):
- Use Odoo reverse entry mechanism
- Reverse both payment and clearing entries
- FX difference must reverse automatically

All clearing entries must store references:
- payment_id
- allocated_invoice_id

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DATA MODELS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Wizard:
- model: buz.clearing.payment.wizard
- fields:
  - paying_partner_id
  - journal_id
  - payment_date
  - currency_id
  - amount
  - allocation_line_ids (One2many)

Allocation Line (Transient):
- model: buz.clearing.payment.line
- fields:
  - wizard_id
  - invoice_id
  - invoice_partner_id
  - branch_id
  - residual_amount (related)
  - allocate_amount
  - currency_id

Persistent Model (optional but recommended):
- buz.clearing.link
  - payment_id
  - clearing_move_id
  - invoice_id
  - amount

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MODULE STRUCTURE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

buz_inter_customer_clearing_payment/
├── __manifest__.py
├── models/
│   ├── __init__.py
│   ├── clearing_payment.py
│   ├── clearing_entry.py
│   └── clearing_link.py
├── wizard/
│   ├── __init__.py
│   ├── clearing_payment_wizard.py
│   └── clearing_payment_line.py
├── views/
│   ├── clearing_payment_menu.xml
│   ├── clearing_payment_wizard_views.xml
│   └── account_move_views.xml
├── security/
│   └── ir.model.access.csv
└── README.md

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TECHNICAL CONSTRAINTS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- Odoo version: 17.0
- Python 3.10+
- Follow Odoo ORM and accounting best practices
- No core modification
- Clean, commented, production-ready code

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DELIVERABLE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Generate:
- Full Python code
- XML views (wizard + menu)
- Manifest
- Security access
- README.md explaining business & accounting flow

Code must be installable and runnable in Odoo 17.
