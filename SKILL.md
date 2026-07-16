---
name: webmail-daily-secretary
description: Operate a daily secretary workflow for any webmail mailbox that can be opened in a browser, including WPS/KDocs, Outlook web, Gmail web, enterprise webmail, or other signed-in mailbox pages. Use when asked to read browser-based mail, classify same-day messages, maintain Markdown/HTML/PNG daily email briefs, run daytime polling, prioritize direct-addressed mail, or push report updates through 企业微信/WeCom.
---

# Webmail Daily Secretary

## Quick Start

Use the signed-in browser tab for the user’s webmail. Prefer Chrome when the task depends on an existing login session. If the mailbox is logged out, stop and ask the user to log in; do not bypass authentication. Use the mailbox URL or visible browser tab supplied by the user; this skill is webmail-provider neutral.

Use the user’s requested timezone, or `WEBMAIL_TIMEZONE` when configured. Default to Asia/Shanghai for China-based workflows. Write reports into the user-provided report directory, or `WEBMAIL_REPORT_DIR` when configured. Report files are named:

- `{YYYY-MM-DD}-邮件简报.md`
- `{YYYY-MM-DD}-邮件简报-可视化版.md`
- `{YYYY-MM-DD}-邮件简报-可视化版.html`
- `{YYYY-MM-DD}-邮件简报-可视化版.png`

After updating reports, run:

```bash
cd "$WEBMAIL_REPORT_DIR"
python3 wechat_push.py notify-if-changed
```

If system Python lacks Pillow, set `BUNDLED_PYTHON` to a Python executable that has Pillow installed, or install Pillow in the Python used to run the script.

## Workflow

1. Connect to the user’s signed-in browser session and claim the open webmail tab, or open the webmail URL the user provides.
2. Refresh or read the inbox top list; many webmail apps can show stale content until refreshed.
3. Identify all visible same-day messages. Use platform-specific date labels such as `今天`, exact times, or messages above the first `昨天`/older-date marker.
4. Read list snippets first; open details only when the snippet is insufficient for recipient/Cc/action judgment.
5. Classify and dedupe using `time + sender + subject`.
6. Update all three report files and regenerate the PNG visual brief.
7. Run the WeCom push script. It dedupes by report hash and sends only meaningful changes.
8. Keep the Chrome tab as handoff after browser work.

Daytime polling is China time `08:00-21:59`, every 10 minutes. Avoid night polling unless the user explicitly asks.

## Classification

- `需要回复/处理`: explicit requests to confirm, approve, quote, provide documents, update systems, book space, amend documents, arrange time, or answer a question.
- `需要关注知晓`: project, risk, schedule, policy, handoff, compliance, cost, or customer information with no immediate reply duty.
- `与你无关/低优先级`: generic notifications, attachment-only circulation, system mail without action, or cc-only mail with no action.

Raise priority when:

- The user’s configured email address appears in direct recipients, not only Cc. Configure addresses with `USER_EMAILS`.
- The body directly addresses the user by configured names or titles. Configure these with `DIRECT_SALUTATIONS`.
- The message includes deadlines, booking blocks, customs/document risks, payment approval, system update needs, or customer-facing delay risk.

## WeCom Push

Use `scripts/wechat_push.py` as the reusable implementation reference. Copy it into the report folder or run it from the skill folder with `WEBMAIL_REPORT_DIR` pointing at the report folder.

Required local `.env.local` fields:

```env
WECHAT_CORP_ID=
WECHAT_AGENT_ID=
WECHAT_APP_SECRET=
WECHAT_TO_USER=
```

Never copy secrets into skill files, reports, screenshots, or final answers. The script caches tokens locally and generates visual PNGs with Pillow by default to avoid Chrome headless crashes.

For a reusable config template, see `references/env-example.txt`.

## References

Read `references/workflow.md` when you need the detailed operational checklist, report layout, automation rules, or troubleshooting notes.
