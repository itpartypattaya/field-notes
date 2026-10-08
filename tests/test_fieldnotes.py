"""Тесты fieldnotes.py: `py -3 -m unittest discover -s tests` из корня репозитория."""

import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
import fieldnotes as fn  # noqa: E402

LEGACY_INDEX = """# Field Notes — тест

Ручная шапка, которая должна пережить пересборку.

## Индекс

| Date | Note | Area | Status | Candidate skill | Summary |
|---|---|---|---|---|---|
| 2026-09-11 · обн. 10-04 | [TZ врёт](notes/2026-09-11-tz.md) | git bash | active | — | `TZ=Asia/Bangkok` даёт UTC, промах 7 часов |
| 2026-09-12 | [Кадр врёт](notes/2026-09-12-frame.md) | browser | promoted to skill (`ui-verify`) | `ui-verify` | снимок до композитинга `a | b` с пайпом |
"""

LEGACY_TZ = """# `TZ=Asia/Bangkok` в Git Bash молча даёт UTC
- **Date:** 2026-09-11 · **Area:** windows / git bash · **Status:** active

## Контекст
Git Bash, /c/Users/someone/project.

## Симптом
`02:18` вместо `09:18`.

## Обновление 04.10: сервер не в UTC
Текст.
"""

LEGACY_FRAME = """# Кадр врёт
- **Date:** 2026-09-12 · дополнения 13.09, 17.09 · **Area:** browser pane · **Status:** promoted to skill (`ui-verify`)

## Симптом
Пусто.
"""


class StoreCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="fn-test-"))
        self.store = self.tmp / "store"
        self.env = {"FIELDNOTES_TODAY": "2026-10-08", "FIELD_NOTES_DIR": str(self.store)}
        self.old_env = {k: os.environ.get(k) for k in self.env}
        os.environ.update(self.env)

    def tearDown(self):
        for k, v in self.old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = fn.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def ctx(self):
        class A:
            root = None
            read_only = False
        return fn.Context(A())

    def write_note(self, note_id, **meta):
        base = {"schema_version": 1, "id": note_id, "title": "Заголовок", "date": note_id[:10],
                "area": "git", "status": "active", "summary": "плотная строка"}
        base.update(meta)
        body = meta.pop("body", None) or f"# {base['title']}\n\n## Симптом\nтекст\n"
        base.pop("body", None)
        path = self.store / "notes" / f"{note_id}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(fn.dump_frontmatter(base) + body, encoding="utf-8")
        return path

    def make_legacy(self):
        src = self.tmp / "legacy"
        (src / "notes").mkdir(parents=True)
        (src / "INDEX.md").write_text(LEGACY_INDEX, encoding="utf-8")
        (src / "notes" / "2026-09-11-tz.md").write_text(LEGACY_TZ, encoding="utf-8")
        (src / "notes" / "2026-09-12-frame.md").write_text(LEGACY_FRAME, encoding="utf-8")
        return src


class FrontmatterTest(unittest.TestCase):
    def test_roundtrip_quotes_colons_lists_cyrillic(self):
        meta = {"schema_version": 1, "title": 'Флаг `--x` "ломает": всё', "date": "2026-10-08",
                "tags": ['a"b', "c,d", "кириллица"], "summary": "1:30 # не комментарий", "area": "yes"}
        back, _, body, errors = fn.split_frontmatter(fn.dump_frontmatter(meta) + "тело\n")
        self.assertEqual(errors, [])
        self.assertEqual(back, meta)
        self.assertEqual(body, "тело\n")

    def test_bad_frontmatter_is_reported(self):
        self.assertTrue(fn.split_frontmatter("без шапки")[3])
        self.assertTrue(fn.split_frontmatter("---\ntitle: x\n  nested: y\n---\n")[3])
        self.assertTrue(fn.split_frontmatter("---\ntitle: x\n---oops\n")[3])


class NewAndIndexTest(StoreCase):
    def test_new_uses_today_and_never_overwrites(self):
        code, out, _ = self.run_cli("new", "my-bug", "--title", "Флаг молча ломает сборку", "--area", "npm")
        self.assertEqual(code, 0)
        path = Path(out.strip())
        self.assertEqual(path.name, "2026-10-08-my-bug.md")
        note = fn.Note(path)
        self.assertEqual(note.errors, [])
        self.assertEqual(note.get("title"), "Флаг молча ломает сборку")
        self.assertEqual(note.get("area"), "npm")
        code, _, err = self.run_cli("new", "my-bug", "--title", "другое")
        self.assertEqual(code, fn.EXIT_EXISTS)
        self.assertIn("обновление", err)

    def test_new_warns_about_similar_note(self):
        self.write_note("2026-09-01-ssh-pkill", title="ssh pkill убивает собственную команду")
        code, _, err = self.run_cli("new", "other", "--title", "Снова ssh pkill и собственная команда")
        self.assertEqual(code, fn.EXIT_EXISTS)
        self.assertIn("2026-09-01-ssh-pkill", err)
        code, _, _ = self.run_cli("new", "other", "--title", "Снова ssh pkill и собственная команда", "--force")
        self.assertEqual(code, 0)

    def test_index_keeps_head_and_sorts_newest_first(self):
        self.write_note("2026-09-01-old", summary="старая")
        self.write_note("2026-10-01-new", summary="новая", updated="2026-10-05",
                        upstream="https://github.com/o/r/issues/7", candidate_skill="x-skill")
        (self.store / "INDEX.md").write_text("# Мой индекс\n\nМоя шапка.\n", encoding="utf-8")
        self.assertEqual(self.run_cli("index")[0], 0)
        text = (self.store / "INDEX.md").read_text(encoding="utf-8")
        self.assertTrue(text.startswith("# Мой индекс\n\nМоя шапка.\n"))
        self.assertLess(text.index("2026-10-01-new"), text.index("2026-09-01-old"))
        self.assertIn("2026-10-01 · обн. 10-05", text)
        self.assertIn("[o/r#7](https://github.com/o/r/issues/7)", text)
        self.assertIn("| x-skill |", text)
        (self.store / "INDEX.md").write_text(text.replace("Моя шапка.", "Правка шапки."), encoding="utf-8")
        self.run_cli("index")
        self.assertIn("Правка шапки.", (self.store / "INDEX.md").read_text(encoding="utf-8"))

    def test_pipe_in_summary_is_escaped(self):
        self.write_note("2026-09-01-a", summary="a | b")
        self.run_cli("index")
        self.assertIn("a \\| b", (self.store / "INDEX.md").read_text(encoding="utf-8"))

    def test_touch_sets_updated_status_upstream(self):
        self.write_note("2026-09-01-a")
        self.run_cli("index")
        code, _, _ = self.run_cli("touch", "a", "--status", "fixed-upstream",
                                  "--upstream", "https://github.com/o/r/pull/9")
        self.assertEqual(code, 0)
        note = fn.Note(self.store / "notes" / "2026-09-01-a.md")
        self.assertEqual((note.get("updated"), note.status), ("2026-10-08", "fixed-upstream"))
        self.assertEqual(self.run_cli("lint")[0], 0)

    def test_read_only_writes_nothing(self):
        self.write_note("2026-09-01-a")
        self.run_cli("index")
        before = {p: p.stat().st_mtime_ns for p in self.store.rglob("*")}
        for argv in (["index"], ["new", "x-y", "--title", "t"], ["touch", "a"], ["lint"], ["search", "заголовок"]):
            self.run_cli(*argv, "--read-only")
        after = {p: p.stat().st_mtime_ns for p in self.store.rglob("*")}
        self.assertEqual(before, after)
        self.assertEqual(self.run_cli("index", "--read-only")[0], fn.EXIT_ERR)


class LintTest(StoreCase):
    def problems(self):
        return [(lvl, msg) for lvl, _, msg in fn.lint(self.ctx(), fn.load_notes(self.ctx()))]

    def test_clean_store_has_no_problems(self):
        self.write_note("2026-09-01-a")
        self.run_cli("index")
        self.assertEqual(self.problems(), [])
        self.assertEqual(self.run_cli("lint")[0], 0)

    def test_stale_index_is_an_error(self):
        self.write_note("2026-09-01-a")
        self.run_cli("index")
        self.write_note("2026-09-02-b")
        self.assertIn(("error", "индекс устарел — `fieldnotes.py index`"), self.problems())
        self.assertEqual(self.run_cli("lint")[0], fn.EXIT_ERR)

    def test_rules(self):
        cases = [
            (dict(status="done"), "error", "status 'done'"),
            (dict(id="other"), "error", "не совпадает с именем файла"),
            (dict(summary=""), "error", "нет поля 'summary'"),
            (dict(date="08.10.2026"), "error", "date должно быть"),
            (dict(updated="2026-08-01"), "error", "updated раньше date"),
            (dict(status="fixed-upstream"), "error", "fixed-upstream без ссылки"),
            (dict(summary="ключ sk-" + "a" * 30), "error", "похоже на секрет"),
            (dict(summary="<заглушка>"), "warn", "заглушка шаблона"),
            (dict(title="Другой"), "warn", "H1 не совпадает"),
            (dict(status="needs-verification"), "warn", "needs-verification дольше"),
            (dict(body="# Заголовок\n\n## Симптом\n\n## Caveats\nесть\n"), "warn", "пустой раздел «Симптом»"),
            (dict(body="# Заголовок\n\nсм. [x](нет-такого.md)\n"), "warn", "битая ссылка"),
        ]
        for meta, level, needle in cases:
            with self.subTest(needle=needle):
                shutil.rmtree(self.store, ignore_errors=True)
                body = meta.pop("body", None)
                if "title" in meta:
                    body = "# Заголовок\n"
                path = self.write_note("2026-09-01-a", **meta, **({"body": body} if body else {}))
                if meta.get("id"):
                    self.assertTrue(path.exists())
                found = [m for lvl, m in self.problems() if lvl == level and needle in m]
                self.assertTrue(found, self.problems())

    def test_github_actions_braces_are_not_placeholders(self):
        self.write_note("2026-09-01-a", body="# Заголовок\n\n## Симптом\n`${{ github.sha }}`\n")
        self.run_cli("index")
        self.assertEqual(self.problems(), [])


class SearchTest(StoreCase):
    def test_title_beats_body_and_stems_work(self):
        self.write_note("2026-09-01-body", title="Другое", summary="ничего",
                        body="# Другое\n\nгде-то в тексте таймзона\n")
        self.write_note("2026-09-02-title", title="Таймзоны в Git Bash врут", summary="TZ")
        hits = fn.search(fn.load_notes(self.ctx()), ["таймзона"])
        self.assertEqual([n.id for _, n, _ in hits], ["2026-09-02-title", "2026-09-01-body"])

    def test_all_words_must_match_latin_and_cyrillic(self):
        self.write_note("2026-09-01-a", title="codex exec висит на stdin", summary="x")
        self.write_note("2026-09-02-b", title="codex ревью", summary="y")
        hits = fn.search(fn.load_notes(self.ctx()), ["codex", "висит"])
        self.assertEqual([n.id for _, n, _ in hits], ["2026-09-01-a"])
        self.assertEqual(fn.search(fn.load_notes(self.ctx()), ["CODEX"])[0][1].id[:10], "2026-09-01")

    def test_filters_and_json(self):
        self.write_note("2026-09-01-a", title="codex", status="obsolete")
        self.write_note("2026-09-02-b", title="codex", area="ssh")
        code, out, _ = self.run_cli("search", "codex", "--status", "active", "--json")
        self.assertEqual([h["id"] for h in json.loads(out)], ["2026-09-02-b"])
        self.assertEqual(self.run_cli("search", "нетакого")[0], fn.EXIT_NOTFOUND)


class IssueDraftTest(StoreCase):
    def test_mask_paths_secrets_addresses(self):
        text = ("C:\\Users\\anton\\x /c/Users/anton/y C:/Users/anton/z /home/deb/q /Users/mac/w "
                "~/.claude/projects/C--Users-anton-Documents-app/ "
                "10.1.2.3 me@example.com -1001234567890 ghp_" + "a" * 36 + " 123456789:" + "A" * 35 +
                "\n-----BEGIN RSA PRIVATE KEY-----\nMIIEsecret\n-----END RSA PRIVATE KEY-----")
        masked = fn.mask(text)
        for leak in ("anton", "deb", "/Users/mac", "10.1.2.3", "example.com", "1234567890", "ghp_", "AAAA",
                     "MIIEsecret"):
            self.assertNotIn(leak, masked)

    def test_draft_takes_russian_sections(self):
        self.write_note("2026-09-01-a", title="Баг", tool_version="Git 2.53",
                        body="# Баг\n\n## Симптом\nпадает в /home/anton\n\n## Root cause\nмеханизм\n\n"
                             "## Фикс / workaround\n`cmd`\n")
        code, out, _ = self.run_cli("issue-draft", "a")
        self.assertEqual(code, 0)
        self.assertIn("**Version:** Git 2.53", out)
        self.assertIn("падает в ~", out)
        self.assertIn("### Workaround\n`cmd`", out)
        self.assertIn("ЧЕРНОВИК", out)


class MigrateTest(StoreCase):
    def test_legacy_notes_and_index(self):
        src = self.make_legacy()
        code, out, _ = self.run_cli("migrate", "--from", str(src), "--root", str(src))
        self.assertIn("пробный прогон", out)
        self.assertTrue((src / "notes" / "2026-09-11-tz.md").read_text(encoding="utf-8").startswith("# "))
        code, out, _ = self.run_cli("migrate", "--from", str(src), "--root", str(src), "--apply")
        self.assertEqual(code, 0, out)
        tz = fn.Note(src / "notes" / "2026-09-11-tz.md")
        self.assertEqual(tz.errors, [])
        self.assertEqual((tz.status, tz.get("area"), tz.get("updated")), ("active", "windows / git bash", "2026-10-04"))
        self.assertEqual(tz.get("summary"), "`TZ=Asia/Bangkok` даёт UTC, промах 7 часов")
        self.assertNotIn("**Date:**", tz.body)
        self.assertTrue(tz.body.lstrip("\n").startswith("# `TZ=Asia/Bangkok` в Git Bash молча даёт UTC\n\n## Контекст"))
        frame = fn.Note(src / "notes" / "2026-09-12-frame.md")
        self.assertEqual((frame.status, frame.get("candidate_skill"), frame.get("updated")),
                         ("promoted", "`ui-verify`", "2026-09-17"))
        self.assertEqual(frame.get("summary"), "снимок до композитинга `a | b` с пайпом")
        index = (src / "INDEX.md").read_text(encoding="utf-8")
        self.assertIn("Ручная шапка, которая должна пережить пересборку.", index)
        self.assertNotIn("## Индекс", index)
        self.assertEqual(self.run_cli("lint", "--root", str(src))[0], 0)
        code, out, _ = self.run_cli("migrate", "--from", str(src), "--root", str(src), "--apply")
        self.assertIn("уже в новом формате", out)

    def test_status_mapping(self):
        for raw, want in [("fixed locally", "workaround"), ("promoted to skill (`x`)", "promoted"),
                          ("deferred", "active"), ("fixed upstream in 1.2", "fixed-upstream"), ("", "active")]:
            self.assertEqual(fn._map_status(raw), want)

    def test_damaged_frontmatter_is_skipped(self):
        src = self.tmp / "bad"
        (src / "notes").mkdir(parents=True)
        bad = src / "notes" / "2026-01-01-x.md"
        bad.write_text("---\ntitle: x\n  nested: y\n---\nbody\n", encoding="utf-8")
        code, out, _ = self.run_cli("migrate", "--from", str(src), "--root", str(src), "--apply")
        self.assertEqual(code, fn.EXIT_ERR)
        self.assertIn("ПРОПУЩЕНА", out)
        self.assertEqual(bad.read_text(encoding="utf-8"), "---\ntitle: x\n  nested: y\n---\nbody\n")


class RootTest(unittest.TestCase):
    def test_git_bash_path_is_converted_on_windows(self):
        if os.name == "nt":
            self.assertEqual(fn._native("/c/Users/x"), "C:/Users/x")
        self.assertEqual(fn._native("relative/path"), "relative/path")


class EvalsFileTest(unittest.TestCase):
    def test_evals_shape(self):
        data = json.loads((REPO / "evals" / "evals.json").read_text(encoding="utf-8"))
        pos = [e for e in data["triggers"] if e["should_trigger"]]
        neg = [e for e in data["triggers"] if not e["should_trigger"]]
        self.assertGreaterEqual(len(pos), 12)
        self.assertGreaterEqual(len(neg), 8)

    def test_description_starts_with_triggers(self):
        text = (REPO / "SKILL.md").read_text(encoding="utf-8")
        meta, _, _, errors = fn.split_frontmatter(text)
        self.assertEqual(errors, [])
        self.assertIn("запиши грабли", meta["description"][:250])
        self.assertLessEqual(len(meta["description"]), 1024)


if __name__ == "__main__":
    unittest.main()
