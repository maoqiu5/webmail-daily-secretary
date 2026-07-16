#!/usr/bin/env python3
"""Send webmail daily report update notifications through a WeCom app message."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env.local"


def preload_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


preload_env_file(ENV_PATH)
REPORT_DATE = datetime.now().strftime("%Y-%m-%d")
REPORT_DIR = Path(os.environ.get("WEBMAIL_REPORT_DIR", BASE_DIR)).expanduser()
REPORT_TITLE = os.environ.get("REPORT_TITLE", "邮件每日简报")
DEFAULT_REPORT_MD = REPORT_DIR / f"{REPORT_DATE}-邮件简报.md"
DEFAULT_VISUAL_MD = REPORT_DIR / f"{REPORT_DATE}-邮件简报-可视化版.md"
DEFAULT_HTML = REPORT_DIR / f"{REPORT_DATE}-邮件简报-可视化版.html"
DEFAULT_IMAGE = REPORT_DIR / f"{REPORT_DATE}-邮件简报-可视化版.png"
DEFAULT_CHROME = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
BUNDLED_PYTHON_VALUE = os.environ.get("BUNDLED_PYTHON", "").strip()
BUNDLED_PYTHON = Path(BUNDLED_PYTHON_VALUE).expanduser() if BUNDLED_PYTHON_VALUE else None
CHINESE_FONT_REGULAR = Path("/System/Library/Fonts/Hiragino Sans GB.ttc")
CHINESE_FONT_BOLD = Path("/System/Library/Fonts/Hiragino Sans GB.ttc")
CHINESE_FONT_FALLBACK_REGULAR = Path("/System/Library/Fonts/STHeiti Light.ttc")
CHINESE_FONT_FALLBACK_BOLD = Path("/System/Library/Fonts/STHeiti Medium.ttc")
STATE_PATH = REPORT_DIR / "wechat_push_state.json"
TOKEN_CACHE_PATH = REPORT_DIR / ".wechat_token_cache.json"


class PushError(RuntimeError):
    pass


@dataclass(frozen=True)
class Config:
    corp_id: str
    agent_id: str
    app_secret: str
    to_user: str
    report_md: Path
    visual_md: Path
    html_report: Path
    report_image: Path
    chrome_path: Path
    report_title: str


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise PushError(f"Missing required config: {name}")
    return value


def load_config() -> Config:
    load_env_file(ENV_PATH)
    return Config(
        corp_id=require_env("WECHAT_CORP_ID"),
        agent_id=require_env("WECHAT_AGENT_ID"),
        app_secret=require_env("WECHAT_APP_SECRET"),
        to_user=require_env("WECHAT_TO_USER"),
        report_md=Path(os.environ.get("MAIL_REPORT_MD", DEFAULT_REPORT_MD)).expanduser(),
        visual_md=Path(os.environ.get("MAIL_REPORT_VISUAL_MD", DEFAULT_VISUAL_MD)).expanduser(),
        html_report=Path(os.environ.get("MAIL_REPORT_HTML", DEFAULT_HTML)).expanduser(),
        report_image=Path(os.environ.get("MAIL_REPORT_IMAGE", DEFAULT_IMAGE)).expanduser(),
        chrome_path=Path(os.environ.get("CHROME_PATH", DEFAULT_CHROME)).expanduser(),
        report_title=REPORT_TITLE,
    )


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def post_json(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            body = response.read().decode("utf-8")
    except urllib.error.URLError as exc:
        raise PushError(f"WeCom network request failed: {exc.reason}") from exc
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise PushError(f"WeCom returned non-JSON response: {body[:160]}") from exc


def post_multipart_file(url: str, field_name: str, file_path: Path) -> dict[str, Any]:
    boundary = "----CodexWeComBoundary" + hashlib.sha256(str(time.time()).encode()).hexdigest()[:16]
    filename = file_path.name
    content_type = "image/png" if file_path.suffix.lower() == ".png" else "application/octet-stream"
    file_bytes = file_path.read_bytes()
    body = b"".join(
        [
            f"--{boundary}\r\n".encode("utf-8"),
            f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"\r\n'.encode("utf-8"),
            f"Content-Type: {content_type}\r\n\r\n".encode("utf-8"),
            file_bytes,
            b"\r\n",
            f"--{boundary}--\r\n".encode("utf-8"),
        ]
    )
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            response_body = response.read().decode("utf-8")
    except urllib.error.URLError as exc:
        raise PushError(f"WeCom network request failed: {exc.reason}") from exc
    try:
        return json.loads(response_body)
    except json.JSONDecodeError as exc:
        raise PushError(f"WeCom returned non-JSON response: {response_body[:160]}") from exc


def get_json(url: str) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(url, timeout=20) as response:
            body = response.read().decode("utf-8")
    except urllib.error.URLError as exc:
        raise PushError(f"WeCom network request failed: {exc.reason}") from exc
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise PushError(f"WeCom returned non-JSON response: {body[:160]}") from exc


def get_access_token(config: Config, force_refresh: bool = False) -> str:
    cache = read_json(TOKEN_CACHE_PATH)
    now = int(time.time())
    cached_token = str(cache.get("access_token", ""))
    expires_at = int(cache.get("expires_at", 0) or 0)
    if cached_token and expires_at - now > 300 and not force_refresh:
        return cached_token

    query = urllib.parse.urlencode({"corpid": config.corp_id, "corpsecret": config.app_secret})
    result = get_json(f"https://qyapi.weixin.qq.com/cgi-bin/gettoken?{query}")
    if result.get("errcode") != 0:
        raise PushError(f"Failed to get access_token: errcode={result.get('errcode')} errmsg={result.get('errmsg')}")

    token = str(result.get("access_token", ""))
    if not token:
        raise PushError("Failed to get access_token: empty token")
    expires_in = int(result.get("expires_in", 7200) or 7200)
    write_json(TOKEN_CACHE_PATH, {"access_token": token, "expires_at": now + expires_in})
    return token


def send_markdown(config: Config, content: str, force_token_refresh: bool = False) -> dict[str, Any]:
    token = get_access_token(config, force_refresh=force_token_refresh)
    url = "https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token=" + urllib.parse.quote(token)
    payload = {
        "touser": config.to_user,
        "msgtype": "markdown",
        "agentid": int(config.agent_id),
        "markdown": {"content": content},
        "safe": 0,
        "enable_duplicate_check": 1,
        "duplicate_check_interval": 600,
    }
    result = post_json(url, payload)
    if result.get("errcode") in {40014, 42001, 41001} and not force_token_refresh:
        return send_markdown(config, content, force_token_refresh=True)
    if result.get("errcode") != 0:
        raise PushError(f"Failed to send message: errcode={result.get('errcode')} errmsg={result.get('errmsg')}")
    return result


def upload_image_media(config: Config, image_path: Path, force_token_refresh: bool = False) -> str:
    if not image_path.exists():
        raise PushError(f"Report image does not exist: {image_path}")
    token = get_access_token(config, force_refresh=force_token_refresh)
    url = (
        "https://qyapi.weixin.qq.com/cgi-bin/media/upload?access_token="
        + urllib.parse.quote(token)
        + "&type=image"
    )
    result = post_multipart_file(url, "media", image_path)
    if result.get("errcode") in {40014, 42001, 41001} and not force_token_refresh:
        return upload_image_media(config, image_path, force_token_refresh=True)
    if result.get("errcode") != 0:
        raise PushError(f"Failed to upload image: errcode={result.get('errcode')} errmsg={result.get('errmsg')}")
    media_id = str(result.get("media_id", ""))
    if not media_id:
        raise PushError("Failed to upload image: empty media_id")
    return media_id


def send_image(config: Config, image_path: Path, force_token_refresh: bool = False) -> dict[str, Any]:
    media_id = upload_image_media(config, image_path, force_token_refresh=force_token_refresh)
    token = get_access_token(config)
    url = "https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token=" + urllib.parse.quote(token)
    payload = {
        "touser": config.to_user,
        "msgtype": "image",
        "agentid": int(config.agent_id),
        "image": {"media_id": media_id},
        "safe": 0,
        "enable_duplicate_check": 1,
        "duplicate_check_interval": 600,
    }
    result = post_json(url, payload)
    if result.get("errcode") in {40014, 42001, 41001} and not force_token_refresh:
        return send_image(config, image_path, force_token_refresh=True)
    if result.get("errcode") != 0:
        raise PushError(f"Failed to send image: errcode={result.get('errcode')} errmsg={result.get('errmsg')}")
    return result


def render_report_image(config: Config) -> Path:
    if os.environ.get("WECHAT_USE_CHROME_RENDER") != "1":
        return render_report_image_with_pillow_or_bundled(config)
    if not config.html_report.exists():
        raise PushError(f"HTML report does not exist: {config.html_report}")
    chrome = config.chrome_path
    if not chrome.exists():
        resolved = shutil.which("google-chrome") or shutil.which("chromium") or shutil.which("chrome")
        if not resolved:
            raise PushError(f"Chrome not found: {chrome}")
        chrome = Path(resolved)

    config.report_image.parent.mkdir(parents=True, exist_ok=True)
    profile_dir = BASE_DIR / ".chrome-headless-profile"
    profile_dir.mkdir(parents=True, exist_ok=True)
    file_url = config.html_report.resolve().as_uri()
    command = [
        str(chrome),
        "--headless=new",
        "--disable-gpu",
        "--hide-scrollbars",
        "--no-first-run",
        "--no-default-browser-check",
        f"--user-data-dir={profile_dir}",
        "--window-size=1280,7200",
        f"--screenshot={config.report_image}",
        file_url,
    ]
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=60)
        if completed.returncode != 0:
            legacy_command = command.copy()
            legacy_command[1] = "--headless"
            completed = subprocess.run(legacy_command, capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        return render_report_image_with_pillow_or_bundled(config)
    if completed.returncode != 0:
        return render_report_image_with_pillow_or_bundled(config)
    if not config.report_image.exists() or config.report_image.stat().st_size == 0:
        return render_report_image_with_pillow_or_bundled(config)
    return config.report_image


def render_report_image_with_pillow_or_bundled(config: Config) -> Path:
    try:
        return render_report_image_with_pillow(config)
    except ImportError:
        if not BUNDLED_PYTHON or not BUNDLED_PYTHON.exists():
            raise PushError("Pillow is not installed. Install Pillow or set BUNDLED_PYTHON to a Python executable that has Pillow.")
        env = os.environ.copy()
        env["WECHAT_FORCE_PILLOW_RENDER"] = "1"
        completed = subprocess.run(
            [str(BUNDLED_PYTHON), str(Path(__file__).resolve()), "render-image"],
            cwd=REPORT_DIR,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if completed.returncode != 0:
            stderr = (completed.stderr or completed.stdout or "").strip()
            raise PushError(f"Failed to render report image with bundled Python: {stderr[:300]}")
        if not config.report_image.exists() or config.report_image.stat().st_size == 0:
            raise PushError(f"Failed to render report image: empty output at {config.report_image}")
        return config.report_image


def load_font(size: int, bold: bool = False):
    from PIL import ImageFont

    preferred = CHINESE_FONT_BOLD if bold else CHINESE_FONT_REGULAR
    fallback = CHINESE_FONT_FALLBACK_BOLD if bold else CHINESE_FONT_FALLBACK_REGULAR
    for font_path in [preferred, CHINESE_FONT_REGULAR, CHINESE_FONT_BOLD, fallback, CHINESE_FONT_FALLBACK_REGULAR, CHINESE_FONT_FALLBACK_BOLD]:
        if font_path.exists():
            return ImageFont.truetype(str(font_path), size)
    return ImageFont.load_default()


def wrap_text(draw: Any, text: str, font: Any, max_width: int) -> list[str]:
    text = re.sub(r"\s+", " ", text.strip())
    if not text:
        return [""]
    lines: list[str] = []
    current = ""
    for char in text:
        candidate = current + char
        if draw.textlength(candidate, font=font) <= max_width or not current:
            current = candidate
        else:
            lines.append(current)
            current = char
    if current:
        lines.append(current)
    return lines


def draw_wrapped(draw: Any, xy: tuple[int, int], text: str, font: Any, fill: str, max_width: int, line_gap: int = 8) -> int:
    x, y = xy
    line_height = int(font.size * 1.28)
    for line in wrap_text(draw, text, font, max_width):
        draw.text((x, y), line, font=font, fill=fill)
        y += line_height + line_gap
    return y


def parse_table_rows(markdown: str, heading: str, min_cells: int = 3) -> list[list[str]]:
    start = markdown.find(heading)
    if start == -1:
        return []
    section = markdown[start:]
    next_heading = section.find("\n## ", 1)
    if next_heading != -1:
        section = section[:next_heading]
    rows: list[list[str]] = []
    for line in section.splitlines():
        line = line.strip()
        if not line.startswith("|") or "---" in line:
            continue
        cells = [cell.strip().replace("<br>", " ") for cell in line.strip("|").split("|")]
        if len(cells) >= min_cells and not any(cell in {"指标", "顺序", "时间", "优先级"} for cell in cells[:1]):
            rows.append(cells)
    return rows


def short_metric(value: str) -> tuple[str, str]:
    match = re.search(r"(约\s*)?(\d+\+?)", value)
    if not match:
        return value, ""
    number = match.group(2)
    suffix = value.replace(match.group(0), "").strip(" ，,。")
    return number, suffix


def render_report_image_with_pillow(config: Config) -> Path:
    from PIL import Image, ImageDraw

    visual_text = config.visual_md.read_text(encoding="utf-8") if config.visual_md.exists() else ""
    summary = extract_report_summary(config)
    top_rows = parse_table_rows(visual_text, "## 今天最该先处理的", min_cells=3)[:8]
    priority_rows = parse_table_rows(visual_text, "## 红黄绿处理盘", min_cells=4)[:10]
    reply_rows = parse_table_rows(visual_text, "## 需要回复清单", min_cells=4)[:12]

    width = 1280
    margin = 58
    card_gap = 20
    bg = "#f4f6f8"
    ink = "#17202a"
    muted = "#5f6b7a"
    blue = "#185abc"
    red = "#c62828"
    amber = "#b26a00"
    green = "#2e7d32"

    title_font = load_font(42, bold=True)
    h2_font = load_font(28, bold=True)
    body_font = load_font(22)
    small_font = load_font(18)
    label_font = load_font(19, bold=True)

    scratch = Image.new("RGB", (width, 100), bg)
    draw = ImageDraw.Draw(scratch)
    y = margin

    def section_height_for_rows(rows: list[str], font: Any, max_width: int, base: int = 74) -> int:
        total = base
        for row in rows:
            total += max(42, len(wrap_text(draw, row, font, max_width)) * 34) + 12
        return total

    metric_rows = [
        f"已处理：{summary['processed']}",
        f"需要回复：{summary['needs_reply']}",
        f"紧急事项：{summary['urgent']}",
        f"更新时间：{summary['updated_at']}",
    ]
    top_text_rows = [f"{cells[0]}. {cells[1]}｜{cells[2]}" for cells in top_rows]
    priority_text_rows = [f"{cells[0]}｜{cells[1]}：{cells[2]}" for cells in priority_rows]
    reply_text_rows = [f"{cells[0]} {cells[1]}｜{cells[2]}：{cells[3]}" for cells in reply_rows]

    estimated_height = (
        220
        + 180
        + section_height_for_rows(top_text_rows, body_font, width - margin * 2 - 56)
        + section_height_for_rows(priority_text_rows, small_font, width - margin * 2 - 56)
        + section_height_for_rows(reply_text_rows, small_font, width - margin * 2 - 56)
        + 120
    )
    image = Image.new("RGB", (width, max(1600, estimated_height)), bg)
    draw = ImageDraw.Draw(image)

    def card(top: int, height: int, fill: str = "#ffffff") -> tuple[int, int, int, int]:
        box = (margin, top, width - margin, top + height)
        draw.rounded_rectangle(box, radius=16, fill=fill, outline="#dde3ea", width=1)
        return box

    draw.rectangle((0, 0, width, 190), fill="#16213e")
    draw.text((margin, 44), config.report_title, font=title_font, fill="#ffffff")
    draw.text((margin, 104), f"可视化图片版｜{summary['updated_at']}", font=body_font, fill="#d7e3ff")
    y = 220

    card(y, 170)
    metric_width = (width - margin * 2 - 72) // 4
    for idx, metric in enumerate(metric_rows):
        x = margin + 24 + idx * (metric_width + 24)
        color = [blue, amber, red, muted][idx]
        label, value = metric.split("：", 1)
        draw.text((x, y + 34), label, font=label_font, fill=muted)
        draw_wrapped(draw, (x, y + 72), value, body_font, color, metric_width)
    y += 190

    def draw_section(title: str, rows: list[str], accent: str, row_font: Any) -> None:
        nonlocal y
        max_text_width = width - margin * 2 - 74
        row_heights = [max(48, len(wrap_text(draw, row, row_font, max_text_width)) * 34 + 8) for row in rows]
        height = 80 + sum(row_heights) + max(0, len(rows) - 1) * 10 + 24
        card(y, height)
        draw.rounded_rectangle((margin, y, margin + 12, y + height), radius=6, fill=accent)
        draw.text((margin + 30, y + 24), title, font=h2_font, fill=ink)
        cursor = y + 82
        for row, row_height in zip(rows, row_heights):
            draw.rounded_rectangle((margin + 24, cursor - 6, width - margin - 24, cursor + row_height), radius=10, fill="#f8fafc")
            cursor = draw_wrapped(draw, (margin + 42, cursor + 8), row, row_font, ink, max_text_width)
            cursor += 16
        y += height + card_gap

    draw_section("今天最该先处理", top_text_rows or ["暂无提取到优先事项，请查看 Markdown/HTML 报告。"], red, body_font)
    draw_section("红黄绿处理盘", priority_text_rows or ["暂无提取到红黄绿事项。"], amber, small_font)
    draw_section("需要回复清单", reply_text_rows or ["暂无提取到需要回复清单。"], blue, small_font)

    footer = f"本图由 {config.visual_md.name} 生成。完整报告：{config.html_report}"
    draw_wrapped(draw, (margin, y + 22), footer, small_font, muted, width - margin * 2)
    y += 100

    cropped = image.crop((0, 0, width, min(image.height, y)))
    config.report_image.parent.mkdir(parents=True, exist_ok=True)
    cropped.save(config.report_image, "PNG", optimize=True)
    return config.report_image


def render_report_image_with_pillow(config: Config) -> Path:
    from PIL import Image, ImageDraw

    visual_text = config.visual_md.read_text(encoding="utf-8") if config.visual_md.exists() else ""
    summary = extract_report_summary(config)
    top_rows = parse_table_rows(visual_text, "## 今天最该先处理的", min_cells=3)[:6]
    priority_rows = parse_table_rows(visual_text, "## 红黄绿处理盘", min_cells=4)[:12]
    reply_rows = parse_table_rows(visual_text, "## 需要回复清单", min_cells=4)[:10]
    watch_rows = parse_table_rows(visual_text, "## 关注但不一定马上回复", min_cells=3)[:6]

    width = 1080
    margin = 52
    gutter = 20
    bg = "#edf2f7"
    ink = "#172033"
    muted = "#647084"
    soft = "#f8fafc"
    border = "#dbe3ee"
    navy = "#111c33"
    navy2 = "#1d3557"
    red = "#d92d20"
    amber = "#b7791f"
    green = "#287d3c"
    blue = "#2563eb"

    title_font = load_font(48, bold=True)
    sub_font = load_font(24)
    h_font = load_font(30, bold=True)
    body_font = load_font(23)
    small_font = load_font(19)
    tiny_font = load_font(17)
    metric_font = load_font(35, bold=True)
    pill_font = load_font(18, bold=True)

    scratch = Image.new("RGB", (width, 100), bg)
    draw = ImageDraw.Draw(scratch)

    def text_height(text: str, font: Any, max_width: int, line_gap: int = 7) -> int:
        lines = wrap_text(draw, text, font, max_width)
        return max(1, len(lines)) * int(font.size * 1.28) + max(0, len(lines) - 1) * line_gap

    def rows_height(rows: list[str], font: Any, max_width: int, pad_y: int = 20) -> int:
        return sum(max(58, text_height(row, font, max_width) + pad_y) for row in rows)

    top_items = [f"{cells[0]}. {cells[1]}｜{cells[2]}" for cells in top_rows]
    urgent_items = [f"{cells[1]}｜{cells[2]}" for cells in priority_rows if cells and cells[0] == "红"][:3]
    yellow_items = [f"{cells[1]}｜{cells[2]}" for cells in priority_rows if cells and cells[0] == "黄"][:5]
    reply_items = [f"{cells[0]} {cells[1]}｜{cells[2]}：{cells[3]}" for cells in reply_rows]
    watch_items = [f"{cells[0]}｜{cells[1]}：{cells[2]}" for cells in watch_rows]

    estimated_height = (
        300
        + 170
        + 150
        + rows_height(top_items, body_font, width - margin * 2 - 78)
        + rows_height(urgent_items + yellow_items, small_font, width - margin * 2 - 96)
        + rows_height(reply_items, small_font, width - margin * 2 - 84)
        + rows_height(watch_items, tiny_font, width - margin * 2 - 84)
        + 260
    )
    image = Image.new("RGB", (width, max(1700, estimated_height)), bg)
    draw = ImageDraw.Draw(image)

    def rounded_box(box: tuple[int, int, int, int], fill: str, outline: str = border, radius: int = 28) -> None:
        draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=1)

    def shadow_card(x1: int, y1: int, x2: int, y2: int, fill: str = "#ffffff", radius: int = 28) -> None:
        draw.rounded_rectangle((x1 + 0, y1 + 8, x2 + 0, y2 + 8), radius=radius, fill="#dce5f0")
        rounded_box((x1, y1, x2, y2), fill, radius=radius)

    def pill(x: int, y: int, text: str, fill: str, text_color: str = "#ffffff") -> int:
        w = int(draw.textlength(text, font=pill_font)) + 32
        h = 36
        draw.rounded_rectangle((x, y, x + w, y + h), radius=18, fill=fill)
        draw.text((x + 16, y + 7), text, font=pill_font, fill=text_color)
        return x + w + 10

    def draw_text_block(x: int, y: int, text: str, font: Any, fill: str, max_width: int, line_gap: int = 7) -> int:
        return draw_wrapped(draw, (x, y), text, font, fill, max_width, line_gap=line_gap)

    def metric_card(x: int, y: int, w: int, h: int, label: str, value: str, color: str) -> None:
        main, caption = short_metric(value)
        shadow_card(x, y, x + w, y + h, fill="#ffffff", radius=22)
        draw.rounded_rectangle((x, y, x + 8, y + h), radius=4, fill=color)
        draw.text((x + 24, y + 22), label, font=tiny_font, fill=muted)
        draw.text((x + 24, y + 56), main, font=metric_font, fill=color)
        if caption:
            draw_text_block(x + 24, y + 99, caption, tiny_font, muted, w - 48, line_gap=2)

    y = 0
    draw.rectangle((0, 0, width, 276), fill=navy)
    draw.rectangle((0, 190, width, 276), fill=navy2)
    draw.text((margin, 46), config.report_title, font=title_font, fill="#ffffff")
    draw.text((margin, 112), f"可视化行动版 · {summary['updated_at']}", font=sub_font, fill="#c9d7ef")
    px = margin
    px = pill(px, 176, "今日已读完", green)
    px = pill(px, 176, "需回复优先", red)
    pill(px, 176, "企业微信图报", blue)
    draw.text((margin, 228), "先看红色事项，再处理回复清单；详情仍以 Markdown/HTML 底稿为准。", font=small_font, fill="#dbe7ff")
    y = 316

    metric_w = (width - margin * 2 - gutter * 2) // 3
    metric_card(margin, y, metric_w, 136, "已处理邮件", summary["processed"], blue)
    metric_card(margin + metric_w + gutter, y, metric_w, 136, "需要回复", summary["needs_reply"], amber)
    metric_card(margin + (metric_w + gutter) * 2, y, metric_w, 136, "紧急事项", summary["urgent"], red)
    y += 176

    def draw_section_header(title: str, subtitle: str, color: str) -> None:
        nonlocal y
        draw.rounded_rectangle((margin, y, margin + 12, y + 48), radius=6, fill=color)
        draw.text((margin + 28, y + 2), title, font=h_font, fill=ink)
        draw.text((margin + 28, y + 40), subtitle, font=tiny_font, fill=muted)
        y += 78

    draw_section_header("今日最该先处理", "按影响和时效排序，适合直接照着处理", red)
    for idx, item in enumerate(top_items or ["暂无提取到优先事项，请查看详细报告。"], start=1):
        h = max(92, text_height(item, body_font, width - margin * 2 - 112) + 42)
        shadow_card(margin, y, width - margin, y + h, fill="#ffffff", radius=24)
        badge_color = red if idx <= 3 else amber if idx <= 5 else blue
        draw.ellipse((margin + 24, y + 26, margin + 64, y + 66), fill=badge_color)
        draw.text((margin + 38 - int(draw.textlength(str(idx), font=pill_font)) // 2, y + 34), str(idx), font=pill_font, fill="#ffffff")
        draw_text_block(margin + 84, y + 22, item.split(". ", 1)[-1], body_font, ink, width - margin * 2 - 116)
        y += h + 16
    y += 18

    draw_section_header("红黄绿处理盘", "红色要先打通，黄色安排跟进，绿色归档即可", amber)
    board_x1, board_x2 = margin, width - margin
    max_width = board_x2 - board_x1 - 120
    for level, color, rows in [
        ("红", red, urgent_items or ["暂无红色事项"]),
        ("黄", amber, yellow_items or ["暂无黄色事项"]),
    ]:
        h = rows_height(rows, small_font, max_width, pad_y=24) + 30
        shadow_card(board_x1, y, board_x2, y + h, fill="#ffffff", radius=24)
        draw.rounded_rectangle((board_x1 + 24, y + 24, board_x1 + 74, y + 64), radius=20, fill=color)
        draw.text((board_x1 + 40, y + 31), level, font=pill_font, fill="#ffffff")
        cursor = y + 24
        for row in rows:
            cursor = draw_text_block(board_x1 + 96, cursor + 2, row, small_font, ink, max_width)
            cursor += 14
        y += h + 16
    y += 18

    draw_section_header("需要回复清单", "按时间列出，手机上先扫发件人和动作", blue)
    for item in reply_items or ["暂无提取到需要回复清单。"]:
        h = max(62, text_height(item, small_font, width - margin * 2 - 74) + 26)
        rounded_box((margin, y, width - margin, y + h), soft, outline="#e4ebf3", radius=16)
        draw_text_block(margin + 26, y + 17, item, small_font, ink, width - margin * 2 - 74)
        y += h + 10
    y += 24

    if watch_items:
        draw_section_header("关注但不一定马上回复", "政策、单证、舱位和费用变化", green)
        for item in watch_items:
            h = max(56, text_height(item, tiny_font, width - margin * 2 - 70) + 24)
            rounded_box((margin, y, width - margin, y + h), "#ffffff", outline="#e2eadf", radius=16)
            draw_text_block(margin + 24, y + 15, item, tiny_font, ink, width - margin * 2 - 70)
            y += h + 8
        y += 20

    footer_h = 124
    shadow_card(margin, y, width - margin, y + footer_h, fill="#101828", radius=26)
    draw.text((margin + 28, y + 26), "本图为摘要版", font=small_font, fill="#ffffff")
    draw_text_block(
        margin + 28,
        y + 58,
        f"完整底稿：{config.report_md.name}｜可视化 HTML：{config.html_report.name}",
        tiny_font,
        "#c7d2e5",
        width - margin * 2 - 56,
    )
    y += footer_h + 44

    cropped = image.crop((0, 0, width, min(image.height, y)))
    config.report_image.parent.mkdir(parents=True, exist_ok=True)
    cropped.save(config.report_image, "PNG", optimize=True)
    return config.report_image


def send_report_image(config: Config) -> Path:
    image_path = render_report_image(config)
    send_image(config, image_path)
    return image_path


def file_digest(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in paths:
        digest.update(str(path).encode("utf-8"))
        if path.exists():
            digest.update(path.read_bytes())
        else:
            digest.update(b"<missing>")
    return digest.hexdigest()


def first_match(pattern: str, text: str, default: str = "未识别") -> str:
    match = re.search(pattern, text, re.MULTILINE)
    return match.group(1).strip() if match else default


def extract_top_items(visual_text: str, limit: int = 3) -> list[str]:
    marker = "## 今天最该先处理的"
    start = visual_text.find(marker)
    if start == -1:
        return []
    section = visual_text[start:]
    next_heading = section.find("\n## ", 1)
    if next_heading != -1:
        section = section[:next_heading]

    items: list[str] = []
    for line in section.splitlines():
        line = line.strip()
        if not line.startswith("|") or "---" in line or "顺序" in line:
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) >= 3 and cells[0].isdigit():
            items.append(f"{cells[0]}. {cells[1]}：{cells[2]}")
        if len(items) >= limit:
            break
    return items


def extract_report_summary(config: Config) -> dict[str, Any]:
    report_text = config.report_md.read_text(encoding="utf-8") if config.report_md.exists() else ""
    visual_text = config.visual_md.read_text(encoding="utf-8") if config.visual_md.exists() else ""
    combined = report_text + "\n" + visual_text

    updated_at = first_match(r"更新时间[:：]\s*([^\n]+)", combined, datetime.now().strftime("%Y-%m-%d %H:%M"))
    processed = first_match(r"当前已处理邮件数[:：]\s*([^\n。]+)", combined)
    needs_reply = first_match(r"需要回复/处理[:：]\s*([^\n。]+)", combined)
    urgent = first_match(r"紧急事项[:：]\s*([^\n。]+)", combined)
    if urgent == "未识别":
        urgent = first_match(r"紧急/高风险\s*\|\s*([^|]+)", visual_text)

    return {
        "updated_at": updated_at,
        "processed": processed,
        "needs_reply": needs_reply,
        "urgent": urgent,
        "top_items": extract_top_items(visual_text),
    }


def trim_for_wecom(text: str, max_bytes: int = 1800) -> str:
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    clipped = encoded[: max_bytes - len("\n\n内容较长，已截断，请查看本地HTML报告。".encode("utf-8"))]
    while True:
        try:
            return clipped.decode("utf-8") + "\n\n内容较长，已截断，请查看本地HTML报告。"
        except UnicodeDecodeError:
            clipped = clipped[:-1]


def build_update_message(config: Config, force_title: str | None = None) -> str:
    summary = extract_report_summary(config)
    top_items = summary["top_items"] or ["暂无可提取的 Top 事项，请打开本地报告查看。"]
    item_lines = "\n".join(f"> {item}" for item in top_items)
    title = force_title or "邮件简报已更新"
    content = f"""# {title}
> 更新时间：{summary["updated_at"]}
> 已处理：{summary["processed"]}
> 需要回复：{summary["needs_reply"]}
> 紧急事项：{summary["urgent"]}

**优先事项**
{item_lines}

**本地HTML报告**
`{config.html_report}`
"""
    return trim_for_wecom(content)


def build_test_message(config: Config) -> str:
    content = f"""# 邮件简报机器人连接成功
> 时间：{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
> 接收人：{config.to_user}

后续邮件简报有实质更新时，我会通过这个企业微信应用推送摘要和本地HTML报告路径。
"""
    return trim_for_wecom(content)


def append_report_log(config: Config, message: str) -> None:
    if not config.report_md.exists():
        return
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M CST")
    text = config.report_md.read_text(encoding="utf-8")
    line = f"- {stamp}：企业微信推送失败：{message}\n"
    marker = "## 更新记录\n\n"
    if marker in text:
        text = text.replace(marker, marker + line, 1)
    else:
        text += "\n## 更新记录\n\n" + line
    config.report_md.write_text(text, encoding="utf-8")


def initialize_state(config: Config, send_initial: bool = False) -> bool:
    digest = file_digest([config.report_md, config.visual_md, config.html_report])
    state = read_json(STATE_PATH)
    if state.get("last_report_hash") == digest:
        return False
    state.update(
        {
            "last_report_hash": digest,
            "last_checked_at": datetime.now().isoformat(timespec="seconds"),
            "last_push_reason": "initialized" if not send_initial else "initial_push",
        }
    )
    if send_initial:
        send_markdown(config, build_update_message(config, "邮件简报初始推送"))
        send_report_image(config)
        state["last_pushed_at"] = datetime.now().isoformat(timespec="seconds")
    write_json(STATE_PATH, state)
    return send_initial


def notify_if_changed(config: Config, send_initial: bool = False) -> bool:
    digest = file_digest([config.report_md, config.visual_md, config.html_report])
    state = read_json(STATE_PATH)
    previous_digest = state.get("last_report_hash")

    if not previous_digest:
        return initialize_state(config, send_initial=send_initial)
    if previous_digest == digest:
        state["last_checked_at"] = datetime.now().isoformat(timespec="seconds")
        write_json(STATE_PATH, state)
        return False

    send_markdown(config, build_update_message(config))
    send_report_image(config)
    state.update(
        {
            "last_report_hash": digest,
            "last_checked_at": datetime.now().isoformat(timespec="seconds"),
            "last_pushed_at": datetime.now().isoformat(timespec="seconds"),
            "last_push_reason": "report_changed",
        }
    )
    write_json(STATE_PATH, state)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Push webmail daily report updates to WeCom.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("test", help="Send a connection test message.")
    subparsers.add_parser("render-image", help="Render the visual HTML report to a PNG image.")
    subparsers.add_parser("send-image", help="Render and send the visual report image.")
    subparsers.add_parser("init", help="Initialize report hash state without sending a message.")
    changed = subparsers.add_parser("notify-if-changed", help="Send only when report files changed.")
    changed.add_argument("--send-initial", action="store_true", help="Send once if no previous state exists.")
    subparsers.add_parser("force", help="Send the current report summary regardless of state.")

    args = parser.parse_args()
    try:
        config = load_config()
        if args.command == "test":
            send_markdown(config, build_test_message(config))
            print("WeCom test message sent.")
        elif args.command == "render-image":
            image_path = render_report_image(config)
            print(f"Report image rendered: {image_path}")
        elif args.command == "send-image":
            image_path = send_report_image(config)
            print(f"WeCom report image sent: {image_path}")
        elif args.command == "init":
            initialize_state(config, send_initial=False)
            print("WeCom push state initialized.")
        elif args.command == "notify-if-changed":
            sent = notify_if_changed(config, send_initial=args.send_initial)
            print("WeCom update message sent." if sent else "No report change; no WeCom message sent.")
        elif args.command == "force":
            send_markdown(config, build_update_message(config, "邮件简报手动推送"))
            print("WeCom report summary sent.")
    except PushError as exc:
        try:
            config = load_config()
            append_report_log(config, str(exc))
        except Exception:
            pass
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
