# Heuristics System

The heuristics system provides fast-path pattern matching for common moderation scenarios, reducing LLM calls and enabling instant responses to known violations.

## Overview

**mod-gpt** uses a two-tier moderation approach:

1. **Heuristics (Fast Path)**: Pattern-based rules checked against every message
2. **LLM Reasoning (Slow Path)**: Context-aware decisions when heuristics match or manual review needed

This hybrid approach balances speed, cost, and accuracy.

## Pattern Types

### 1. **Exact Match**

Matches whole words with word boundaries (case-insensitive).

**Example:**

```python
{
    "pattern": "spam",
    "pattern_type": "exact"
}
```

- ✅ Matches: "This is spam", "SPAM message", "Stop spam!"
- ❌ No match: "spammer", "spamming", "aspam"

**Use for:** Known bad words, exact phrases, specific command names

### 2. **Regex Match**

Matches using regular expressions (case-insensitive by default).

**Example:**

```python
{
    "pattern": r"free[\s_\-]*(discord[\s_\-]*)?nitro",
    "pattern_type": "regex"
}
```

- ✅ Matches: "free nitro", "free_discord_nitro", "FREE-NITRO", "free discordnitro"
- ❌ No match: "paid nitro", "nitro free" (order matters)

**Use for:** Flexible patterns, URL matching, variations of phrases

### 3. **Fuzzy Match**

Allows typos and character substitutions using Levenshtein distance.

**Example:**

```python
{
    "pattern": "nigger",
    "pattern_type": "fuzzy"
}
```

- ✅ Matches: "n1gger", "nigg3r", "n!gger" (common evasion tactics)
- Maximum edit distance: 2 characters

**Use for:** Hate speech, slurs with common substitutions, typo-resistant profanity

### 4. **Contains Match**

Simple substring match (case-insensitive).

**Example:**

```python
{
    "pattern": "click here",
    "pattern_type": "contains"
}
```

- ✅ Matches: "Please click here to verify", "CLICK HERE NOW!", "Just click here"
- ❌ May have false positives in legitimate messages

**Use for:** Phishing phrases, suspicious call-to-actions, low-confidence patterns

## Confidence Scores

Each heuristic has a confidence score (0.0-1.0) indicating how certain the pattern indicates a violation:

| Confidence  | Interpretation                         | Examples                               |
| ----------- | -------------------------------------- | -------------------------------------- |
| **0.9-1.0** | Almost certainly a violation           | "free nitro scam", racial slurs        |
| **0.7-0.9** | Likely a violation                     | "double your money", "click this link" |
| **0.5-0.7** | Suspicious, needs context              | "join my server", URL shorteners       |
| **0.3-0.5** | Low confidence, LLM review recommended | Generic spam words                     |

**How it affects decisions:**

- High confidence (>0.8): LLM may auto-delete with strong justification
- Medium confidence (0.5-0.8): LLM reviews with matched pattern as evidence
- Low confidence (<0.5): Pattern used as weak signal, needs additional context

## Severity Levels

| Severity     | Description                        | Example Violations              | Typical Actions                        |
| ------------ | ---------------------------------- | ------------------------------- | -------------------------------------- |
| **Critical** | Immediate threats, illegal content | Death threats, CSAM, doxxing    | Instant ban, delete, report to Discord |
| **High**     | Serious violations                 | Hate speech, harassment, scams  | Timeout, delete, warn                  |
| **Medium**   | Moderate issues                    | Spam, profanity, self-promotion | Delete, warn                           |
| **Low**      | Minor infractions                  | Minor spam, off-topic           | Warn only                              |

## Global vs. Guild-Specific Heuristics

### Global Heuristics (`guild_id = NULL`)

Universal patterns that apply to **all servers**:

- Discord Nitro scams ("free nitro")
- Gaming currency scams ("free robux", "free vbucks")
- Cryptocurrency scams ("double your bitcoin")
- Investment scams ("guaranteed returns")
- Common URL shorteners (may be phishing)

**Seeded on bot startup** from `modgpt/utils/seed_heuristics.py`.

### Guild-Specific Heuristics (`guild_id = 123456789`)

Server-specific patterns learned from:

- Context channels (rules, guidelines)
- Admin memories (persistent instructions)
- User feedback (flagged messages via context menu)

**Generated dynamically** by the LLM using the `suggest_heuristic` function.

## Heuristic Generation

### From Context Channels

When a context channel is added or refreshed:

```python
await moderation.generate_heuristics_from_context(guild)
```

**Process:**

1. LLM reads all context channels and memories
2. Identifies patterns that would violate stated rules
3. Suggests heuristics via `suggest_heuristic` function
4. Bot stores heuristics in database with `guild_id`

**Example:**
If rules say "No crypto discussion", LLM might suggest:

```python
{
    "rule_type": "off_topic",
    "pattern": r"(bitcoin|ethereum|crypto|nft|web3)",
    "pattern_type": "regex",
    "confidence": 0.75,
    "severity": "low",
    "reason": "Server rules prohibit cryptocurrency discussion"
}
```

### From User Feedback

When a moderator flags a message:

```python
# Right-click message → "Flag for Moderation"
await moderation.generate_heuristic_from_feedback(guild, message, reason)
```

**Process:**

1. LLM analyzes the flagged message
2. Extracts patterns that should have been caught
3. Suggests a heuristic to catch similar messages
4. Bot stores heuristic and provides feedback to moderator

### From Moderation Events

When LLM takes an action (delete, warn, etc.):

```python
# During reasoning, LLM can call suggest_heuristic
{
    "name": "suggest_heuristic",
    "arguments": {
        "rule_type": "spam",
        "pattern": "join my server",
        "pattern_type": "contains",
        "confidence": 0.70,
        "severity": "medium",
        "reason": "Unsolicited server promotion"
    }
}
```

**Benefits:**

- Bot learns from its own decisions
- Reduces future LLM calls for similar content
- Improves response time for repeat violations

## Matching Algorithm

When a message is received:

```python
async def check_heuristics(message: discord.Message, guild_id: int) -> List[Match]:
    # 1. Fetch all active heuristics (global + guild-specific)
    heuristics = await database.get_active_heuristics(guild_id)

    # 2. Check each pattern type
    matches = []
    content = message.content.lower()

    for heuristic in heuristics:
        if heuristic.pattern_type == "exact":
            if re.search(rf"\b{re.escape(heuristic.pattern)}\b", content, re.I):
                matches.append(heuristic)

        elif heuristic.pattern_type == "regex":
            if re.search(heuristic.pattern, content, re.I):
                matches.append(heuristic)

        elif heuristic.pattern_type == "fuzzy":
            if fuzzy_match(heuristic.pattern, content, max_distance=2):
                matches.append(heuristic)

        elif heuristic.pattern_type == "contains":
            if heuristic.pattern in content:
                matches.append(heuristic)

    # 3. Return all matches (LLM decides which to act on)
    return matches
```

## LLM Integration

When heuristics match:

```python
# Build event prompt with matched patterns
event_prompt = f"""
Message from {author}: "{content}"

Matched heuristics:
1. Pattern: "free nitro" (regex)
   Type: fraud_scam
   Confidence: 0.95
   Severity: high
   Reason: Common Discord Nitro scam pattern

2. Pattern: "click here" (contains)
   Type: fraud_phishing
   Confidence: 0.80
   Severity: medium
   Reason: Common phishing tactic

Review the message in context and decide if action is needed.
"""

# LLM can then:
# - Delete the message (high confidence match)
# - Warn the user (medium confidence)
# - Do nothing (false positive)
# - Suggest improved heuristic
```

## Managing Heuristics

### View Heuristics

```
/list-heuristics [rule_type]
```

Shows all active heuristics, optionally filtered by type.

### Disable Heuristic

```
/disable-heuristic <heuristic_id>
```

Marks heuristic as inactive (soft delete). Can be re-enabled later.

### Add Manual Heuristic

```
/add-heuristic
  rule_type: spam
  pattern: join my server
  pattern_type: contains
  confidence: 0.70
  severity: medium
  reason: Unsolicited server promotion
```

### Heuristic Analytics

```sql
-- Most frequently matched patterns
SELECT pattern, rule_type, COUNT(*) as hits
FROM heuristic_rules h
JOIN moderation_actions m ON m.metadata->>'matched_heuristic_id' = h.id::text
WHERE h.guild_id = $1 OR h.guild_id IS NULL
GROUP BY h.id
ORDER BY hits DESC
LIMIT 20;
```

## Best Practices

### 1. **Start Conservative**

- Begin with high-confidence global heuristics
- Let LLM learn guild-specific patterns organically
- Avoid overly broad patterns that cause false positives

### 2. **Balance Confidence & Severity**

- High confidence + high severity → Automatic action
- Low confidence + medium severity → LLM review
- Adjust based on false positive rate

### 3. **Use Appropriate Pattern Types**

- Exact: Known bad words (fewer false positives)
- Regex: Flexible variations (more coverage)
- Fuzzy: Evasion-resistant (for determined bad actors)
- Contains: Low confidence screening (needs LLM review)

### 4. **Provide Context in Reasons**

Always reference specific rules:

- ❌ Bad: "This is spam"
- ✅ Good: "Violates Rule #3: No server advertisements"

### 5. **Regular Review**

- Check `/list-heuristics` monthly
- Disable outdated or problematic patterns
- Refine confidence scores based on outcomes

### 6. **Dry-Run Testing**

Enable dry-run mode when adding new heuristics:

```
/set-dry-run enabled
```

Bot will log intended actions without executing them.

## Performance Considerations

- **Database Indexes**: `guild_id` and `active` columns indexed for fast queries
- **Regex Compilation**: Patterns compiled once and cached in memory
- **Batch Checking**: All heuristics checked in a single pass
- **Early Exit**: High-confidence matches may skip further checks

**Typical Performance:**

- 100 heuristics checked: ~5-10ms
- LLM reasoning call: ~500-1500ms
- Net benefit: 50-150x faster for matched patterns

## Examples

### Example 1: Nitro Scam Detection

```python
{
    "rule_type": "fraud_scam",
    "pattern": r"free[\s_\-]*(discord[\s_\-]*)?nitro",
    "pattern_type": "regex",
    "confidence": 0.95,
    "severity": "high",
    "reason": "Common Discord Nitro scam pattern - 'free nitro' is almost always fraudulent"
}
```

**Matches:**

- "Get free Discord Nitro here!"
- "FREE_NITRO giveaway!"
- "Claim your free nitro"

**Action:** LLM deletes message, warns user, possibly timeouts on repeat offense

### Example 2: Server-Specific Rule

Context channel says: "No discussions about politics or religion"

**Generated Heuristic:**

```python
{
    "rule_type": "off_topic",
    "pattern": r"(democrat|republican|biden|trump|christian|muslim|atheist)",
    "pattern_type": "regex",
    "confidence": 0.60,
    "severity": "low",
    "reason": "Server rules prohibit political and religious discussions"
}
```

**Action:** LLM reviews context (may be legitimate if discussing history/culture)

### Example 3: Hate Speech Evasion

```python
{
    "rule_type": "hate_speech",
    "pattern": "fag",
    "pattern_type": "fuzzy",
    "confidence": 0.90,
    "severity": "high",
    "reason": "Homophobic slur - fuzzy match catches common evasions (f4g, f@g, etc.)"
}
```

**Matches:**

- "f4g", "f@g", "f4gg0t"
- Maximum edit distance: 2

**Action:** LLM deletes, warns, timeout on repeat

## Troubleshooting

### False Positives

If legitimate messages are being flagged:

1. Check confidence score (lower if too aggressive)
2. Use more specific pattern_type (regex instead of contains)
3. Add context to reason (LLM can override with justification)
4. Disable heuristic if consistently wrong

### False Negatives

If violations are being missed:

1. Use "Flag for Moderation" context menu to teach bot
2. Add variations to pattern (regex or fuzzy)
3. Check if pattern is too specific (broaden it)
4. Ensure heuristic is active and has reasonable confidence

### Performance Issues

If bot is slow to respond:

1. Check number of active heuristics (>1000 may be too many)
2. Optimize regex patterns (avoid backtracking)
3. Disable low-value heuristics with low hit rates
4. Consider guild-specific filtering before pattern matching
