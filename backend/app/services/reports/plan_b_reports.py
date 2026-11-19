"""Plan B Report Generation Service (WP-11 Step 3).

Generates authoritative Excel reports for Plan B:
1. Complete Purchase Report (Excel .xlsx only) — Admin Only
2. Commission Report (Excel .xlsx only) — Admin Only
3. Individual Distributor Report (Excel .xlsx only) — Admin Only
4. Distributor Self-Service Commission Statement (Excel .xlsx only) — Scoped to authenticated distributor
"""

from datetime import datetime
from decimal import Decimal
import logging
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException, status
from sqlalchemy import or_
from sqlalchemy.orm import Session, aliased, joinedload

from app.models.billing import BillingId
from app.models.commission import PlanBCommission
from app.models.enums import AccountStatus, Programme, WalletType
from app.models.order import Order, OrderItem
from app.models.product import Product
from app.models.referral import ReferralRelationship
from app.models.user import User
from app.models.wallet import Wallet, WalletFreezeHistory, WalletTransaction, Withdrawal
from app.services.reports.common import (
    MAX_EXPORT_ROWS,
    format_currency,
    format_dt,
    sanitize_filename,
    validate_date_range,
)
from app.services.reports.excel_builder import ExcelReportBuilder

logger = logging.getLogger("shopeasy.reports.plan_b")


class PlanBReportService:
    """Service providing authoritative Plan B reporting in Excel (.xlsx) format."""

    # =========================================================================
    # 1. COMPLETE PLAN B PURCHASE REPORT (ADMIN ONLY, EXCEL ONLY)
    # =========================================================================

    @classmethod
    def get_purchases_data(
        cls,
        db: Session,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        customer_name: Optional[str] = None,
        distributor_name: Optional[str] = None,
        mobile: Optional[str] = None,
        billing_id: Optional[str] = None,
        order_id: Optional[int] = None,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """Fetch authoritative Plan B purchase records with filter bounds."""
        validate_date_range(start_date, end_date)

        query = (
            db.query(BillingId)
            .options(
                joinedload(BillingId.user),
                joinedload(BillingId.order),
                joinedload(BillingId.product),
            )
            .filter(BillingId.programme == Programme.PLAN_B)
        )

        if start_date:
            query = query.filter(BillingId.created_at >= start_date)
        if end_date:
            query = query.filter(BillingId.created_at <= end_date)
        if order_id is not None:
            query = query.filter(BillingId.order_id == order_id)
        if billing_id:
            cleaned_bid = billing_id.strip()
            query = query.filter(
                or_(
                    BillingId.billing_number == cleaned_bid,
                    BillingId.sequence_number == int(cleaned_bid) if cleaned_bid.isdigit() else False,
                )
            )

        if customer_name:
            c_name_term = f"%{customer_name.strip()}%"
            query = query.join(BillingId.user).filter(User.full_name.ilike(c_name_term))

        if mobile:
            m_term = f"%{mobile.strip()}%"
            query = query.join(BillingId.user).filter(User.phone.ilike(m_term))

        billing_records = (
            query.order_by(BillingId.created_at.desc(), BillingId.id.desc())
            .limit(MAX_EXPORT_ROWS)
            .all()
        )

        # Batch lookup commissions and referring distributors for these billing records
        billing_ids_list = [b.id for b in billing_records]
        comm_map: Dict[int, PlanBCommission] = {}
        if billing_ids_list:
            comms = (
                db.query(PlanBCommission)
                .options(joinedload(PlanBCommission.distributor))
                .filter(PlanBCommission.billing_id.in_(billing_ids_list))
                .all()
            )
            for comm in comms:
                if comm.billing_id:
                    comm_map[comm.billing_id] = comm

        # Batch lookup referring distributors from orders or referral relationships
        order_ids_list = list({b.order_id for b in billing_records})
        ref_rel_map: Dict[int, User] = {}
        if order_ids_list:
            # Map by user_id
            user_ids = list({b.user_id for b in billing_records})
            rels = (
                db.query(ReferralRelationship)
                .options(joinedload(ReferralRelationship.referrer))
                .filter(
                    ReferralRelationship.referee_id.in_(user_ids),
                    ReferralRelationship.referrer_programme == Programme.PLAN_B,
                )
                .all()
            )
            for r in rels:
                if r.referrer:
                    ref_rel_map[r.referee_id] = r.referrer

        rows_data = []
        for b in billing_records:
            # Determine referring distributor
            comm = comm_map.get(b.id)
            distributor = comm.distributor if comm and comm.distributor else ref_rel_map.get(b.user_id)
            dist_name = distributor.full_name if distributor else "-"

            # Check distributor name filter if supplied
            if distributor_name and dist_name != "-":
                if distributor_name.strip().lower() not in dist_name.lower():
                    continue
            elif distributor_name and dist_name == "-":
                continue

            comm_details = f"{comm.commission_type}: ₹{comm.net_amount:,.2f} ({comm.status})" if comm else "None"

            rows_data.append({
                "customer_name": b.user.full_name if b.user else f"#{b.user_id}",
                "customer_phone": b.user.phone if b.user else "-",
                "distributor_name": dist_name,
                "order_id": b.order_id,
                "billing_id": b.billing_number,
                "product_name": b.product.name if b.product else f"Product #{b.product_id}",
                "quantity": 1,
                "purchase_date": b.created_at,
                "payment_status": b.order.payment_status.value if b.order else "-",
                "commission_details": comm_details,
            })

        summary = {
            "record_count": len(rows_data),
            "total_units": sum(r["quantity"] for r in rows_data),
        }
        return rows_data, summary

    @classmethod
    def generate_purchase_excel(
        cls,
        db: Session,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        customer_name: Optional[str] = None,
        distributor_name: Optional[str] = None,
        mobile: Optional[str] = None,
        billing_id: Optional[str] = None,
        order_id: Optional[int] = None,
    ) -> Tuple[bytes, str]:
        """Generate Complete Plan B Purchase Report in Excel (.xlsx)."""
        rows_data, summary = cls.get_purchases_data(
            db,
            start_date=start_date,
            end_date=end_date,
            customer_name=customer_name,
            distributor_name=distributor_name,
            mobile=mobile,
            billing_id=billing_id,
            order_id=order_id,
        )

        builder = ExcelReportBuilder("Plan B Purchase Report")
        ws = builder.create_sheet("Plan B Purchases")

        meta = [
            ("Generated At:", format_dt(datetime.utcnow()) + " UTC"),
            ("Programme:", "Plan B (Direct Sales & Distributor Network)"),
            ("Date Range:", f"{format_dt(start_date)} to {format_dt(end_date)}"),
            ("Total Records:", str(summary["record_count"])),
            ("Total Units:", str(summary["total_units"])),
        ]
        builder.add_title_block(ws, "Arya Global Digital — Complete Plan B Purchase Report", "Authoritative Sales & Fulfilment Ledger", meta)

        headers = [
            "Customer Name",
            "Customer Mobile",
            "Distributor Name",
            "Order ID",
            "Billing ID",
            "Product Name",
            "Quantity",
            "Purchase Date (UTC)",
            "Payment Status",
            "Commission Details",
        ]

        rows = [
            [
                r["customer_name"],
                r["customer_phone"],
                r["distributor_name"],
                r["order_id"],
                r["billing_id"],
                r["product_name"],
                r["quantity"],
                format_dt(r["purchase_date"]),
                r["payment_status"],
                r["commission_details"],
            ]
            for r in rows_data
        ]

        builder.add_table(ws, headers, rows)
        filename = sanitize_filename(f"Plan_B_Purchases_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}", "xlsx")
        return builder.to_bytes(), filename

    # =========================================================================
    # 2. PLAN B COMMISSION REPORT (ADMIN ONLY, EXCEL ONLY)
    # =========================================================================

    @classmethod
    def get_commissions_data(
        cls,
        db: Session,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        distributor_name: Optional[str] = None,
        customer_name: Optional[str] = None,
        billing_id: Optional[str] = None,
        order_id: Optional[int] = None,
        commission_type: Optional[str] = None,
    ) -> Tuple[List[PlanBCommission], Dict[str, Any]]:
        """Fetch authoritative Plan B direct and generation commissions."""
        validate_date_range(start_date, end_date)

        query = (
            db.query(PlanBCommission)
            .options(
                joinedload(PlanBCommission.distributor),
                joinedload(PlanBCommission.referee),
                joinedload(PlanBCommission.billing_id_rel),
            )
        )

        if start_date:
            query = query.filter(PlanBCommission.processed_at >= start_date)
        if end_date:
            query = query.filter(PlanBCommission.processed_at <= end_date)
        if order_id is not None:
            query = query.filter(PlanBCommission.order_id == order_id)
        if commission_type:
            query = query.filter(PlanBCommission.commission_type == commission_type.strip().upper())
        if billing_id:
            cleaned_bid = billing_id.strip()
            query = query.join(PlanBCommission.billing_id_rel).filter(
                or_(
                    BillingId.billing_number == cleaned_bid,
                    BillingId.sequence_number == int(cleaned_bid) if cleaned_bid.isdigit() else False,
                )
            )

        if distributor_name:
            d_name_term = f"%{distributor_name.strip()}%"
            query = query.join(PlanBCommission.distributor).filter(User.full_name.ilike(d_name_term))

        if customer_name:
            c_name_term = f"%{customer_name.strip()}%"
            query = query.join(PlanBCommission.referee).filter(User.full_name.ilike(c_name_term))

        records = (
            query.order_by(PlanBCommission.processed_at.desc(), PlanBCommission.id.desc())
            .limit(MAX_EXPORT_ROWS)
            .all()
        )

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
        distributor_name: Optional[str] = None,
        customer_name: Optional[str] = None,
        billing_id: Optional[str] = None,
        order_id: Optional[int] = None,
        commission_type: Optional[str] = None,
    ) -> Tuple[bytes, str]:
        """Generate Plan B Commission Report in Excel (.xlsx)."""
        records, summary = cls.get_commissions_data(
            db,
            start_date=start_date,
            end_date=end_date,
            distributor_name=distributor_name,
            customer_name=customer_name,
            billing_id=billing_id,
            order_id=order_id,
            commission_type=commission_type,
        )

        builder = ExcelReportBuilder("Plan B Commission Report")
        ws = builder.create_sheet("Plan B Commissions")

        meta = [
            ("Generated At:", format_dt(datetime.utcnow()) + " UTC"),
            ("Programme:", "Plan B (Direct ₹466.66 Net & Generation ₹46.66/₹46.67 Net)"),
            ("Date Range:", f"{format_dt(start_date)} to {format_dt(end_date)}"),
            ("Total Records:", str(summary["record_count"])),
            ("Total Net Commission:", format_currency(summary["total_net"])),
        ]
        builder.add_title_block(ws, "Arya Global Digital — Plan B Commission Report", "Authoritative Distributor Commission Ledger", meta)

        headers = [
            "Distributor Name",
            "Customer Name",
            "Billing ID",
            "Order ID",
            "Commission Type",
            "Gross (₹)",
            "Op Cost (₹)",
            "TDS (₹)",
            "Net (₹)",
            "Transaction ID",
            "Credit Date (UTC)",
            "Status",
        ]

        rows = []
        for r in records:
            dist_name = r.distributor.full_name if r.distributor else f"Distributor #{r.distributor_id}"
            cust_name = r.referee.full_name if r.referee else f"User #{r.referee_id}"
            bid_num = r.billing_id_rel.billing_number if r.billing_id_rel else f"ID-{r.billing_id}"
            rows.append([
                dist_name,
                cust_name,
                bid_num,
                r.order_id,
                r.commission_type,
                r.gross_amount,
                r.operational_cost_amount,
                r.tds_amount,
                r.net_amount,
                r.idempotency_key,
                format_dt(r.processed_at),
                r.status,
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
        filename = sanitize_filename(f"Plan_B_Commissions_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}", "xlsx")
        return builder.to_bytes(), filename

    # =========================================================================
    # 3. INDIVIDUAL DISTRIBUTOR REPORT (ADMIN ONLY, EXCEL ONLY)
    # =========================================================================

    @classmethod
    def resolve_distributor(cls, db: Session, identifier: Any) -> User:
        """Resolve a Plan B distributor by User ID (integer) or registered phone number.

        Supports:
          - Database primary key ID (e.g. 101)
          - 10-digit mobile phone number (e.g. "9812345679")
          - Mobile with country code prefix (e.g. "+919812345679" or "919812345679")
          - Referral code (e.g. "PB4Z6O3R")
        """
        raw_str = str(identifier).strip() if identifier is not None else ""
        if not raw_str:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Distributor identifier cannot be empty.",
            )

        distributor = None
        digits_only = "".join(ch for ch in raw_str if ch.isdigit())

        # 1. If 10-digit number, look up by registered phone number first
        if len(digits_only) == 10:
            distributor = db.query(User).filter(User.phone == digits_only).first()
        elif len(digits_only) == 12 and digits_only.startswith("91"):
            phone_10 = digits_only[2:]
            distributor = db.query(User).filter(User.phone == phone_10).first()

        # 2. If not found by phone and is numeric, look up by User.id
        if not distributor and digits_only.isdigit():
            try:
                num_id = int(digits_only)
                distributor = db.query(User).filter(User.id == num_id).first()
            except ValueError:
                pass

        # 3. If still not found, try referral code or exact string phone
        if not distributor:
            distributor = db.query(User).filter(
                or_(
                    User.phone == raw_str,
                    User.referral_code == raw_str.upper(),
                )
            ).first()

        if not distributor:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Distributor with identifier '{raw_str}' does not exist.",
            )

        if distributor.programme != Programme.PLAN_B:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"User {distributor.id} ({distributor.full_name}) is registered under {distributor.programme.value}, not Plan B. Please use the Plan A Customer Statement instead.",
            )

        return distributor

    @classmethod
    def get_distributor_data(
        cls,
        db: Session,
        distributor_id: Any,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """Fetch authoritative Plan B distributor records."""
        validate_date_range(start_date, end_date)

        distributor = cls.resolve_distributor(db, distributor_id)
        dist_id = distributor.id

        # 1. Referral hierarchy
        referrals = (
            db.query(ReferralRelationship)
            .options(joinedload(ReferralRelationship.referee))
            .filter(ReferralRelationship.referrer_id == dist_id)
            .order_by(ReferralRelationship.created_at.asc())
            .all()
        )

        # 2. Own Purchases and Billing IDs
        purchases = (
            db.query(BillingId)
            .options(joinedload(BillingId.order), joinedload(BillingId.product))
            .filter(BillingId.user_id == dist_id, BillingId.programme == Programme.PLAN_B)
            .order_by(BillingId.created_at.asc())
            .all()
        )

        # 3. Direct Commissions
        d_query = (
            db.query(PlanBCommission)
            .options(joinedload(PlanBCommission.referee), joinedload(PlanBCommission.billing_id_rel))
            .filter(PlanBCommission.distributor_id == dist_id, PlanBCommission.commission_type == "DIRECT")
        )
        if start_date:
            d_query = d_query.filter(PlanBCommission.processed_at >= start_date)
        if end_date:
            d_query = d_query.filter(PlanBCommission.processed_at <= end_date)
        direct_commissions = d_query.order_by(PlanBCommission.processed_at.desc()).all()

        # 4. Generation Commissions
        g_query = (
            db.query(PlanBCommission)
            .options(joinedload(PlanBCommission.referee), joinedload(PlanBCommission.billing_id_rel))
            .filter(PlanBCommission.distributor_id == dist_id, PlanBCommission.commission_type == "GENERATION")
        )
        if start_date:
            g_query = g_query.filter(PlanBCommission.processed_at >= start_date)
        if end_date:
            g_query = g_query.filter(PlanBCommission.processed_at <= end_date)
        generation_commissions = g_query.order_by(PlanBCommission.processed_at.desc()).all()

        # 5. Wallet & Withdrawals
        wallet = (
            db.query(Wallet)
            .filter(Wallet.user_id == dist_id, Wallet.wallet_type == WalletType.DIRECT_REFERRAL)
            .first()
        )
        w_query = (
            db.query(Withdrawal)
            .join(Wallet, Withdrawal.wallet_id == Wallet.id)
            .filter(Withdrawal.user_id == dist_id, Wallet.wallet_type == WalletType.DIRECT_REFERRAL)
        )
        if start_date:
            w_query = w_query.filter(Withdrawal.requested_at >= start_date)
        if end_date:
            w_query = w_query.filter(Withdrawal.requested_at <= end_date)
        withdrawals = w_query.order_by(Withdrawal.requested_at.desc()).all()

        # 6. Wallet Freeze History
        freeze_history = []
        if wallet:
            freeze_records = (
                db.query(WalletFreezeHistory)
                .filter(WalletFreezeHistory.wallet_id == wallet.id)
                .order_by(WalletFreezeHistory.created_at.desc())
                .all()
            )
            admin_ids = list({h.admin_id for h in freeze_records})
            admin_map = {}
            if admin_ids:
                admins = db.query(User).filter(User.id.in_(admin_ids)).all()
                admin_map = {a.id: a.full_name for a in admins}
            for h in freeze_records:
                freeze_history.append({
                    "action": h.action,
                    "admin_name": admin_map.get(h.admin_id, f"Admin #{h.admin_id}"),
                    "reason": h.reason,
                    "created_at": h.created_at,
                })

        total_direct_net = sum((c.net_amount for c in direct_commissions if c.status == "EARNED"), Decimal("0.00"))
        total_gen_net = sum((c.net_amount for c in generation_commissions if c.status == "EARNED"), Decimal("0.00"))
        wallet_balance = wallet.balance if wallet else Decimal("0.00")
        total_withdrawn = wallet.total_withdrawn if wallet else Decimal("0.00")
        is_frozen = wallet.is_frozen if wallet else False

        return {
            "distributor": distributor,
            "referrals": referrals,
            "purchases": purchases,
            "direct_commissions": direct_commissions,
            "generation_commissions": generation_commissions,
            "wallet": wallet,
            "withdrawals": withdrawals,
            "freeze_history": freeze_history,
            "summary": {
                "total_referrals": len(referrals),
                "total_direct_net": total_direct_net,
                "total_gen_net": total_gen_net,
                "grand_total_earned": total_direct_net + total_gen_net,
                "wallet_balance": wallet_balance,
                "total_withdrawn": total_withdrawn,
                "is_frozen": is_frozen,
            },
        }

    @classmethod
    def generate_distributor_report_excel(
        cls,
        db: Session,
        distributor_id: Any,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> Tuple[bytes, str]:
        """Generate Individual Distributor Report in Excel (.xlsx) — Admin Only."""
        data = cls.get_distributor_data(db, distributor_id, start_date=start_date, end_date=end_date)
        dist: User = data["distributor"]
        summary = data["summary"]

        builder = ExcelReportBuilder("Distributor Report")

        # Sheet 1: Profile & Summary
        ws_prof = builder.create_sheet("Profile & Wallet Summary")
        meta = [
            ("Distributor Name:", dist.full_name),
            ("Mobile Phone:", dist.phone),
            ("Referral Code:", dist.referral_code or "-"),
            ("Account Status:", dist.account_status.value),
            ("Wallet Freeze Status:", "FROZEN" if summary["is_frozen"] else "ACTIVE"),
            ("Current Wallet Balance:", format_currency(summary["wallet_balance"])),
            ("Lifetime Withdrawn:", format_currency(summary["total_withdrawn"])),
            ("Direct Commissions Earned:", format_currency(summary["total_direct_net"])),
            ("Generation Commissions Earned:", format_currency(summary["total_gen_net"])),
            ("Grand Total Earnings:", format_currency(summary["grand_total_earned"])),
        ]
        builder.add_title_block(ws_prof, f"Plan B Distributor Report — {dist.full_name}", "Confidential Administrator Record", meta)

        # Sheet 2: Referral Hierarchy
        ws_ref = builder.create_sheet("Referrals Hierarchy")
        builder.add_title_block(ws_ref, "Direct Referees", "Bound Referral Relationships")
        ref_h = ["Referee Name", "Referee Phone", "Referee Programme", "Bound Channel", "Date Bound (UTC)"]
        ref_r = [
            [
                r.referee.full_name if r.referee else f"#{r.referee_id}",
                r.referee.phone if r.referee else "-",
                r.referee_programme.value,
                r.binding_channel,
                format_dt(r.created_at),
            ]
            for r in data["referrals"]
        ]
        builder.add_table(ws_ref, ref_h, ref_r)

        # Sheet 3: Direct Commissions
        ws_dc = builder.create_sheet("Direct Commissions")
        builder.add_title_block(ws_dc, "Direct Commissions", "₹500.00 Net Lifetime Bonus per Qualifying Sale")
        dc_h = ["Billing ID", "Order ID", "Customer", "Gross (₹)", "Op Cost (₹)", "TDS (₹)", "Net (₹)", "Status", "Date (UTC)"]
        dc_r = [
            [
                c.billing_id_rel.billing_number if c.billing_id_rel else f"ID-{c.billing_id}",
                c.order_id,
                c.referee.full_name if c.referee else f"#{c.referee_id}",
                c.gross_amount,
                c.operational_cost_amount,
                c.tds_amount,
                c.net_amount,
                c.status,
                format_dt(c.processed_at),
            ]
            for c in data["direct_commissions"]
        ]
        dc_tot = ["TOTALS", "", "", sum((c.gross_amount for c in data["direct_commissions"]), Decimal("0.00")), "", "", summary["total_direct_net"], "", ""]
        builder.add_table(ws_dc, dc_h, dc_r, total_row=dc_tot)

        # Sheet 4: Generation Commissions
        ws_gc = builder.create_sheet("Generation Commissions")
        builder.add_title_block(ws_gc, "Generation Commissions", "₹50.00 Net per Eligible Billing ID")
        gc_h = ["Billing ID", "Order ID", "Customer", "Gross (₹)", "Op Cost (₹)", "TDS (₹)", "Net (₹)", "Status", "Date (UTC)"]
        gc_r = [
            [
                c.billing_id_rel.billing_number if c.billing_id_rel else f"ID-{c.billing_id}",
                c.order_id,
                c.referee.full_name if c.referee else f"#{c.referee_id}",
                c.gross_amount,
                c.operational_cost_amount,
                c.tds_amount,
                c.net_amount,
                c.status,
                format_dt(c.processed_at),
            ]
            for c in data["generation_commissions"]
        ]
        gc_tot = ["TOTALS", "", "", sum((c.gross_amount for c in data["generation_commissions"]), Decimal("0.00")), "", "", summary["total_gen_net"], "", ""]
        builder.add_table(ws_gc, gc_h, gc_r, total_row=gc_tot)

        # Sheet 5: Withdrawals
        ws_w = builder.create_sheet("Withdrawals")
        builder.add_title_block(ws_w, "Withdrawal History", "Payout State Machine Records")
        w_h = ["Amount (₹)", "Status", "Requested At (UTC)", "Completed At (UTC)", "Transaction ID"]
        w_r = [
            [
                w.amount,
                w.status.value,
                format_dt(w.requested_at),
                format_dt(w.completed_at),
                w.idempotency_key,
            ]
            for w in data["withdrawals"]
        ]
        builder.add_table(ws_w, w_h, w_r)

        # Sheet 6: Wallet Freeze History
        if data["freeze_history"]:
            ws_fh = builder.create_sheet("Wallet Freeze History")
            builder.add_title_block(ws_fh, "Wallet Freeze & Unfreeze Audit", "Administrative Actions")
            fh_h = ["Action", "Admin User", "Reason", "Date (UTC)"]
            fh_r = [
                [
                    h["action"],
                    h["admin_name"],
                    h["reason"],
                    format_dt(h["created_at"]),
                ]
                for h in data["freeze_history"]
            ]
            builder.add_table(ws_fh, fh_h, fh_r)

        filename = sanitize_filename(f"Plan_B_Distributor_Report_{dist.id}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}", "xlsx")
        return builder.to_bytes(), filename

    # =========================================================================
    # 4. DISTRIBUTOR SELF-SERVICE COMMISSION STATEMENT & METRICS (EXCEL ONLY)
    # =========================================================================

    @classmethod
    def get_distributor_dashboard_overview(
        cls, db: Session, distributor_id: int
    ) -> Dict[str, Any]:
        """Fetch composite overview for the Plan B distributor dashboard (Section 8).

        Returns:
          - 9 Wallet and Summary metrics:
            1. Available Direct Referral Wallet Balance
            2. Lifetime Direct Referral Commission Earned
            3. Generation Commission Earned
            4. Total Gross Commission
            5. Total Operational Cost Deducted
            6. Total TDS Deducted
            7. Total Net Commission Earned
            8. Total Amount Withdrawn
            9. Available Withdrawable Balance
          - Separate Direct Referral Commission history list (one per referred customer)
          - Separate Generation Commission history list (one per eligible Billing ID)
        """
        distributor = db.query(User).filter(User.id == distributor_id).first()
        if not distributor:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Distributor profile not found.",
            )

        wallet = (
            db.query(Wallet)
            .filter(
                Wallet.user_id == distributor_id,
                Wallet.wallet_type == WalletType.DIRECT_REFERRAL,
            )
            .first()
        )
        current_balance = wallet.balance if wallet else Decimal("0.00")
        total_withdrawn = wallet.total_withdrawn if wallet else Decimal("0.00")

        # Fetch all EARNED Plan B commissions for this distributor
        commissions = (
            db.query(PlanBCommission)
            .options(
                joinedload(PlanBCommission.referee),
                joinedload(PlanBCommission.billing_id_rel),
            )
            .filter(
                PlanBCommission.distributor_id == distributor_id,
                PlanBCommission.status == "EARNED",
            )
            .order_by(PlanBCommission.processed_at.desc(), PlanBCommission.id.desc())
            .all()
        )

        direct_comms = [c for c in commissions if c.commission_type == "DIRECT"]
        gen_comms = [c for c in commissions if c.commission_type == "GENERATION"]

        lifetime_direct_earned = sum((c.net_amount for c in direct_comms), Decimal("0.00"))
        generation_commission_earned = sum((c.net_amount for c in gen_comms), Decimal("0.00"))

        total_gross_commission = sum((c.gross_amount for c in commissions), Decimal("0.00"))
        total_operational_cost = sum((c.operational_cost_amount for c in commissions), Decimal("0.00"))
        total_tds = sum((c.tds_amount for c in commissions), Decimal("0.00"))
        total_net_commission_earned = sum((c.net_amount for c in commissions), Decimal("0.00"))

        def mask_phone(phone: Optional[str]) -> str:
            if not phone:
                return "—"
            clean = phone.strip()
            if len(clean) >= 6:
                return f"{clean[:2]}****{clean[-4:]}"
            return "****"

        direct_list = []
        for c in direct_comms:
            ref = c.referee
            b_rel = c.billing_id_rel
            direct_list.append({
                "id": c.id,
                "customer_id": c.referee_id,
                "customer_name": ref.full_name if ref else f"#{c.referee_id}",
                "customer_phone": mask_phone(ref.phone if ref else None),
                "purchase_date": c.processed_at.isoformat() if c.processed_at else None,
                "order_id": c.order_id,
                "billing_id": c.billing_id,
                "billing_number": b_rel.billing_number if b_rel else (f"ID-{c.billing_id}" if c.billing_id else "—"),
                "gross_amount": c.gross_amount,
                "operational_cost": c.operational_cost_amount,
                "tds_amount": c.tds_amount,
                "net_amount": c.net_amount,
                "status": c.status,
                "idempotency_key": c.idempotency_key,
            })

        gen_list = []
        for c in gen_comms:
            ref = c.referee
            b_rel = c.billing_id_rel
            gen_list.append({
                "id": c.id,
                "customer_id": c.referee_id,
                "customer_name": ref.full_name if ref else f"#{c.referee_id}",
                "order_id": c.order_id,
                "billing_id": c.billing_id,
                "billing_number": b_rel.billing_number if b_rel else f"ID-{c.billing_id}",
                "commission_date": c.processed_at.isoformat() if c.processed_at else None,
                "gross_amount": c.gross_amount,
                "operational_cost": c.operational_cost_amount,
                "tds_amount": c.tds_amount,
                "net_amount": c.net_amount,
                "status": c.status,
                "idempotency_key": c.idempotency_key,
            })

        return {
            "distributor": {
                "id": distributor.id,
                "full_name": distributor.full_name,
                "referral_code": distributor.referral_code,
                "phone": distributor.phone,
                "programme": distributor.programme.value if hasattr(distributor.programme, "value") else str(distributor.programme),
                "account_status": distributor.account_status.value if hasattr(distributor.account_status, "value") else str(distributor.account_status),
            },
            "summary_metrics": {
                "available_wallet_balance": current_balance,
                "lifetime_direct_earned": lifetime_direct_earned,
                "has_received_direct_bonus": bool(direct_comms),
                "direct_bonus_date": direct_comms[0].processed_at.isoformat() if direct_comms and direct_comms[0].processed_at else None,
                "direct_bonus_transaction_id": direct_comms[0].idempotency_key if direct_comms else None,
                "generation_commission_earned": generation_commission_earned,
                "eligible_generation_billing_ids_count": len(gen_comms),
                "total_gross_commission": total_gross_commission,
                "total_operational_cost": total_operational_cost,
                "total_tds": total_tds,
                "total_net_commission_earned": total_net_commission_earned,
                "total_withdrawn": total_withdrawn,
                "available_withdrawable_balance": current_balance,
            },
            "direct_commissions": direct_list,
            "generation_commissions": gen_list,
        }

    @classmethod
    def generate_distributor_self_statement_excel(
        cls,
        db: Session,
        distributor_id: int,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> Tuple[bytes, str]:
        """Generate distributor's own commission statement in Excel (.xlsx) only.

        Strictly prohibited in PDF format (R-08). Scoped to authenticated distributor.
        """
        validate_date_range(start_date, end_date)

        distributor = db.query(User).filter(User.id == distributor_id).first()
        if not distributor:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Distributor profile not found.",
            )

        if distributor.programme != Programme.PLAN_B:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Distributor statement is available only for Plan B distributors.",
            )

        # 1. Fetch Plan B commissions
        c_query = (
            db.query(PlanBCommission)
            .options(
                joinedload(PlanBCommission.referee),
                joinedload(PlanBCommission.billing_id_rel),
            )
            .filter(PlanBCommission.distributor_id == distributor_id)
        )
        if start_date:
            c_query = c_query.filter(PlanBCommission.processed_at >= start_date)
        if end_date:
            c_query = c_query.filter(PlanBCommission.processed_at <= end_date)
        commissions = c_query.order_by(PlanBCommission.processed_at.desc()).all()

        # 2. Fetch withdrawals
        w_query = (
            db.query(Withdrawal)
            .join(Wallet, Withdrawal.wallet_id == Wallet.id)
            .filter(Withdrawal.user_id == distributor_id, Wallet.wallet_type == WalletType.DIRECT_REFERRAL)
        )
        if start_date:
            w_query = w_query.filter(Withdrawal.requested_at >= start_date)
        if end_date:
            w_query = w_query.filter(Withdrawal.requested_at <= end_date)
        withdrawals = w_query.order_by(Withdrawal.requested_at.desc()).all()

        # 3. Wallet balance
        wallet = (
            db.query(Wallet)
            .filter(Wallet.user_id == distributor_id, Wallet.wallet_type == WalletType.DIRECT_REFERRAL)
            .first()
        )
        current_balance = wallet.balance if wallet else Decimal("0.00")

        builder = ExcelReportBuilder("Distributor Commission Statement")
        ws = builder.create_sheet("Commission Statement")

        meta = [
            ("Distributor Name:", distributor.full_name),
            ("Referral Code:", distributor.referral_code or "-"),
            ("Account Status:", distributor.account_status.value),
            ("Current Wallet Balance:", format_currency(current_balance)),
            ("Statement Generated:", format_dt(datetime.utcnow()) + " UTC"),
            ("Format:", "Excel (.xlsx) Only — Confirmed Rule R-08"),
        ]
        builder.add_title_block(ws, f"Plan B Commission Statement — {distributor.full_name}", "Distributor Self-Service Export", meta)

        headers = [
            "Transaction Date (UTC)",
            "Customer Name",
            "Billing ID",
            "Order ID",
            "Commission Type",
            "Gross (₹)",
            "Operational Cost (₹)",
            "TDS (₹)",
            "Net Commission (₹)",
            "Transaction ID",
            "Withdrawal Amount (₹)",
            "Wallet Balance (₹)",
        ]

        rows = []
        for c in commissions:
            bid_num = c.billing_id_rel.billing_number if c.billing_id_rel else (f"ID-{c.billing_id}" if c.billing_id else "—")
            cust_name = c.referee.full_name if c.referee else f"#{c.referee_id}"
            comm_type_desc = (
                "Direct Referral Commission (₹500.00 once per distributor)"
                if c.commission_type == "DIRECT"
                else "Generation Commission (₹50.00 per eligible Billing ID)"
                if c.commission_type == "GENERATION"
                else c.commission_type
            )
            rows.append([
                format_dt(c.processed_at),
                cust_name,
                bid_num,
                c.order_id,
                comm_type_desc,
                c.gross_amount,
                c.operational_cost_amount,
                c.tds_amount,
                c.net_amount,
                c.idempotency_key,
                Decimal("0.00"),
                current_balance,
            ])

        for w in withdrawals:
            rows.append([
                format_dt(w.requested_at),
                "-",
                "-",
                "-",
                "WITHDRAWAL",
                Decimal("0.00"),
                Decimal("0.00"),
                Decimal("0.00"),
                Decimal("0.00"),
                w.idempotency_key,
                w.amount,
                current_balance,
            ])

        rows.sort(key=lambda r: r[0], reverse=True)

        tot_gross = sum((c.gross_amount for c in commissions if c.status == "EARNED"), Decimal("0.00"))
        tot_op = sum((c.operational_cost_amount for c in commissions if c.status == "EARNED"), Decimal("0.00"))
        tot_tds = sum((c.tds_amount for c in commissions if c.status == "EARNED"), Decimal("0.00"))
        tot_net = sum((c.net_amount for c in commissions if c.status == "EARNED"), Decimal("0.00"))
        tot_withdrawn = sum((w.amount for w in withdrawals), Decimal("0.00"))
        total_row = [
            "TOTALS",
            "",
            "",
            "",
            "",
            tot_gross,
            tot_op,
            tot_tds,
            tot_net,
            "",
            tot_withdrawn,
            current_balance,
        ]

        builder.add_table(ws, headers, rows, total_row=total_row)
        filename = sanitize_filename(f"Plan_B_Statement_{distributor.referral_code or distributor.id}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}", "xlsx")
        return builder.to_bytes(), filename
