# Security Policy

## Supported Versions

We release patches for security vulnerabilities in the following versions:

| Version | Supported          |
| ------- | ------------------ |
| 0.1.x   | :white_check_mark: |

## Reporting a Vulnerability

**Please do not report security vulnerabilities through public GitHub issues.**

If you discover a security vulnerability, please report it privately to the maintainers:

1. **Email:** [Your security email]
2. **Subject:** `[SECURITY] mod-gpt vulnerability report`

### What to Include

- **Type of vulnerability**
- **Affected component(s)**
- **Steps to reproduce**
- **Potential impact**
- **Suggested fix** (if you have one)

### Response Timeline

- **Acknowledgment:** Within 48 hours
- **Initial assessment:** Within 7 days
- **Fix & disclosure:** Coordinated with reporter

## Security Considerations

### API Keys & Tokens

- **Never commit secrets** to version control
- Use environment variables or secret management
- Rotate keys regularly (every 90 days recommended)
- Use separate keys for development and production

### Database Security

- **Use strong passwords** (generated, not dictionary words)
- **Enable SSL/TLS** for database connections
- **Restrict access** by IP when possible
- **Create bot-specific user** (not superuser)
- **Regular backups** with encryption at rest

### Discord Bot Security

- **Minimum permissions** required for functionality
- **No Administrator permission** (too broad)
- **Role hierarchy** - Bot role should be high enough to moderate but not higher than admins
- **Private logs channel** to protect moderation reasoning
- **Rate limiting** respected (discord.py handles this)

### LLM Security

- **Prompt injection protection** - System prompts wrapped in UUID tags
- **Input validation** - Pydantic models validate all configuration
- **Output sanitization** - Bot checks LLM responses before execution
- **Dry-run mode** available for testing before enforcement
- **Human escalation** for critical decisions

### Deployment Security

- **HTTPS only** for all external connections
- **Health check endpoints** don't expose sensitive data
- **Logging** excludes tokens and API keys
- **Resource limits** prevent DoS (connection pooling, rate limiting)
- **Regular updates** for dependencies

### Data Privacy

- **Minimal data collection** - Only moderation-relevant information
- **Audit trails** for transparency and accountability
- **User IDs hashed** in analytics (if implemented)
- **Message content** not stored long-term (only in active conversations)
- **GDPR considerations** - Users can request data deletion

## Known Security Limitations

### 1. LLM Hallucinations
**Risk:** LLM may generate incorrect or biased moderation decisions  
**Mitigation:** Heuristics provide first-pass filtering, dry-run mode for testing, human review for critical actions

### 2. Prompt Injection
**Risk:** Users may try to manipulate system prompts  
**Mitigation:** System prompts wrapped in UUID-tagged guards, user input sanitized, function calling restricts actions

### 3. Database Access
**Risk:** Database compromise exposes moderation history  
**Mitigation:** Strong passwords, SSL connections, IP restrictions, separate bot user with limited permissions

### 4. API Key Exposure
**Risk:** Exposed keys grant access to OpenAI/Discord accounts  
**Mitigation:** Never commit to Git, use secret management, rotate regularly, monitor usage for anomalies

### 5. Discord Permissions
**Risk:** Bot with excessive permissions could be weaponized  
**Mitigation:** Minimum required permissions, role hierarchy checks, audit logging, dry-run mode

## Best Practices for Users

### Setting Up the Bot

1. **Create dedicated database user** with limited permissions
2. **Use strong passwords** (generate them, don't create manually)
3. **Enable SSL** for database connections
4. **Restrict bot permissions** to minimum required
5. **Keep logs channel private** (moderators only)
6. **Enable dry-run mode** initially for testing
7. **Review context channels** for sensitive information
8. **Rotate API keys** quarterly

### Ongoing Maintenance

1. **Review logs weekly** for unexpected behavior
2. **Update dependencies** monthly (security patches)
3. **Backup database** daily with 30-day retention
4. **Monitor API usage** for anomalies
5. **Audit heuristics** for false positives/negatives
6. **Test in dry-run** before major configuration changes
7. **Review moderation actions** for bias or errors

### Incident Response

If you suspect a security incident:

1. **Enable dry-run mode** immediately to prevent further actions
2. **Review recent logs** for suspicious activity
3. **Check database** for unauthorized changes
4. **Rotate API keys** if compromise suspected
5. **Report to maintainers** via security email
6. **Document timeline** and impact
7. **Notify affected users** if data was exposed

## Security Updates

We will disclose security vulnerabilities and patches through:

- **GitHub Security Advisories** (preferred)
- **Release notes** with `[SECURITY]` tag
- **Email notification** to known deployments (if possible)

**Subscribe to releases** to be notified of security updates.

## Responsible Disclosure

We appreciate security researchers who:

- **Report privately** first (not public disclosure)
- **Allow time** for us to patch before disclosure
- **Provide details** to help us reproduce and fix
- **Don't exploit** the vulnerability beyond proof-of-concept

We commit to:

- **Acknowledge** reports within 48 hours
- **Provide updates** on fix progress
- **Credit researchers** in security advisories (if desired)
- **Coordinate disclosure** timing with reporter

## Contact

- **Security issues:** [Your security email]
- **General issues:** [GitHub Issues](https://github.com/your-username/mod-gpt/issues)
- **Questions:** [GitHub Discussions](https://github.com/your-username/mod-gpt/discussions)

---

Thank you for helping keep mod-gpt and its users safe! 🔒

