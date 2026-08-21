import logging
from typing import Optional
from app.models import PrescriptionExtraction, VerificationResult
from app.config import settings
from app.blueprints.base import BlueprintConfig
from app.blueprints.loader import get_active_blueprint

logger = logging.getLogger(__name__)


def determine_approval_status(
    extraction: PrescriptionExtraction,
    verification: Optional[VerificationResult] = None,
    blueprint: Optional[BlueprintConfig] = None,
) -> tuple[str, str]:
    """Determine the approval status for an incoming order dynamically across blueprints.
    
    Returns:
        (status, explanation) where status is one of:
        - "Needs Human" — unparseable / low confidence
        - "Auto-Approved" — high confidence, standard item, low risk/value
        - "Needs Approval" — requires manager/optometrist review in Notion
    """
    bp = blueprint or get_active_blueprint()
    rules = bp.gating_rules
    confidence = extraction.confidence
    
    # If verification found contradictions, revise confidence downward
    if verification and verification.has_mismatches:
        confidence = min(confidence, verification.revised_confidence)
    
    value = extraction.estimated_value or 0.0
    
    # Gate 1: Garbage / unparseable input
    if confidence <= 0.2:
        explanation = f"Needs Human — very low confidence ({confidence:.2f}). Could not reliably extract data."
        if extraction.explanation:
            explanation += f" AI note: {extraction.explanation}"
        logger.info(f"Order routed to Needs Human (confidence={confidence:.2f})")
        return "Needs Human", explanation

    # Gate 2: Check category risk
    is_complex_category = False
    category_val = "standard"
    if rules.gated_category_field:
        raw_cat = extraction.get_field_value(rules.gated_category_field)
        if raw_cat:
            category_val = str(raw_cat).lower().strip()
            for gated in rules.gated_categories:
                if gated.lower() in category_val:
                    is_complex_category = True
                    break

    # Gate 3: Auto-approve conditions
    is_high_confidence = confidence >= rules.min_confidence
    is_low_value = value <= rules.max_auto_approve_value if rules.max_auto_approve_value > 0 else True
    no_mismatches = not (verification and verification.has_mismatches)

    if is_high_confidence and not is_complex_category and is_low_value and no_mismatches:
        explanation = f"Auto-Approved — high confidence ({confidence:.2f}), standard {category_val}"
        if value > 0:
            explanation += f", estimated {bp.currency_symbol}{value:.0f}"
        explanation += f". {extraction.explanation}"
        logger.info(f"Order auto-approved ({bp.id}): confidence={confidence:.2f}, val={value}")
        return "Auto-Approved", explanation

    # Gate 4: Needs Human Review / Approval
    reasons = []
    if not is_high_confidence:
        reasons.append(f"confidence {confidence:.2f}")
    if is_complex_category:
        reasons.append(f"requires review for {category_val}")
    if not is_low_value:
        reasons.append(f"value {bp.currency_symbol}{value:.0f} exceeds auto threshold")
    if verification and verification.has_mismatches:
        reasons.append(f"contradiction flagged: {', '.join(verification.mismatch_details[:2])}")

    explanation = f"Needs Approval — {', '.join(reasons)}. {extraction.explanation}"
    logger.info(f"Order needs approval ({bp.id}): {', '.join(reasons)}")
    return "Needs Approval", explanation
