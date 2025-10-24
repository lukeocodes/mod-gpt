"""Seed global fraud heuristics into the database.

This script populates the heuristic_rules table with universal fraud patterns
that apply to ALL guilds (guild_id=NULL). These are well-known scam patterns
that every Discord server benefits from detecting.

Run this on bot startup or as a one-time migration.
"""

from typing import Any, Dict, List

# Global fraud heuristics - apply to all guilds
GLOBAL_FRAUD_HEURISTICS: List[Dict[str, Any]] = [
    # Free Nitro scams (very common)
    {
        "rule_type": "fraud_scam",
        "pattern": r"free[\s_\-]*(discord[\s_\-]*)?nitro",
        "pattern_type": "regex",
        "confidence": 0.95,
        "severity": "high",
        "reason": "Common Discord Nitro scam pattern - 'free nitro' is almost always fraudulent",
    },
    # Free game currency scams
    {
        "rule_type": "fraud_scam",
        "pattern": r"free[\s_\-]*(steam|robux|vbucks|v-bucks)",
        "pattern_type": "regex",
        "confidence": 0.92,
        "severity": "high",
        "reason": "Common gaming scam offering free virtual currency",
    },
    # Generic free cryptocurrency scam
    {
        "rule_type": "fraud_scam",
        "pattern": r"free[\s_\-]*(crypto|bitcoin|btc|eth|ethereum)",
        "pattern_type": "regex",
        "confidence": 0.90,
        "severity": "high",
        "reason": "Cryptocurrency giveaway scam pattern",
    },
    # Claim/win free items (urgency tactics)
    {
        "rule_type": "fraud_scam",
        "pattern": r"(claim|get|win)[\s_\-]*free",
        "pattern_type": "regex",
        "confidence": 0.85,
        "severity": "medium",
        "reason": "Urgency-based scam language encouraging immediate action",
    },
    # Double your money scam
    {
        "rule_type": "fraud_scam",
        "pattern": r"double[\s_\-]*your[\s_\-]*(money|crypto|bitcoin)",
        "pattern_type": "regex",
        "confidence": 0.95,
        "severity": "critical",
        "reason": "Classic investment scam promise - 'double your money' is always fraudulent",
    },
    # URL shorteners (often used to hide phishing links)
    {
        "rule_type": "fraud_link",
        "pattern": r"(?:https?://)?(?:www\.)?(bit\.ly|tinyurl\.com|is\.gd|goo\.gl|ow\.ly|buff\.ly)",
        "pattern_type": "regex",
        "confidence": 0.70,
        "severity": "medium",
        "reason": "URL shortener - often used to hide malicious links (may be legitimate, needs LLM context)",
    },
    # Phishing - click this link
    {
        "rule_type": "fraud_phishing",
        "pattern": "click this link",
        "pattern_type": "contains",
        "confidence": 0.80,
        "severity": "medium",
        "reason": "Common phishing tactic - suspicious call to action",
    },
    # Phishing - click here
    {
        "rule_type": "fraud_phishing",
        "pattern": "click here",
        "pattern_type": "contains",
        "confidence": 0.75,
        "severity": "medium",
        "reason": "Generic phishing language (may be legitimate, needs context)",
    },
    # Phishing - claim your free
    {
        "rule_type": "fraud_phishing",
        "pattern": "claim your free",
        "pattern_type": "contains",
        "confidence": 0.88,
        "severity": "high",
        "reason": "Phishing/scam language offering free items",
    },
    # Urgency tactics - limited time
    {
        "rule_type": "fraud_urgency",
        "pattern": "limited time offer",
        "pattern_type": "contains",
        "confidence": 0.70,
        "severity": "low",
        "reason": "Urgency tactic common in scams (may be legitimate marketing)",
    },
    # Urgency tactics - act now
    {
        "rule_type": "fraud_urgency",
        "pattern": "act now",
        "pattern_type": "contains",
        "confidence": 0.72,
        "severity": "low",
        "reason": "Urgency tactic to prevent critical thinking",
    },
    # Account verification scam
    {
        "rule_type": "fraud_phishing",
        "pattern": "verify your account",
        "pattern_type": "contains",
        "confidence": 0.85,
        "severity": "high",
        "reason": "Account verification phishing attempt - Discord doesn't request this",
    },
    # Identity confirmation scam
    {
        "rule_type": "fraud_phishing",
        "pattern": "confirm your identity",
        "pattern_type": "contains",
        "confidence": 0.85,
        "severity": "high",
        "reason": "Identity confirmation phishing - common account takeover tactic",
    },
    # Suspended account scare tactic
    {
        "rule_type": "fraud_phishing",
        "pattern": "suspended account",
        "pattern_type": "contains",
        "confidence": 0.82,
        "severity": "high",
        "reason": "Scare tactic to trick users into clicking phishing links",
    },
    # Unusual activity scare tactic
    {
        "rule_type": "fraud_phishing",
        "pattern": "unusual activity",
        "pattern_type": "contains",
        "confidence": 0.80,
        "severity": "medium",
        "reason": "Scare tactic commonly used in phishing attempts",
    },
    # Investment opportunity
    {
        "rule_type": "fraud_investment",
        "pattern": "investment opportunity",
        "pattern_type": "contains",
        "confidence": 0.75,
        "severity": "medium",
        "reason": "Unsolicited investment offers are typically scams",
    },
    # Guaranteed return
    {
        "rule_type": "fraud_investment",
        "pattern": "guaranteed return",
        "pattern_type": "contains",
        "confidence": 0.90,
        "severity": "high",
        "reason": "No legitimate investment guarantees returns - classic scam indicator",
    },
    # Risk free investment
    {
        "rule_type": "fraud_investment",
        "pattern": "risk free",
        "pattern_type": "contains",
        "confidence": 0.88,
        "severity": "high",
        "reason": "All investments have risk - 'risk free' is always fraudulent",
    },
    # Make money fast
    {
        "rule_type": "fraud_scam",
        "pattern": "make money fast",
        "pattern_type": "contains",
        "confidence": 0.85,
        "severity": "medium",
        "reason": "Get-rich-quick scheme indicator",
    },
    # Work from home scam
    {
        "rule_type": "fraud_scam",
        "pattern": "work from home",
        "pattern_type": "contains",
        "confidence": 0.65,
        "severity": "low",
        "reason": "Often used in MLM/pyramid schemes (may be legitimate, needs context)",
    },
    # You won / congratulations scam
    {
        "rule_type": "fraud_scam",
        "pattern": r"congratulations.*you.*won",
        "pattern_type": "regex",
        "confidence": 0.88,
        "severity": "high",
        "reason": "Fake prize notification - user didn't enter any contest",
    },
    # You have been selected
    {
        "rule_type": "fraud_scam",
        "pattern": "you have been selected",
        "pattern_type": "contains",
        "confidence": 0.85,
        "severity": "high",
        "reason": "Fake selection/prize scam tactic",
    },
    # Exclusive access scam
    {
        "rule_type": "fraud_scam",
        "pattern": "exclusive access",
        "pattern_type": "contains",
        "confidence": 0.70,
        "severity": "low",
        "reason": "Used to create false sense of privilege (may be legitimate marketing)",
    },
    # DM me for crypto
    {
        "rule_type": "fraud_crypto",
        "pattern": r"dm.*me.*for.*(crypto|bitcoin|btc|eth)",
        "pattern_type": "regex",
        "confidence": 0.92,
        "severity": "high",
        "reason": "Soliciting crypto transactions via DM - common scam pattern",
    },
    # Send me crypto
    {
        "rule_type": "fraud_crypto",
        "pattern": r"send.*(me|us).*(crypto|bitcoin|btc|eth)",
        "pattern_type": "regex",
        "confidence": 0.95,
        "severity": "critical",
        "reason": "Direct request for cryptocurrency - almost always a scam",
    },
    # Prompt injection - ignore previous/above instructions
    {
        "rule_type": "prompt_injection",
        "pattern": r"ignore\s+.{0,20}(instruction|instructions|prompt|prompts|rules|directives)",
        "pattern_type": "regex",
        "confidence": 0.95,
        "severity": "critical",
        "reason": "Attempting to override bot instructions via prompt injection attack",
    },
    # Prompt injection - disregard system
    {
        "rule_type": "prompt_injection",
        "pattern": r"disregard\s+.{0,20}(instruction|instructions|prompt|prompts|rules|directives)",
        "pattern_type": "regex",
        "confidence": 0.95,
        "severity": "critical",
        "reason": "Attempting to override bot instructions via prompt injection attack",
    },
    # Prompt injection - forget instructions
    {
        "rule_type": "prompt_injection",
        "pattern": r"forget\s+.{0,20}(instruction|instructions|prompt|prompts|rules|directives)",
        "pattern_type": "regex",
        "confidence": 0.95,
        "severity": "critical",
        "reason": "Attempting to reset bot instructions via prompt injection attack",
    },
    # Prompt injection - new instructions
    {
        "rule_type": "prompt_injection",
        "pattern": r"(new|updated|revised)\s+(instruction|instructions|prompt|prompts|rules|directive)",
        "pattern_type": "regex",
        "confidence": 0.90,
        "severity": "critical",
        "reason": "Attempting to provide new instructions to override bot behavior",
    },
    # Prompt injection - you are now
    {
        "rule_type": "prompt_injection",
        "pattern": r"you\s+are\s+now\s+(a|an|programmed|instructed)",
        "pattern_type": "regex",
        "confidence": 0.92,
        "severity": "critical",
        "reason": "Attempting to redefine bot identity or behavior via prompt injection",
    },
    # Prompt injection - system override
    {
        "rule_type": "prompt_injection",
        "pattern": r"(override|bypass)\s+(system|security|safety|moderation)",
        "pattern_type": "regex",
        "confidence": 0.93,
        "severity": "critical",
        "reason": "Attempting to bypass security controls via prompt injection",
    },
    # Prompt injection - act as/pretend to be
    {
        "rule_type": "prompt_injection",
        "pattern": r"(act\s+as|pretend\s+to\s+be|roleplay\s+as)\s+(a|an|the)",
        "pattern_type": "regex",
        "confidence": 0.85,
        "severity": "high",
        "reason": "Attempting to change bot behavior via role manipulation (may be legitimate roleplay, needs context)",
    },
    # Prompt injection - show system prompt
    {
        "rule_type": "prompt_injection",
        "pattern": r"(show|display|reveal|print)\s+(me\s+)?(your\s+)?(system\s+)?(prompt|instructions|rules)",
        "pattern_type": "regex",
        "confidence": 0.94,
        "severity": "critical",
        "reason": "Attempting to extract system prompt via prompt injection",
    },
    # Prompt injection - reveal context
    {
        "rule_type": "prompt_injection",
        "pattern": r"(reveal|show|display)\s+(your\s+)?(hidden|private|internal)\s+(context|data|information)",
        "pattern_type": "regex",
        "confidence": 0.93,
        "severity": "critical",
        "reason": "Attempting to extract internal bot data via prompt injection",
    },
    # Prompt injection - sudo/admin mode
    {
        "rule_type": "prompt_injection",
        "pattern": r"\b(sudo|admin|administrator|developer|debug)\s+mode\b",
        "pattern_type": "regex",
        "confidence": 0.90,
        "severity": "critical",
        "reason": "Attempting to activate elevated privileges via prompt injection",
    },
    # Prompt injection - execute with privilege
    {
        "rule_type": "prompt_injection",
        "pattern": r"execute\s+(as|with)\s+(admin|root|elevated|system)",
        "pattern_type": "regex",
        "confidence": 0.95,
        "severity": "critical",
        "reason": "Attempting to execute commands with elevated privileges via prompt injection",
    },
    # Prompt injection - /system command
    {
        "rule_type": "prompt_injection",
        "pattern": r"/system\s+",
        "pattern_type": "regex",
        "confidence": 0.88,
        "severity": "high",
        "reason": "Attempting to use system commands via prompt injection (may be legitimate slash command)",
    },
    # Prompt injection - XML/JSON tags for system role
    {
        "rule_type": "prompt_injection",
        "pattern": r"<\s*system\s*>|[\{\[][\s\"']*role[\s\"']*:[\s\"']*system",
        "pattern_type": "regex",
        "confidence": 0.94,
        "severity": "critical",
        "reason": "Attempting to inject system role via XML/JSON tags",
    },
    # Prompt injection - assistant/AI role manipulation
    {
        "rule_type": "prompt_injection",
        "pattern": r"<\s*assistant\s*>|{[\s\"']*role[\s\"']*:[\s\"']*assistant[\s\"']*}",
        "pattern_type": "regex",
        "confidence": 0.92,
        "severity": "critical",
        "reason": "Attempting to inject assistant role to control bot responses",
    },
]


async def seed_global_heuristics(db) -> int:
    """Seed global fraud heuristics into the database.

    Args:
        db: Database instance

    Returns:
        Number of heuristics seeded
    """
    import logging

    logger = logging.getLogger(__name__)

    seeded_count = 0

    for heuristic in GLOBAL_FRAUD_HEURISTICS:
        try:
            # Check if this pattern already exists as a global heuristic
            existing = await db.fetch_active_heuristics(
                guild_id=None,  # Global patterns have guild_id=None
                min_confidence=0.0,
            )

            # Check if pattern already exists
            pattern_exists = any(
                h["pattern"] == heuristic["pattern"]
                and h["pattern_type"] == heuristic["pattern_type"]
                and h["guild_id"] is None
                for h in existing
            )

            if pattern_exists:
                logger.debug(f"Global heuristic already exists: {heuristic['pattern']}")
                continue

            # Insert global heuristic (guild_id=None)
            rule_id, is_new = await db.insert_heuristic_rule(
                guild_id=None,  # NULL = applies to all guilds
                rule_type=heuristic["rule_type"],
                pattern=heuristic["pattern"],
                pattern_type=heuristic["pattern_type"],
                confidence=heuristic["confidence"],
                severity=heuristic["severity"],
                reason=heuristic["reason"],
                created_by="system",  # System-seeded, not LLM-generated
            )

            if rule_id and is_new:
                seeded_count += 1
                logger.info(f"Seeded global heuristic {rule_id}: {heuristic['pattern']}")
            elif rule_id and not is_new:
                logger.debug(f"Global heuristic {rule_id} already existed: {heuristic['pattern']}")

        except Exception:
            logger.exception(f"Failed to seed heuristic: {heuristic['pattern']}")

    logger.info(f"Seeded {seeded_count} global fraud heuristics")
    return seeded_count
