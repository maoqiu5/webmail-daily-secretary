# Webmail Daily Secretary Workflow Reference

## Report Layout

Maintain a concise answer-first report:

- 今日总览: coverage, latest visible mail, processed count, reply count, awareness count, low-priority count, urgent count.
- 优先处理清单: sort by urgency, customer impact, deadline, and direct-address signals.
- 需要回复: each item with suggested reply/action.
- 需要关注知晓: project/risk/policy updates that do not need immediate reply.
- 与你无关/低优先级: brief archive rationale.
- 已处理邮件索引: `time｜sender｜subject`.
- 更新记录: every polling run that changes state or hits a blocker.

The visual Markdown should be scan-friendly:

- 一屏结论 metrics.
- 红黄绿处理盘.
- 今天最该先处理的事项.
- 需要回复清单.
- 关注但不一定马上回复.
- 状态说明.

## Browser Notes

Use the appropriate browser skill and browser-client runtime, not standalone Playwright. Prefer Chrome when the mailbox depends on the user’s existing login session.

Claim an existing webmail tab when available. If no tab is exposed, open the mailbox URL supplied by the user. If the page redirects to a login page, login expired; report the blocker and keep the login page for handoff.

Webmail lists can be stale. Refresh once before concluding there is no new mail. After refresh, wait several seconds before reading `document.body.innerText`.

Do not inspect cookies, local storage, passwords, or session stores.

## Incremental Extraction

Treat visible same-day rows as today’s current inbox window. For Chinese webmail, rows above the first `昨天` marker are usually today’s current window. For English UI, use visible exact times, “Today”, or date group headers. Parse rows as:

- sender
- optional `外部`
- subject
- snippet
- time

For ambiguous actions, open the email detail if possible. Different webmail apps expose To/Cc differently; use detail view for high-priority direct-address judgments. If details are not accessible, state that classification is based on list/snippet text.

## Automation

Preferred heartbeat schedule:

- China daytime: every 10 minutes from 08:00 through 21:59.
- Nighttime: paused unless explicitly requested.

When updating the automation prompt, avoid hardcoded dates. Use `{YYYY-MM-DD}` placeholders and instruct the agent to substitute the current Asia/Shanghai date.

## WeCom Image Briefs

Use the working report-folder script:

```bash
cd "$WEBMAIL_REPORT_DIR"
python3 wechat_push.py render-image
python3 wechat_push.py notify-if-changed
```

The script should:

- Compute current date by default.
- Read `.env.local` for WeCom credentials.
- Read optional path overrides from environment variables.
- Deduplicate using `wechat_push_state.json`.
- Render PNG with Pillow and `Hiragino Sans GB`/STHeiti fallback.
- Send markdown summary plus PNG only when report hash changes.

If network access is blocked, rerun with required approval only when the user has authorized WeCom export. Never print secrets or access tokens.

## Power Management

Only change macOS sleep settings when the user explicitly asks. Save current `pmset -g custom` first. Restore original values when requested. Avoid leaving LaunchAgents or background `caffeinate` processes behind.
