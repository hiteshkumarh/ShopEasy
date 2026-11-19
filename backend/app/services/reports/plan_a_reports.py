"""Plan A Report Generation Service (WP-11 Step 3).

Generates authoritative reports for Plan A:
1. Commission Report (PDF & Excel)
2. Cashback Report (PDF & Excel)
3. Individual Customer Statement (PDF & Excel) — Admin Only
"""

from datetime import datetime
from decimal import Decimal
import logging
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException, status
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from app.models.billing import BillingId
from app.models.cashback import (
    PlanACashbackContribution,
    PlanACashbackCycle,
    PlanACashbackEntry,
    PlanACashbackQueue,
    PlanAUnallocatedCashbackReserve,
)
from app.models.commission import PlanACommission
from app.models.enums import Programme, WalletType
from app.models.user import User
from app.models.wallet import Wallet, WalletTransaction, Withdrawal
from app.services.reports.common import (
    MAX_EXPORT_ROWS,
    format_currency,
    format_dt,
    sanitize_filename,
    validate_date_range,
)
from app.services.reports.excel_builder import ExcelReportBuilder
from app.services.reports.pdf_builder import PDFReportBuilder

logger = logging.getLogger("shopeasy.reports.plan_a")


class PlanAReportService:
    """Service providing authoritative Plan A reporting and exports."""

    # =========================================================================
    # 1. PLAN A COMMISSION REPORT
    # =========================================================================

    @classmethod
    def get_commissions_data(
        cls,
        db: Session,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        customer_id: Optional[int] = None,
        billing_id: Optional[str] = None,
    ) -> Tuple[List[PlanACommission], Dict[str, Any]]:
        """Query authoritative Plan A commission records with strict filters."""
        validate_date_range(start_date, end_date)

        query = (
            db.query(PlanACommission)
            .options(
                joinedload(PlanACommission.purchaser),
                joinedload(PlanACommission.referrer),
                joinedload(PlanACommission.billing_id_rel),
            )
        )

        if start_date:
            query = query.filter(PlanACommission.processed_at >= start_date)
        if end_date:
            query = query.filter(PlanACommission.processed_at <= end_date)
        if customer_id is not None:
            query = query.filter(
                or_(
                    PlanACommission.purchaser_id == customer_id,
                    PlanACommission.referrer_id == customer_id,
                )
            )
        if billing_id:
            cleaned_bid = billing_id.strip()
            query = query.join(PlanACommission.billing_id_rel).filter(
                or_(
                    BillingId.billing_number == cleaned_bid,
                    BillingId.sequence_number == int(cleaned_bid) if cleaned_bid.isdigit() else False,
                )
            )

        records = (
            query.order_by(PlanACommission.processed_at.desc(), PlanACommission.id.desc())
            .limit(MAX_EXPORT_ROWS)
            .all()
        )

        # Exact Decimal financial aggregation
        total_gross = sum((r.gross_amount for r in records), Decimal("0.00"))
        total_op_cost = sum((r.operational_cost_amount for r in records), Decimal("0.00"))
        total_tds = sum((r.tds_amount for r in records), Decimal("0.00"))
        total_net = sum((r.net_amount for r in records), Decimal("0.00"))

        summary = {
            "record_count": len(records),
            "total_gross": total_gross,
            "total_op_cost": total_op_cost,
            "total_tds": total_tds,
            "total_net": total_net,
        }
        return records, summary

    @classmethod
    def generate_commission_excel(
        cls,
        db: Session,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        customer_id: Optional[int] = None,
        billing_id: Optional[str] = None,
    ) -> Tuple[bytes, str]:
        """Generate Plan A Commission Report in Excel format (.xlsx)."""
        records, summary = cls.get_commissions_data(
            db, start_date=start_date, end_date=end_date, customer_id=customer_id, billing_id=billing_id
        )

        builder = ExcelReportBuilder("Plan A Commission Report")
        ws = builder.create_sheet("Plan A Commissions")

        meta = [
            ("Generated At:", format_dt(datetime.utcnow()) + " UTC"),
            ("Programme:", "Plan A (Direct Referral ₹700 Net)"),
            ("Date Range:", f"{format_dt(start_date)} to {format_dt(end_date)}"),
            ("Total Records:", str(summary["record_count"])),
        ]
        builder.add_title_block(ws, "Arya Global Digital — Plan A Commission Report", "Authoritative Financial Ledger", meta)

        headers = [
            "Billing ID",
            "Order ID",
            "Purchaser Name",
            "Referrer Name",
            "Referral Code",
            "Gross (₹)",
            "Op Cost (₹)",
            "TDS (₹)",
            "Net Comm (₹)",
            "Transaction Ref",
            "Status",
            "Processed At (UTC)",
        ]

        rows = []
        for r in records:
            bid_num = r.billing_id_rel.billing_number if r.billing_id_rel else f"ID-{r.billing_id}"
            purchaser_name = r.purchaser.full_name if r.purchaser else f"User #{r.purchaser_id}"
            referrer_name = r.referrer.full_name if r.referrer else "-"
            rows.append([
                bid_num,
                r.order_id,
                purchaser_name,
                referrer_name,
                r.applied_referral_code or "-",
                r.gross_amount,
                r.operational_cost_amount,
                r.tds_amount,
                r.net_amount,
                r.idempotency_key,
                r.status,
                format_dt(r.processed_at),
            ])

        total_row = [
            "TOTALS",
            "",
            "",
            "",
            "",
            summary["total_gross"],
            summary["total_op_cost"],
            summary["total_tds"],
            summary["total_net"],
            "",
            "",
            "",
        ]

        builder.add_table(ws, headers, rows, total_row=total_row)
        filename = sanitize_filename(f"Plan_A_Commissions_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}", "xlsx")
        return builder.to_bytes(), filename

    @classmethod
    def generate_commission_pdf(
        cls,
        db: Session,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        customer_id: Optional[int] = None,
        billing_id: Optional[str] = None,
    ) -> Tuple[bytes, str]:
        """Generate Plan A Commission Report in PDF format."""
        records, summary = cls.get_commissions_data(
            db, start_date=start_date, end_date=end_date, customer_id=customer_id, billing_id=billing_id
        )

        builder = PDFReportBuilder("Plan A Commission Report", is_landscape=True)
        meta = [
            ("Generated At:", format_dt(datetime.utcnow()) + " UTC"),
            ("Programme:", "Plan A (Direct Referral ₹700 Net)"),
            ("Total Records:", f"{summary['record_count']} | Total Net: {format_currency(summary['total_net'])}"),
        ]
        builder.add_title_block("Arya Global Digital — Plan A Commission Report", "Authoritative Financial Ledger", meta)

        headers = [
            "Billing ID",
            "Order",
            "Purchaser",
            "Referrer",
            "Code",
            "Gross",
            "Op Cost",
            "TDS",
            "Net",
            "Status",
            "Processed At",
        ]

        rows = []
        for r in records:
            bid_num = r.billing_id_rel.billing_number if r.billing_id_rel else f"#{r.billing_id}"
            purchaser_name = r.purchaser.full_name if r.purchaser else f"#{r.purchaser_id}"
            referrer_name = r.referrer.full_name if r.referrer else "-"
            rows.append([
                bid_num,
                r.order_id,
                purchaser_name,
                referrer_name,
                r.applied_referral_code or "-",
                r.gross_amount,
                r.operational_cost_amount,
                r.tds_amount,
                r.net_amount,
                r.status,
                format_dt(r.processed_at),
            ])

        total_row = [
            "TOTALS",
            "",
            "",
            "",
            "",
            summary["total_gross"],
            summary["total_op_cost"],
            summary["total_tds"],
            summary["total_net"],
            "",
            "",
        ]

        # Explicit column widths matching landscape A4 (~770 pt printable width)
        col_widths = [75, 45, 95, 95, 55, 55, 50, 45, 60, 85, 110]
        builder.add_table(headers, rows, col_widths=col_widths, total_row=total_row)

        filename = sanitize_filename(f"Plan_A_Commissions_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}", "pdf")
        return builder.to_bytes(), filename

    # =========================================================================
    # 2. PLAN A CASHBACK REPORT
    # =========================================================================

    @classmethod
    def get_cashback_data(
        cls,
        db: Session,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        customer_id: Optional[int] = None,
        queue_id: Optional[int] = None,
        billing_id: Optional[str] = None,
    ) -> Tuple[List[PlanACashbackContribution], List[PlanAUnallocatedCashbackReserve], Dict[str, Any]]:
        """Query authoritative Plan A cashback contributions and company reserve records."""
        validate_date_range(start_date, end_date)

        # 1. Contributions query
        c_query = (
            db.query(PlanACashbackContribution)
            .options(
                joinedload(PlanACashbackContribution.queue).joinedload(PlanACashbackQueue.root_user),
                joinedload(PlanACashbackContribution.cycle),
                joinedload(PlanACashbackContribution.contributing_billing),
                joinedload(PlanACashbackContribution.contributing_user),
                joinedload(PlanACashbackContribution.recipient_user),
            )
        )
        if start_date:
            c_query = c_query.filter(PlanACashbackContribution.created_at >= start_date)
        if end_date:
            c_query = c_query.filter(PlanACashbackContribution.created_at <= end_date)
        if customer_id is not None:
            c_query = c_query.filter(
                or_(
                    PlanACashbackContribution.contributing_user_id == customer_id,
                    PlanACashbackContribution.recipient_user_id == customer_id,
                )
            )
        if queue_id is not None:
            c_query = c_query.filter(PlanACashbackContribution.queue_id == queue_id)
        if billing_id:
            cleaned_bid = billing_id.strip()
            c_query = c_query.join(PlanACashbackContribution.contributing_billing).filter(
                or_(
                    BillingId.billing_number == cleaned_bid,
                    BillingId.sequence_number == int(cleaned_bid) if cleaned_bid.isdigit() else False,
                )
            )

        contributions = (
            c_query.order_by(PlanACashbackContribution.created_at.desc(), PlanACashbackContribution.id.desc())
            .limit(MAX_EXPORT_ROWS)
            .all()
        )

        # 2. Company Reserve query
        r_query = (
            db.query(PlanAUnallocatedCashbackReserve)
            .options(
                joinedload(PlanAUnallocatedCashbackReserve.queue).joinedload(PlanACashbackQueue.root_user),
                joinedload(PlanAUnallocatedCashbackReserve.billing),
                joinedload(PlanAUnallocatedCashbackReserve.customer),
            )
        )
        if start_date:
            r_query = r_query.filter(PlanAUnallocatedCashbackReserve.reserved_at >= start_date)
        if end_date:
            r_query = r_query.filter(PlanAUnallocatedCashbackReserve.reserved_at <= end_date)
        if customer_id is not None:
            r_query = r_query.filter(PlanAUnallocatedCashbackReserve.customer_id == customer_id)
        if queue_id is not None:
            r_query = r_query.filter(PlanAUnallocatedCashbackReserve.queue_id == queue_id)
        if billing_id:
            cleaned_bid = billing_id.strip()
            r_query = r_query.join(PlanAUnallocatedCashbackReserve.billing).filter(
                or_(
                    BillingId.billing_number == cleaned_bid,
                    BillingId.sequence_number == int(cleaned_bid) if cleaned_bid.isdigit() else False,
                )
            )

        reserves = (
            r_query.order_by(PlanAUnallocatedCashbackReserve.reserved_at.desc(), PlanAUnallocatedCashbackReserve.id.desc())
            .limit(MAX_EXPORT_ROWS)
            .all()
        )

        total_contrib_amount = sum((c.amount for c in contributions), Decimal("0.00"))
        total_reserve_amount = sum((r.amount for r in reserves), Decimal("0.00"))
        allocated_count = sum(1 for c in contributions if c.status == "ALLOCATED")

        summary = {
            "contribution_count": len(contributions),
            "reserve_count": len(reserves),
            "allocated_count": allocated_count,
            "total_contribution_amount": total_contrib_amount,
            "total_reserve_amount": total_reserve_amount,
            "grand_total_cashback": total_contrib_amount + total_reserve_amount,
        }
        return contributions, reserves, summary

    @classmethod
    def generate_cashback_excel(
        cls,
        db: Session,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        customer_id: Optional[int] = None,
        queue_id: Optional[int] = None,
        billing_id: Optional[str] = None,
    ) -> Tuple[bytes, str]:
        """Generate Plan A Cashback Report in Excel format (.xlsx)."""
        contributions, reserves, summary = cls.get_cashback_data(
            db, start_date=start_date, end_date=end_date, customer_id=customer_id, queue_id=queue_id, billing_id=billing_id
        )

        builder = ExcelReportBuilder("Plan A Cashback Report")

        # Sheet 1: Cashback Contributions
        ws1 = builder.create_sheet("Cashback Contributions")
        meta1 = [
            ("Generated At:", format_dt(datetime.utcnow()) + " UTC"),
            ("Programme:", "Plan A (16-Contribution ₹250 Cycles)"),
            ("Total Contributions:", f"{summary['contribution_count']} ({format_currency(summary['total_contribution_amount'])})"),
            ("Total Company Reserve:", f"{summary['reserve_count']} ({format_currency(summary['total_reserve_amount'])})"),
        ]
        builder.add_title_block(ws1, "Arya Global Digital — Plan A Cashback Report", "Authoritative Contribution Ledger", meta1)

        headers1 = [
            "Queue ID",
            "Queue Root",
            "Contributing Billing ID",
            "Contributing Customer",
            "Recipient Customer",
            "Cycle ID",
            "Cycle Progress",
            "Amount (₹)",
            "Status",
            "Cycle Status",
            "Transaction Ref",
            "Created At (UTC)",
        ]

        rows1 = []
        for c in contributions:
            queue_root = c.queue.root_user.full_name if c.queue and c.queue.root_user else f"Root #{c.queue_id}"
            bid_num = c.contributing_billing.billing_number if c.contributing_billing else f"ID-{c.contributing_billing_id}"
            contrib_cust = c.contributing_user.full_name if c.contributing_user else f"#{c.contributing_user_id}"
            recip_cust = c.recipient_user.full_name if c.recipient_user else "Company Reserve"
            progress = f"{c.cycle.completed_contributions}/16" if c.cycle else "-"
            cycle_status = c.cycle.status if c.cycle else "-"
            rows1.append([
                c.queue_id,
                queue_root,
                bid_num,
                contrib_cust,
                recip_cust,
                c.cycle_id or "-",
                progress,
                c.amount,
                c.status,
                cycle_status,
                c.idempotency_key,
                format_dt(c.created_at),
            ])

        tot_row1 = [
            "TOTALS", "", "", "", "", "", "", summary["total_contribution_amount"], "", "", "", ""
        ]
        builder.add_table(ws1, headers1, rows1, total_row=tot_row1)

        # Sheet 2: Unallocated Company Reserve
        ws2 = builder.create_sheet("Company Cashback Reserve")
        meta2 = [
            ("Reserve Rule:", "BR-A4 Option A & BR-A5 Option A (Company Owned)"),
            ("Reserve Status:", "UNALLOCATED — COMPANY OWNED"),
            ("Total Reserve Entries:", str(summary["reserve_count"])),
            ("Total Reserve Amount:", format_currency(summary["total_reserve_amount"])),
        ]
        builder.add_title_block(ws2, "Plan A Unallocated Cashback Reserve", "Permanently Retained Company-Owned Ledger", meta2)

        headers2 = [
            "Queue ID",
            "Queue Root",
            "Billing ID",
            "Customer Name",
            "Amount (₹)",
            "Reserve Status",
            "Transaction Ref",
            "Reserved At (UTC)",
        ]
        rows2 = []
        for r in reserves:
            q_root = r.queue.root_user.full_name if r.queue and r.queue.root_user else f"Queue #{r.queue_id}"
            b_num = r.billing.billing_number if r.billing else f"ID-{r.billing_id}"
            cust_name = r.customer.full_name if r.customer else f"User #{r.customer_id}"
            rows2.append([
                r.queue_id,
                q_root,
                b_num,
                cust_name,
                r.amount,
                r.status,
                r.idempotency_key,
                format_dt(r.reserved_at),
            ])
        tot_row2 = ["TOTALS", "", "", "", summary["total_reserve_amount"], "", "", ""]
        builder.add_table(ws2, headers2, rows2, total_row=tot_row2)

        filename = sanitize_filename(f"Plan_A_Cashback_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}", "xlsx")
        return builder.to_bytes(), filename

    @classmethod
    def generate_cashback_pdf(
        cls,
        db: Session,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        customer_id: Optional[int] = None,
        queue_id: Optional[int] = None,
        billing_id: Optional[str] = None,
    ) -> Tuple[bytes, str]:
        """Generate Plan A Cashback Report in PDF format."""
        contributions, reserves, summary = cls.get_cashback_data(
            db, start_date=start_date, end_date=end_date, customer_id=customer_id, queue_id=queue_id, billing_id=billing_id
        )

        builder = PDFReportBuilder("Plan A Cashback Report", is_landscape=True)
        meta = [
            ("Generated At:", format_dt(datetime.utcnow()) + " UTC"),
            ("Programme:", "Plan A (16-Contribution ₹250 Cycles)"),
            ("Summary:", f"Contributions: {summary['contribution_count']} ({format_currency(summary['total_contribution_amount'])}) | Company Reserve: {summary['reserve_count']} ({format_currency(summary['total_reserve_amount'])})"),
        ]
        builder.add_title_block("Arya Global Digital — Plan A Cashback Report", "Authoritative Contribution & Reserve Ledger", meta)

        builder.add_section_heading("1. Cashback Contributions Ledger")
        headers1 = [
            "Queue",
            "Root",
            "Billing ID",
            "Contributor",
            "Recipient",
            "Cycle",
            "Progress",
            "Amount",
            "Status",
            "Created At",
        ]
        rows1 = []
        for c in contributions:
            q_root = c.queue.root_user.full_name if c.queue and c.queue.root_user else f"#{c.queue_id}"
            bid_num = c.contributing_billing.billing_number if c.contributing_billing else f"#{c.contributing_billing_id}"
            contrib_cust = c.contributing_user.full_name if c.contributing_user else f"#{c.contributing_user_id}"
            recip_cust = c.recipient_user.full_name if c.recipient_user else "Reserve"
            progress = f"{c.cycle.completed_contributions}/16" if c.cycle else "-"
            rows1.append([
                c.queue_id,
                q_root,
                bid_num,
                contrib_cust,
                recip_cust,
                c.cycle_id or "-",
                progress,
                c.amount,
                c.status,
                format_dt(c.created_at),
            ])
        tot1 = ["TOTALS", "", "", "", "", "", "", summary["total_contribution_amount"], "", ""]
        col_widths1 = [45, 90, 80, 95, 95, 45, 55, 60, 90, 115]
        builder.add_table(headers1, rows1, col_widths=col_widths1, total_row=tot1)

        if reserves:
            builder.add_section_heading("2. Company-Owned Unallocated Cashback Reserve (BR-A4 / BR-A5)")
            headers2 = [
                "Queue",
                "Queue Root",
                "Billing ID",
                "Customer",
                "Amount",
                "Status",
                "Reserved At",
            ]
            rows2 = []
            for r in reserves:
                q_root = r.queue.root_user.full_name if r.queue and r.queue.root_user else f"#{r.queue_id}"
                b_num = r.billing.billing_number if r.billing else f"#{r.billing_id}"
                cust_name = r.customer.full_name if r.customer else f"#{r.customer_id}"
                rows2.append([
                    r.queue_id,
                    q_root,
                    b_num,
                    cust_name,
                    r.amount,
                    r.status,
                    format_dt(r.reserved_at),
                ])
            tot2 = ["TOTALS", "", "", "", summary["total_reserve_amount"], "", ""]
            col_widths2 = [50, 120, 90, 120, 70, 180, 140]
            builder.add_table(headers2, rows2, col_widths=col_widths2, total_row=tot2)

        filename = sanitize_filename(f"Plan_A_Cashback_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}", "pdf")
        return builder.to_bytes(), filename

    # =========================================================================
    # 3. INDIVIDUAL PLAN A CUSTOMER STATEMENT (ADMIN ONLY)
    # =========================================================================

    @classmethod
    def resolve_customer(cls, db: Session, identifier: Any) -> User:
        """Resolve a customer by User ID (integer) or registered phone number.

        Supports:
          - Database primary key ID (e.g. 30001)
          - 10-digit mobile phone number (e.g. "9019443501")
          - Mobile with country code prefix (e.g. "+919019443501" or "919019443501")
          - Referral code (e.g. "PA4Z6O3R")
        """
        raw_str = str(identifier).strip() if identifier is not None else ""
        if not raw_str:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Customer identifier cannot be empty.",
            )

        customer = None
        digits_only = "".join(ch for ch in raw_str if ch.isdigit())

        # 1. If 10-digit number, look up by registered phone number first
        if len(digits_only) == 10:
            customer = db.query(User).filter(User.phone == digits_only).first()
        elif len(digits_only) == 12 and digits_only.startswith("91"):
            phone_10 = digits_only[2:]
            customer = db.query(User).filter(User.phone == phone_10).first()

        # 2. If not found by phone and is numeric, look up by User.id
        if not customer and digits_only.isdigit():
            try:
                num_id = int(digits_only)
                customer = db.query(User).filter(User.id == num_id).first()
            except ValueError:
                pass

        # 3. If still not found, try referral code or exact string phone
        if not customer:
            customer = db.query(User).filter(
                or_(
                    User.phone == raw_str,
                    User.referral_code == raw_str.upper(),
                )
            ).first()

        if not customer:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Customer with identifier '{raw_str}' does not exist.",
            )

        if customer.programme != Programme.PLAN_A:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"User {customer.id} ({customer.full_name}) is registered under {customer.programme.value}, not Plan A. Please use the Individual Distributor Profile Report instead.",
            )

        return customer

    @classmethod
    def get_customer_statement_data(
        cls,
        db: Session,
        customer_id: Any,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """Fetch all consolidated authoritative Plan A financial and ledger records for a customer."""
        validate_date_range(start_date, end_date)

        customer = cls.resolve_customer(db, customer_id)
        cust_id = customer.id

        # 1. Billing IDs & Purchases
        b_query = (
            db.query(BillingId)
            .options(joinedload(BillingId.order), joinedload(BillingId.product))
            .filter(BillingId.user_id == cust_id, BillingId.programme == Programme.PLAN_A)
        )
        if start_date:
            b_query = b_query.filter(BillingId.created_at >= start_date)
        if end_date:
            b_query = b_query.filter(BillingId.created_at <= end_date)
        billing_ids = b_query.order_by(BillingId.created_at.asc()).all()

        # 2. Direct Referral Commissions Earned
        c_query = (
            db.query(PlanACommission)
            .options(joinedload(PlanACommission.purchaser), joinedload(PlanACommission.billing_id_rel))
            .filter(PlanACommission.referrer_id == cust_id)
        )
        if start_date:
            c_query = c_query.filter(PlanACommission.processed_at >= start_date)
        if end_date:
            c_query = c_query.filter(PlanACommission.processed_at <= end_date)
        commissions = c_query.order_by(PlanACommission.processed_at.desc()).all()

        # 3. Direct Referral Wallet & Transactions
        dr_wallet = (
            db.query(Wallet)
            .filter(Wallet.user_id == cust_id, Wallet.wallet_type == WalletType.DIRECT_REFERRAL)
            .first()
        )
        dr_tx_query = (
            db.query(WalletTransaction)
            .filter(WalletTransaction.user_id == cust_id, WalletTransaction.wallet_type == WalletType.DIRECT_REFERRAL)
        )
        if start_date:
            dr_tx_query = dr_tx_query.filter(WalletTransaction.created_at >= start_date)
        if end_date:
            dr_tx_query = dr_tx_query.filter(WalletTransaction.created_at <= end_date)
        dr_transactions = dr_tx_query.order_by(WalletTransaction.created_at.desc()).all()

        # 4. Direct Referral Withdrawals
        dr_withdrawals_query = (
            db.query(Withdrawal)
            .join(Wallet, Withdrawal.wallet_id == Wallet.id)
            .filter(Withdrawal.user_id == cust_id, Wallet.wallet_type == WalletType.DIRECT_REFERRAL)
        )
        if start_date:
            dr_withdrawals_query = dr_withdrawals_query.filter(Withdrawal.requested_at >= start_date)
        if end_date:
            dr_withdrawals_query = dr_withdrawals_query.filter(Withdrawal.requested_at <= end_date)
        dr_withdrawals = dr_withdrawals_query.order_by(Withdrawal.requested_at.desc()).all()

        # 5. Cashback Queue Entries
        queue_entries = (
            db.query(PlanACashbackEntry)
            .options(joinedload(PlanACashbackEntry.billing), joinedload(PlanACashbackEntry.queue))
            .filter(PlanACashbackEntry.user_id == cust_id)
            .order_by(PlanACashbackEntry.enrolled_at.asc())
            .all()
        )

        # 6. Cashback Cycles where recipient
        cb_cycles = (
            db.query(PlanACashbackCycle)
            .filter(PlanACashbackCycle.recipient_user_id == cust_id)
            .order_by(PlanACashbackCycle.started_at.desc())
            .all()
        )

        # 7. Cashback Contributions received as recipient
        cb_contrib_query = (
            db.query(PlanACashbackContribution)
            .options(joinedload(PlanACashbackContribution.contributing_billing), joinedload(PlanACashbackContribution.contributing_user))
            .filter(PlanACashbackContribution.recipient_user_id == cust_id)
        )
        if start_date:
            cb_contrib_query = cb_contrib_query.filter(PlanACashbackContribution.created_at >= start_date)
        if end_date:
            cb_contrib_query = cb_contrib_query.filter(PlanACashbackContribution.created_at <= end_date)
        cb_contributions = cb_contrib_query.order_by(PlanACashbackContribution.created_at.desc()).all()

        # 8. Cashback Reserve entries attributable to customer
        reserves = (
            db.query(PlanAUnallocatedCashbackReserve)
            .options(joinedload(PlanAUnallocatedCashbackReserve.billing))
            .filter(PlanAUnallocatedCashbackReserve.customer_id == cust_id)
            .order_by(PlanAUnallocatedCashbackReserve.reserved_at.desc())
            .all()
        )

        # 9. Sequential Commission (Cashback) Wallet & Withdrawals
        sc_wallet = (
            db.query(Wallet)
            .filter(Wallet.user_id == cust_id, Wallet.wallet_type == WalletType.SEQUENTIAL_COMMISSION)
            .first()
        )
        sc_withdrawals_query = (
            db.query(Withdrawal)
            .join(Wallet, Withdrawal.wallet_id == Wallet.id)
            .filter(Withdrawal.user_id == cust_id, Wallet.wallet_type == WalletType.SEQUENTIAL_COMMISSION)
        )
        if start_date:
            sc_withdrawals_query = sc_withdrawals_query.filter(Withdrawal.requested_at >= start_date)
        if end_date:
            sc_withdrawals_query = sc_withdrawals_query.filter(Withdrawal.requested_at <= end_date)
        sc_withdrawals = sc_withdrawals_query.order_by(Withdrawal.requested_at.desc()).all()

        # Exact financial reconciliations
        total_comm_earned = sum((c.net_amount for c in commissions if c.status == "EARNED"), Decimal("0.00"))
        total_cb_earned = sum((c.amount for c in cb_contributions if c.status == "ALLOCATED"), Decimal("0.00"))
        dr_balance = dr_wallet.balance if dr_wallet else Decimal("0.00")
        sc_balance = sc_wallet.balance if sc_wallet else Decimal("0.00")
        dr_withdrawn = dr_wallet.total_withdrawn if dr_wallet else Decimal("0.00")
        sc_withdrawn = sc_wallet.total_withdrawn if sc_wallet else Decimal("0.00")

        return {
            "customer": customer,
            "billing_ids": billing_ids,
            "commissions": commissions,
            "dr_wallet": dr_wallet,
            "dr_transactions": dr_transactions,
            "dr_withdrawals": dr_withdrawals,
            "queue_entries": queue_entries,
            "cb_cycles": cb_cycles,
            "cb_contributions": cb_contributions,
            "reserves": reserves,
            "sc_wallet": sc_wallet,
            "sc_withdrawals": sc_withdrawals,
            "summary": {
                "total_purchases": len(billing_ids),
                "total_comm_earned": total_comm_earned,
                "dr_balance": dr_balance,
                "dr_withdrawn": dr_withdrawn,
                "total_cb_earned": total_cb_earned,
                "sc_balance": sc_balance,
                "sc_withdrawn": sc_withdrawn,
            },
        }

    @classmethod
    def generate_customer_statement_excel(
        cls,
        db: Session,
        customer_id: Any,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> Tuple[bytes, str]:
        """Generate Individual Plan A Customer Statement in Excel format (.xlsx) — Admin Only."""
        data = cls.get_customer_statement_data(db, customer_id, start_date=start_date, end_date=end_date)
        cust: User = data["customer"]
        summary = data["summary"]

        builder = ExcelReportBuilder("Customer Statement")

        # Sheet 1: Statement Overview & Summary
        ws_summary = builder.create_sheet("Account Statement")
        meta = [
            ("Customer Name:", cust.full_name),
            ("Customer Phone:", cust.phone),
            ("Customer ID:", str(cust.id)),
            ("Programme:", cust.programme.value),
            ("Referral Code:", cust.referral_code or "-"),
            ("Account Status:", cust.account_status.value),
            ("Statement Generated:", format_dt(datetime.utcnow()) + " UTC"),
            ("Direct Commission Balance:", format_currency(summary["dr_balance"])),
            ("Direct Commission Withdrawn:", format_currency(summary["dr_withdrawn"])),
            ("Cashback Balance:", format_currency(summary["sc_balance"])),
            ("Cashback Withdrawn:", format_currency(summary["sc_withdrawn"])),
        ]
        builder.add_title_block(ws_summary, f"Plan A Customer Statement — {cust.full_name}", "Confidential Administrator Record", meta)

        # Add Summary Financial Reconciliations Table
        recon_headers = ["Ledger Stream", "Total Earned (₹)", "Total Withdrawn (₹)", "Current Balance (₹)"]
        recon_rows = [
            ["Direct Referral Commissions", summary["total_comm_earned"], summary["dr_withdrawn"], summary["dr_balance"]],
            ["Sequential Cashback Cycles", summary["total_cb_earned"], summary["sc_withdrawn"], summary["sc_balance"]],
        ]
        builder.add_table(ws_summary, recon_headers, recon_rows)

        # Sheet 2: Purchases & Billing IDs
        ws_purchases = builder.create_sheet("Purchases & Billing IDs")
        builder.add_title_block(ws_purchases, "Purchase History", "Allocated Plan A Power Bank Units")
        p_headers = ["Billing ID", "Order ID", "Product", "Allocated At (UTC)", "Status"]
        p_rows = [
            [
                b.billing_number,
                b.order_id,
                b.product.name if b.product else f"Product #{b.product_id}",
                format_dt(b.created_at),
                b.status,
            ]
            for b in data["billing_ids"]
        ]
        builder.add_table(ws_purchases, p_headers, p_rows)

        # Sheet 3: Referral Commissions Earned
        ws_comm = builder.create_sheet("Commissions Earned")
        builder.add_title_block(ws_comm, "Direct Referral Commissions", "₹700 Net per Valid Direct Referee Purchase")
        comm_headers = ["Billing ID", "Order ID", "Purchaser", "Gross (₹)", "Op Cost (₹)", "TDS (₹)", "Net (₹)", "Status", "Date (UTC)"]
        comm_rows = [
            [
                c.billing_id_rel.billing_number if c.billing_id_rel else f"ID-{c.billing_id}",
                c.order_id,
                c.purchaser.full_name if c.purchaser else f"#{c.purchaser_id}",
                c.gross_amount,
                c.operational_cost_amount,
                c.tds_amount,
                c.net_amount,
                c.status,
                format_dt(c.processed_at),
            ]
            for c in data["commissions"]
        ]
        comm_tot = ["TOTALS", "", "", sum((c.gross_amount for c in data["commissions"]), Decimal("0.00")), "", "", summary["total_comm_earned"], "", ""]
        builder.add_table(ws_comm, comm_headers, comm_rows, total_row=comm_tot)

        # Sheet 4: Cashback Queue & Received Contributions
        ws_cb = builder.create_sheet("Cashback History")
        builder.add_title_block(ws_cb, "Cashback Cycles & Contributions", "16-Contribution ₹250 Cycles")
        cb_headers = ["Contributing Billing ID", "Contributor", "Cycle ID", "Amount (₹)", "Status", "Date (UTC)"]
        cb_rows = [
            [
                c.contributing_billing.billing_number if c.contributing_billing else f"ID-{c.contributing_billing_id}",
                c.contributing_user.full_name if c.contributing_user else f"#{c.contributing_user_id}",
                c.cycle_id or "-",
                c.amount,
                c.status,
                format_dt(c.created_at),
            ]
            for c in data["cb_contributions"]
        ]
        cb_tot = ["TOTALS", "", "", summary["total_cb_earned"], "", ""]
        builder.add_table(ws_cb, cb_headers, cb_rows, total_row=cb_tot)

        # Sheet 5: Withdrawals
        ws_w = builder.create_sheet("Withdrawals")
        builder.add_title_block(ws_w, "Withdrawal History", "Payout State Machine Records")
        w_headers = ["Wallet Type", "Amount (₹)", "Status", "Requested At (UTC)", "Completed At (UTC)", "Transaction Key"]
        w_rows = [
            [
                "Direct Referral",
                w.amount,
                w.status.value,
                format_dt(w.requested_at),
                format_dt(w.completed_at),
                w.idempotency_key,
            ]
            for w in data["dr_withdrawals"]
        ] + [
            [
                "Sequential Cashback",
                w.amount,
                w.status.value,
                format_dt(w.requested_at),
                format_dt(w.completed_at),
                w.idempotency_key,
            ]
            for w in data["sc_withdrawals"]
        ]
        builder.add_table(ws_w, w_headers, w_rows)

        filename = sanitize_filename(f"Plan_A_Customer_Statement_{cust.id}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}", "xlsx")
        return builder.to_bytes(), filename

    @classmethod
    def generate_customer_statement_pdf(
        cls,
        db: Session,
        customer_id: Any,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> Tuple[bytes, str]:
        """Generate Individual Plan A Customer Statement in PDF format — Admin Only."""
        data = cls.get_customer_statement_data(db, customer_id, start_date=start_date, end_date=end_date)
        cust: User = data["customer"]
        summary = data["summary"]

        builder = PDFReportBuilder("Customer Statement", is_landscape=False)  # Portrait layout for statements
        meta = [
            ("Customer Name:", f"{cust.full_name} (ID #{cust.id})"),
            ("Phone / Status:", f"{cust.phone} | {cust.account_status.value}"),
            ("Referral Code:", cust.referral_code or "-"),
            ("Direct Commission Balance:", f"{format_currency(summary['dr_balance'])} (Withdrawn: {format_currency(summary['dr_withdrawn'])})"),
            ("Cashback Balance:", f"{format_currency(summary['sc_balance'])} (Withdrawn: {format_currency(summary['sc_withdrawn'])})"),
            ("Generated At:", format_dt(datetime.utcnow()) + " UTC"),
        ]
        builder.add_title_block("Arya Global Digital — Customer Statement", "Plan A Consolidate Financial Summary (Admin Only)", meta)

        # 1. Financial Reconciliations
        builder.add_section_heading("1. Financial Balances & Earnings Summary")
        recon_h = ["Ledger Stream", "Total Earned", "Withdrawn", "Current Balance"]
        recon_r = [
            ["Direct Referral (₹700 net)", summary["total_comm_earned"], summary["dr_withdrawn"], summary["dr_balance"]],
            ["Sequential Cashback (₹250 cycles)", summary["total_cb_earned"], summary["sc_withdrawn"], summary["sc_balance"]],
        ]
        builder.add_table(recon_h, recon_r, col_widths=[170, 110, 110, 130])

        # 2. Purchases & Billing IDs
        builder.add_section_heading("2. Purchased Billing IDs")
        p_h = ["Billing ID", "Order ID", "Allocated At", "Status"]
        p_r = [
            [b.billing_number, b.order_id, format_dt(b.created_at), b.status]
            for b in data["billing_ids"]
        ]
        builder.add_table(p_h, p_r, col_widths=[140, 90, 160, 130])

        # 3. Direct Referral Commissions
        if data["commissions"]:
            builder.add_section_heading("3. Referral Commission History")
            c_h = ["Billing ID", "Purchaser", "Net Comm", "Status", "Processed At"]
            c_r = [
                [
                    c.billing_id_rel.billing_number if c.billing_id_rel else f"#{c.billing_id}",
                    c.purchaser.full_name if c.purchaser else f"#{c.purchaser_id}",
                    c.net_amount,
                    c.status,
                    format_dt(c.processed_at),
                ]
                for c in data["commissions"]
            ]
            builder.add_table(c_h, c_r, col_widths=[120, 120, 80, 80, 120])

        # 4. Cashback Contributions Received
        if data["cb_contributions"]:
            builder.add_section_heading("4. Cashback Contributions Received")
            cb_h = ["Contributing Billing ID", "Contributor", "Amount", "Status", "Date"]
            cb_r = [
                [
                    c.contributing_billing.billing_number if c.contributing_billing else f"#{c.contributing_billing_id}",
                    c.contributing_user.full_name if c.contributing_user else f"#{c.contributing_user_id}",
                    c.amount,
                    c.status,
                    format_dt(c.created_at),
                ]
                for c in data["cb_contributions"]
            ]
            builder.add_table(cb_h, cb_r, col_widths=[130, 130, 80, 70, 110])

        # 5. Withdrawals
        withdrawals_all = data["dr_withdrawals"] + data["sc_withdrawals"]
        if withdrawals_all:
            builder.add_section_heading("5. Payout & Withdrawal History")
            w_h = ["Wallet Type", "Amount", "Status", "Requested At", "Completed At"]
            w_r = [
                [
                    "Direct Referral" if w in data["dr_withdrawals"] else "Cashback",
                    w.amount,
                    w.status.value,
                    format_dt(w.requested_at),
                    format_dt(w.completed_at),
                ]
                for w in withdrawals_all
            ]
            builder.add_table(w_h, w_r, col_widths=[120, 80, 90, 115, 115])

        filename = sanitize_filename(f"Plan_A_Customer_Statement_{cust.id}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}", "pdf")
        return builder.to_bytes(), filename
