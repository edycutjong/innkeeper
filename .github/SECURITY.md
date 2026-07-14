# Security Policy

## Supported Versions
| Version | Supported |
|---|---|
| latest (`main`) | ✅ |

## Reporting a Vulnerability
Please **do not** open a public issue for security vulnerabilities. Instead,
report them privately:

- Email **edy.cu@live.com**, or
- Use GitHub's [private vulnerability reporting](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability) (Security → Report a vulnerability).

You'll get an acknowledgment within 48 hours and a resolution timeline after
triage. Please give us a reasonable window to patch before public disclosure.

## Notes specific to Innkeeper
- The demo Ed25519 keypair under `fixtures/month_07/keys/` is intentionally
  committed — it signs **demo data only** and must never be reused for a
  production night-close chain.
- The optional `--live` path sends OTA statement pages and reconciliation
  data to the DashScope (Qwen Cloud) API using `DASHSCOPE_API_KEY`. No PMS,
  processor, or OTA credentials are ever transmitted — Innkeeper only reads
  from the three (mocked, in this repo) source-system MCP servers.
