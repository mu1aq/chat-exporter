"""명령줄 인터페이스.

    cse get   <링크|파일…>   추출해서 저장 (첫 인자가 링크·파일이면 get 생략 가능)
    cse show  <링크|파일>    터미널에서 읽기
    cse info  <링크|파일…>   요약 통계
    cse url   <링크…>        스냅샷 주소 출력/열기
    cse cache list|path|rm|clear
    cse                      대화형 모드
"""

from __future__ import annotations

import argparse
import base64
import copy
import glob
import json
import mimetypes
import os
import re
import shlex
import shutil
import sys
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlsplit

from . import __version__
from . import clipboard
from .cache import SnapshotCache
from .audit import verify as verify_audit
from .bundle import write_bundle
from .chatgpt import (
    ChatGPTBrowserUnavailable,
    ChatGPTError,
    capture_chatgpt,
    chatgpt_share_id,
    extract_chatgpt,
    validate_chatgpt_url,
)
from .exporters import DESCRIPTIONS, EXT, EXT_TO_FORMAT, FORMATS, export
from .extract import Options, extract
from .fetch import METHODS, FetchError, Fetcher, describe_origin
from .select import SelectError, select_turns
from .snapshot import (
    NotAShareLink,
    SnapshotError,
    decode_bytes,
    parse_snapshot_text,
    read_text_file,
    share_id_from,
    share_page_url,
    snapshot_api_url,
)
from .term import UI, Style, page, pad, setup_streams, truncate, unicode_ok, use_color, width, write_stdout

SUBCOMMANDS = ("get", "extract", "show", "info", "url", "cache", "verify")
EXIT_OK, EXIT_FAIL, EXIT_USAGE, EXIT_INTERRUPT = 0, 1, 2, 130


# ====================================================================== inputs
@dataclass
class Item:
    label: str
    kind: str  # file | claude | chatgpt | stdin
    path: Optional[Path] = None
    share_id: Optional[str] = None
    url: Optional[str] = None


@dataclass
class Loaded:
    item: Item
    data: Dict[str, Any]
    raw: str
    origin: str
    provider: str


def _read_list_file(path: str) -> List[str]:
    text = sys.stdin.read() if path == "-" else read_text_file(path)
    out = []
    for line in text.splitlines():
        line = re.split(r"\s#", line, maxsplit=1)[0].strip()  # 줄 끝 주석 (URL 안의 #은 유지)
        if line and not line.startswith("#"):
            out.extend(line.split())
    return out


def resolve_inputs(values: List[str], input_file: Optional[str]) -> Tuple[List[Item], List[str]]:
    raw = list(values or [])
    if input_file:
        raw += _read_list_file(input_file)
    items: List[Item] = []
    errors: List[str] = []
    seen = set()

    def add(it: Item) -> None:
        key = (it.kind, str(it.path) if it.path else (it.url or it.share_id))
        if key not in seen:
            seen.add(key)
            items.append(it)

    for v in raw:
        v = v.strip().strip("\"'")
        if not v:
            continue
        if v == "-":
            add(Item("표준 입력", "stdin"))
            continue
        p = Path(v).expanduser()
        if p.is_dir():
            files = sorted(x for x in p.iterdir() if x.is_file() and x.suffix.lower() == ".json")
            if not files:
                errors.append(f"{v}: 폴더에 .json 파일이 없습니다.")
            for f in files:
                add(Item(str(f), "file", path=f))
            continue
        if p.is_file():
            add(Item(v, "file", path=p))
            continue
        if any(ch in v for ch in "*?[") and not v.lower().startswith("http"):
            matches = sorted(glob.glob(os.path.expanduser(v)))
            if not matches:
                errors.append(f"{v}: 일치하는 파일이 없습니다.")
            for m in matches:
                if Path(m).is_file():
                    add(Item(m, "file", path=Path(m)))
            continue
        try:
            if "chatgpt.com" in v.lower():
                url = validate_chatgpt_url(v)
                add(Item(v, "chatgpt", share_id=chatgpt_share_id(url), url=url))
            else:
                add(Item(v, "claude", share_id=share_id_from(v)))
        except (NotAShareLink, ValueError) as e:
            if re.search(r"[\\/]|\.json$", v) and "claude.ai" not in v:
                errors.append(f"{v}: 파일이 없습니다.")
            else:
                errors.append(str(e))
    return items, errors


def make_fetcher(args: argparse.Namespace, ui: UI) -> Fetcher:
    cache = None if args.no_cache else SnapshotCache(Path(args.cache_dir).expanduser() if args.cache_dir else None)
    watch = [Path(d).expanduser() for d in args.watch_dir] if args.watch_dir else None
    return Fetcher(via=args.via, cache=cache, refresh=args.refresh, ui=ui, timeout=args.timeout,
                   open_browser=not args.no_open, use_clipboard=not args.no_clipboard, watch_dirs=watch,
                   delay=args.delay, browser_channel=args.browser_channel, browser_path=args.browser_path,
                   headless=args.headless)


def load_items(items: List[Item], args: argparse.Namespace, ui: UI) -> Tuple[List[Loaded], List[str]]:
    loaded: List[Loaded] = []
    failures: List[str] = []
    fetcher: Optional[Fetcher] = None
    shares = sum(1 for it in items if it.kind in ("claude", "chatgpt"))
    done_shares = 0
    try:
        for it in items:
            try:
                provider = "claude"
                if it.kind == "file":
                    text, origin = read_text_file(it.path), "file"
                elif it.kind == "stdin":
                    text, origin = decode_bytes(sys.stdin.buffer.read()), "stdin"
                elif it.kind == "chatgpt":
                    done_shares += 1
                    if shares > 1:
                        ui.info(ui.style(f"[{done_shares}/{shares}] ", "dim") + it.label)
                    ui.status("ChatGPT 공유 페이지와 미디어를 보존하는 중…")
                    data = capture_chatgpt(
                        it.url or it.label,
                        timeout=args.timeout,
                        channel=args.browser_channel,
                        executable=args.browser_path,
                        headless=args.headless,
                        screenshot=bool(getattr(args, "screenshot", False)),
                        max_asset_bytes=max(1, int(getattr(args, "max_asset_mb", 50))) * 1024 * 1024,
                    )
                    ui.end_status()
                    text, origin, provider = json.dumps(data, ensure_ascii=False), "browser", "chatgpt"
                else:
                    if fetcher is None:
                        fetcher = make_fetcher(args, ui)
                    done_shares += 1
                    if shares > 1:
                        ui.info(ui.style(f"[{done_shares}/{shares}] ", "dim") + it.label)
                    text, origin = fetcher.get(it.share_id)
                if it.kind in ("file", "stdin"):
                    try:
                        candidate = json.loads(text.lstrip("\ufeff"))
                    except ValueError:
                        candidate = None
                    if isinstance(candidate, dict) and candidate.get("provider") == "chatgpt" and isinstance(candidate.get("records"), list):
                        data, provider = candidate, "chatgpt"
                    else:
                        data = parse_snapshot_text(text)
                elif it.kind != "chatgpt":
                    data = parse_snapshot_text(text)
                loaded.append(Loaded(it, data, text, origin, provider))
                if it.kind in ("claude", "chatgpt"):
                    title = data.get("title") if provider == "chatgpt" else data.get("snapshot_name")
                    ui.success(f"받았습니다: {title or it.share_id}"
                               + ui.style(f"  ({describe_origin(origin)})", "dim"))
            except (SnapshotError, FetchError, ChatGPTError, ChatGPTBrowserUnavailable, OSError) as e:
                msg = f"{it.label}: {e}"
                failures.append(msg)
                ui.error(msg)
    finally:
        if fetcher is not None:
            fetcher.close()
    return loaded, failures


def options_from(args: argparse.Namespace) -> Options:
    return Options(attachments=not args.no_attachments, artifacts=not args.no_artifacts,
                   tools=args.tools, thinking=args.thinking)


def build_convs(loaded: List[Loaded], args: argparse.Namespace, ui: UI) -> List[Dict[str, Any]]:
    opts = options_from(args)
    convs = []
    for ld in loaded:
        conv = extract_chatgpt(ld.data) if ld.provider == "chatgpt" else extract(ld.data, opts)
        conv["_label"] = ld.item.path.stem if ld.item.path else (ld.item.share_id or "snapshot")
        conv["_raw"] = ld.raw
        for w in conv["warnings"]:
            ui.warn(f"{conv['source']['title'] or conv['_label']}: {w}")
        if getattr(args, "turns", None) or getattr(args, "last", None) or getattr(args, "grep", None):
            conv = select_turns(conv, turns=args.turns, last=args.last, grep=args.grep)
        convs.append(conv)
    return convs


# ====================================================================== naming / writing
_BAD = re.compile(r'[\\/:*?"<>|\x00-\x1f]+')


def safe_name(text: str, limit: int = 60) -> str:
    s = _BAD.sub("_", str(text or "")).strip()
    s = re.sub(r"\s+", "_", s)
    s = re.sub(r"_+", "_", s).strip("._ ")
    if width(s) > limit:
        s = truncate(s, limit).rstrip("…").rstrip("._ ")
    return s or "shared-chat"


def conv_basename(conv: Dict[str, Any]) -> str:
    sid = conv["source"].get("share_id")
    title = conv["source"].get("title")
    if sid:
        return f"{safe_name(title or 'shared-chat')}_{str(sid)[:8]}"
    return safe_name(title or conv.get("_label") or "shared-chat")


def infer_format(output: Optional[str]) -> Optional[str]:
    if not output or output == "-":
        return None
    ext = Path(output).suffix.lower().lstrip(".")
    return EXT_TO_FORMAT.get(ext)


def is_dir_target(output: str) -> bool:
    return Path(output).expanduser().is_dir() or output.endswith(("/", "\\"))


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def unique(path: Path, used: set) -> Path:
    cand, n = path, 2
    while str(cand).lower() in used:
        cand = path.with_name(f"{path.stem}-{n}{path.suffix}")
        n += 1
    used.add(str(cand).lower())
    return cand


def save_artifacts(convs: List[Dict[str, Any]], root: Path, ui: UI) -> int:
    count = 0
    for c in convs:
        if not c.get("artifacts"):
            continue
        folder = root / conv_basename(c)
        used: set = set()
        for a in c["artifacts"]:
            title = Path(str(a["title"]).replace("\\", "/")).name or a["key"]
            stem = safe_name(title, 80)
            if not stem.lower().endswith("." + a["ext"].lower()):
                stem = f"{stem}.{a['ext']}"
            p = unique(folder / stem, used)
            write_text(p, a["content"])
            count += 1
    if count:
        ui.success(f"아티팩트 {count}개 → {root}")
    else:
        ui.hint("저장할 아티팩트가 없습니다.")
    return count


def _bundle_assets(conv: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Decode provider-neutral base64 assets only at bundle-write time."""
    originals = list(conv.get("assets") or [])
    # Claude snapshots expose pasted text bytes, but frequently only metadata
    # for binary files.  Save the former and explicitly manifest the latter.
    branch_nodes = (conv.get("branches") or {}).get("nodes") or []
    source_messages = [n.get("message") for n in branch_nodes if isinstance(n, dict)] or conv.get("messages") or []
    for message in source_messages:
        if not isinstance(message, dict):
            continue
        mid = str(message.get("uuid") or "message")
        for index, attachment in enumerate(message.get("attachments") or []):
            if not isinstance(attachment, dict):
                continue
            item = {"id": f"{mid}-attachment-{index}", "name": attachment.get("name") or "attachment.txt",
                    "mime": "text/plain; charset=utf-8", "source": mid}
            if attachment.get("content"):
                item["data"] = str(attachment["content"]).encode("utf-8")
            else:
                item["reason"] = "snapshot contains attachment metadata but no extracted bytes"
            originals.append(item)
        for index, file_meta in enumerate(message.get("files_meta") or []):
            if not isinstance(file_meta, dict):
                continue
            meta = file_meta.get("meta") if isinstance(file_meta.get("meta"), dict) else {}
            originals.append({"id": str(meta.get("file_uuid") or f"{mid}-file-{index}"),
                              "name": file_meta.get("name") or "file", "mime": meta.get("file_type") or "",
                              "url": meta.get("url") or meta.get("download_url"), "source": mid,
                              "reason": "binary file bytes are not present in the public Claude snapshot"})
    out = []
    seen = set()
    for original in originals:
        if not isinstance(original, dict):
            continue
        identity = str(original.get("id") or original.get("url") or original.get("name") or len(out))
        if identity in seen:
            continue
        seen.add(identity)
        asset = {k: v for k, v in original.items() if k not in ("content_base64", "data")}
        data = original.get("data")
        if data is None and isinstance(original.get("content_base64"), str):
            try:
                data = base64.b64decode(original["content_base64"], validate=True)
            except (ValueError, TypeError):
                asset["reason"] = "base64 asset data is invalid"
        if data is not None:
            asset["data"] = data
            if not asset.get("name"):
                url_name = Path(urlsplit(str(asset.get("url") or "")).path).name
                ext = mimetypes.guess_extension(str(asset.get("mime") or "").split(";", 1)[0]) or ""
                asset["name"] = url_name or str(asset.get("id") or "asset") + ext
        out.append(asset)
    return out


def save_bundles(convs: List[Dict[str, Any]], root: Path, force: bool, ui: UI) -> bool:
    """Write one complete archive directory per conversation."""
    targets = [(root if len(convs) == 1 else root / conv_basename(c), c) for c in convs]
    clashes = [p for p, _ in targets if p.exists() and any(p.iterdir())]
    if clashes and not force:
        ui.error("이미 내용이 있는 bundle 폴더가 있습니다 (덮어쓰려면 --force):\n  "
                 + "\n  ".join(str(p) for p in clashes))
        return False
    for folder, conv in targets:
        provider = conv.get("provider") or conv.get("source", {}).get("provider") or "claude"
        preservation = conv.get("preservation") or {}
        extra: Dict[str, Any] = {}
        capture = conv.get("capture") if isinstance(conv.get("capture"), dict) else {}
        if capture.get("page_html") is not None:
            extra["page.html"] = capture["page_html"]
        shot = capture.get("screenshot") if isinstance(capture.get("screenshot"), dict) else {}
        if isinstance(shot.get("content_base64"), str):
            try:
                extra["screenshot.png"] = base64.b64decode(shot["content_base64"], validate=True)
            except (ValueError, TypeError):
                preservation.setdefault("uncertain", []).append(
                    {"item": "screenshot", "reason": "screenshot base64 was invalid"})
        bundle_conv = copy.deepcopy(conv)
        bundle_conv.pop("_raw", None)
        # Binary bodies and complete page HTML remain verbatim in capture.json,
        # page.html and assets/.  Keep only their hashes/metadata in the
        # normalized conversation.json to avoid 2-3x base64 duplication.
        bundle_capture = bundle_conv.get("capture") if isinstance(bundle_conv.get("capture"), dict) else {}
        bundle_capture.pop("page_html", None)
        shot_meta = bundle_capture.get("screenshot")
        if isinstance(shot_meta, dict):
            shot_meta.pop("content_base64", None)
        for response in bundle_capture.get("responses") or []:
            if isinstance(response, dict):
                response.pop("body_base64", None)
                response.pop("text", None)
                response.pop("json", None)
        for asset in bundle_conv.get("assets") or []:
            if isinstance(asset, dict):
                asset.pop("content_base64", None)
                asset.pop("data", None)
        write_bundle(
            folder, bundle_conv, raw_source=conv.get("_raw"),
            raw_name="capture.json" if provider == "chatgpt" else "raw.json",
            transcript=export([conv], "md"), assets=_bundle_assets(conv), provider=provider,
            dropped=preservation.get("dropped"), uncertain=preservation.get("uncertain"),
            limitations=preservation.get("limitations"), extra_files=extra,
        )
        ui.success(f"보존 bundle → {folder}")
    return True


# ====================================================================== commands
def cmd_get(args: argparse.Namespace, ui: UI) -> int:
    fmt = args.format or infer_format(args.output) or "jsonl"
    if args.only and fmt in ("chat", "json"):
        ui.warn(f"--only 는 {fmt} 형식에는 적용되지 않습니다.")
    if args.system and fmt != "chat":
        ui.warn("--system 은 chat 형식에서만 쓰입니다.")

    items, errors = resolve_inputs(args.inputs, args.input_file)
    for e in errors:
        ui.error(e)
    if not items:
        if not errors:
            ui.error("추출할 링크나 파일을 넣어 주세요. 예: shared-chat-export https://chatgpt.com/share/…")
        return EXIT_USAGE if not errors else EXIT_FAIL

    out = args.output
    targets: List[Tuple[Path, Any]] = []  # 쓰기 전에 덮어쓰기 검사를 위해 미리 계산
    if out and out != "-" and not is_dir_target(out):
        single = Path(out).expanduser()
        if single.is_file() and not args.force:
            ui.error(f"{single} 파일이 이미 있습니다. 덮어쓰려면 --force 를 붙이세요.")
            return EXIT_FAIL

    loaded, failures = load_items(items, args, ui)
    failures = errors + failures
    if not loaded:
        return EXIT_FAIL
    try:
        convs = build_convs(loaded, args, ui)
    except SelectError as e:
        ui.error(str(e))
        return EXIT_USAGE

    kw = {"only": args.only, "system": args.system}
    combined: Optional[str] = None
    turns_total = sum(len(c["turns"]) for c in convs)

    if not out and args.bundle:
        dest_label = None
    elif not out or out == "-":
        combined = export(convs, fmt, **kw)
        write_stdout(combined)
        dest_label = None
    elif is_dir_target(out):
        folder = Path(out).expanduser()
        used: set = set()
        for c in convs:
            targets.append((unique(folder / f"{conv_basename(c)}.{EXT[fmt]}", used), c))
        clash = [str(p) for p, _ in targets if p.exists()]
        if clash and not args.force:
            ui.error("이미 있는 파일이 있습니다 (덮어쓰려면 --force):\n  " + "\n  ".join(clash))
            return EXIT_FAIL
        for p, c in targets:
            write_text(p, export([c], fmt, **kw))
        dest_label = f"{folder}{os.sep} (파일 {len(targets)}개)"
        if args.copy:
            combined = export(convs, fmt, **kw)
    else:
        combined = export(convs, fmt, **kw)
        write_text(Path(out).expanduser(), combined)
        dest_label = str(Path(out).expanduser())

    if args.save_raw:
        root = Path(args.save_raw).expanduser()
        for c in convs:
            write_text(root / f"{c['source'].get('share_id') or safe_name(c['_label'])}.json", c["_raw"])
        ui.success(f"원본 스냅샷 {len(convs)}개 → {root}")
    if args.save_artifacts:
        save_artifacts(convs, Path(args.save_artifacts).expanduser(), ui)
    if args.bundle:
        if not save_bundles(convs, Path(args.bundle).expanduser(), args.force, ui):
            return EXIT_FAIL
    if args.copy and combined is not None:
        if clipboard.write(combined):
            ui.success("결과를 클립보드에 복사했습니다.")
        else:
            ui.warn("클립보드에 복사하지 못했습니다. " + clipboard.missing_hint())

    if dest_label:
        ui.success(f"대화 {len(convs)}개 · 턴 {turns_total}개 · {fmt} → {dest_label}")
    elif not ui.quiet and ui.tty and not sys.stdout.isatty():
        ui.success(f"대화 {len(convs)}개 · 턴 {turns_total}개 · {fmt}")
    if failures:
        ui.warn(f"{len(failures)}개는 실패했습니다.")
        return EXIT_FAIL
    return EXIT_OK


def cmd_verify(args: argparse.Namespace, ui: UI) -> int:
    target = Path(args.bundle).expanduser()
    audit_path = target if target.is_file() else target / "audit.json"
    if not audit_path.is_file():
        ui.error(f"audit.json을 찾을 수 없습니다: {audit_path}")
        return EXIT_FAIL
    try:
        result = verify_audit(audit_path)
    except (OSError, ValueError, json.JSONDecodeError) as e:
        ui.error(f"감사 보고서를 읽지 못했습니다: {e}")
        return EXIT_FAIL
    if result["ok"]:
        ui.success(f"무결성 확인 완료: {len(result['checked'])}개 파일")
        return EXIT_OK
    for error in result["schema_errors"]:
        ui.error("스키마: " + error)
    for path in result["missing"]:
        ui.error("누락: " + path)
    for item in result["mismatches"]:
        ui.error(f"변조/불일치: {item['path']}")
    return EXIT_FAIL


def _short_time(iso: Optional[str]) -> str:
    m = re.match(r"\d{4}-(\d{2})-(\d{2})[T ](\d{2}:\d{2})", iso or "")
    return f"{m.group(1)}/{m.group(2)} {m.group(3)}" if m else ""


def render_show(conv: Dict[str, Any], st: Style, uni: bool, only: Optional[str], cols: int) -> str:
    bar = "▍" if uni else "|"
    rule_ch = "─" if uni else "-"
    src = conv["source"]
    assistant = "ChatGPT" if src.get("provider") == "chatgpt" else "Claude"
    out = [st(src["title"] or assistant + " 대화", "bold")]
    meta = [src.get("share_url") or conv.get("_label") or "", _short_time(src.get("created_at")),
            f"턴 {conv['stats']['turns']}개"]
    if len(conv["turns"]) != conv["stats"]["turns"]:
        meta.append(f"{len(conv['turns'])}개 표시")
    out.append(st(" · ".join(x for x in meta if x), "dim"))
    for t in conv["turns"]:
        head = f"{rule_ch * 2} 턴 {t['turn']} "
        when = _short_time(t.get("user_at"))
        line = head + rule_ch * max(3, cols - width(head) - width(when) - 2) + (" " + when if when else "")
        out.append("")
        out.append(st(line, "gray"))
        if only != "assistant":
            extra = f"  {len(t['user_input']):,}자" + (f" · 첨부 {len(t['attachments'])}" if t.get("attachments") else "")
            out.append(st(bar + " 사용자", "yellow", "bold") + st(extra, "dim"))
            out.append(t["user_input"] or st("(입력 없음)", "dim"))
        if only != "user":
            if only != "assistant":
                out.append("")
            extra = f"  {len(t['agent_output']):,}자" + (f" · 도구 {t['tool_call_count']}회" if t["tool_call_count"] else "")
            out.append(st(bar + " " + assistant, "cyan", "bold") + st(extra, "dim"))
            if t.get("thinking"):
                pre = "│ " if uni else "| "
                out.append(st("\n".join(pre + ln for ln in t["thinking"].splitlines()), "dim"))
            for c in t.get("tool_calls") or []:
                arg = json.dumps(c.get("input"), ensure_ascii=False) if c.get("input") is not None else ""
                res = (c.get("result") or "").replace("\n", " ")
                mark = "⚙ " if uni else "* "
                out.append(st(f"{mark}{c['name']} {truncate(arg, max(20, cols - 8))}", "magenta"))
                if res:
                    out.append(st(f"  → {truncate(res, max(20, cols - 6))}", "dim"))
            out.append(t["agent_output"] or st("(텍스트 출력 없음)", "dim"))
    for w in conv.get("warnings") or []:
        out.append("")
        out.append(st("! " + w, "yellow"))
    return "\n".join(out) + "\n"


def cmd_show(args: argparse.Namespace, ui: UI) -> int:
    items, errors = resolve_inputs(args.inputs, args.input_file)
    for e in errors:
        ui.error(e)
    if not items:
        if not errors:
            ui.error("보여줄 링크나 파일을 넣어 주세요.")
        return EXIT_USAGE if not errors else EXIT_FAIL
    loaded, failures = load_items(items, args, ui)
    if not loaded:
        return EXIT_FAIL
    try:
        convs = build_convs(loaded, args, NullWarn(ui))
    except SelectError as e:
        ui.error(str(e))
        return EXIT_USAGE
    st = Style(use_color(sys.stdout, args.color))
    cols = min(100, shutil.get_terminal_size((88, 24)).columns)
    text = "\n\n".join(render_show(c, st, unicode_ok(sys.stdout), args.only, cols) for c in convs)
    page(text, use_pager=not args.no_pager)
    return EXIT_FAIL if failures or errors else EXIT_OK


class NullWarn(UI):
    """show 화면 안에 경고를 넣으므로 stderr 경고는 생략합니다."""

    def __init__(self, base: UI) -> None:
        self.__dict__.update(base.__dict__)

    def warn(self, msg: str) -> None:
        pass


def cmd_info(args: argparse.Namespace, ui: UI) -> int:
    items, errors = resolve_inputs(args.inputs, args.input_file)
    for e in errors:
        ui.error(e)
    if not items:
        if not errors:
            ui.error("링크나 파일을 넣어 주세요.")
        return EXIT_USAGE if not errors else EXIT_FAIL
    loaded, failures = load_items(items, args, ui)
    convs = build_convs(loaded, args, NullWarn(ui))
    if args.json:
        payload = [{"source": c["source"], "stats": c["stats"], "warnings": c["warnings"],
                    "artifacts": [{"title": a["title"], "ext": a["ext"], "versions": a["versions"],
                                   "chars": len(a["content"])} for a in c["artifacts"]]} for c in convs]
        write_stdout(json.dumps(payload[0] if len(payload) == 1 else payload, ensure_ascii=False, indent=2) + "\n")
        return EXIT_FAIL if failures or errors else EXIT_OK
    st = Style(use_color(sys.stdout, args.color))
    blocks = []
    for c in convs:
        s, src = c["stats"], c["source"]
        tools = ", ".join(f"{k} {v}" for k, v in s["tool_calls"].items()) or "없음"
        names = [a for t in c["turns"] for a in t.get("attachments") or []]
        rows = [
            ("제목", st(src["title"] or "(없음)", "bold")),
            ("공유 ID", src.get("share_id") or "-"),
            ("링크", src.get("share_url") or "-"),
            ("만든 시각", (src.get("created_at") or "-").replace("T", " ")[:16]),
            ("턴 / 메시지", f"{s['turns']} / {s['messages']}"
             + (f"  (스냅샷 전체 {s['messages_in_snapshot']})" if s["messages_in_snapshot"] != s["messages"] else "")),
            ("글자 수", f"사용자 {s['user_chars']:,} · {'ChatGPT' if src.get('provider') == 'chatgpt' else 'Claude'} {s['assistant_chars']:,}"),
            ("도구 호출", tools),
            ("첨부", f"{s['attachments']}" + (f"  ({', '.join(names[:5])}{' …' if len(names) > 5 else ''})" if names else "")),
            ("아티팩트", f"{s['artifacts']}" + (f"  ({', '.join(a['title'] for a in c['artifacts'][:5])})" if c["artifacts"] else "")),
            ("생각 과정", f"{s['thinking_blocks']}개 블록"),
        ]
        if src.get("model"):
            rows.insert(4, ("모델", src["model"]))
        lines = [st(pad(k, 13), "dim") + v for k, v in rows]
        lines += [st(pad("주의", 13), "dim") + st(w, "yellow") for w in c["warnings"]]
        blocks.append("\n".join(lines))
    write_stdout("\n\n".join(blocks) + ("\n" if blocks else ""))
    return EXIT_FAIL if failures or errors or not convs else EXIT_OK


def cmd_url(args: argparse.Namespace, ui: UI) -> int:
    code = EXIT_OK
    for v in args.inputs:
        if "chatgpt.com" in v.lower():
            try:
                url = validate_chatgpt_url(v)
            except ValueError as e:
                ui.error(str(e))
                code = EXIT_FAIL
                continue
            write_stdout(url + "\n")
            if args.open:
                try:
                    webbrowser.open(url, new=2)
                except Exception:
                    ui.warn("브라우저를 열지 못했습니다.")
            continue
        try:
            sid = share_id_from(v)
        except NotAShareLink as e:
            ui.error(str(e))
            code = EXIT_FAIL
            continue
        url = share_page_url(sid) if args.page else snapshot_api_url(sid)
        write_stdout(url + "\n")
        if args.open:
            try:
                webbrowser.open(url, new=2)
            except Exception:
                ui.warn("브라우저를 열지 못했습니다.")
    if not args.inputs:
        ui.error("공유 링크를 넣어 주세요.")
        return EXIT_USAGE
    return code


def cmd_cache(args: argparse.Namespace, ui: UI) -> int:
    cache = SnapshotCache(Path(args.cache_dir).expanduser() if args.cache_dir else None)
    action = args.action or "list"
    if action == "path":
        write_stdout(str(cache.dir) + "\n")
        return EXIT_OK
    if action == "list":
        entries = cache.entries()
        if not entries:
            ui.info("캐시가 비어 있습니다. " + ui.style(str(cache.dir), "dim"))
            return EXIT_OK
        st = Style(use_color(sys.stdout, args.color))
        lines = [st(f"{'저장 시각':<16}  {'공유 ID':<36}  턴  제목", "dim")]
        for e in entries:
            turns = "-" if e["user_messages"] is None else str(e["user_messages"])
            lines.append(f"{e['saved_at']:<16}  {e['share_id']:<36}  {turns:>2}  {e['title']}")
        total = sum(int(e["bytes"]) for e in entries)
        lines.append(st(f"{len(entries)}개 · {total / 1024:,.0f} KB · {cache.dir}", "dim"))
        write_stdout("\n".join(lines) + "\n")
        return EXIT_OK
    if action == "rm":
        code = EXIT_OK
        for v in args.ids:
            try:
                sid = share_id_from(v)
            except NotAShareLink:
                sid = v
            if cache.remove(sid):
                ui.success(f"지웠습니다: {sid}")
            else:
                ui.warn(f"캐시에 없습니다: {sid}")
                code = EXIT_FAIL
        return code
    if action == "clear":
        n = len(cache.entries())
        if n and not args.yes:
            if not sys.stdin.isatty():
                ui.error("확인 없이 지우려면 --yes 를 붙이세요.")
                return EXIT_USAGE
            ans = input(f"캐시의 스냅샷 {n}개를 지울까요? [y/N] ").strip().lower()
            if ans not in ("y", "yes", "ㅛ"):
                ui.info("취소했습니다.")
                return EXIT_OK
        ui.success(f"스냅샷 {cache.clear()}개를 지웠습니다.")
        return EXIT_OK
    return EXIT_USAGE


# ====================================================================== parser
def _common(p: argparse.ArgumentParser) -> None:
    g = p.add_argument_group("출력 일반")
    g.add_argument("-q", "--quiet", action="store_true", help="진행 메시지를 숨김 (오류·경고는 표시)")
    g.add_argument("--color", dest="color", action="store_const", const=True, default=None, help="항상 색 사용")
    g.add_argument("--no-color", dest="color", action="store_const", const=False, help="색 사용 안 함")


def _input_opts(p: argparse.ArgumentParser) -> None:
    p.add_argument("inputs", nargs="*", metavar="입력",
                   help="공유 링크, 공유 ID, 스냅샷 JSON 파일·폴더·와일드카드, 또는 - (표준 입력)")
    g = p.add_argument_group("가져오기")
    g.add_argument("-i", "--input-file", metavar="파일", help="링크·경로 목록 파일 (한 줄에 하나, # 주석)")
    g.add_argument("--via", choices=METHODS, default="auto",
                   help="받는 방법: auto(기본, 직접→브라우저→수동), direct, browser(Playwright), manual(복사/저장 감지)")
    g.add_argument("--refresh", action="store_true", help="캐시를 무시하고 새로 받기")
    g.add_argument("--no-cache", action="store_true", help="캐시를 읽지도 쓰지도 않기")
    g.add_argument("--cache-dir", metavar="폴더", help="캐시 위치 (기본: OS 캐시 폴더, 환경변수 CSE_CACHE_DIR)")
    g.add_argument("--timeout", type=float, default=300.0, metavar="초", help="브라우저·수동 모드 대기 시간 (기본 300)")
    g.add_argument("--no-open", action="store_true", help="수동 모드에서 브라우저를 자동으로 열지 않기")
    g.add_argument("--no-clipboard", action="store_true", help="수동 모드에서 클립보드 감시 안 함")
    g.add_argument("--watch-dir", action="append", metavar="폴더",
                   help="수동 모드에서 저장 파일을 기다릴 폴더 (기본: 다운로드 폴더, 여러 번 지정 가능)")
    g.add_argument("--delay", type=float, default=1.0, metavar="초", help="직접 요청 사이 간격 (기본 1)")
    g.add_argument("--browser-channel", choices=("chrome", "msedge", "chromium"),
                   help="브라우저 모드에서 쓸 브라우저 (기본: chrome → msedge → 내장 chromium)")
    g.add_argument("--browser-path", metavar="경로", help="브라우저 실행 파일 경로를 직접 지정")
    g.add_argument("--headless", action="store_true", help="브라우저 창을 띄우지 않기 (확인 화면이 뜨면 실패할 수 있음)")
    g.add_argument("--screenshot", action="store_true",
                   help="보존 bundle에 PNG 화면 캡처 포함 (가상화된 긴 대화는 한 장에 모두 안 나올 수 있음)")
    g.add_argument("--max-asset-mb", type=int, default=50, metavar="MB",
                   help="첨부·이미지 한 개당 자동 보존 상한 (기본 50MB)")
    e = p.add_argument_group("추출")
    e.add_argument("--tools", action="store_true", help="도구 호출과 결과를 tool_calls 로 포함")
    e.add_argument("--thinking", action="store_true", help="생각 과정을 thinking 으로 포함")
    e.add_argument("--no-attachments", action="store_true", help="첨부·붙여넣은 텍스트를 입력에서 제외")
    e.add_argument("--no-artifacts", action="store_true", help="아티팩트 내용을 출력에서 제외")


def _select_opts(p: argparse.ArgumentParser) -> None:
    g = p.add_argument_group("고르기")
    g.add_argument("--turns", metavar="범위", help="턴 번호 범위. 예: 1-3,5,8-")
    g.add_argument("--last", type=int, metavar="N", help="마지막 N개 턴만")
    g.add_argument("--grep", metavar="패턴", help="입력·출력에 정규식이 들어 있는 턴만 (대소문자 무시)")
    g.add_argument("--only", choices=("user", "assistant"), help="사용자 입력만 또는 에이전트 출력만")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="shared-chat-export",
        description="Claude·ChatGPT 공유 링크에서 공개된 원문, 분기, 도구, 첨부, 아티팩트를 보존합니다.",
        epilog="예: shared-chat-export <공유 링크> -o 대화.md   ·   cse show <링크>   ·   인자 없이 실행하면 대화형 모드",
    )
    ap.add_argument("-V", "--version", action="version", version=f"%(prog)s {__version__}")
    sub = ap.add_subparsers(dest="cmd", metavar="명령")

    g = sub.add_parser("get", aliases=["extract"], help="추출해서 저장 (기본 명령)",
                       description="링크나 스냅샷 파일에서 턴별 입력·출력을 뽑아 저장합니다.")
    _input_opts(g)
    _select_opts(g)
    o = g.add_argument_group("저장")
    o.add_argument("-f", "--format", choices=list(FORMATS),
                   help="형식: " + "; ".join(f"{k}={v}" for k, v in DESCRIPTIONS.items())
                   + ". 생략하면 -o 확장자로 추정, 그것도 없으면 jsonl")
    o.add_argument("-o", "--output", metavar="경로",
                   help="저장할 파일. 폴더(끝에 /)면 대화마다 파일 하나. 생략하거나 - 면 화면(표준 출력)")
    o.add_argument("--force", action="store_true", help="이미 있는 파일 덮어쓰기")
    o.add_argument("--copy", action="store_true", help="결과를 클립보드에도 복사")
    o.add_argument("--system", metavar="문장", help="chat 형식에서 맨 앞에 넣을 system 메시지")
    o.add_argument("--save-artifacts", metavar="폴더", help="아티팩트·생성 파일의 최종본을 파일로 저장")
    o.add_argument("--save-raw", metavar="폴더", help="원본 스냅샷 JSON도 저장")
    o.add_argument("--bundle", metavar="폴더",
                   help="원본·모든 분기·블록·Artifact 버전·미디어·manifest·해시를 보존하는 archive 폴더")
    _common(g)
    g.set_defaults(func=cmd_get)

    s = sub.add_parser("show", help="터미널에서 대화 읽기", description="대화를 턴별로 색을 입혀 보여줍니다.")
    _input_opts(s)
    _select_opts(s)
    s.add_argument("--no-pager", action="store_true", help="길어도 페이저(less)를 쓰지 않기")
    _common(s)
    s.set_defaults(func=cmd_show)

    i = sub.add_parser("info", help="요약 통계", description="턴 수, 글자 수, 도구 호출, 첨부, 아티팩트를 요약합니다.")
    _input_opts(i)
    i.add_argument("--json", action="store_true", help="JSON으로 출력")
    _common(i)
    i.set_defaults(func=cmd_info, turns=None, last=None, grep=None)

    u = sub.add_parser("url", help="스냅샷 주소 출력·열기",
                       description="공유 링크를 브라우저에서 열 스냅샷 JSON 주소로 바꿉니다.")
    u.add_argument("inputs", nargs="*", metavar="링크")
    u.add_argument("--open", action="store_true", help="기본 브라우저로 열기")
    u.add_argument("--page", action="store_true", help="스냅샷 대신 공유 페이지 주소")
    _common(u)
    u.set_defaults(func=cmd_url)

    c = sub.add_parser("cache", help="받아둔 스냅샷 관리", description="받아둔 원본 스냅샷을 보거나 지웁니다.")
    c.add_argument("action", nargs="?", choices=("list", "path", "rm", "clear"), help="기본 list")
    c.add_argument("ids", nargs="*", metavar="ID", help="rm 할 공유 ID나 링크")
    c.add_argument("-y", "--yes", action="store_true", help="clear 할 때 묻지 않기")
    c.add_argument("--cache-dir", metavar="폴더")
    _common(c)
    c.set_defaults(func=cmd_cache)

    v = sub.add_parser("verify", help="bundle 파일들의 SHA-256 무결성 검증")
    v.add_argument("bundle", metavar="BUNDLE|AUDIT.JSON")
    _common(v)
    v.set_defaults(func=cmd_verify)
    return ap


# ====================================================================== interactive
def _split_line(line: str) -> List[str]:
    try:
        parts = shlex.split(line, posix=os.name != "nt")
    except ValueError:
        parts = line.split()
    return [p.strip("\"'") for p in parts if p.strip("\"'")]


def interactive(ui: UI) -> int:
    st = ui.style
    ui.info(st("공유 대화 보존기 (Claude + ChatGPT)", "bold") + st(f"  v{__version__}", "dim"))
    ui.hint("claude.ai/share/… 또는 chatgpt.com/share/… 링크를 넣으세요. 여러 개는 공백으로, 끝내려면 빈 줄.")
    names = list(FORMATS)
    last_fmt = "md"
    code = EXIT_OK
    while True:
        try:
            line = input(st("링크/파일> ", "cyan", "bold")).strip()
            if not line:
                return code
            values = _split_line(line)
            ui.info("형식: " + "  ".join(f"[{n + 1}] {k}" for n, k in enumerate(names)))
            ans = input(st(f"형식 번호나 이름 (기본 {last_fmt})> ", "cyan")).strip().lower()
            if ans.isdigit() and 1 <= int(ans) <= len(names):
                last_fmt = names[int(ans) - 1]
            elif ans in FORMATS:
                last_fmt = ans
            elif ans:
                ui.warn(f"알 수 없는 형식이라 {last_fmt}로 합니다.")
            dest = input(st("저장 위치 (기본: 현재 폴더, - 는 화면)> ", "cyan")).strip().strip("\"'") or "." + os.sep
        except EOFError:
            print(file=ui.stream)
            return code
        argv = ["get", *values, "-f", last_fmt, "-o", dest]
        if dest not in ("-",) and not is_dir_target(dest) and Path(dest).expanduser().exists():
            try:
                yn = input(st(f"{dest} 파일이 있습니다. 덮어쓸까요? [y/N]> ", "yellow")).strip().lower()
            except EOFError:
                return code
            if yn in ("y", "yes", "ㅛ"):
                argv.append("--force")
            else:
                continue
        args = build_parser().parse_args(argv)
        args.quiet = ui.quiet
        args.color = None
        r = args.func(args, ui)
        code = r if r != EXIT_OK else code
        print(file=ui.stream)


# ====================================================================== main
def main(argv: Optional[List[str]] = None) -> int:
    setup_streams()
    argv = list(sys.argv[1:] if argv is None else argv)
    pre_quiet = "-q" in argv or "--quiet" in argv
    pre_color = False if "--no-color" in argv else (True if "--color" in argv else None)
    ui = UI(quiet=pre_quiet, color=pre_color)
    try:
        if not argv:
            if sys.stdin.isatty():
                return interactive(ui)
            build_parser().print_help(sys.stderr)
            return EXIT_USAGE
        if argv[0] not in SUBCOMMANDS and argv[0] not in ("-h", "--help", "-V", "--version"):
            argv.insert(0, "get")
        try:
            args = build_parser().parse_args(argv)
        except SystemExit as e:  # --help, --version, 잘못된 옵션
            return e.code if isinstance(e.code, int) else (EXIT_OK if e.code is None else EXIT_USAGE)
        if not getattr(args, "func", None):
            build_parser().print_help(sys.stderr)
            return EXIT_USAGE
        return args.func(args, ui)
    except KeyboardInterrupt:
        ui.end_status()
        ui.warn("취소했습니다.")
        return EXIT_INTERRUPT


if __name__ == "__main__":
    sys.exit(main())
