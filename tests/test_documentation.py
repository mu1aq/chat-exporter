import json
import re
import tempfile
import unittest

try:
    import tomllib
except ModuleNotFoundError:  # Python < 3.11
    import tomli as tomllib
from pathlib import Path
from urllib.parse import unquote, urlsplit

from jsonschema import Draft202012Validator

from shared_chat_exporter.bundle import write_bundle
from shared_chat_exporter.chatgpt import extract_chatgpt
from shared_chat_exporter.cli import build_parser
from shared_chat_exporter.exporters import export
from shared_chat_exporter.extract import Options, extract

from helpers import fixture, fixture_text


ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
SCHEMAS = ROOT / "schemas"


def load_schema(name):
    return json.loads((SCHEMAS / name).read_text(encoding="utf-8"))


def validate_json(schema_name, value):
    Draft202012Validator(load_schema(schema_name)).validate(value)


def all_parser_options(parser):
    found = set()
    seen = set()

    def visit(current):
        if id(current) in seen:
            return
        seen.add(id(current))
        for action in current._actions:
            found.update(opt for opt in action.option_strings if opt.startswith("--"))
            choices = getattr(action, "choices", None)
            if isinstance(choices, dict):
                for child in choices.values():
                    visit(child)

    visit(parser)
    return found


class DocumentationTest(unittest.TestCase):
    def test_required_document_set_exists(self):
        names = {
            "README.md", "installation.md", "cli-reference.md", "output-formats.md",
            "archive-format.md", "providers.md", "faq.md", "security.md",
            "troubleshooting.md", "python-api.md", "architecture.md",
            "development.md", "refactoring.md", "future-sessions.md",
        }
        self.assertEqual({p.name for p in DOCS.glob("*.md")}, names)

    def test_all_relative_markdown_links_stay_inside_project_and_exist(self):
        pattern = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
        failures = []
        for path in ROOT.rglob("*.md"):
            if ".venv" in path.parts:  # installed virtualenvs are not project docs
                continue
            text = path.read_text(encoding="utf-8")
            for target in pattern.findall(text):
                target = target.strip().strip("<>")
                parsed = urlsplit(target)
                if parsed.scheme or target.startswith("#"):
                    continue
                resolved = (path.parent / unquote(parsed.path)).resolve()
                if ROOT not in (resolved, *resolved.parents) or not resolved.exists():
                    failures.append((str(path.relative_to(ROOT)), target))
        self.assertEqual(failures, [])

    def test_cli_reference_mentions_every_long_option(self):
        text = (DOCS / "cli-reference.md").read_text(encoding="utf-8")
        missing = sorted(opt for opt in all_parser_options(build_parser()) if opt not in text)
        self.assertEqual(missing, [])
        self.assertIn("--detect", text)

    def test_json_schemas_parse_and_have_internal_ids(self):
        expected = {
            "conversation.schema.json", "capture.schema.json",
            "manifest.schema.json", "audit.schema.json",
        }
        self.assertEqual({p.name for p in SCHEMAS.glob("*.json")}, expected)
        for path in SCHEMAS.glob("*.json"):
            value = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(value["$schema"], "https://json-schema.org/draft/2020-12/schema")
            self.assertTrue(value["$id"].startswith("urn:shared-chat-exporter:schema:"))
            self.assertEqual(value["type"], "object")
            self.assertTrue(value["required"])

    def test_schemas_validate_real_claude_bundle(self):
        conversation = extract(fixture("rich.json"), Options(tools=True, thinking=True))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_bundle(
                root,
                conversation,
                raw_source=fixture_text("rich.json"),
                transcript=export([conversation], "md"),
            )
            for schema_name, file_name in (
                ("conversation.schema.json", "conversation.json"),
                ("manifest.schema.json", "manifest.json"),
                ("audit.schema.json", "audit.json"),
            ):
                validate_json(schema_name, json.loads((root / file_name).read_text(encoding="utf-8")))

    def test_schemas_validate_chatgpt_capture_and_bundle(self):
        capture = {
            "provider": "chatgpt",
            "source_url": "https://chatgpt.com/share/12345678",
            "final_url": "https://chatgpt.com/share/12345678",
            "http_status": 200,
            "title": "Example",
            "document_language": "ko",
            "body_text": "hello",
            "page_html": "<html></html>",
            "scripts": [],
            "responses": [],
            "assets": [],
            "observations": [2],
            "records": [
                {
                    "role": "user", "source_id": "u1", "turn_index": 1,
                    "plain_text": "hello", "text_content": "hello",
                    "html": "<div>hello</div>", "outer_html": "<div>hello</div>",
                    "resources": [], "source": "dom",
                },
                {
                    "role": "assistant", "source_id": "a1", "turn_index": 2,
                    "plain_text": "answer", "text_content": "answer",
                    "html": "<p>answer</p>", "outer_html": "<div>answer</div>",
                    "resources": [], "source": "dom",
                },
            ],
            "traversal": {
                "toc_prompt_count": 1,
                "toc_prompts_visited": 1,
                "unique_message_counts": [2],
                "deadline_reached": False,
            },
        }
        validate_json("capture.schema.json", capture)
        conversation = extract_chatgpt(capture)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_bundle(root, conversation, provider="chatgpt")
            for schema_name, file_name in (
                ("conversation.schema.json", "conversation.json"),
                ("manifest.schema.json", "manifest.json"),
                ("audit.schema.json", "audit.json"),
            ):
                validate_json(schema_name, json.loads((root / file_name).read_text(encoding="utf-8")))

    def test_python_support_floor_is_310(self):
        project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(project["project"]["requires-python"], ">=3.10")
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        self.assertIn('python-version: ["3.10", "3.11", "3.12", "3.13", "3.14"]', workflow)


if __name__ == "__main__":
    unittest.main()
