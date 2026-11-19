/**
 * distributor-dashboard.js
 * Arya Global Digital — Plan B Distributor Portal Controller
 * WP-12 Step 4 Implementation
 *
 * Implements:
 * - Authentication guard & Programme isolation check (Plan B only)
 * - Blocked distributor account detection & compliance notice display
 * - Real-time metrics from GET /api/v1/auth/me, GET /api/v1/dashboard/earnings, GET /api/v1/wallets
 * - Negative requirement PB-15: strictly exclude aggregate referral count and volume metrics
 * - Granular commission breakdown (Direct ₹500/₹466.66 net vs Generation ₹50/₹46.66 net)
 * - Excel statement download (.xlsx only) via ShopEasyDistributorReports
 * - Notifications panel & mark read flows via ShopEasyNotifications
 * - Direct Referral Wallet full-balance withdrawal execution with idempotency protection
 */

(function () {
  'use strict';

  let currentDistributor = null;
  let earningsData = null;
  let walletsData = [];
  let transactionsData = [];
  let withdrawalsData = [];
  let notificationsData = [];
  let directWallet = null;
  let overviewLoaded = false;

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', async () => {
      await initDistributorDashboard();
    });
  } else {
    initDistributorDashboard();
  }

  async function initDistributorDashboard() {
    try {
      // 1. Authenticate user
      if (typeof window.requireCustomerAuth !== 'function') {
        console.error('requireCustomerAuth is not defined');
        return;
      }
      currentDistributor = await window.requireCustomerAuth();
      if (!currentDistributor) return;

      // 2. Enforce Programme Isolation (RG-12)
      // Only Plan B distributors may access this dashboard. Plan A customers are barred and redirected.
      if (currentDistributor.programme && currentDistributor.programme !== 'PLAN_B') {
        const container = document.querySelector('main .container');
        if (container) {
          container.innerHTML = `
            <div style="background:#FFF;padding:var(--space-8);border-radius:var(--radius-xl);border:1px solid var(--color-border);margin:var(--space-8) 0;text-align:center;">
              <h2 style="font-size:var(--text-xl);font-weight:700;color:var(--color-text);margin-bottom:var(--space-2);">Plan A Retail Customer Account</h2>
              <p style="color:var(--color-muted);max-width:540px;margin:0 auto var(--space-4);">
                Your account is enrolled in <strong>Plan A (Single-Product Retail &amp; Cashback Queue)</strong>. 
                The Distributor Portal is exclusive to Plan B Direct Sales Distributors.
              </p>
              <a href="dashboard.html" class="btn btn-primary btn-sm">Go to Plan A Customer Dashboard</a>
              <a href="profile.html" class="btn btn-secondary btn-sm" style="margin-left: 8px;">View Profile</a>
            </div>
          `;
        }
        return;
      }

      // 3. Render Profile & Header Information
      renderDistributorHeader();

      // 4. Setup Event Listeners
      setupEventListeners();

      // 5. Fetch Dashboard Data concurrently
      await Promise.allSettled([
        loadDashboardOverview(),
        loadEarningsAndWallets(),
        loadLedgerTransactions(),
        loadWithdrawalsList(),
        loadNotifications(),
        loadDistributorPurchaseHistory()
      ]);

    } catch (err) {
      console.error('Failed to initialize distributor dashboard:', err);
    }
  }

  function renderDistributorHeader() {
    if (!currentDistributor) return;

    const nameEl = document.getElementById('distributor-name');
    if (nameEl) {
      nameEl.textContent = currentDistributor.full_name || 'Distributor';
    }

    // Account status badge & banner
    const statusBadge = document.getElementById('badge-account-status');
    const blockedBanner = document.getElementById('blocked-distributor-banner');
    const statusVal = String(currentDistributor.account_status || 'ACTIVE').toUpperCase();

    if (statusBadge) {
      statusBadge.textContent = statusVal;
      if (statusVal === 'BLOCKED') {
        statusBadge.style.background = '#EF4444';
      } else if (statusVal === 'INACTIVE') {
        statusBadge.style.background = '#F59E0B';
      } else {
        statusBadge.style.background = '#10B981';
      }
    }

    if (blockedBanner) {
      blockedBanner.style.display = (statusVal === 'BLOCKED') ? 'block' : 'none';
    }

    // Referral Identity
    const refCode = currentDistributor.referral_code || '--------';
    const codeEl = document.getElementById('distributor-referral-code');
    if (codeEl) codeEl.textContent = refCode;
  }

  function setupEventListeners() {
    // Copy referral code
    const copyCodeBtn = document.getElementById('copy-ref-code-btn');
    if (copyCodeBtn) {
      copyCodeBtn.addEventListener('click', () => {
        const refCode = currentDistributor ? currentDistributor.referral_code : '';
        if (refCode) {
          navigator.clipboard.writeText(refCode).then(() => {
            copyCodeBtn.textContent = 'Copied!';
            setTimeout(() => { copyCodeBtn.textContent = 'Copy Code'; }, 1800);
          }).catch(() => { });
        }
      });
    }

    // Statement export form (Excel format .xlsx only per R-08)
    const stmtForm = document.getElementById('statement-export-form');
    if (stmtForm) {
      stmtForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const msgEl = document.getElementById('statement-message');
        const submitBtn = document.getElementById('download-statement-btn');

        const params = {};

        if (submitBtn) {
          submitBtn.disabled = true;
          submitBtn.textContent = 'Generating Excel...';
        }
        if (msgEl) {
          msgEl.style.display = 'block';
          msgEl.style.color = 'var(--color-muted)';
          msgEl.textContent = 'Requesting statement from compliance server...';
        }

        try {
          if (!window.ShopEasyDistributorReports || typeof window.ShopEasyDistributorReports.downloadStatement !== 'function') {
            throw new Error('Distributor reporting module is not loaded.');
          }
          await window.ShopEasyDistributorReports.downloadStatement(params);
          if (msgEl) {
            msgEl.style.color = '#059669';
            msgEl.textContent = 'Statement downloaded successfully (.xlsx)!';
            setTimeout(() => { msgEl.style.display = 'none'; }, 4000);
          }
        } catch (err) {
          if (msgEl) {
            msgEl.style.color = '#DC2626';
            msgEl.textContent = err.detail || err.message || 'Failed to download statement.';
          }
        } finally {
          if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.innerHTML = `
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                <polyline points="7 10 12 15 17 10"></polyline>
                <line x1="12" y1="15" x2="12" y2="3"></line>
              </svg>
              <span>Download Statement (.xlsx)</span>
            `;
          }
        }
      });
    }

    // Ledger Filter Change
    const filterSelect = document.getElementById('ledger-filter-type');
    if (filterSelect) {
      filterSelect.addEventListener('change', () => {
        renderLedgerTable();
      });
    }

    // Refresh Purchases Button
    const refreshPurchasesBtn = document.getElementById('refresh-distributor-purchases-btn');
    if (refreshPurchasesBtn) {
      refreshPurchasesBtn.addEventListener('click', async () => {
        await loadDistributorPurchaseHistory();
      });
    }

    // Modal Triggers
    const withdrawBtn = document.getElementById('distributor-withdraw-btn');
    const modalOverlay = document.getElementById('distributor-modal-overlay');
    const closeModalBtn = document.getElementById('close-modal-btn');
    const cancelModalBtn = document.getElementById('modal-cancel-btn');
    const confirmModalBtn = document.getElementById('modal-confirm-btn');

    if (withdrawBtn && modalOverlay) {
      withdrawBtn.addEventListener('click', () => {
        openWithdrawalModal();
      });
    }

    if (closeModalBtn && modalOverlay) {
      closeModalBtn.addEventListener('click', () => {
        modalOverlay.style.display = 'none';
      });
    }

    if (cancelModalBtn && modalOverlay) {
      cancelModalBtn.addEventListener('click', () => {
        modalOverlay.style.display = 'none';
      });
    }

    if (confirmModalBtn) {
      confirmModalBtn.addEventListener('click', async () => {
        await executeDistributorWithdrawal();
      });
    }
  }

  // ---------------------------------------------------------------------------
  // Data Fetching: Dashboard Overview (9 Summary Metrics & Separate History)
  // ---------------------------------------------------------------------------
  async function loadDashboardOverview() {
    try {
      if (window.ShopEasyDistributorReports && typeof window.ShopEasyDistributorReports.getDashboardOverview === 'function') {
        const overview = await window.ShopEasyDistributorReports.getDashboardOverview();
        if (overview) {
          overviewLoaded = true;
          renderSummaryCards(overview.summary_metrics);
          renderDirectCommissionHistory(overview.direct_commissions || []);
          renderGenerationCommissionHistory(overview.generation_commissions || []);
        }
      }
    } catch (err) {
      console.warn('Dashboard overview endpoint error (falling back to client aggregation):', err);
    }
  }

  function renderSummaryCards(metrics) {
    if (!metrics) return;
    const availBalEl = document.getElementById('stat-available-balance');
    const withBalEl = document.getElementById('stat-withdrawable-balance');
    const directEl = document.getElementById('stat-direct-comm-total');
    const genEl = document.getElementById('stat-gen-comm-total');
    const grossEl = document.getElementById('stat-total-gross-comm');
    const opCostEl = document.getElementById('stat-total-opcost-deducted');
    const tdsEl = document.getElementById('stat-total-tds-deducted');
    const netEl = document.getElementById('stat-total-net-comm');
    const withdrawnEl = document.getElementById('stat-withdrawn-total');

    if (availBalEl) availBalEl.textContent = formatCurrency(metrics.available_wallet_balance || 0);
    if (withBalEl) withBalEl.textContent = formatCurrency(metrics.available_withdrawable_balance || metrics.available_wallet_balance || 0);
    if (directEl) directEl.textContent = formatCurrency(metrics.lifetime_direct_earned || 0);
    if (genEl) genEl.textContent = formatCurrency(metrics.generation_commission_earned || 0);
    if (grossEl) grossEl.textContent = formatCurrency(metrics.total_gross_commission || 0);
    if (opCostEl) opCostEl.textContent = formatCurrency(metrics.total_operational_cost || 0);
    if (tdsEl) tdsEl.textContent = formatCurrency(metrics.total_tds || 0);
    if (netEl) netEl.textContent = formatCurrency(metrics.total_net_commission_earned || 0);
    if (withdrawnEl) withdrawnEl.textContent = formatCurrency(metrics.total_withdrawn || 0);

    const directBadge = document.getElementById('stat-direct-bonus-badge');
    const directSubtext = document.getElementById('stat-direct-bonus-subtext');
    if (metrics.has_received_direct_bonus) {
      if (directBadge) {
        directBadge.textContent = 'Received (1-Time)';
        directBadge.style.background = '#ECFDF5';
        directBadge.style.color = '#059669';
      }
      if (directSubtext) {
        const dStr = metrics.direct_bonus_date ? new Date(metrics.direct_bonus_date).toLocaleDateString() : '';
        directSubtext.textContent = dStr ? `Received on ${dStr} (One-Time Entitlement)` : 'One-Time Entitlement Consumed';
      }
    } else {
      if (directBadge) {
        directBadge.textContent = '₹500 Eligible';
        directBadge.style.background = '#EFF6FF';
        directBadge.style.color = '#2563EB';
      }
      if (directSubtext) {
        directSubtext.textContent = 'One-Time ₹500.00 Lifetime Entitlement per Distributor';
      }
    }

    const genBadge = document.getElementById('stat-gen-comm-count-badge');
    if (genBadge && typeof metrics.eligible_generation_billing_ids_count === 'number') {
      genBadge.textContent = `${metrics.eligible_generation_billing_ids_count} Units (₹50/item)`;
    }
  }

  function renderDirectCommissionHistory(directComms) {
    const tbody = document.getElementById('direct-commission-history-tbody');
    if (!tbody) return;

    if (!directComms || directComms.length === 0) {
      tbody.innerHTML = `<tr><td colspan="9" style="padding:24px;text-align:center;color:var(--color-muted);">No direct referral commissions earned yet. Refer customers using your referral code.</td></tr>`;
      return;
    }

    tbody.innerHTML = directComms.map(c => `
      <tr style="border-bottom:1px solid var(--color-border);">
        <td style="padding:10px 12px;font-weight:600;color:var(--color-text);">${escapeHtml(c.customer_name || 'Customer')}</td>
        <td style="padding:10px 12px;font-family:monospace;color:var(--color-muted);">${escapeHtml(c.customer_phone || '—')}</td>
        <td style="padding:10px 12px;color:var(--color-muted);">${formatDate(c.purchase_date)}</td>
        <td style="padding:10px 12px;font-family:monospace;">${escapeHtml(c.billing_number || (c.order_id ? '#' + c.order_id : '—'))}</td>
        <td style="padding:10px 12px;text-align:right;font-weight:500;">${formatCurrency(c.gross_amount)}</td>
        <td style="padding:10px 12px;text-align:right;color:#DC2626;">-${formatCurrency(c.operational_cost)}</td>
        <td style="padding:10px 12px;text-align:right;color:#DC2626;">-${formatCurrency(c.tds_amount)}</td>
        <td style="padding:10px 12px;text-align:right;font-weight:700;color:#059669;">+${formatCurrency(c.net_amount)}</td>
        <td style="padding:10px 12px;">
          <span class="badge" style="background:#ECFDF5;color:#059669;font-size:10px;padding:2px 8px;border-radius:4px;font-weight:600;">
            ${escapeHtml(c.status || 'EARNED')}
          </span>
        </td>
      </tr>
    `).join('');
  }

  function renderGenerationCommissionHistory(genComms) {
    const tbody = document.getElementById('generation-commission-history-tbody');
    if (!tbody) return;

    if (!genComms || genComms.length === 0) {
      tbody.innerHTML = `<tr><td colspan="9" style="padding:24px;text-align:center;color:var(--color-muted);">No generation commissions earned yet. Each eligible Billing ID purchased by your referred customers earns ₹50 gross.</td></tr>`;
      return;
    }

    tbody.innerHTML = genComms.map(c => `
      <tr style="border-bottom:1px solid var(--color-border);">
        <td style="padding:10px 12px;font-weight:600;color:var(--color-text);">${escapeHtml(c.customer_name || 'Customer')}</td>
        <td style="padding:10px 12px;font-family:monospace;color:var(--color-muted);">#${escapeHtml(String(c.order_id || '—'))}</td>
        <td style="padding:10px 12px;font-family:monospace;font-weight:600;color:var(--color-primary);">${escapeHtml(c.billing_number || '—')}</td>
        <td style="padding:10px 12px;color:var(--color-muted);">${formatDate(c.commission_date)}</td>
        <td style="padding:10px 12px;text-align:right;font-weight:500;">${formatCurrency(c.gross_amount)}</td>
        <td style="padding:10px 12px;text-align:right;color:#DC2626;">-${formatCurrency(c.operational_cost)}</td>
        <td style="padding:10px 12px;text-align:right;color:#DC2626;">-${formatCurrency(c.tds_amount)}</td>
        <td style="padding:10px 12px;text-align:right;font-weight:700;color:#16A34A;">+${formatCurrency(c.net_amount)}</td>
        <td style="padding:10px 12px;">
          <span class="badge" style="background:#F0FDF4;color:#16A34A;font-size:10px;padding:2px 8px;border-radius:4px;font-weight:600;">
            ${escapeHtml(c.status || 'EARNED')}
          </span>
        </td>
      </tr>
    `).join('');
  }

  // ---------------------------------------------------------------------------
  // Data Fetching: Earnings & Wallets
  // ---------------------------------------------------------------------------
  async function loadEarningsAndWallets() {
    try {
      if (window.ShopEasyWallets && typeof window.ShopEasyWallets.list === 'function') {
        const walletsRes = await window.ShopEasyWallets.list();
        walletsData = Array.isArray(walletsRes) ? walletsRes : (walletsRes.items || []);
        directWallet = walletsData.find(w => w.wallet_type === 'direct_referral') || null;
      }

      renderWalletMetrics();
    } catch (err) {
      console.error('Failed to load earnings or wallets:', err);
    }
  }

  function renderWalletMetrics() {
    const balEl = document.getElementById('stat-available-balance');
    const paidEl = document.getElementById('stat-withdrawn-total');
    const noteEl = document.getElementById('withdrawal-eligibility-note');
    const withdrawBtn = document.getElementById('distributor-withdraw-btn');

    const balanceNum = directWallet ? Number(directWallet.balance || 0) : 0;
    const isFrozen = directWallet ? Boolean(directWallet.is_frozen) : false;
    const isBlocked = (currentDistributor && currentDistributor.account_status === 'BLOCKED');

    if (balEl) balEl.textContent = formatCurrency(balanceNum);

    // Sum total paid out from withdrawalsData
    const completedPayouts = withdrawalsData
      .filter(w => w.status === 'COMPLETED')
      .reduce((sum, w) => sum + Number(w.amount || 0), 0);
    if (paidEl) paidEl.textContent = formatCurrency(completedPayouts);

    // Check withdrawal eligibility
    let canWithdraw = true;
    let noteText = '';

    if (isFrozen) {
      canWithdraw = false;
      noteText = 'Direct Referral Wallet is currently frozen by administration. Withdrawals are temporarily suspended.';
    } else if (balanceNum <= 0) {
      canWithdraw = false;
      noteText = 'Available balance is ₹0.00. No funds to liquidate.';
    } else if (!withdrawalsData.some(w => w.status === 'COMPLETED') && balanceNum < 750) {
      canWithdraw = false;
      noteText = `Initial payout requires a minimum balance of ₹750. Current balance: ${formatCurrency(balanceNum)}.`;
    } else if (isBlocked) {
      canWithdraw = true;
      noteText = `Compliance Warning: Your account is BLOCKED. A withdrawal request for full balance (${formatCurrency(balanceNum)}) will be submitted for manual administrative review.`;
    } else {
      canWithdraw = true;
      noteText = `Eligible for full-balance liquidation: ${formatCurrency(balanceNum)}. Payout will execute automatically upon confirmation.`;
    }

    if (noteEl) {
      noteEl.textContent = noteText;
      if (isFrozen) {
        noteEl.style.color = '#DC2626';
        noteEl.style.borderColor = '#FCA5A5';
      } else if (isBlocked) {
        noteEl.style.color = '#B45309';
        noteEl.style.borderColor = '#FCD34D';
      } else {
        noteEl.style.color = 'var(--color-muted)';
        noteEl.style.borderColor = '#E2E8F0';
      }
    }

    if (withdrawBtn) {
      withdrawBtn.disabled = !canWithdraw;
    }
  }

  // ---------------------------------------------------------------------------
  // Data Fetching: Ledger Transactions & Granular Totals
  // ---------------------------------------------------------------------------
  async function loadLedgerTransactions() {
    try {
      if (window.ShopEasyWallets && typeof window.ShopEasyWallets.getTransactions === 'function') {
        const res = await window.ShopEasyWallets.getTransactions({
          wallet_type: 'direct_referral',
          page: 1,
          page_size: 100
        });
        transactionsData = Array.isArray(res) ? res : (res.items || []);
      }

      computeGranularCommissions();
      renderLedgerTable();
    } catch (err) {
      console.error('Failed to load ledger transactions:', err);
      const tbody = document.getElementById('commission-ledger-tbody');
      if (tbody) {
        tbody.innerHTML = `<tr><td colspan="6" style="padding:24px;text-align:center;color:#DC2626;">Failed to load commission ledger transactions.</td></tr>`;
      }
    }
  }

  function computeGranularCommissions() {
    // If overview was already loaded from authoritative backend reports, do not overwrite summary cards
    if (overviewLoaded) return;

    let directTotal = 0;
    let genTotal = 0;

    transactionsData.forEach(tx => {
      const txType = String(tx.transaction_type || tx.tx_type || '').toUpperCase();
      if (txType === 'CREDIT') {
        const amt = Number(tx.amount || 0);
        const idemp = String(tx.idempotency_key || '');
        if (idemp.startsWith('PB-DIRECT:')) {
          directTotal += amt;
        } else if (idemp.startsWith('PB-GEN:')) {
          genTotal += amt;
        }
        // Strictly exclude Plan A (PA-COMM:), cashback, manual adjustments, or unknown transactions
      }
    });

    const directEl = document.getElementById('stat-direct-comm-total');
    const genEl = document.getElementById('stat-gen-comm-total');

    if (directEl) directEl.textContent = formatCurrency(directTotal);
    if (genEl) genEl.textContent = formatCurrency(genTotal);
  }

  function renderLedgerTable() {
    const tbody = document.getElementById('commission-ledger-tbody');
    const filterSelect = document.getElementById('ledger-filter-type');
    const filter = filterSelect ? filterSelect.value : 'ALL';

    if (!tbody) return;

    let filtered = transactionsData;
    if (filter === 'PB-DIRECT') {
      filtered = transactionsData.filter(tx => String(tx.idempotency_key || '').startsWith('PB-DIRECT:'));
    } else if (filter === 'PB-GEN') {
      filtered = transactionsData.filter(tx => String(tx.idempotency_key || '').startsWith('PB-GEN:'));
    } else if (filter === 'WITHDRAWAL') {
      filtered = transactionsData.filter(tx => String(tx.transaction_type || tx.tx_type || '').toUpperCase() === 'DEBIT');
    }

    if (filtered.length === 0) {
      tbody.innerHTML = `<tr><td colspan="6" style="padding:24px;text-align:center;color:var(--color-muted);">No transactions found matching criteria.</td></tr>`;
      return;
    }

    tbody.innerHTML = filtered.map(tx => {
      const txType = String(tx.transaction_type || tx.tx_type || '').toUpperCase();
      const isCredit = txType === 'CREDIT';
      const amtPrefix = isCredit ? '+' : '-';
      const amtColor = isCredit ? '#059669' : '#DC2626';
      const idemp = tx.idempotency_key || '—';
      const dateStr = formatDate(tx.created_at);

      let badgeLabel = 'Commission';
      let badgeBg = '#EFF6FF';
      let badgeFg = '#2563EB';
      let txDescription = tx.description;

      if (idemp.startsWith('PB-DIRECT:')) {
        badgeLabel = 'Lifetime Direct ₹500';
        badgeBg = '#ECFDF5';
        badgeFg = '#059669';
        if (!txDescription) {
          txDescription = `Lifetime Direct Referral Bonus (Ref #${tx.reference_id || '—'})`;
        }
      } else if (idemp.startsWith('PB-GEN:')) {
        badgeLabel = 'Generation ₹50';
        badgeBg = '#F0FDF4';
        badgeFg = '#16A34A';
        if (!txDescription) {
          txDescription = `Generation Commission (Ref #${tx.reference_id || '—'})`;
        }
      } else if (!isCredit) {
        badgeLabel = 'Payout Debit';
        badgeBg = '#FEF2F2';
        badgeFg = '#DC2626';
        if (!txDescription) {
          txDescription = `Wallet Liquidation Payout (Ref #${tx.reference_id || '—'})`;
        }
      } else if (!txDescription) {
        const refTypeLabel = tx.reference_type ? String(tx.reference_type).replace(/_/g, ' ') : 'Credit';
        txDescription = `${refTypeLabel} (Ref #${tx.reference_id || '—'})`;
      }

      return `
        <tr style="border-bottom:1px solid var(--color-border);">
          <td style="padding:10px 12px;color:var(--color-muted);">${dateStr}</td>
          <td style="padding:10px 12px;">
            <div style="display:flex;align-items:center;gap:6px;">
              <span class="badge" style="background:${badgeBg};color:${badgeFg};font-size:10px;padding:2px 6px;border-radius:4px;font-weight:600;">
                ${badgeLabel}
              </span>
              <span style="font-weight:500;color:var(--color-text);">${escapeHtml(txDescription)}</span>
            </div>
          </td>
          <td style="padding:10px 12px;font-family:monospace;color:var(--color-muted);">${escapeHtml(String(tx.reference_id || '—'))}</td>
          <td style="padding:10px 12px;text-align:right;font-weight:700;color:${amtColor};">${amtPrefix}${formatCurrency(tx.amount)}</td>
          <td style="padding:10px 12px;text-align:right;color:var(--color-text);">${formatCurrency(tx.balance_after)}</td>
          <td style="padding:10px 12px;font-family:monospace;font-size:11px;color:var(--color-muted);max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${escapeHtml(idemp)}">
            ${escapeHtml(idemp)}
          </td>
        </tr>
      `;
    }).join('');
  }

  // ---------------------------------------------------------------------------
  // Data Fetching: Withdrawals List
  // ---------------------------------------------------------------------------
  async function loadWithdrawalsList() {
    try {
      if (window.ShopEasyWallets && typeof window.ShopEasyWallets.getWithdrawals === 'function') {
        const res = await window.ShopEasyWallets.getWithdrawals({
          wallet_type: 'direct_referral',
          page: 1,
          page_size: 50
        });
        withdrawalsData = Array.isArray(res) ? res : (res.items || []);
      }

      renderWithdrawalsTable();
      renderWalletMetrics(); // Updates total liquidated amount & withdrawal eligibility
    } catch (err) {
      console.error('Failed to load withdrawals:', err);
      const tbody = document.getElementById('distributor-withdrawals-tbody');
      if (tbody) {
        tbody.innerHTML = `<tr><td colspan="5" style="padding:24px;text-align:center;color:#DC2626;">Failed to load liquidation records.</td></tr>`;
      }
    }
  }

  function renderWithdrawalsTable() {
    const tbody = document.getElementById('distributor-withdrawals-tbody');
    if (!tbody) return;

    if (withdrawalsData.length === 0) {
      tbody.innerHTML = `<tr><td colspan="5" style="padding:24px;text-align:center;color:var(--color-muted);">No liquidation requests submitted yet.</td></tr>`;
      return;
    }

    tbody.innerHTML = withdrawalsData.map(w => {
      const dateStr = formatDate(w.created_at);
      const status = String(w.status || 'PENDING').toUpperCase();
      let statusBg = '#EFF6FF';
      let statusFg = '#2563EB';

      if (status === 'COMPLETED') {
        statusBg = '#ECFDF5';
        statusFg = '#059669';
      } else if (status === 'REJECTED' || status === 'FAILED') {
        statusBg = '#FEF2F2';
        statusFg = '#DC2626';
      } else if (status === 'REQUESTED' || status === 'PENDING') {
        statusBg = '#FFFBEB';
        statusFg = '#D97706';
      }

      const netAmount = (w.payout_amount !== undefined && w.payout_amount !== null)
        ? formatCurrency(w.payout_amount)
        : formatCurrency(w.amount);

      return `
        <tr style="border-bottom:1px solid var(--color-border);">
          <td style="padding:10px 12px;color:var(--color-muted);">${dateStr}</td>
          <td style="padding:10px 12px;font-weight:600;color:var(--color-text);">${formatCurrency(w.amount)}</td>
          <td style="padding:10px 12px;font-weight:700;color:#059669;">${netAmount}</td>
          <td style="padding:10px 12px;">
            <span class="badge" style="background:${statusBg};color:${statusFg};font-size:11px;padding:3px 8px;border-radius:9999px;font-weight:600;">
              ${escapeHtml(status)}
            </span>
          </td>
          <td style="padding:10px 12px;color:var(--color-muted);max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">
            ${escapeHtml(w.rejection_reason || w.idempotency_key || 'Full-balance liquidation')}
          </td>
        </tr>
      `;
    }).join('');
  }

  // ---------------------------------------------------------------------------
  // Data Fetching: Notifications
  // ---------------------------------------------------------------------------
  async function loadNotifications() {
    const listEl = document.getElementById('notifications-list-container');
    const badgeEl = document.getElementById('notification-badge');
    const unreadCountBadge = document.getElementById('unread-notifications-count-badge');

    try {
      if (window.ShopEasyNotifications && typeof window.ShopEasyNotifications.list === 'function') {
        const res = await window.ShopEasyNotifications.list({ page: 1, page_size: 20 });
        notificationsData = Array.isArray(res) ? res : (res.items || []);
      }

      const unreadCount = notificationsData.filter(n => !n.is_read).length;

      if (badgeEl) {
        if (unreadCount > 0) {
          badgeEl.textContent = unreadCount > 9 ? '9+' : String(unreadCount);
          badgeEl.style.display = 'block';
        } else {
          badgeEl.style.display = 'none';
        }
      }

      if (unreadCountBadge) {
        unreadCountBadge.textContent = `${unreadCount} Unread`;
      }

      if (!listEl) return;

      if (notificationsData.length === 0) {
        listEl.innerHTML = `<p style="color:var(--color-muted);font-size:var(--text-sm);text-align:center;padding:var(--space-4) 0;">No notifications found.</p>`;
        return;
      }

      listEl.innerHTML = notificationsData.map(n => {
        const isRead = Boolean(n.is_read);
        const bg = isRead ? '#FFFFFF' : '#F0F9FF';
        const border = isRead ? 'var(--color-border)' : '#BAE6FD';
        const dateStr = formatDate(n.created_at);

        return `
          <div style="background:${bg};border:1px solid ${border};border-radius:var(--radius-md);padding:10px 14px;margin-bottom:8px;display:flex;justify-content:space-between;align-items:flex-start;gap:12px;">
            <div style="flex-grow:1;">
              <div style="display:flex;align-items:center;gap:6px;margin-bottom:2px;">
                ${!isRead ? '<span style="width:7px;height:7px;border-radius:50%;background:#0284C7;display:inline-block;"></span>' : ''}
                <strong style="font-size:var(--text-xs);color:var(--color-text);">${escapeHtml(n.title || 'Notification')}</strong>
                <span style="font-size:10px;color:var(--color-muted);">${dateStr}</span>
              </div>
              <p style="font-size:var(--text-xs);color:var(--color-muted);margin:0;line-height:1.4;">${escapeHtml(n.message || '')}</p>
            </div>
            <div>
              ${!isRead ? `
                <button type="button" class="btn btn-outline btn-xs mark-single-read-btn" data-notif-id="${n.id}" style="padding:2px 8px;font-size:10px;">
                  Mark Read
                </button>
              ` : ''}
            </div>
          </div>
        `;
      }).join('');

      // Wire up single mark read buttons
      listEl.querySelectorAll('.mark-single-read-btn').forEach(btn => {
        btn.addEventListener('click', async (e) => {
          const notifId = e.target.getAttribute('data-notif-id');
          if (notifId && window.ShopEasyNotifications) {
            try {
              await window.ShopEasyNotifications.markRead(notifId);
              await loadNotifications();
            } catch (err) {
              console.error('Failed to mark notification read:', err);
            }
          }
        });
      });

    } catch (err) {
      console.error('Failed to load notifications:', err);
      if (listEl) {
        listEl.innerHTML = `<p style="color:#DC2626;font-size:var(--text-sm);text-align:center;padding:var(--space-4) 0;">Failed to load notifications.</p>`;
      }
    }
  }

  // ---------------------------------------------------------------------------
  // Modal & Withdrawal Execution
  // ---------------------------------------------------------------------------
  function openWithdrawalModal() {
    const modal = document.getElementById('distributor-modal-overlay');
    const amtEl = document.getElementById('modal-liquidation-amount');
    const modeEl = document.getElementById('modal-settlement-mode');
    const blockedWarning = document.getElementById('modal-blocked-warning');

    if (!modal) return;

    const balanceNum = directWallet ? Number(directWallet.balance || 0) : 0;
    const isBlocked = (currentDistributor && currentDistributor.account_status === 'BLOCKED');

    if (amtEl) amtEl.textContent = formatCurrency(balanceNum);

    if (modeEl) {
      if (isBlocked) {
        modeEl.textContent = 'Manual Review (Compliance Hold)';
        modeEl.style.color = '#DC2626';
      } else {
        modeEl.textContent = 'Instant Payout';
        modeEl.style.color = '#059669';
      }
    }

    if (blockedWarning) {
      blockedWarning.style.display = isBlocked ? 'block' : 'none';
    }

    modal.style.display = 'flex';
  }

  async function executeDistributorWithdrawal() {
    const confirmBtn = document.getElementById('modal-confirm-btn');
    const cancelBtn = document.getElementById('modal-cancel-btn');
    const modal = document.getElementById('distributor-modal-overlay');

    if (!directWallet) {
      alert('Direct Referral Wallet record not found.');
      return;
    }

    const balanceNum = Number(directWallet.balance || 0);
    if (balanceNum <= 0) {
      alert('Available balance is zero.');
      if (modal) modal.style.display = 'none';
      return;
    }

    if (confirmBtn) {
      confirmBtn.disabled = true;
      confirmBtn.textContent = 'Processing Payout...';
    }
    if (cancelBtn) cancelBtn.disabled = true;

    try {
      if (!window.ShopEasyWallets || typeof window.ShopEasyWallets.withdraw !== 'function') {
        throw new Error('Wallet withdrawal service is not available.');
      }

      // Generate robust client idempotency key to prevent accidental double submission
      const idempotencyKey = `PB-WITHDRAW:${currentDistributor.id}:${Date.now()}`;

      const res = await window.ShopEasyWallets.withdraw({
        wallet_type: 'direct_referral',
        amount: balanceNum,
        idempotency_key: idempotencyKey
      });

      if (modal) modal.style.display = 'none';

      const isBlocked = (currentDistributor && currentDistributor.account_status === 'BLOCKED');
      if (isBlocked) {
        alert('Liquidation request submitted successfully! Your account is under compliance review, so your request is in REQUESTED state pending manual approval.');
      } else {
        alert('Liquidation request processed successfully! Payout completed.');
      }

      // Refresh all state
      await Promise.allSettled([
        loadEarningsAndWallets(),
        loadLedgerTransactions(),
        loadWithdrawalsList(),
        loadNotifications()
      ]);

    } catch (err) {
      alert(err.detail || err.message || 'Liquidation request failed.');
    } finally {
      if (confirmBtn) {
        confirmBtn.disabled = false;
        confirmBtn.textContent = 'Confirm & Proceed';
      }
      if (cancelBtn) cancelBtn.disabled = false;
    }
  }

  // ---------------------------------------------------------------------------
  // Section: Distributor Purchases & Billing IDs (OR-12)
  // ---------------------------------------------------------------------------
  async function loadDistributorPurchaseHistory() {
    const container = document.getElementById('distributor-purchase-container');
    if (!container) return;

    container.innerHTML = `
      <div style="padding:var(--space-6) 0;text-align:center;color:var(--color-muted);font-size:var(--text-xs);">
        <div class="spinner" style="width:20px;height:20px;border:2px solid var(--color-border);border-top-color:var(--color-primary);border-radius:50%;animation:spin 0.8s linear infinite;margin:0 auto var(--space-2);"></div>
        Loading purchase history...
      </div>
    `;

    try {
      if (!window.ShopEasyOrders || typeof window.ShopEasyOrders.list !== 'function') {
        throw new Error('Orders service is unavailable.');
      }
      const response = await window.ShopEasyOrders.list();
      const orders = (response && response.items) ? response.items : (Array.isArray(response) ? response : []);
      renderDistributorPurchasesTable(orders, container);
    } catch (err) {
      console.error('Failed to load distributor purchases:', err);
      container.innerHTML = `
        <div style="padding:var(--space-4);text-align:center;">
          <p style="color:var(--color-danger);font-size:var(--text-xs);margin-bottom:var(--space-2);">
            ${escapeHtml(err.detail || err.message || 'Unable to load purchase history.')}
          </p>
          <button type="button" class="btn btn-secondary btn-xs" onclick="window.retryLoadDistributorPurchases()">
            Retry
          </button>
        </div>
      `;
    }
  }

  function renderDistributorPurchasesTable(orders, container) {
    if (!orders || orders.length === 0) {
      container.innerHTML = `
        <div style="padding:var(--space-6) 0;text-align:center;">
          <p style="color:var(--color-muted);font-size:var(--text-xs);margin-bottom:var(--space-2);">
            No purchases found. Your personal distributor product orders and allocated Billing IDs will appear here.
          </p>
          <a href="products.html" class="btn btn-primary btn-xs">Browse Products</a>
        </div>
      `;
      return;
    }

    container.innerHTML = `
      <div style="display:flex;flex-direction:column;gap:var(--space-4);">
        ${orders.map(order => {
      const orderNum = order.order_number || (`#ORD-${order.id}`);
      const dateStr = formatDate(order.created_at);
      const totalStr = formatCurrency(order.total_amount);
      const payStatus = String(order.payment_status || '').toUpperCase();

      let payBadgeBg = '#EFF6FF';
      let payBadgeFg = '#2563EB';
      let payLabel = payStatus || 'PENDING';

      if (payStatus === 'COMPLETED') {
        payBadgeBg = '#ECFDF5';
        payBadgeFg = '#059669';
        payLabel = 'Payment Completed';
      } else if (payStatus === 'FAILED') {
        payBadgeBg = '#FEF2F2';
        payBadgeFg = '#DC2626';
        payLabel = 'Payment Failed';
      } else {
        payBadgeBg = '#FFFBEB';
        payBadgeFg = '#D97706';
        payLabel = 'Payment Pending';
      }

      const itemsHtml = (order.order_items || []).map(item => {
        const qty = item.quantity || 1;
        const unitPriceStr = formatCurrency(item.unit_price);
        const lineTotalStr = formatCurrency(item.line_total);

        // Extract authoritative backend billing IDs if provided
        let itemBillingIds = [];
        if (Array.isArray(item.billing_ids)) {
          itemBillingIds = item.billing_ids
            .map(b => (typeof b === 'object' && b !== null) ? (b.billing_number || b.id || '') : String(b))
            .filter(Boolean);
        } else if (item.billing_id) {
          itemBillingIds = [(typeof item.billing_id === 'object') ? (item.billing_id.billing_number || item.billing_id.id || '') : String(item.billing_id)].filter(Boolean);
        } else if (Array.isArray(order.billing_ids)) {
          const matching = order.billing_ids.filter(b => (typeof b === 'object' && b !== null && b.order_item_id) ? b.order_item_id === item.id : true);
          itemBillingIds = matching.map(b => (typeof b === 'object' && b !== null) ? (b.billing_number || b.id || '') : String(b)).filter(Boolean);
        }

        let billingContentHtml = '';
        if (payStatus !== 'COMPLETED') {
          billingContentHtml = `
                <div style="font-size:11px;color:var(--color-muted);font-style:italic;">
                  No Billing ID issued (Payment ${escapeHtml(payLabel)})
                </div>
              `;
        } else if (itemBillingIds.length === 0) {
          billingContentHtml = `
                <div style="font-size:11px;color:var(--color-muted);font-style:italic;">
                  Awaiting Billing ID allocation / Not provided by server
                </div>
              `;
        } else {
          billingContentHtml = `
                <div style="display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin-top:4px;">
                  ${itemBillingIds.map((bid, idx) => `
                    <div class="billing-id-pill" style="display:inline-flex;align-items:center;gap:6px;background:#F1F5F9;border:1px solid #CBD5E1;border-radius:var(--radius-md);padding:2px 8px;">
                      <span style="font-size:10px;font-weight:600;color:var(--color-muted);text-transform:uppercase;">Unit ${idx + 1}:</span>
                      <code style="font-size:11px;font-weight:700;color:var(--color-primary);letter-spacing:0.04em;word-break:break-all;">${escapeHtml(bid)}</code>
                      <button type="button" class="btn btn-outline btn-xs" style="padding:1px 5px;font-size:10px;line-height:1.2;" onclick="copyDistributorBillingIdText('${escapeHtml(bid)}', this)">Copy</button>
                    </div>
                  `).join('')}
                </div>
              `;
        }

        return `
              <div style="padding:var(--space-2) 0;border-top:1px solid var(--color-border);display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:var(--space-2);">
                <div style="flex:1;min-width:200px;">
                  <div style="font-weight:600;font-size:var(--text-xs);color:var(--color-text);">${escapeHtml(item.product_name)}</div>
                  <div style="font-size:11px;color:var(--color-muted);margin-top:2px;">
                    Quantity: ${qty} &times; ${unitPriceStr} = <strong>${lineTotalStr}</strong>
                  </div>
                  <div style="margin-top:4px;">
                    ${billingContentHtml}
                  </div>
                </div>
              </div>
            `;
      }).join('');

      return `
            <div style="background:#F8FAFC;border:1px solid var(--color-border);border-radius:var(--radius-md);padding:var(--space-3);">
              <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:var(--space-2);margin-bottom:var(--space-2);">
                <div>
                  <span style="font-size:10px;font-weight:700;color:var(--color-muted);text-transform:uppercase;">Order</span>
                  <code style="font-size:var(--text-xs);font-weight:700;color:var(--color-text);word-break:break-all;margin-left:4px;">
                    ${escapeHtml(orderNum)}
                  </code>
                </div>
                <div style="display:flex;align-items:center;gap:var(--space-2);flex-wrap:wrap;">
                  <span style="font-size:11px;color:var(--color-muted);">${dateStr}</span>
                  <span style="background:${payBadgeBg};color:${payBadgeFg};padding:2px 6px;border-radius:9999px;font-size:10px;font-weight:600;">
                    ${payLabel}
                  </span>
                  <span style="font-size:var(--text-xs);font-weight:700;color:var(--color-text);">
                    ${totalStr}
                  </span>
                </div>
              </div>
              <div style="border-top:1px solid #E2E8F0;padding-top:var(--space-1);">
                ${itemsHtml || '<p style="color:var(--color-muted);font-size:11px;">No items in this order.</p>'}
              </div>
            </div>
          `;
    }).join('')}
      </div>
    `;
  }

  function copyDistributorBillingIdText(text, btnEl) {
    if (!text) return;
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(() => {
        if (btnEl) {
          const orig = btnEl.textContent;
          btnEl.textContent = 'Copied!';
          setTimeout(() => { btnEl.textContent = orig; }, 1500);
        }
      }).catch(() => { });
    }
  }

  // ---------------------------------------------------------------------------
  // Helper Utilities
  // ---------------------------------------------------------------------------
  function formatCurrency(amount) {
    const num = Number(amount || 0);
    return '₹' + num.toLocaleString('en-IN', {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2
    });
  }

  function formatDate(isoStr) {
    if (!isoStr) return '—';
    try {
      const d = new Date(isoStr);
      return d.toLocaleDateString('en-IN', {
        day: '2-digit',
        month: 'short',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit'
      });
    } catch (_) {
      return String(isoStr);
    }
  }

  function escapeHtml(str) {
    if (str === null || str === undefined) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  // Global window exports for inline attributes / triggers / testing
  window.loadDistributorPurchaseHistory = loadDistributorPurchaseHistory;
  window.retryLoadDistributorPurchases = loadDistributorPurchaseHistory;
  window.renderDistributorPurchasesTable = renderDistributorPurchasesTable;
  window.copyDistributorBillingIdText = copyDistributorBillingIdText;

})();
