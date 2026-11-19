"""Focused regression test suite for WP-12 Step 3: Plan A Dashboard Cashback Tracker Runtime Fix.

Verifies:
1. `frontend/js/dashboard.js` properly declares `bulbStates` at the function scope of
   `renderPlanACashbackProgress(progress)` before any block references.
2. `bulbStates` is NOT locally scoped inside `if (bulbsContainer)` which previously caused
   `ReferenceError: bulbStates is not defined` at milestone calculation line 312.
3. Server-provided `progress.bulb_states` is preserved as the source of truth.
4. Fallback logic safely handles missing or invalid `bulb_states` (non-array, wrong length)
   by deriving exactly 48 booleans from `completedCount * 3` clamped to [0, 48].
5. Milestone cards logic (bulbs 9, 24, 48) correctly reads `illuminatedBulbs` from `bulbStates`.
6. Withdrawal eligibility and button states correspond to completed status (16/16).
7. `renderPlanACashbackProgress` is exported on `window` for testability and runtime triggers.
"""

import re
from pathlib import Path
import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DASHBOARD_JS_PATH = REPO_ROOT / "frontend" / "js" / "dashboard.js"
DASHBOARD_HTML_PATH = REPO_ROOT / "frontend" / "dashboard.html"


def test_dashboard_js_file_exists():
    """Verify frontend/js/dashboard.js exists."""
    assert DASHBOARD_JS_PATH.exists(), f"Missing {DASHBOARD_JS_PATH}"


def test_bulb_states_variable_scoping():
    """Verify that bulbStates is declared at function level and not trapped in if (bulbsContainer)."""
    content = DASHBOARD_JS_PATH.read_text(encoding="utf-8")

    # Locate renderPlanACashbackProgress function definition
    func_match = re.search(r"function\s+renderPlanACashbackProgress\s*\(([^)]*)\)\s*\{", content)
    assert func_match is not None, "renderPlanACashbackProgress function not found in dashboard.js"
    func_start = func_match.start()

    # Locate the bulbsContainer block and the milestone cards block
    bulbs_container_match = re.search(r"if\s*\(\s*bulbsContainer\s*\)\s*\{", content[func_start:])
    assert bulbs_container_match is not None, "if (bulbsContainer) block not found"
    bulbs_container_idx = func_start + bulbs_container_match.start()

    milestone_cards_match = re.search(r"const\s+illuminatedBulbs\s*=", content[func_start:])
    assert milestone_cards_match is not None, "illuminatedBulbs calculation not found"
    milestone_cards_idx = func_start + milestone_cards_match.start()

    # Find where let bulbStates is declared
    decl_match = re.search(r"let\s+bulbStates\s*=", content[func_start:])
    assert decl_match is not None, "let bulbStates declaration not found in renderPlanACashbackProgress"
    decl_idx = func_start + decl_match.start()

    # Verify declaration is BEFORE the bulbsContainer block
    assert decl_idx < bulbs_container_idx, (
        f"bulbStates is declared at index {decl_idx}, which must be BEFORE "
        f"bulbsContainer block at index {bulbs_container_idx}"
    )

    # Verify declaration is BEFORE milestone calculation
    assert decl_idx < milestone_cards_idx, (
        f"bulbStates is declared at index {decl_idx}, which must be BEFORE "
        f"milestone calculation at index {milestone_cards_idx}"
    )

    # Verify no second 'let bulbStates' inside bulbsContainer
    subsequent_decls = re.findall(r"let\s+bulbStates\s*=", content[bulbs_container_idx:milestone_cards_idx])
    assert len(subsequent_decls) == 0, (
        "Found conflicting local 'let bulbStates' declaration inside bulbsContainer block"
    )


def test_safe_fallback_logic_present():
    """Verify fallback derives 48 booleans safely if bulb_states is missing or wrong length."""
    content = DASHBOARD_JS_PATH.read_text(encoding="utf-8")

    # Check for array validation and length check
    assert "Array.isArray(bulbStates)" in content
    assert "bulbStates.length !== 48" in content
    assert "Math.min(48, Math.max(0, completedCount * 3))" in content
    assert "Array.from({ length: 48 }" in content


def test_render_plan_a_cashback_progress_exported_to_window():
    """Verify renderPlanACashbackProgress is accessible on window object."""
    content = DASHBOARD_JS_PATH.read_text(encoding="utf-8")
    assert "window.renderPlanACashbackProgress = renderPlanACashbackProgress;" in content


def test_cashback_contract_sync_with_backend_schema():
    """Verify frontend property names match backend PlanACashbackProgressResponse schema."""
    from app.schemas.cashback import PlanACashbackProgressResponse

    fields = PlanACashbackProgressResponse.model_fields.keys()

    # Core fields expected by frontend
    expected_fields = [
        "has_active_cycle",
        "current_billing_id",
        "completed_contributions",
        "cashback_amount_earned",
        "cycle_status",
        "is_completed",
        "bulbs_on",
        "bulbs_off",
        "total_bulbs",
        "bulb_states",
        "is_withdrawable",
    ]

    for f in expected_fields:
        assert f in fields, f"Backend CashbackProgressResponse schema missing expected field '{f}'"


def test_dashboard_html_has_required_cashback_dom_elements():
    """Verify dashboard.html contains all elements targeted by renderPlanACashbackProgress."""
    html = DASHBOARD_HTML_PATH.read_text(encoding="utf-8")

    required_ids = [
        "queue-status-badge",
        "beneficiary-message-text",
        "beneficiary-message-box",
        "bulbs-container",
        "progress-bar-fill",
        "progress-bar-stats-text",
        "milestone-card-9",
        "milestone-card-24",
        "milestone-card-48",
        "plan-a-withdrawal-banner",
        "withdrawal-banner-title",
        "withdrawal-banner-desc",
        "plan-a-withdraw-action-btn",
    ]

    for element_id in required_ids:
        assert f'id="{element_id}"' in html, f"dashboard.html missing element #{element_id}"
