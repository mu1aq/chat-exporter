"""Command-line interface.

    cse get   <link|file…>   extract and save (get may be omitted if the first arg is a link/file)
    cse show  <link|file>    read in the terminal
    cse info  <link|file…>   summary statistics
    cse url   <link…>        print/open the snapshot URL
    cse cache list|path|rm|clear
    cse                      interactive mode
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
        line = re.split(r"\s#", line, maxsplit=1)[0].strip()  # trailing comment (# inside a URL is kept)
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
            add(Item("standard input", "stdin"))
            continue
        p = Path(v).expanduser()
        if p.is_dir():
            files = sorted(x for x in p.iterdir() if x.is_file() and x.suffix.lower() == ".json")
            if not files:
                errors.append(f"{v}: no .json files in the folder.")
            for f in files:
                add(Item(str(f), "file", path=f))
            continue
        if p.is_file():
            add(Item(v, "file", path=p))
            continue
        if any(ch in v for ch in "*?[") and not v.lower().startswith("http"):
            matches = sorted(glob.glob(os.path.expanduser(v)))
            if not matches:
                errors.append(f"{v}: no matching files.")
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
                errors.append(f"{v}: no such file.")
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
                    ui.status("Preserving the ChatGPT share page and its media…")
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
                    ui.success(f"Fetched: {title or it.share_id}"
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
        ui.success(f"{count} artifact(s) → {root}")
    else:
        ui.hint("No artifacts to save.")
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
        ui.error("A non-empty bundle folder already exists (use --force to overwrite):\n  "
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
        ui.success(f"Preservation bundle → {folder}")
    return True


# ====================================================================== commands
def cmd_get(args: argparse.Namespace, ui: UI) -> int:
    fmt = args.format or infer_format(args.output) or "jsonl"
    if args.only and fmt in ("chat", "json"):
        ui.warn(f"--only does not apply to the {fmt} format.")
    if args.system and fmt != "chat":
        ui.warn("--system is used only with the chat format.")

    items, errors = resolve_inputs(args.inputs, args.input_file)
    for e in errors:
        ui.error(e)
    if not items:
        if not errors:
            ui.error("Provide a link or file to extract. Example: shared-chat-export https://chatgpt.com/share/…")
        return EXIT_USAGE if not errors else EXIT_FAIL

    out = args.output
    targets: List[Tuple[Path, Any]] = []  # computed ahead of time to check for overwrites before writing
    if out and out != "-" and not is_dir_target(out):
        single = Path(out).expanduser()
        if single.is_file() and not args.force:
            ui.error(f"{single} already exists. Add --force to overwrite.")
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
            ui.error("Some files already exist (use --force to overwrite):\n  " + "\n  ".join(clash))
            return EXIT_FAIL
        for p, c in targets:
            write_text(p, export([c], fmt, **kw))
        dest_label = f"{folder}{os.sep} ({len(targets)} files)"
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
        ui.success(f"{len(convs)} raw snapshot(s) → {root}")
    if args.save_artifacts:
        save_artifacts(convs, Path(args.save_artifacts).expanduser(), ui)
    if args.bundle:
        if not save_bundles(convs, Path(args.bundle).expanduser(), args.force, ui):
            return EXIT_FAIL
    if args.copy and combined is not None:
        if clipboard.write(combined):
            ui.success("Copied the result to the clipboard.")
        else:
            ui.warn("Could not copy to the clipboard. " + clipboard.missing_hint())

    if dest_label:
        ui.success(f"{len(convs)} conversation(s) · {turns_total} turns · {fmt} → {dest_label}")
    elif not ui.quiet and ui.tty and not sys.stdout.isatty():
        ui.success(f"{len(convs)} conversation(s) · {turns_total} turns · {fmt}")
    if failures:
        ui.warn(f"{len(failures)} failed.")
        return EXIT_FAIL
    return EXIT_OK


def cmd_verify(args: argparse.Namespace, ui: UI) -> int:
    target = Path(args.bundle).expanduser()
    audit_path = target if target.is_file() else target / "audit.json"
    if not audit_path.is_file():
        ui.error(f"audit.json not found: {audit_path}")
        return EXIT_FAIL
    try:
        result = verify_audit(audit_path)
    except (OSError, ValueError, json.JSONDecodeError) as e:
        ui.error(f"Could not read the audit report: {e}")
        return EXIT_FAIL
    if result["ok"]:
        ui.success(f"Integrity verified: {len(result['checked'])} files")
        return EXIT_OK
    for error in result["schema_errors"]:
        ui.error("schema: " + error)
    for path in result["missing"]:
        ui.error("missing: " + path)
    for item in result["mismatches"]:
        ui.error(f"tampered/mismatch: {item['path']}")
    return EXIT_FAIL


def _short_time(iso: Optional[str]) -> str:
    m = re.match(r"\d{4}-(\d{2})-(\d{2})[T ](\d{2}:\d{2})", iso or "")
    return f"{m.group(1)}/{m.group(2)} {m.group(3)}" if m else ""


def render_show(conv: Dict[str, Any], st: Style, uni: bool, only: Optional[str], cols: int) -> str:
    bar = "▍" if uni else "|"
    rule_ch = "─" if uni else "-"
    src = conv["source"]
    assistant = "ChatGPT" if src.get("provider") == "chatgpt" else "Claude"
    out = [st(src["title"] or assistant + " conversation", "bold")]
    meta = [src.get("share_url") or conv.get("_label") or "", _short_time(src.get("created_at")),
            f"{conv['stats']['turns']} turns"]
    if len(conv["turns"]) != conv["stats"]["turns"]:
        meta.append(f"{len(conv['turns'])} shown")
    out.append(st(" · ".join(x for x in meta if x), "dim"))
    for t in conv["turns"]:
        head = f"{rule_ch * 2} Turn {t['turn']} "
        when = _short_time(t.get("user_at"))
        line = head + rule_ch * max(3, cols - width(head) - width(when) - 2) + (" " + when if when else "")
        out.append("")
        out.append(st(line, "gray"))
        if only != "assistant":
            extra = f"  {len(t['user_input']):,} chars" + (f" · {len(t['attachments'])} attachments" if t.get("attachments") else "")
            out.append(st(bar + " User", "yellow", "bold") + st(extra, "dim"))
            out.append(t["user_input"] or st("(no input)", "dim"))
        if only != "user":
            if only != "assistant":
                out.append("")
            extra = f"  {len(t['agent_output']):,} chars" + (f" · {t['tool_call_count']} tool calls" if t["tool_call_count"] else "")
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
            out.append(t["agent_output"] or st("(no text output)", "dim"))
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
            ui.error("Provide a link or file to show.")
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
    """Warnings are shown inside the show view, so stderr warnings are suppressed."""

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
            ui.error("Provide a link or file.")
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
        tools = ", ".join(f"{k} {v}" for k, v in s["tool_calls"].items()) or "none"
        names = [a for t in c["turns"] for a in t.get("attachments") or []]
        rows = [
            ("Title", st(src["title"] or "(none)", "bold")),
            ("Share ID", src.get("share_id") or "-"),
            ("Link", src.get("share_url") or "-"),
            ("Created", (src.get("created_at") or "-").replace("T", " ")[:16]),
            ("Turns / messages", f"{s['turns']} / {s['messages']}"
             + (f"  ({s['messages_in_snapshot']} in full snapshot)" if s["messages_in_snapshot"] != s["messages"] else "")),
            ("Characters", f"user {s['user_chars']:,} · {'ChatGPT' if src.get('provider') == 'chatgpt' else 'Claude'} {s['assistant_chars']:,}"),
            ("Tool calls", tools),
            ("Attachments", f"{s['attachments']}" + (f"  ({', '.join(names[:5])}{' …' if len(names) > 5 else ''})" if names else "")),
            ("Artifacts", f"{s['artifacts']}" + (f"  ({', '.join(a['title'] for a in c['artifacts'][:5])})" if c["artifacts"] else "")),
            ("Thinking", f"{s['thinking_blocks']} blocks"),
        ]
        if src.get("model"):
            rows.insert(4, ("Model", src["model"]))
        lines = [st(pad(k, 18), "dim") + v for k, v in rows]
        lines += [st(pad("Note", 18), "dim") + st(w, "yellow") for w in c["warnings"]]
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
                    ui.warn("Could not open the browser.")
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
                ui.warn("Could not open the browser.")
    if not args.inputs:
        ui.error("Provide a share link.")
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
            ui.info("The cache is empty. " + ui.style(str(cache.dir), "dim"))
            return EXIT_OK
        st = Style(use_color(sys.stdout, args.color))
        lines = [st(f"{'Saved at':<16}  {'Share ID':<36}  Turns  Title", "dim")]
        for e in entries:
            turns = "-" if e["user_messages"] is None else str(e["user_messages"])
            lines.append(f"{e['saved_at']:<16}  {e['share_id']:<36}  {turns:>2}  {e['title']}")
        total = sum(int(e["bytes"]) for e in entries)
        lines.append(st(f"{len(entries)} entries · {total / 1024:,.0f} KB · {cache.dir}", "dim"))
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
                ui.success(f"Removed: {sid}")
            else:
                ui.warn(f"Not in cache: {sid}")
                code = EXIT_FAIL
        return code
    if action == "clear":
        n = len(cache.entries())
        if n and not args.yes:
            if not sys.stdin.isatty():
                ui.error("Add --yes to clear without confirmation.")
                return EXIT_USAGE
            ans = input(f"Clear {n} snapshot(s) from the cache? [y/N] ").strip().lower()
            if ans not in ("y", "yes"):
                ui.info("Cancelled.")
                return EXIT_OK
        ui.success(f"Cleared {cache.clear()} snapshot(s).")
        return EXIT_OK
    return EXIT_USAGE


# ====================================================================== parser
def _common(p: argparse.ArgumentParser) -> None:
    g = p.add_argument_group("general output")
    g.add_argument("-q", "--quiet", action="store_true", help="hide progress messages (errors and warnings still shown)")
    g.add_argument("--color", dest="color", action="store_const", const=True, default=None, help="always use color")
    g.add_argument("--no-color", dest="color", action="store_const", const=False, help="never use color")


def _input_opts(p: argparse.ArgumentParser) -> None:
    p.add_argument("inputs", nargs="*", metavar="INPUT",
                   help="share link, share ID, snapshot JSON file/folder/wildcard, or - (standard input)")
    g = p.add_argument_group("fetching")
    g.add_argument("-i", "--input-file", metavar="FILE", help="file listing links/paths (one per line, # comments)")
    g.add_argument("--via", choices=METHODS, default="auto",
                   help="fetch method: auto (default: direct->browser->manual), direct, browser (Playwright), manual (copy/save detection)")
    g.add_argument("--refresh", action="store_true", help="ignore the cache and fetch anew")
    g.add_argument("--no-cache", action="store_true", help="neither read nor write the cache")
    g.add_argument("--cache-dir", metavar="DIR", help="cache location (default: OS cache folder, env CSE_CACHE_DIR)")
    g.add_argument("--timeout", type=float, default=300.0, metavar="SEC", help="wait time for browser/manual modes (default 300)")
    g.add_argument("--no-open", action="store_true", help="do not auto-open the browser in manual mode")
    g.add_argument("--no-clipboard", action="store_true", help="do not watch the clipboard in manual mode")
    g.add_argument("--watch-dir", action="append", metavar="DIR",
                   help="folder to watch for a saved file in manual mode (default: downloads; may repeat)")
    g.add_argument("--delay", type=float, default=1.0, metavar="SEC", help="interval between direct requests (default 1)")
    g.add_argument("--browser-channel", choices=("chrome", "msedge", "chromium"),
                   help="browser to use in browser mode (default: chrome -> msedge -> bundled chromium)")
    g.add_argument("--browser-path", metavar="PATH", help="path to the browser executable")
    g.add_argument("--headless", action="store_true", help="do not show a browser window (may fail on a challenge page)")
    g.add_argument("--screenshot", action="store_true",
                   help="include a PNG screen capture in the bundle (a long virtualized chat may not fit in one image)")
    g.add_argument("--max-asset-mb", type=int, default=50, metavar="MB",
                   help="per-attachment/image auto-preservation limit (default 50MB)")
    e = p.add_argument_group("extraction")
    e.add_argument("--tools", action="store_true", help="include tool calls and results as tool_calls")
    e.add_argument("--thinking", action="store_true", help="include the thinking process as thinking")
    e.add_argument("--no-attachments", action="store_true", help="exclude attachment/pasted text from the input")
    e.add_argument("--no-artifacts", action="store_true", help="exclude artifact content from the output")


def _select_opts(p: argparse.ArgumentParser) -> None:
    g = p.add_argument_group("selection")
    g.add_argument("--turns", metavar="RANGE", help="turn number range. e.g. 1-3,5,8-")
    g.add_argument("--last", type=int, metavar="N", help="only the last N turns")
    g.add_argument("--grep", metavar="PATTERN", help="only turns whose input/output match a regex (case-insensitive)")
    g.add_argument("--only", choices=("user", "assistant"), help="only user input or only agent output")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="shared-chat-export",
        description="Preserve public text, branches, tools, attachments and artifacts from Claude/ChatGPT share links.",
        epilog="e.g. shared-chat-export <share link> -o chat.md   ·   cse show <link>   ·   run with no args for interactive mode",
    )
    ap.add_argument("-V", "--version", action="version", version=f"%(prog)s {__version__}")
    sub = ap.add_subparsers(dest="cmd", metavar="COMMAND")

    g = sub.add_parser("get", aliases=["extract"], help="extract and save (default command)",
                       description="Extract per-turn input/output from a link or snapshot file and save it.")
    _input_opts(g)
    _select_opts(g)
    o = g.add_argument_group("saving")
    o.add_argument("-f", "--format", choices=list(FORMATS),
                   help="format: " + "; ".join(f"{k}={v}" for k, v in DESCRIPTIONS.items())
                   + ". If omitted, inferred from the -o extension, else jsonl")
    o.add_argument("-o", "--output", metavar="PATH",
                   help="file to write. A folder (trailing /) means one file per conversation. Omitted or - means stdout")
    o.add_argument("--force", action="store_true", help="overwrite an existing file")
    o.add_argument("--copy", action="store_true", help="also copy the result to the clipboard")
    o.add_argument("--system", metavar="TEXT", help="system message to put first in the chat format")
    o.add_argument("--save-artifacts", metavar="DIR", help="save the final version of artifacts/generated files")
    o.add_argument("--save-raw", metavar="DIR", help="also save the raw snapshot JSON")
    o.add_argument("--bundle", metavar="DIR",
                   help="archive folder preserving raw, all branches, blocks, artifact versions, media, manifest and hashes")
    _common(g)
    g.set_defaults(func=cmd_get)

    s = sub.add_parser("show", help="read a conversation in the terminal", description="Show a conversation turn by turn with color.")
    _input_opts(s)
    _select_opts(s)
    s.add_argument("--no-pager", action="store_true", help="do not use a pager (less) even when long")
    _common(s)
    s.set_defaults(func=cmd_show)

    i = sub.add_parser("info", help="summary statistics", description="Summarize turn count, characters, tool calls, attachments and artifacts.")
    _input_opts(i)
    i.add_argument("--json", action="store_true", help="output as JSON")
    _common(i)
    i.set_defaults(func=cmd_info, turns=None, last=None, grep=None)

    u = sub.add_parser("url", help="print/open the snapshot URL",
                       description="Convert a share link to the snapshot JSON URL to open in a browser.")
    u.add_argument("inputs", nargs="*", metavar="LINK")
    u.add_argument("--open", action="store_true", help="open in the default browser")
    u.add_argument("--page", action="store_true", help="the share page URL instead of the snapshot")
    _common(u)
    u.set_defaults(func=cmd_url)

    c = sub.add_parser("cache", help="manage fetched snapshots", description="List or remove fetched raw snapshots.")
    c.add_argument("action", nargs="?", choices=("list", "path", "rm", "clear"), help="default: list")
    c.add_argument("ids", nargs="*", metavar="ID", help="share IDs or links to rm")
    c.add_argument("-y", "--yes", action="store_true", help="do not prompt on clear")
    c.add_argument("--cache-dir", metavar="DIR")
    _common(c)
    c.set_defaults(func=cmd_cache)

    v = sub.add_parser("verify", help="verify SHA-256 integrity of bundle files")
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
    ui.info(st("Shared chat preserver (Claude + ChatGPT)", "bold") + st(f"  v{__version__}", "dim"))
    ui.hint("Enter a claude.ai/share/… or chatgpt.com/share/… link. Separate several with spaces; empty line to quit.")
    names = list(FORMATS)
    last_fmt = "md"
    code = EXIT_OK
    while True:
        try:
            line = input(st("link/file> ", "cyan", "bold")).strip()
            if not line:
                return code
            values = _split_line(line)
            ui.info("format: " + "  ".join(f"[{n + 1}] {k}" for n, k in enumerate(names)))
            ans = input(st(f"format number or name (default {last_fmt})> ", "cyan")).strip().lower()
            if ans.isdigit() and 1 <= int(ans) <= len(names):
                last_fmt = names[int(ans) - 1]
            elif ans in FORMATS:
                last_fmt = ans
            elif ans:
                ui.warn(f"Unknown format, using {last_fmt}.")
            dest = input(st("save location (default: current folder, - for screen)> ", "cyan")).strip().strip("\"'") or "." + os.sep
        except EOFError:
            print(file=ui.stream)
            return code
        argv = ["get", *values, "-f", last_fmt, "-o", dest]
        if dest not in ("-",) and not is_dir_target(dest) and Path(dest).expanduser().exists():
            try:
                yn = input(st(f"{dest} exists. Overwrite? [y/N]> ", "yellow")).strip().lower()
            except EOFError:
                return code
            if yn in ("y", "yes"):
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
        except SystemExit as e:  # --help, --version, invalid option
            return e.code if isinstance(e.code, int) else (EXIT_OK if e.code is None else EXIT_USAGE)
        if not getattr(args, "func", None):
            build_parser().print_help(sys.stderr)
            return EXIT_USAGE
        return args.func(args, ui)
    except KeyboardInterrupt:
        ui.end_status()
        ui.warn("Cancelled.")
        return EXIT_INTERRUPT


if __name__ == "__main__":
    sys.exit(main())
