/**
 * Arya Global Digital --- Plan A Customer Dashboard & 48-Bulb Cashback Tracker
 *
 * Handles:
 *  - Customer authentication guard via requireCustomerAuth().
 *  - Plan A programme check (blocks/redirects Plan B users).
 *  - Real-time fetching of Plan A 48-bulb cashback progress and cycle history.
 *  - Visual 48-bulb track strictly driven by server bulb_states.
 *  - Milestone indicators: Bulb 9 (₹750), Bulb 24 (₹2,000), Bulb 48 (₹4,000).
 *  - Dual isolated wallets (Direct Referral & Sequential Commission).
 *  - Full-balance simulated withdrawals with client idempotency key generation.
 *  - Auditable transaction ledgers and withdrawal histories.
 *  - Referral code sharing and referee purchase tracking.
 */

(function () {
  'use strict';

  let currentCustomer = null;
  let earningsData = null;
  let cashbackProgress = null;
  let cashbackCycles = [];
  let referralData = null;
  let activeWalletTab = 'direct_referral';
  let pendingWithdrawalType = null;

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', async () => {
      await initDashboard();
    });
  } else {
    initDashboard();
  }

  async function initDashboard() {
    try {
      currentCustomer = await window.requireCustomerAuth();
      if (!currentCustomer) return;

      // Plan A programme isolation guard: Plan B users must not access Plan A cashback engine
      if (currentCustomer.programme && currentCustomer.programme !== 'PLAN_A') {
        const mainEl = document.querySelector('main .container');
        if (mainEl) {
          mainEl.innerHTML = `
            <div style="background:#FFF;padding:var(--space-8);border-radius:var(--radius-xl);border:1px solid var(--color-border);margin:var(--space-8) 0;text-align:center;">
              <h2 style="font-size:var(--text-xl);font-weight:700;color:var(--color-text);margin-bottom:var(--space-2);">Plan B Distributor Account</h2>
              <p style="color:var(--color-muted);max-width:540px;margin:0 auto var(--space-4);">
                Your account is enrolled in <strong>Plan B (Direct Sales &amp; Distributor Network)</strong>. The 48-bulb cashback tracker is exclusive to Plan A Retail Customers.
              </p>
              <a href="distributor-dashboard.html" class="btn btn-primary btn-sm">Go to Distributor Dashboard</a>
              <a href="profile.html" class="btn btn-secondary btn-sm" style="margin-left: 8px;">View Profile</a>
            </div>
          `;
        }
        return;
      }

      setupEventListeners();
      await loadAllDashboardData();
    } catch (err) {
      console.error('Failed to initialize dashboard:', err);
      if (typeof showToast === 'function') {
        showToast('Failed to load dashboard. Please refresh.', 'error');
      }
    }
  }

  function setupEventListeners() {
    // Tab switching for dual wallets
    const tabButtons = document.querySelectorAll('.wallet-tab-btn');
    tabButtons.forEach(btn => {
      btn.addEventListener('click', () => {
        const targetTab = btn.getAttribute('data-tab');
        if (targetTab) {
          switchWalletTab(targetTab);
        }
      });
    });

    // Plan A withdraw action button in cashback card
    const planAWithdrawBtn = document.getElementById('plan-a-withdraw-action-btn');
    if (planAWithdrawBtn) {
      planAWithdrawBtn.addEventListener('click', () => {
        const bal = parseFloat(cashbackProgress?.current_wallet_balance || earningsData?.sequential_commission_balance || 0);
        openWithdrawModal('sequential_commission', bal);
      });
    }

    // Modal close button and overlay click
    const modalCloseBtn = document.getElementById('modal-close-btn');
    const modalCancelBtn = document.getElementById('modal-cancel-btn');
    const modalOverlay = document.getElementById('withdraw-modal-overlay');

    if (modalCloseBtn) modalCloseBtn.addEventListener('click', closeWithdrawModal);
    if (modalCancelBtn) modalCancelBtn.addEventListener('click', closeWithdrawModal);
    if (modalOverlay) {
      modalOverlay.addEventListener('click', (e) => {
        if (e.target === modalOverlay) {
          closeWithdrawModal();
        }
      });
    }

    const modalConfirmBtn = document.getElementById('modal-confirm-btn');
    if (modalConfirmBtn) {
      modalConfirmBtn.addEventListener('click', executeWithdrawal);
    }

    // Refresh purchase history button
    const refreshPurchasesBtn = document.getElementById('refresh-purchases-btn');
    if (refreshPurchasesBtn) {
      refreshPurchasesBtn.addEventListener('click', () => {
        loadPurchaseHistory();
      });
    }
  }

  async function loadAllDashboardData() {
    try {
      // 1. Fetch Composite Earnings
      earningsData = await window.ShopEasyDashboard.getEarnings();
      renderEarningsSummary(earningsData);

      // 2. Fetch Plan A Cashback Progress & Cycles (WP-10 / WP-12)
      try {
        if (window.ShopEasyCashback) {
          cashbackProgress = await window.ShopEasyCashback.getProgress();
          renderPlanACashbackProgress(cashbackProgress);

          cashbackCycles = await window.ShopEasyCashback.getCycles();
          renderCompletedCycles(cashbackCycles);
        } else {
          // Fallback to earningsData sequential_progress if cashback client unavailable
          renderPlanACashbackProgress(earningsData.sequential_progress);
        }
      } catch (cbErr) {
        console.warn('Could not load Plan A cashback progress:', cbErr);
        if (earningsData && earningsData.sequential_progress) {
          renderPlanACashbackProgress(earningsData.sequential_progress);
        }
      }

      // 3. Fetch Referrals Summary
      referralData = await window.ShopEasyDashboard.getReferrals();
      renderReferralManagement(referralData);

      // 4. Load Purchase History & Unit Billing IDs (OR-12)
      await loadPurchaseHistory();

      // 5. Load Wallets and Ledgers
      await loadWalletViews();
    } catch (err) {
      console.error('Error fetching dashboard metrics:', err);
      if (typeof showToast === 'function') {
        showToast(err.detail || err.message || 'Error loading dashboard metrics', 'error');
      }
    }
  }

  // -------------------------------------------------------------------------
  // Section 1: Composite Earnings Summary
  // -------------------------------------------------------------------------
  function renderEarningsSummary(data) {
    if (!data) return;

    const totalEl = document.getElementById('metric-total-earnings');
    if (totalEl) totalEl.textContent = formatCurrency(data.total_earnings);

    const drBalEl = document.getElementById('metric-dr-balance');
    if (drBalEl) drBalEl.textContent = formatCurrency(data.direct_referral_balance);

    const scBalEl = document.getElementById('metric-sc-balance');
    if (scBalEl) scBalEl.textContent = formatCurrency(data.sequential_commission_balance);

    const totalWithdrawnEl = document.getElementById('metric-total-withdrawn');
    if (totalWithdrawnEl) totalWithdrawnEl.textContent = formatCurrency(data.total_withdrawn);

    const drWithdrawnEl = document.getElementById('metric-dr-withdrawn');
    if (drWithdrawnEl) drWithdrawnEl.textContent = formatCurrency(data.direct_referral_withdrawn);

    const scWithdrawnEl = document.getElementById('metric-sc-withdrawn');
    if (scWithdrawnEl) {
      const activeEarned = parseFloat(cashbackProgress?.active_cycle_earnings ?? cashbackProgress?.cashback_amount_earned ?? data.sequential_progress?.total_earned ?? '0.00');
      const scBal = parseFloat(data.sequential_commission_balance || '0.00');
      if (scBal === 0 && activeEarned > 0) {
        scWithdrawnEl.innerHTML = `${formatCurrency(data.sequential_commission_withdrawn)} <span style="display:block;font-size:11px;color:var(--color-primary-600);margin-top:2px;">(Pending: ${formatCurrency(activeEarned)})</span>`;
      } else {
        scWithdrawnEl.textContent = formatCurrency(data.sequential_commission_withdrawn);
      }
    }

    // Update customer greeting
    const userNameEl = document.getElementById('dashboard-customer-name');
    if (userNameEl && currentCustomer) {
      userNameEl.textContent = currentCustomer.full_name || 'Customer';
    }
  }

  // -------------------------------------------------------------------------
  // Section 2: Plan A 48-Bulb Visual Cashback Track
  // -------------------------------------------------------------------------
  function renderPlanACashbackProgress(progress) {
    const statusBadgeEl = document.getElementById('queue-status-badge');
    const statusMessageTextEl = document.getElementById('beneficiary-message-text');
    const statusMessageBox = document.getElementById('beneficiary-message-box');
    const bulbsContainer = document.getElementById('bulbs-container');
    const progressBarFill = document.getElementById('progress-bar-fill');
    const progressStatsEl = document.getElementById('progress-bar-stats-text');

    const milestoneCard9 = document.getElementById('milestone-card-9');
    const milestoneCard24 = document.getElementById('milestone-card-24');
    const milestoneCard48 = document.getElementById('milestone-card-48');

    const bannerBox = document.getElementById('plan-a-withdrawal-banner');
    const bannerTitle = document.getElementById('withdrawal-banner-title');
    const bannerDesc = document.getElementById('withdrawal-banner-desc');
    const withdrawActionBtn = document.getElementById('plan-a-withdraw-action-btn');

    if (!progress) return;

    const cycleStatus = (progress.cycle_status || progress.status || 'NO_CYCLE').toUpperCase();
    const completedCount = progress.completed_contributions !== undefined
      ? progress.completed_contributions
      : (progress.completed_commissions || 0);
    const earned = parseFloat(progress.cashback_amount_earned || progress.total_earned || '0.00');
    const billingId = progress.current_billing_id || null;
    const isCompleted = Boolean(progress.is_completed || cycleStatus === 'COMPLETED');
    const isWithdrawable = Boolean(progress.is_withdrawable);
    const withdrawalStatus = progress.withdrawal_status || null;

    // Server-provided bulb states as the source of truth (safe fallback if missing/invalid)
    let bulbStates = progress.bulb_states;
    if (!Array.isArray(bulbStates) || bulbStates.length !== 48) {
      const countOn = Math.min(48, Math.max(0, completedCount * 3));
      bulbStates = Array.from({ length: 48 }, (_, i) => i < countOn);
    }

    // 1. Status Badge
    if (statusBadgeEl) {
      statusBadgeEl.className = 'queue-badge';
      if (cycleStatus === 'ACTIVE') {
        statusBadgeEl.classList.add('active');
        statusBadgeEl.textContent = billingId ? `Active Cycle (${billingId})` : 'Active Cycle';
      } else if (cycleStatus === 'COMPLETED') {
        statusBadgeEl.classList.add('completed');
        statusBadgeEl.textContent = 'Cycle Completed (48 Bulbs)';
      } else if (cycleStatus === 'WAITING') {
        statusBadgeEl.classList.add('waiting');
        statusBadgeEl.textContent = billingId ? `Waiting in Queue (${billingId})` : 'Waiting in Queue';
      } else {
        statusBadgeEl.classList.add('not_enrolled');
        statusBadgeEl.textContent = 'No Active Cycle';
      }
    }

    // 2. Beneficiary Message Text
    if (statusMessageBox && statusMessageTextEl) {
      statusMessageBox.className = 'beneficiary-status-message';
      if (cycleStatus === 'ACTIVE') {
        statusMessageBox.classList.add('active-notice');
        statusMessageTextEl.innerHTML = `
          <strong>You are the current active cycle beneficiary!</strong>
          Billing ID: <code>${escapeHtml(billingId || 'Active')}</code>. Every eligible Power Bank purchase illuminates 3 bulbs and credits ₹250.00 to your cashback balance.
        `;
      } else if (cycleStatus === 'COMPLETED') {
        statusMessageBox.classList.add('completed-notice');
        statusMessageTextEl.innerHTML = `
          <strong>Cycle Target Completed (₹4,000.00)!</strong>
          All 48 bulbs have been illuminated. Your accumulated cashback is fully earned.
        `;
      } else if (cycleStatus === 'WAITING') {
        statusMessageBox.classList.add('notice');
        statusMessageTextEl.innerHTML = `
          <strong>Your order is enrolled in the queue!</strong>
          Billing ID: <code>${escapeHtml(billingId || 'Enrolled')}</code>. As earlier cycles complete, your cycle will automatically become active.
        `;
      } else {
        statusMessageBox.classList.add('notice');
        statusMessageTextEl.innerHTML = `
          <strong>No active cashback cycle.</strong>
          Purchase an eligible Power Bank to enroll in Plan A and generate a new 48-bulb cashback cycle!
        `;
      }
    }

    // Calculate illuminated bulb count
    const illuminatedBulbs = bulbStates ? bulbStates.filter(Boolean).length : (completedCount * 3);

    // Update clean progress summary in section header
    const cleanSummaryEl = document.getElementById('cashback-progress-summary');
    if (cleanSummaryEl) {
      cleanSummaryEl.textContent = `Progress: ${illuminatedBulbs}/48 Bulbs` + ` (${completedCount}/16 Contributions)`;
    }

    // 3. Render 48 Bulbs from Server bulb_states
    if (bulbsContainer) {
      let bulbsHtml = '';
      for (let i = 0; i < 48; i++) {
        const bulbNum = i + 1;
        const isOn = Boolean(bulbStates[i]);
        const isPulse = (cycleStatus === 'ACTIVE' && i === completedCount * 3 && !isCompleted);

        let milestoneClass = '';
        let milestoneTag = '';
        if (bulbNum === 9) {
          milestoneClass = 'milestone milestone-9';
          milestoneTag = ''; // Removed ₹750 label per Option A specification
        } else if (bulbNum === 24) {
          milestoneClass = 'milestone milestone-24';
          milestoneTag = '<span class="bulb-tag">₹2,000</span>';
        } else if (bulbNum === 48) {
          milestoneClass = 'milestone milestone-48';
          milestoneTag = '<span class="bulb-tag">₹4,000</span>';
        }

        const completedTagClass = isOn ? 'completed' : '';

        // Clean lightbulb SVG icon without raw numbers
        const bulbSvg = `
          <svg class="bulb-icon-svg ${isOn ? 'lit' : 'unlit'}" viewBox="0 0 24 24" fill="${isOn ? '#F59E0B' : 'none'}" stroke="${isOn ? '#D97706' : '#94A3B8'}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
            <path d="M9 18h6"></path>
            <path d="M10 22h4"></path>
            <path d="M12 2a7 7 0 0 0-7 7c0 2.5 1.5 4.5 3 6h8c1.5-1.5 3-3.5 3-6a7 7 0 0 0-7-7z"></path>
          </svg>
        `;

        bulbsHtml += `
          <div class="bulb-slot ${milestoneClass} ${completedTagClass}" title="Bulb ${bulbNum}: ${isOn ? 'Illuminated (Earned)' : 'Unlit (Pending)'}">
            <div class="bulb-indicator ${isOn ? 'bulb-on' : 'bulb-off'} ${isPulse ? 'bulb-pulse' : ''}" aria-label="Bulb ${bulbNum} ${isOn ? 'Illuminated' : 'Unlit'}">
              ${bulbSvg}
            </div>
            ${milestoneTag}
          </div>
        `;
      }
      bulbsContainer.innerHTML = bulbsHtml;
    }

    // 4. Progress Bar & Stats
    const percent = Math.min(100, Math.round((completedCount / 16) * 100));
    if (progressBarFill) {
      progressBarFill.style.width = `${percent}%`;
    }
    if (progressStatsEl) {
      progressStatsEl.textContent = `Progress: ${illuminatedBulbs}/48 Bulbs (${completedCount}/16 Contributions)`;
    }

    // 5. Milestone Cards State
    if (milestoneCard9) {
      if (illuminatedBulbs >= 9) milestoneCard9.classList.add('reached');
      else milestoneCard9.classList.remove('reached');
    }
    if (milestoneCard24) {
      if (illuminatedBulbs >= 24) milestoneCard24.classList.add('reached');
      else milestoneCard24.classList.remove('reached');
    }
    if (milestoneCard48) {
      if (illuminatedBulbs >= 48) milestoneCard48.classList.add('reached');
      else milestoneCard48.classList.remove('reached');
    }

    // 6. Plan A Cycle Withdrawal Banner State
    if (bannerBox && bannerTitle && bannerDesc && withdrawActionBtn) {
      bannerBox.className = 'plan-a-withdrawal-banner';

      if (withdrawalStatus === 'REQUESTED' || withdrawalStatus === 'PENDING') {
        bannerBox.classList.add('withdrawn');
        bannerTitle.textContent = 'Withdrawal Under Process';
        bannerDesc.textContent = 'Your simulated ₹4,000.00 withdrawal request has been received and is being processed.';
        withdrawActionBtn.disabled = true;
        withdrawActionBtn.textContent = 'Withdrawal Pending';
      } else if (withdrawalStatus === 'COMPLETED') {
        bannerBox.classList.add('withdrawn');
        bannerTitle.textContent = 'Cashback Fully Liquidated';
        bannerDesc.textContent = 'Your cycle payout of ₹4,000.00 has been completed and liquidated to your registered account.';
        withdrawActionBtn.disabled = true;
        withdrawActionBtn.textContent = 'Payout Completed';
      } else if (isWithdrawable) {
        bannerBox.classList.add('eligible');
        bannerTitle.textContent = 'Congratulations! ₹4,000.00 Ready for Withdrawal';
        bannerDesc.textContent = 'You have completed all 16 contributions (48 bulbs). Click below to request full liquidation.';
        withdrawActionBtn.disabled = false;
        withdrawActionBtn.textContent = 'Request ₹4,000.00 Withdrawal';
      } else {
        bannerTitle.textContent = 'Cashback Cycle in Progress';
        bannerDesc.textContent = 'Complete all 16 contributions to unlock your ₹4,000.00 cycle payout.';
        withdrawActionBtn.disabled = true;
        withdrawActionBtn.textContent = 'Unlock at 16 Contributions';
      }
    }
  }

  // -------------------------------------------------------------------------
  // Section 2B: Completed Cycles History
  // -------------------------------------------------------------------------
  function renderCompletedCycles(cycles) {
    const tableBody = document.getElementById('completed-cycles-table-body');
    if (!tableBody) return;

    if (!Array.isArray(cycles) || cycles.length === 0) {
      tableBody.innerHTML = `
        <tr>
          <td colspan="6" class="empty-state-box">
            No completed cycles recorded yet. Complete 16 contributions to graduate your first cycle.
          </td>
        </tr>
      `;
      return;
    }

    tableBody.innerHTML = cycles.map(c => {
      const isDone = Boolean(c.is_completed || c.status === 'COMPLETED');
      const statusBadge = isDone
        ? '<span class="badge badge-success">COMPLETED</span>'
        : '<span class="badge badge-primary">ACTIVE</span>';

      return `
        <tr>
          <td style="font-weight:700;">Cycle #${c.cycle_number || c.cycle_id}</td>
          <td>${c.completed_contributions} / 16</td>
          <td style="font-weight:600;color:var(--color-success);">${formatCurrency(c.total_earned)}</td>
          <td>${statusBadge}</td>
          <td style="font-size:var(--text-xs);color:var(--color-muted);">${formatDateTime(c.started_at)}</td>
          <td style="font-size:var(--text-xs);color:var(--color-muted);">${formatDateTime(c.completed_at)}</td>
        </tr>
      `;
    }).join('');
  }

  // -------------------------------------------------------------------------
  // Section 3: Dual Wallets, Ledgers & Simulated Withdrawals
  // -------------------------------------------------------------------------
  function switchWalletTab(tabName) {
    activeWalletTab = tabName;
    const tabButtons = document.querySelectorAll('.wallet-tab-btn');
    tabButtons.forEach(btn => {
      if (btn.getAttribute('data-tab') === tabName) {
        btn.classList.add('active');
      } else {
        btn.classList.remove('active');
      }
    });

    const views = document.querySelectorAll('.wallet-view');
    views.forEach(view => {
      if (view.id === `wallet-view-${tabName}`) {
        view.classList.add('active');
      } else {
        view.classList.remove('active');
      }
    });
  }

  async function loadWalletViews() {
    // 1. Direct Referral View
    await loadDirectReferralWallet();

    // 2. Sequential Commission View
    await loadSequentialCommissionWallet();
  }

  async function loadDirectReferralWallet() {
    const balEl = document.getElementById('dr-wallet-balance');
    const withdrawBtn = document.getElementById('dr-withdraw-btn');
    const noteEl = document.getElementById('dr-eligibility-note');
    const tableBody = document.getElementById('dr-transactions-body');
    const withdrawalsBody = document.getElementById('dr-withdrawals-body');

    const drBalance = parseFloat(earningsData?.direct_referral_balance || '0.00');
    const drEligible = Boolean(earningsData?.withdrawal_eligibility?.direct_referral_eligible);

    if (balEl) balEl.textContent = formatCurrency(drBalance);

    if (withdrawBtn) {
      withdrawBtn.disabled = !drEligible;
      withdrawBtn.textContent = drEligible
        ? `Withdraw All Direct Referral Funds (${formatCurrency(drBalance)})`
        : 'Withdraw All Direct Referral Funds';
      withdrawBtn.onclick = () => openWithdrawModal('direct_referral', drBalance);
    }

    if (noteEl) {
      if (drEligible) {
        noteEl.innerHTML = `
          <span class="badge badge-success">Eligible for Full Liquidation</span>
          <span style="color:var(--color-muted);">Balance meets or exceeds the minimum ₹700 threshold.</span>
        `;
      } else {
        noteEl.innerHTML = `
          <span class="badge badge-subtle">Minimum Withdrawal: ₹700</span>
          <span style="color:var(--color-muted);">Minimum withdrawal balance is ₹700.</span>
        `;
      }
    }

    // Load DR Transactions Ledger
    try {
      const txRes = await window.ShopEasyWallets.getTransactions({
        wallet_type: 'direct_referral',
        page: 1,
        page_size: 50,
      });

      if (tableBody) {
        if (!txRes || !txRes.items || txRes.items.length === 0) {
          tableBody.innerHTML = `
            <tr>
              <td colspan="6" class="empty-state-box">
                No ledger transactions found for Direct Referral Wallet.
              </td>
            </tr>
          `;
        } else {
          tableBody.innerHTML = txRes.items.map(tx => {
            const isCredit = tx.transaction_type === 'credit';
            const sign = isCredit ? '+' : '-';
            const amountClass = isCredit ? 'credit' : 'debit';
            return `
              <tr>
                <td>${formatDateTime(tx.created_at)}</td>
                <td><span class="badge ${isCredit ? 'badge-success' : 'badge-danger'}">${tx.transaction_type.toUpperCase()}</span></td>
                <td>${formatReference(tx.reference_type, tx.reference_id)}</td>
                <td class="tx-amount ${amountClass}">${sign}${formatCurrency(tx.amount)}</td>
                <td style="font-weight:600;">${formatCurrency(tx.balance_after)}</td>
                <td style="font-family:var(--font-mono);font-size:11px;color:var(--color-muted);">${tx.idempotency_key || `TX-${tx.id}`}</td>
              </tr>
            `;
          }).join('');
        }
      }
    } catch (err) {
      if (tableBody) {
        tableBody.innerHTML = `
          <tr>
            <td colspan="6" style="color:var(--color-danger);text-align:center;padding:var(--space-4);">
              Failed to load transactions.
            </td>
          </tr>
        `;
      }
    }

    // Load DR Withdrawals
    try {
      const wdRes = await window.ShopEasyWallets.getWithdrawals({
        wallet_type: 'direct_referral',
        page: 1,
        page_size: 50,
      });

      if (withdrawalsBody) {
        if (!wdRes || !wdRes.items || wdRes.items.length === 0) {
          withdrawalsBody.innerHTML = `
            <tr>
              <td colspan="5" class="empty-state-box">
                No withdrawal records found for Direct Referral Wallet.
              </td>
            </tr>
          `;
        } else {
          withdrawalsBody.innerHTML = wdRes.items.map(w => `
            <tr>
              <td>${formatDateTime(w.requested_at)}</td>
              <td style="font-weight:600;">${formatCurrency(w.amount)}</td>
              <td><span class="badge badge-success">${w.status.toUpperCase()}</span></td>
              <td style="font-family:var(--font-mono);font-size:11px;">${w.idempotency_key}</td>
              <td>${formatDateTime(w.completed_at)}</td>
            </tr>
          `).join('');
        }
      }
    } catch (err) {
      if (withdrawalsBody) {
        withdrawalsBody.innerHTML = `
          <tr>
            <td colspan="5" style="color:var(--color-danger);text-align:center;padding:var(--space-4);">
              Failed to load withdrawals.
            </td>
          </tr>
        `;
      }
    }
  }

  async function loadSequentialCommissionWallet() {
    const balEl = document.getElementById('sc-wallet-balance');
    const activeEarnedEl = document.getElementById('sc-active-cycle-earnings');
    const cycleBadgeEl = document.getElementById('sc-cycle-badge');
    const cyclePendingTextEl = document.getElementById('sc-cycle-pending-text');
    const contribsBody = document.getElementById('sc-contributions-body');
    const contribsSummaryBadge = document.getElementById('sc-contributions-summary-badge');
    const withdrawBtn = document.getElementById('sc-withdraw-btn');
    const noteEl = document.getElementById('sc-eligibility-note');
    const tableBody = document.getElementById('sc-transactions-body');
    const withdrawalsBody = document.getElementById('sc-withdrawals-body');

    const scBalance = parseFloat(earningsData?.sequential_commission_balance ?? cashbackProgress?.current_wallet_balance ?? '0.00');
    const scEligible = Boolean(earningsData?.withdrawal_eligibility?.sequential_commission_eligible || cashbackProgress?.is_withdrawable);
    const completedContributions = typeof cashbackProgress?.completed_contributions === 'number'
      ? cashbackProgress.completed_contributions
      : (earningsData?.sequential_progress?.completed_commissions || 0);
    const completedBulbs = typeof cashbackProgress?.bulbs_on === 'number'
      ? cashbackProgress.bulbs_on
      : Math.min(48, completedContributions * 3);
    const activeCycleEarned = parseFloat(cashbackProgress?.active_cycle_earnings ?? cashbackProgress?.cashback_amount_earned ?? earningsData?.sequential_progress?.total_earned ?? '0.00');
    const remainingContribs = Math.max(0, 16 - completedContributions);
    const remainingAmount = Math.max(0, 4000 - activeCycleEarned);
    const isCompleted = Boolean(cashbackProgress?.is_completed || completedContributions >= 16 || scBalance >= 4000);

    // 1. Available Balance (Withdrawable)
    if (balEl) balEl.textContent = formatCurrency(scBalance);

    // 2. Active Cycle Earnings (Pending Completion)
    if (activeEarnedEl) {
      activeEarnedEl.textContent = formatCurrency(activeCycleEarned);
    }
    const cycleNum = (progress && progress.current_cycle_number) ? progress.current_cycle_number : 1;
    if (cycleBadgeEl && cyclePendingTextEl) {
      if (isCompleted) {
        cycleBadgeEl.className = 'badge badge-success';
        cycleBadgeEl.textContent = `Cycle #${cycleNum}: 16/16 Completed (${completedBulbs}/48 bulbs)`;
        cyclePendingTextEl.textContent = `Full ${formatCurrency(4000)} cycle target earned`;
      } else if (completedContributions > 0) {
        cycleBadgeEl.className = 'badge badge-info';
        cycleBadgeEl.textContent = `Active Cycle #${cycleNum}: ${completedContributions}/16 Contributions (${completedBulbs}/48 bulbs)`;
        cyclePendingTextEl.textContent = `${formatCurrency(remainingAmount)} pending completion (${remainingContribs} contribution${remainingContribs === 1 ? '' : 's'} remaining)`;
      } else {
        cycleBadgeEl.className = 'badge badge-subtle';
        cycleBadgeEl.textContent = '0 / 16 Contributions (0/48 bulbs)';
        cyclePendingTextEl.textContent = 'No contributions accumulated yet';
      }
    }

    // 3. Withdrawal button
    if (withdrawBtn) {
      withdrawBtn.disabled = !scEligible;
      withdrawBtn.textContent = scEligible
        ? `Withdraw All Sequential Commission Funds (${formatCurrency(scBalance)})`
        : 'Withdraw All Sequential Commission Funds';
      withdrawBtn.onclick = () => openWithdrawModal('sequential_commission', scBalance);
    }

    // 4. Eligibility note
    if (noteEl) {
      if (scEligible) {
        noteEl.innerHTML = `
          <span class="badge badge-success">Eligible for Full Liquidation</span>
          <span style="color:var(--color-muted);">Cycle 16/16 (${completedBulbs}/48 bulbs) completed with ${formatCurrency(scBalance)} accumulated.</span>
        `;
      } else {
        noteEl.innerHTML = `
          <span class="badge badge-subtle">Requirement: 48/48 Cycle Completion</span>
          <span style="color:var(--color-muted);">${completedContributions} of 16 contributions (${completedBulbs}/48 bulbs) completed. Sequential wallet allows full withdrawal only upon complete cycle (${formatCurrency(4000)}).</span>
        `;
      }
    }

    // 5. Load Active Cycle / Plan A Contributions
    if (contribsBody) {
      try {
        let contributions = [];
        if (window.ShopEasyCashback && window.ShopEasyCashback.getContributions) {
          contributions = await window.ShopEasyCashback.getContributions();
        }
        if ((!contributions || contributions.length === 0) && cashbackProgress && cashbackProgress.active_contributions) {
          contributions = cashbackProgress.active_contributions;
        }

        const count = contributions ? contributions.length : 0;
        const totalContribAmt = count * 250;
        if (contribsSummaryBadge) {
          contribsSummaryBadge.textContent = `${count} / 16 Contributions (${formatCurrency(totalContribAmt)})`;
          if (count >= 16) {
            contribsSummaryBadge.className = 'badge badge-success';
          } else if (count > 0) {
            contribsSummaryBadge.className = 'badge badge-info';
          } else {
            contribsSummaryBadge.className = 'badge badge-subtle';
          }
        }

        if (!contributions || contributions.length === 0) {
          contribsBody.innerHTML = `
            <tr>
              <td colspan="6" class="empty-state-box">
                No contributions allocated to your active cashback cycle yet. Each eligible Power Bank purchase contributes ₹250.00.
              </td>
            </tr>
          `;
        } else {
          contribsBody.innerHTML = contributions.map((c, idx) => {
            const bNum = c.contributing_billing_number || `BID-${c.contributing_billing_id}`;
            const recipRef = c.recipient_reference || (c.recipient_billing_number ? `Cycle #${c.cycle_number || 1} (${c.recipient_billing_number})` : `Cycle #${c.cycle_number || 1}`);
            const dateStr = formatDateTime(c.created_at);
            const amt = parseFloat(c.amount || 250);
            return `
              <tr>
                <td style="font-weight:600;color:var(--color-muted);">${idx + 1}</td>
                <td>${dateStr}</td>
                <td><span class="billing-badge">${escapeHtml(bNum)}</span></td>
                <td style="font-size:12px;color:var(--color-text-secondary);">${escapeHtml(recipRef)}</td>
                <td class="tx-amount credit" style="font-weight:700;color:var(--color-success);">+${formatCurrency(amt)}</td>
                <td><span class="badge badge-success">${escapeHtml(c.status || 'ALLOCATED')}</span></td>
              </tr>
            `;
          }).join('');
        }
      } catch (cErr) {
        console.warn('Failed to load cashback contributions:', cErr);
        contribsBody.innerHTML = `
          <tr>
            <td colspan="6" class="empty-state-box" style="color:var(--color-danger);">
              Failed to load contributions history.
            </td>
          </tr>
        `;
      }
    }

    // 6. Load SC Transactions Ledger
    try {
      const txRes = await window.ShopEasyWallets.getTransactions({
        wallet_type: 'sequential_commission',
        page: 1,
        page_size: 50,
      });

      if (tableBody) {
        if (!txRes || !txRes.items || txRes.items.length === 0) {
          tableBody.innerHTML = `
            <tr>
              <td colspan="6" class="empty-state-box">
                No wallet ledger transactions yet. The full cycle credit of ${formatCurrency(4000)} will be credited here once all 16/16 contributions (48/48 bulbs) are completed. See individual ₹250 contributions in the Active Cycle Contribution Ledger above.
              </td>
            </tr>
          `;
        } else {
          tableBody.innerHTML = txRes.items.map(tx => {
            const isCredit = tx.transaction_type === 'credit';
            const sign = isCredit ? '+' : '-';
            const amountClass = isCredit ? 'credit' : 'debit';
            return `
              <tr>
                <td>${formatDateTime(tx.created_at)}</td>
                <td><span class="badge ${isCredit ? 'badge-success' : 'badge-danger'}">${tx.transaction_type.toUpperCase()}</span></td>
                <td>${formatReference(tx.reference_type, tx.reference_id)}</td>
                <td class="tx-amount ${amountClass}">${sign}${formatCurrency(tx.amount)}</td>
                <td style="font-weight:600;">${formatCurrency(tx.balance_after)}</td>
                <td style="font-family:var(--font-mono);font-size:11px;color:var(--color-muted);">${tx.idempotency_key || `TX-${tx.id}`}</td>
              </tr>
            `;
          }).join('');
        }
      }
    } catch (err) {
      if (tableBody) {
        tableBody.innerHTML = `
          <tr>
            <td colspan="6" style="color:var(--color-danger);text-align:center;padding:var(--space-4);">
              Failed to load transactions.
            </td>
          </tr>
        `;
      }
    }

    // Load SC Withdrawals
    try {
      const wdRes = await window.ShopEasyWallets.getWithdrawals({
        wallet_type: 'sequential_commission',
        page: 1,
        page_size: 50,
      });

      if (withdrawalsBody) {
        if (!wdRes || !wdRes.items || wdRes.items.length === 0) {
          withdrawalsBody.innerHTML = `
            <tr>
              <td colspan="5" class="empty-state-box">
                No withdrawal records found for Sequential Commission Wallet.
              </td>
            </tr>
          `;
        } else {
          withdrawalsBody.innerHTML = wdRes.items.map(w => `
            <tr>
              <td>${formatDateTime(w.requested_at)}</td>
              <td style="font-weight:600;">${formatCurrency(w.amount)}</td>
              <td><span class="badge badge-success">${w.status.toUpperCase()}</span></td>
              <td style="font-family:var(--font-mono);font-size:11px;">${w.idempotency_key}</td>
              <td>${formatDateTime(w.completed_at)}</td>
            </tr>
          `).join('');
        }
      }
    } catch (err) {
      if (withdrawalsBody) {
        withdrawalsBody.innerHTML = `
          <tr>
            <td colspan="5" style="color:var(--color-danger);text-align:center;padding:var(--space-4);">
              Failed to load withdrawals.
            </td>
          </tr>
        `;
      }
    }
  }

  // -------------------------------------------------------------------------
  // Simulated Withdrawal Modal Handling
  // -------------------------------------------------------------------------
  function openWithdrawModal(walletType, amount) {
    pendingWithdrawalType = walletType;
    const overlay = document.getElementById('withdraw-modal-overlay');
    const titleEl = document.getElementById('modal-wallet-title');
    const amountEl = document.getElementById('modal-withdraw-amount');

    const walletLabel = walletType === 'direct_referral'
      ? 'Direct Referral Wallet'
      : 'Sequential Commission Wallet';

    if (titleEl) titleEl.textContent = `Withdraw from ${walletLabel}`;
    if (amountEl) amountEl.textContent = formatCurrency(amount);

    if (overlay) {
      overlay.classList.add('open');
      overlay.setAttribute('aria-hidden', 'false');
    }
  }

  function closeWithdrawModal() {
    pendingWithdrawalType = null;
    const overlay = document.getElementById('withdraw-modal-overlay');
    if (overlay) {
      overlay.classList.remove('open');
      overlay.setAttribute('aria-hidden', 'true');
    }
  }

  async function executeWithdrawal() {
    if (!pendingWithdrawalType) return;

    const confirmBtn = document.getElementById('modal-confirm-btn');
    const cancelBtn = document.getElementById('modal-cancel-btn');

    if (confirmBtn) {
      confirmBtn.disabled = true;
      confirmBtn.textContent = 'Processing Withdrawal...';
    }
    if (cancelBtn) cancelBtn.disabled = true;

    // Generate unique client-side idempotency key
    const idempotencyKey = `WD-${Date.now()}-${Math.random().toString(36).substring(2, 10).toUpperCase()}`;

    try {
      const res = await window.ShopEasyWallets.withdraw({
        wallet_type: pendingWithdrawalType,
        idempotency_key: idempotencyKey,
      });

      closeWithdrawModal();
      if (typeof showToast === 'function') {
        showToast(`Withdrawal of ${formatCurrency(res.amount)} completed successfully!`);
      }

      // Live reload of dashboard, wallets, and ledgers
      await loadAllDashboardData();
    } catch (err) {
      console.error('Withdrawal failed:', err);
      if (typeof showToast === 'function') {
        showToast(err.detail || err.message || 'Withdrawal failed. Please try again.', 'error');
      }
    } finally {
      if (confirmBtn) {
        confirmBtn.disabled = false;
        confirmBtn.textContent = 'Confirm Full Withdrawal';
      }
      if (cancelBtn) cancelBtn.disabled = false;
    }
  }

  // -------------------------------------------------------------------------
  // Section 4: Referral Management
  // -------------------------------------------------------------------------
  function renderReferralManagement(data) {
    if (!data) return;

    const code = data.referral_code || currentCustomer?.referral_code || 'REF-PENDING';
    const codeDisplayEl = document.getElementById('referral-code-value');
    if (codeDisplayEl) codeDisplayEl.textContent = code;

    const totalRefEl = document.getElementById('referral-total-count');
    if (totalRefEl) totalRefEl.textContent = data.total_referrals || 0;

    const successRefEl = document.getElementById('referral-success-count');
    if (successRefEl) successRefEl.textContent = data.successful_referrals || 0;

    const earningsRefEl = document.getElementById('referral-total-earned');
    if (earningsRefEl) earningsRefEl.textContent = formatCurrency(data.total_referral_earnings || 0);

    const tableBody = document.getElementById('referred-users-body');
    if (tableBody) {
      if (!data.referred_users || data.referred_users.length === 0) {
        tableBody.innerHTML = `
          <tr>
            <td colspan="5" class="empty-state-box">
              No referred friends yet. Share your referral link above to earn ₹750 on every friend's first qualified purchase!
            </td>
          </tr>
        `;
      } else {
        tableBody.innerHTML = data.referred_users.map(u => {
          const hasPurchased = u.has_purchased;
          const statusBadge = hasPurchased
            ? '<span class="badge badge-success">First Purchase Completed</span>'
            : '<span class="badge badge-subtle">Pending First Purchase</span>';
          const purchaseDate = u.first_purchase_at ? formatDateTime(u.first_purchase_at) : '—';
          const rewardText = formatCurrency(u.reward_earned);

          return `
            <tr>
              <td style="font-weight:600;">${escapeHtml(u.full_name)}</td>
              <td style="font-family:var(--font-mono);font-size:var(--text-xs);">${escapeHtml(u.phone_masked)}</td>
              <td>${statusBadge}</td>
              <td style="font-size:var(--text-xs);color:var(--color-muted);">${purchaseDate}</td>
              <td style="font-weight:700;color:${hasPurchased ? 'var(--color-success)' : 'var(--color-muted)'};">${rewardText}</td>
            </tr>
          `;
        }).join('');
      }
    }
  }

  // -------------------------------------------------------------------------
  // Clipboard Actions
  // -------------------------------------------------------------------------
  function copyReferralCode() {
    const codeEl = document.getElementById('referral-code-value');
    const code = codeEl ? codeEl.textContent.trim() : '';
    if (!code || code === 'REF-PENDING') {
      if (typeof showToast === 'function') showToast('No referral code available.', 'error');
      return;
    }

    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(code).then(() => {
        if (typeof showToast === 'function') showToast('Referral code copied to clipboard!');
      }).catch(() => {
        fallbackCopy(code);
      });
    } else {
      fallbackCopy(code);
    }
  }

  function copyShareLink() {
    const codeEl = document.getElementById('referral-code-value');
    const code = codeEl ? codeEl.textContent.trim() : '';
    if (!code || code === 'REF-PENDING') {
      if (typeof showToast === 'function') showToast('No referral code available.', 'error');
      return;
    }

    const shareUrl = `${window.location.origin}/login.html?ref=${encodeURIComponent(code)}`;
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(shareUrl).then(() => {
        if (typeof showToast === 'function') showToast('Referral share link copied to clipboard!');
      }).catch(() => {
        fallbackCopy(shareUrl);
      });
    } else {
      fallbackCopy(shareUrl);
    }
  }

  function fallbackCopy(text) {
    const textarea = document.createElement('textarea');
    textarea.value = text;
    textarea.style.position = 'fixed';
    textarea.style.opacity = '0';
    document.body.appendChild(textarea);
    textarea.select();
    try {
      document.execCommand('copy');
      if (typeof showToast === 'function') showToast('Copied to clipboard!');
    } catch (e) {
      if (typeof showToast === 'function') showToast(`Share text: ${text}`);
    }
    document.body.removeChild(textarea);
  }

  // -------------------------------------------------------------------------
  // Section 5: Customer Purchase History & Unit Billing IDs (OR-12)
  // -------------------------------------------------------------------------
  async function loadPurchaseHistory() {
    const container = document.getElementById('purchase-history-container');
    if (!container) return;

    container.innerHTML = `
      <div class="empty-state-box" style="padding:var(--space-8);text-align:center;color:var(--color-muted);">
        <div class="spinner" style="width:24px;height:24px;border:2px solid var(--color-border);border-top-color:var(--color-primary);border-radius:50%;animation:spin 0.8s linear infinite;margin:0 auto var(--space-2);"></div>
        Loading your purchase history...
      </div>
    `;

    try {
      if (!window.ShopEasyOrders || typeof window.ShopEasyOrders.list !== 'function') {
        throw new Error('Orders service is unavailable.');
      }
      const response = await window.ShopEasyOrders.list();
      const orders = (response && response.items) ? response.items : (Array.isArray(response) ? response : []);
      renderPurchaseHistoryTable(orders, container);
    } catch (err) {
      console.error('Failed to load purchase history:', err);
      container.innerHTML = `
        <div class="empty-state-box" style="padding:var(--space-6);text-align:center;">
          <p style="color:var(--color-danger);font-size:var(--text-sm);margin-bottom:var(--space-3);">
            ${escapeHtml(err.detail || err.message || 'Unable to load purchase history. Please verify your connection.')}
          </p>
          <button type="button" class="btn btn-secondary btn-sm" onclick="window.retryLoadPurchaseHistory()">
            Retry
          </button>
        </div>
      `;
    }
  }

  function renderPurchaseHistoryTable(orders, container) {
    if (!orders || orders.length === 0) {
      container.innerHTML = `
        <div class="empty-state-box" style="padding:var(--space-8);text-align:center;">
          <p style="color:var(--color-muted);margin-bottom:var(--space-3);">
            No purchases found. Placed orders and allocated unit Billing IDs will appear here.
          </p>
          <a href="products.html" class="btn btn-primary btn-sm">Explore Products</a>
        </div>
      `;
      return;
    }

    container.innerHTML = `
      <div style="display:flex;flex-direction:column;gap:var(--space-4);">
        ${orders.map(order => {
          const orderNum = order.order_number || (`#ORD-${order.id}`);
          const dateStr = formatDateTime(order.created_at);
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
                <div style="font-size:var(--text-xs);color:var(--color-muted);font-style:italic;">
                  No Billing ID issued (Payment ${escapeHtml(payLabel)})
                </div>
              `;
            } else if (itemBillingIds.length === 0) {
              billingContentHtml = `
                <div style="font-size:var(--text-xs);color:var(--color-muted);font-style:italic;">
                  Awaiting Billing ID allocation / Not provided by server
                </div>
              `;
            } else {
              billingContentHtml = `
                <div style="display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin-top:4px;">
                  ${itemBillingIds.map((bid, idx) => `
                    <div class="billing-id-pill" style="display:inline-flex;align-items:center;gap:6px;background:#F1F5F9;border:1px solid #CBD5E1;border-radius:var(--radius-md);padding:3px 8px;">
                      <span style="font-size:10px;font-weight:600;color:var(--color-muted);text-transform:uppercase;">Unit ${idx + 1}:</span>
                      <code style="font-size:var(--text-xs);font-weight:700;color:var(--color-primary);letter-spacing:0.04em;word-break:break-all;">${escapeHtml(bid)}</code>
                      <button type="button" class="btn btn-outline btn-xs" style="padding:1px 6px;font-size:10px;line-height:1.2;" onclick="copyBillingIdText('${escapeHtml(bid)}', this)">Copy</button>
                    </div>
                  `).join('')}
                </div>
              `;
            }

            return `
              <div style="padding:var(--space-3) 0;border-top:1px solid var(--color-border);display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:var(--space-2);">
                <div style="flex:1;min-width:200px;">
                  <div style="font-weight:600;font-size:var(--text-sm);color:var(--color-text);">${escapeHtml(item.product_name)}</div>
                  <div style="font-size:var(--text-xs);color:var(--color-muted);margin-top:2px;">
                    Quantity: ${qty} &times; ${unitPriceStr} = <strong>${lineTotalStr}</strong>
                  </div>
                  <div style="margin-top:6px;">
                    ${billingContentHtml}
                  </div>
                </div>
              </div>
            `;
          }).join('');

          return `
            <div class="card" style="background:#FFFFFF;border:1px solid var(--color-border);border-radius:var(--radius-lg);padding:var(--space-4);box-shadow:var(--shadow-sm);">
              <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:var(--space-2);margin-bottom:var(--space-3);">
                <div>
                  <div style="font-size:var(--text-xs);font-weight:700;color:var(--color-muted);text-transform:uppercase;letter-spacing:0.05em;">
                    Order Reference
                  </div>
                  <code style="font-size:var(--text-base);font-weight:700;color:var(--color-text);word-break:break-all;">
                    ${escapeHtml(orderNum)}
                  </code>
                </div>
                <div style="display:flex;align-items:center;gap:var(--space-2);flex-wrap:wrap;">
                  <span style="font-size:var(--text-xs);color:var(--color-muted);">${dateStr}</span>
                  <span style="background:${payBadgeBg};color:${payBadgeFg};padding:3px 8px;border-radius:9999px;font-size:11px;font-weight:600;">
                    ${payLabel}
                  </span>
                  <span style="font-size:var(--text-sm);font-weight:700;color:var(--color-text);">
                    ${totalStr}
                  </span>
                </div>
              </div>
              <div style="border-top:1px solid var(--color-border);padding-top:var(--space-1);">
                ${itemsHtml || '<p style="color:var(--color-muted);font-size:var(--text-xs);">No items in this order.</p>'}
              </div>
            </div>
          `;
        }).join('')}
      </div>
    `;
  }

  function copyBillingIdText(text, btnEl) {
    if (!text) return;
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(() => {
        if (btnEl) {
          const orig = btnEl.textContent;
          btnEl.textContent = 'Copied!';
          setTimeout(() => { btnEl.textContent = orig; }, 1500);
        }
      }).catch(() => {});
    }
  }

  // -------------------------------------------------------------------------
  // Utilities & Formatters
  // -------------------------------------------------------------------------
  function formatCurrency(val) {
    const num = parseFloat(val || 0);
    return '₹' + num.toLocaleString('en-IN', {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
  }

  function formatDateTime(isoString) {
    if (!isoString) return '—';
    try {
      const d = new Date(isoString);
      return d.toLocaleDateString('en-IN', {
        day: '2-digit',
        month: 'short',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
      });
    } catch (e) {
      return isoString;
    }
  }

  function formatReference(refType, refId) {
    if (!refType) return `REF #${refId || 0}`;
    const cleanType = String(refType).replace(/_/g, ' ').toUpperCase();
    return `${cleanType} #${refId || 0}`;
  }

  function escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  // Global window exports for inline attributes / triggers / testing
  window.copyReferralCode = copyReferralCode;
  window.copyShareLink = copyShareLink;
  window.switchWalletTab = switchWalletTab;
  window.openWithdrawModal = openWithdrawModal;
  window.closeWithdrawModal = closeWithdrawModal;
  window.renderPlanACashbackProgress = renderPlanACashbackProgress;
  window.loadPurchaseHistory = loadPurchaseHistory;
  window.retryLoadPurchaseHistory = loadPurchaseHistory;
  window.renderPurchaseHistoryTable = renderPurchaseHistoryTable;
  window.copyBillingIdText = copyBillingIdText;

})();
