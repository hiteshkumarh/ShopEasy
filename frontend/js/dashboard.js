/**
 * ShopEasy --- Customer Earnings & Wallets Dashboard Logic
 *
 * Handles:
 *  - Customer authentication guard via requireCustomerAuth().
 *  - Real-time fetching of earnings, beneficiary queue status, 16-circle progress.
 *  - Dual isolated wallets (Direct Referral & Sequential Commission).
 *  - Full-balance simulated withdrawals with client idempotency key generation.
 *  - Auditable transaction ledgers and withdrawal histories.
 *  - Referral code sharing and referee purchase tracking.
 */

(function () {
  'use strict';

  let currentCustomer = null;
  let earningsData = null;
  let referralData = null;
  let activeWalletTab = 'direct_referral';
  let pendingWithdrawalType = null;

  document.addEventListener('DOMContentLoaded', async () => {
    await initDashboard();
  });

  async function initDashboard() {
    try {
      currentCustomer = await window.requireCustomerAuth();
      if (!currentCustomer) return;

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
  }

  async function loadAllDashboardData() {
    try {
      // 1. Fetch Composite Earnings
      earningsData = await window.ShopEasyDashboard.getEarnings();
      renderEarningsSummary(earningsData);
      renderSequentialProgress(earningsData.sequential_progress);

      // 2. Fetch Referrals Summary
      referralData = await window.ShopEasyDashboard.getReferrals();
      renderReferralManagement(referralData);

      // 3. Load Wallets and Ledgers
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
    if (scWithdrawnEl) scWithdrawnEl.textContent = formatCurrency(data.sequential_commission_withdrawn);

    // Update customer greeting
    const userNameEl = document.getElementById('dashboard-customer-name');
    if (userNameEl && currentCustomer) {
      userNameEl.textContent = currentCustomer.full_name || 'Customer';
    }
  }

  // -------------------------------------------------------------------------
  // Section 2: Sequential Commission 16-Circle Progress Widget
  // -------------------------------------------------------------------------
  function renderSequentialProgress(progress) {
    const statusBadgeEl = document.getElementById('queue-status-badge');
    const statusMessageEl = document.getElementById('beneficiary-message-box');
    const circlesContainer = document.getElementById('circles-container');
    const progressBarFill = document.getElementById('progress-bar-fill');
    const progressStatsEl = document.getElementById('progress-bar-stats-text');

    if (!progress) return;

    const status = progress.status || 'not_enrolled';
    const completed = progress.completed_commissions || 0;
    const earned = parseFloat(progress.total_earned || '0.00');

    // 1. Status Badge
    if (statusBadgeEl) {
      statusBadgeEl.className = `queue-badge ${status}`;
      if (status === 'not_enrolled') {
        statusBadgeEl.textContent = 'Not Enrolled';
      } else if (status === 'waiting') {
        statusBadgeEl.textContent = progress.queue_position
          ? `In Queue (Position #${progress.queue_position})`
          : 'In Queue (Waiting)';
      } else if (status === 'active') {
        statusBadgeEl.textContent = 'Active Beneficiary';
      } else if (status === 'completed') {
        statusBadgeEl.textContent = 'Cycle Completed (16/16)';
      }
    }

    // 2. Beneficiary Message
    if (statusMessageEl) {
      if (status === 'not_enrolled') {
        statusMessageEl.className = 'beneficiary-status-message notice';
        statusMessageEl.innerHTML = `
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="10"></circle>
            <line x1="12" y1="8" x2="12" y2="12"></line>
            <line x1="12" y1="16" x2="12.01" y2="16"></line>
          </svg>
          <div>
            <strong>You are not the current beneficiary.</strong> You are not yet enrolled in the sequential beneficiary queue. Complete an eligible Power Bank purchase to enter the global FIFO queue.
          </div>
        `;
      } else if (status === 'waiting') {
        statusMessageEl.className = 'beneficiary-status-message notice';
        const posText = progress.queue_position ? `at position #${progress.queue_position}` : 'in the queue';
        statusMessageEl.innerHTML = `
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="10"></circle>
            <line x1="12" y1="8" x2="12" y2="12"></line>
            <line x1="12" y1="16" x2="12.01" y2="16"></line>
          </svg>
          <div>
            <strong>You are not the current beneficiary.</strong> You are currently waiting ${posText}. Once all earlier beneficiaries in the queue complete their 16 commissions, your cycle will automatically become active!
          </div>
        `;
      } else if (status === 'active') {
        statusMessageEl.className = 'beneficiary-status-message active-notice';
        statusMessageEl.innerHTML = `
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path>
            <polyline points="22 4 12 14.01 9 11.01"></polyline>
          </svg>
          <div>
            <strong>You are the current active beneficiary!</strong> Every eligible Power Bank purchase made by any customer across the platform credits ₹250 directly to your Sequential Commission Wallet.
          </div>
        `;
      } else if (status === 'completed') {
        statusMessageEl.className = 'beneficiary-status-message completed-notice';
        statusMessageEl.innerHTML = `
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path>
            <polyline points="22 4 12 14.01 9 11.01"></polyline>
          </svg>
          <div>
            <strong>Cycle Completed!</strong> Congratulations, you have completed your active beneficiary cycle of all 16 sequential commissions (₹4,000.00 earned). Your funds are available for full liquidation below.
          </div>
        `;
      }
    }

    // 3. Render 16 Circles
    if (circlesContainer) {
      const circleStates = progress.circle_states || [];
      let circlesHtml = '';

      for (let i = 0; i < 16; i++) {
        const isFilled = Boolean(circleStates[i]);
        const circleNumber = i + 1;
        const isCurrentActive = (status === 'active' && i === completed);

        circlesHtml += `
          <div class="circle-slot" title="Commission #${circleNumber}: ₹250.00 ${isFilled ? '(Received)' : '(Pending)'}">
            <div class="circle-disc ${isFilled ? 'filled' : ''} ${isCurrentActive ? 'pulse' : ''}">
              ${isFilled ? `
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3">
                  <polyline points="20 6 9 17 4 12"></polyline>
                </svg>
              ` : `<span>${circleNumber}</span>`}
            </div>
            <span class="circle-label">#${circleNumber}</span>
            <span class="circle-amount">₹250</span>
          </div>
        `;
      }
      circlesContainer.innerHTML = circlesHtml;
    }

    // 4. Progress Bar & Stats
    const percent = Math.min(100, Math.round((completed / 16) * 100));
    if (progressBarFill) {
      progressBarFill.style.width = `${percent}%`;
    }
    if (progressStatsEl) {
      progressStatsEl.textContent = `${completed} / 16 Commissions Completed (${formatCurrency(earned)} / ₹4,000.00)`;
    }
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
          <span style="color:var(--color-muted);">Balance meets or exceeds the minimum ₹750.00 threshold.</span>
        `;
      } else {
        noteEl.innerHTML = `
          <span class="badge badge-subtle">Threshold: ₹750.00</span>
          <span style="color:var(--color-muted);">Minimum withdrawal balance is ₹750.</span>
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
    const withdrawBtn = document.getElementById('sc-withdraw-btn');
    const noteEl = document.getElementById('sc-eligibility-note');
    const tableBody = document.getElementById('sc-transactions-body');
    const withdrawalsBody = document.getElementById('sc-withdrawals-body');

    const scBalance = parseFloat(earningsData?.sequential_commission_balance || '0.00');
    const scEligible = Boolean(earningsData?.withdrawal_eligibility?.sequential_commission_eligible);
    const completedComm = earningsData?.sequential_progress?.completed_commissions || 0;

    if (balEl) balEl.textContent = formatCurrency(scBalance);

    if (withdrawBtn) {
      withdrawBtn.disabled = !scEligible;
      withdrawBtn.textContent = scEligible
        ? `Withdraw All Sequential Commission Funds (${formatCurrency(scBalance)})`
        : 'Withdraw All Sequential Commission Funds';
      withdrawBtn.onclick = () => openWithdrawModal('sequential_commission', scBalance);
    }

    if (noteEl) {
      if (scEligible) {
        noteEl.innerHTML = `
          <span class="badge badge-success">Eligible for Full Liquidation</span>
          <span style="color:var(--color-muted);">Cycle 16/16 completed with ₹4,000.00 accumulated.</span>
        `;
      } else {
        noteEl.innerHTML = `
          <span class="badge badge-subtle">Requirement: 16/16 Cycle Completion</span>
          <span style="color:var(--color-muted);">${completedComm} of 16 commissions completed. Sequential wallet allows full withdrawal only upon complete cycle (₹4,000.00).</span>
        `;
      }
    }

    // Load SC Transactions Ledger
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
                No ledger transactions found for Sequential Commission Wallet.
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

  // Global window exports for inline attributes / triggers
  window.copyReferralCode = copyReferralCode;
  window.copyShareLink = copyShareLink;
  window.switchWalletTab = switchWalletTab;
  window.openWithdrawModal = openWithdrawModal;
  window.closeWithdrawModal = closeWithdrawModal;

})();
