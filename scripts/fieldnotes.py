#!/usr/bin/env python3
"""fieldnotes.py — общее хранилище инженерных field notes для Claude Code, Codex и других агентов.

Заметка — Markdown-файл notes/YYYY-MM-DD-slug.md с плоским frontmatter. INDEX.md собирается из
frontmatter командой `index`; таблицу руками не правят, текст над маркером — ручной и сохраняется.
Сети скрипт не касается. Только стандартная библиотека, Python >= 3.9.

Коды выхода: 0 — ок · 1 — ошибки lint или использования · 3 — заметка уже есть или похожа ·
4 — хранилище или заметка не найдены.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True

import argparse  # noqa: E402
import datetime as dt  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import time  # noqa: E402
from pathlib import Path  # noqa: E402

VERSION = "2.0.1"
SCHEMA_VERSION = 1
SKILL_DIR = Path(__file__).resolve().parents[1]
TEMPLATE = SKILL_DIR / "assets" / "note-template.md"
INDEX_MARKER = "<!-- fieldnotes:index — всё ниже собирает `fieldnotes.py index`, руками не править -->"

STATUSES = ("active", "workaround", "needs-verification", "fixed-upstream", "obsolete", "promoted")
REQUIRED = ("schema_version", "id", "title", "date", "area", "status", "summary")
SUPPORTED_SCHEMAS = (1,)
VERIFY_DAYS = 30
EXIT_OK, EXIT_ERR, EXIT_EXISTS, EXIT_NOTFOUND = 0, 1, 3, 4

_TOK = r"[A-Za-z0-9_-]"  # алфавит большинства токенов; границы — по нему, а не по \b
SECRET_PATTERNS = [
    ("ключ вида sk-", re.compile(r"(?<![\w-])sk-[A-Za-z0-9_-]{20,}")),
    ("ключ Stripe", re.compile(r"(?<![\w-])[rs]k_(?:live|test)_[A-Za-z0-9]{16,}")),
    ("токен GitHub", re.compile(r"(?<![\w-])gh[pousr]_[A-Za-z0-9]{30,}|(?<![\w-])github_pat_[A-Za-z0-9_]{30,}")),
    ("токен GitLab", re.compile(r"(?<![\w-])gl(?:pat|dt|rt|ptt|cbt)-[A-Za-z0-9_-]{20,}")),
    ("токен Slack", re.compile(r"(?<![\w-])xox[abposr]-[A-Za-z0-9-]{10,}")),
    ("ключ AWS", re.compile(r"(?<![A-Z0-9])(?:AKIA|ASIA)[0-9A-Z]{16}(?![A-Z0-9])")),
    ("ключ Google API", re.compile(r"(?<![\w-])AIza[0-9A-Za-z_-]{35}")),
    ("приватный ключ", re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")),
    ("токен Telegram-бота", re.compile(r"(?<![\w-])\d{8,10}:" + _TOK + r"{35}(?!" + _TOK + r")")),
    ("Bearer-токен", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{20,}")),
    ("JWT", re.compile(r"(?<![\w-])eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")),
]
PEM_BLOCK = re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?(?:-----END [A-Z0-9 ]*PRIVATE KEY-----|\Z)",
                       re.DOTALL)
# имя пользователя в пути: без пробелов — до разделителя; с пробелами — только если дальше идёт
# разделитель («C:\Users\Anton Vaskov\x»), иначе слово после пробела — уже обычный текст
_USER = r"""(?:[^\\/\s"'`<>|]+(?: [^\\/\s"'`<>|]+)+(?=[\\/])|[^\\/\s"'`<>|]+)"""
MASKS = [
    (re.compile(r"/[a-zA-Z]/Users/" + _USER), "~"),                    # Git Bash: /c/Users/<имя>
    (re.compile(r"[A-Za-z]:[\\/]+Users[\\/]+" + _USER, re.IGNORECASE), "~"),
    (re.compile(r"\b[A-Za-z]--Users-[^\s/\\]+"), "~"),                  # слаг проекта Claude: C--Users-<имя>-… целиком
    (re.compile(r"/home/" + _USER), "~"),
    (re.compile(r"/Users/" + _USER), "~"),
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), "<ip>"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"), "<email>"),
    (re.compile(r"-100\d{6,}"), "<chat_id>"),
]


class FieldNotesError(Exception):
    """Ошибка, которую исправляет пользователь; печатается без трейсбэка."""

    def __init__(self, message, code=EXIT_ERR):
        super().__init__(message)
        self.code = code


# ---------------------------------------------------------------------------
# пути
# ---------------------------------------------------------------------------

def _native(path_text):
    """`/c/Users/x` из Git Bash → `C:/Users/x`, иначе Windows-Python его не найдёт."""
    m = re.match(r"^/([a-zA-Z])(/.*)?$", path_text)
    if os.name == "nt" and m:
        return f"{m.group(1).upper()}:{m.group(2) or '/'}"
    return path_text


def resolve_root(explicit=None):
    """--root → $FIELD_NOTES_DIR → ~/.claude/field-notes (если есть) → ~/.codex/field-notes (если есть)
    → ~/.claude/field-notes. Тот же порядок, что в fn.sh."""
    value = explicit or os.environ.get("FIELD_NOTES_DIR")
    if value:
        return Path(_native(value)).expanduser()
    home = Path.home()
    for candidate in (home / ".claude" / "field-notes", home / ".codex" / "field-notes"):
        if candidate.is_dir():
            return candidate
    return home / ".claude" / "field-notes"


class Context:
    def __init__(self, args):
        self.store = resolve_root(getattr(args, "root", None))
        self.read_only = bool(getattr(args, "read_only", False))

    @property
    def notes_dir(self):
        return self.store / "notes"

    @property
    def index_path(self):
        return self.store / "INDEX.md"

    def require_writable(self, what):
        if self.read_only:
            raise FieldNotesError(f"--read-only: отказываюсь {what}")


def today():
    override = os.environ.get("FIELDNOTES_TODAY")  # только для тестов
    return dt.date.fromisoformat(override) if override else dt.date.today()


# ---------------------------------------------------------------------------
# блокировка и запись: в хранилище пишут несколько агентов и сессий сразу
# ---------------------------------------------------------------------------

class Lock:
    """Системная блокировка файла (`fcntl.flock` / `msvcrt.locking`). Её держит открытый дескриптор,
    и ОС снимает её сама, когда процесс-владелец завершился, — поэтому «протухших» замков нет и ломать
    чужой замок по возрасту не нужно. Сам файл `.fieldnotes.lock` не удаляется."""

    def __init__(self, path, wait=30):
        self.path, self.wait = Path(path), wait
        self.fh = None

    def _try(self):
        if os.name == "nt":
            import msvcrt
            self.fh.seek(0)
            msvcrt.locking(self.fh.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(self.fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fh = open(self.path, "a+b")
        deadline = time.monotonic() + self.wait
        while True:
            try:
                self._try()
                return self
            except OSError:
                if time.monotonic() > deadline:
                    self.fh.close()
                    self.fh = None
                    raise FieldNotesError(f"хранилище занято другим процессом: {self.path}")
                time.sleep(0.1)

    def __exit__(self, *exc):
        if self.fh is None:
            return
        try:
            if os.name == "nt":
                import msvcrt
                self.fh.seek(0)
                msvcrt.locking(self.fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.fh.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        finally:
            self.fh.close()
            self.fh = None


def store_lock(ctx):
    return Lock(ctx.store / ".fieldnotes.lock")


def atomic_write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".tmp{os.getpid()}")
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# frontmatter: плоское подмножество YAML, которое читает и yaml.safe_load
# ---------------------------------------------------------------------------

_OPENER = re.compile(r"---[ \t]*\n")
_KEY_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*)\s*:(?:\s+(.*))?$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_BARE_OK = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-/]*$")
_NUMBER_LIKE = re.compile(r"^[-+]?(\d[\d_]*\.?\d*|\.\d+)([eE][-+]?\d+)?$|^0[xXoObB]")
_YAML_WORDS = {"yes", "no", "on", "off", "true", "false", "null", "y", "n", "~"}


def _strip_comment(raw):
    """Отрезать комментарий `#` вне кавычек. Внутри "…" обратный слеш экранирует следующий символ,
    поэтому `"C:\\\\"` закрывается на второй кавычке; незакрытая кавычка — ошибка."""
    out, quote, escaped = [], None, False
    for i, ch in enumerate(raw):
        if quote:
            out.append(ch)
            if escaped:
                escaped = False
            elif ch == "\\" and quote == '"':
                escaped = True
            elif ch == quote:
                quote = None
            continue
        if ch in "\"'":
            quote = ch
        elif ch == "#" and (i == 0 or raw[i - 1] in " \t"):
            break
        out.append(ch)
    if quote:
        raise ValueError("незакрытая кавычка")
    return "".join(out).strip()


def _unquote(token):
    token = token.strip()
    if token[:1] == '"':
        if len(token) < 2 or token[-1] != '"':
            raise ValueError(f"значение в кавычках не закрыто: {token[:40]}")
        try:
            value = json.loads(token)
        except ValueError:
            raise ValueError(f"битое значение в кавычках: {token[:40]}") from None
        if not isinstance(value, str):
            raise ValueError(f"битое значение в кавычках: {token[:40]}")
        return value
    if token[:1] == "'":
        if len(token) < 2 or token[-1] != "'":
            raise ValueError(f"значение в кавычках не закрыто: {token[:40]}")
        return token[1:-1].replace("''", "'")
    return token


def _split_list(inner):
    items, buf, quote, escaped = [], [], None, False
    for ch in inner:
        if quote:
            buf.append(ch)
            if escaped:
                escaped = False
            elif ch == "\\" and quote == '"':
                escaped = True
            elif ch == quote:
                quote = None
            continue
        if ch in "\"'":
            quote = ch
            buf.append(ch)
        elif ch == ",":
            items.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    if quote:
        raise ValueError("незакрытая кавычка в списке")
    if "".join(buf).strip():
        items.append("".join(buf))
    return [_unquote(i) for i in items if i.strip()]


def parse_value(raw):
    """Значение поля; ValueError — если оно битое (кавычки, скобки)."""
    raw = _strip_comment(raw or "")
    if raw.startswith("["):
        if not raw.endswith("]"):
            raise ValueError("список не закрыт ']'")
        return _split_list(raw[1:-1])
    value = _unquote(raw)
    if raw == value and re.fullmatch(r"\d+", value):
        return int(value)
    return value


def split_frontmatter(text):
    """(meta, порядок ключей, тело, ошибки)."""
    text = text.lstrip("\ufeff").replace("\r\n", "\n")
    opener = _OPENER.match(text)
    if not opener:
        return {}, [], text, ["нет frontmatter (файл должен начинаться с '---')"]
    start = opener.end()
    m = re.search(r"^---[ \t]*$", text[start:], re.MULTILINE)
    if not m:
        return {}, [], text, ["frontmatter не закрыт строкой '---'"]
    block = text[start:start + m.start()].rstrip("\n")
    rest = text[start + m.end():]
    body = rest[1:] if rest.startswith("\n") else rest
    meta, order, errors = {}, [], []
    for n, line in enumerate(block.split("\n"), start=2):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line[0] in " \t":
            errors.append(f"строка {n}: вложенные значения не поддерживаются")
            continue
        km = _KEY_RE.match(line)
        if not km:
            errors.append(f"строка {n}: ожидается 'ключ: значение'")
            continue
        key = km.group(1)
        if key in meta:
            errors.append(f"строка {n}: ключ '{key}' повторяется")
            continue
        try:
            meta[key] = parse_value(km.group(2) or "")
        except ValueError as exc:
            errors.append(f"строка {n}: {exc}")
            continue
        order.append(key)
    return meta, order, body, errors


def format_scalar(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    text = "" if value is None else str(value)
    if _DATE_RE.match(text):
        return text
    if (_BARE_OK.match(text) and re.search(r"[A-Za-z]", text) and text.lower() not in _YAML_WORDS
            and not _NUMBER_LIKE.match(text)):
        return text
    return json.dumps(text, ensure_ascii=False)


def dump_frontmatter(meta, order=None):
    keys = list(order or []) + [k for k in meta if k not in (order or [])]
    lines = ["---"]
    for key in keys:
        if key not in meta or meta[key] in (None, "", []):
            continue
        value = meta[key]
        if isinstance(value, (list, tuple)):
            lines.append(f"{key}: [{', '.join(format_scalar(v) for v in value)}]")
        else:
            lines.append(f"{key}: {format_scalar(value)}")
    lines.append("---")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# заметки
# ---------------------------------------------------------------------------

class Note:
    def __init__(self, path):
        self.path = Path(path)
        self.id = self.path.stem
        try:
            self.text = self.path.read_text(encoding="utf-8").replace("\r\n", "\n")
        except (OSError, UnicodeDecodeError) as exc:
            self.text = ""
            self.meta, self.order, self.body, self.errors = {}, [], "", [f"не читается: {exc}"]
            return
        self.meta, self.order, self.body, self.errors = split_frontmatter(self.text)

    def get(self, key, default=""):
        value = self.meta.get(key, default)
        return default if value is None else value

    @property
    def title(self):
        return str(self.get("title") or self.id)

    @property
    def status(self):
        return str(self.get("status") or "active")

    def date(self, key="date"):
        value = str(self.get(key) or "")
        if not _DATE_RE.match(value):  # fromisoformat в 3.11+ принимает и 20260101, и 2026-W01-1
            return None
        try:
            return dt.date.fromisoformat(value)
        except ValueError:
            return None

    def save(self, meta):
        atomic_write(self.path, dump_frontmatter(meta, self.order) + self.body)


def load_notes(ctx):
    if not ctx.notes_dir.is_dir():
        return []
    return [Note(p) for p in sorted(ctx.notes_dir.glob("*.md"))]


def require_store(ctx):
    if not ctx.notes_dir.is_dir():
        raise FieldNotesError(f"хранилища нет: {ctx.store} — `fieldnotes.py init`", EXIT_NOTFOUND)


def find_note(ctx, ref):
    """Заметка по id, имени файла или хвосту slug'а; неоднозначность — ошибка."""
    ref = Path(ref).stem
    path = ctx.notes_dir / f"{ref}.md"
    if path.is_file():
        return Note(path)
    matches = [n for n in load_notes(ctx) if ref in n.id]
    if len(matches) != 1:
        found = ", ".join(n.id for n in matches[:5])
        raise FieldNotesError(f"заметка не найдена или неоднозначна: {ref}" + (f" ({found})" if found else ""),
                              EXIT_NOTFOUND)
    return matches[0]


def _sections(body):
    out, current = {}, None
    for line in body.split("\n"):
        m = re.match(r"^##\s+(.*)$", line)
        if m:
            current = m.group(1).strip()
            out[current] = []
        elif current is not None:
            out[current].append(line)
    return {k: "\n".join(v).strip() for k, v in out.items()}


def _h1(body):
    m = re.search(r"^#\s+(.+)$", body, re.MULTILINE)
    return m.group(1).strip() if m else ""


# ---------------------------------------------------------------------------
# lint
# ---------------------------------------------------------------------------

def lint(ctx, notes):
    """[(уровень, где, сообщение)], уровень — 'error' или 'warn'."""
    out = []
    slugs = {}
    for note in notes:
        where = f"notes/{note.path.name}"
        for err in note.errors:
            out.append(("error", where, err))
        if not note.meta:
            continue
        m = note.meta
        for key in REQUIRED:
            if m.get(key) in (None, "", []):
                out.append(("error", where, f"нет поля '{key}'"))
        if m.get("schema_version") not in (None, "") and m.get("schema_version") not in SUPPORTED_SCHEMAS:
            out.append(("error", where, f"schema_version {m.get('schema_version')!r} не поддерживается "
                                        f"(эта версия скрипта понимает {', '.join(map(str, SUPPORTED_SCHEMAS))})"))
        if m.get("status") and m.get("status") not in STATUSES:
            out.append(("error", where, f"status '{m.get('status')}' — допустимы: {', '.join(STATUSES)}"))
        if m.get("id") and str(m.get("id")) != note.id:
            out.append(("error", where, f"id '{m.get('id')}' не совпадает с именем файла '{note.id}'"))
        for key in ("date", "updated"):
            if m.get(key) and note.date(key) is None:
                out.append(("error", where, f"{key} должно быть YYYY-MM-DD"))
        if note.date("updated") and note.date("date") and note.date("updated") < note.date("date"):
            out.append(("error", where, "updated раньше date"))
        if m.get("status") == "fixed-upstream" and not m.get("upstream"):
            out.append(("error", where, "fixed-upstream без ссылки upstream"))
        if not re.match(r"^\d{4}-\d{2}-\d{2}-[a-z0-9][a-z0-9-]*$", note.id):
            out.append(("warn", where, "имя файла должно быть YYYY-MM-DD-slug.md"))
        for key in ("title", "summary"):
            if re.match(r"^\s*<.*>\s*$", str(m.get(key) or "")):
                out.append(("warn", where, f"{key} — всё ещё заглушка шаблона"))
        if re.search(r"\{\{(id|date|title|title_yaml|area_yaml)\}\}", note.text):
            out.append(("warn", where, "в заметке остались заглушки '{{…}}'"))
        h1 = _h1(note.body)
        if h1 and m.get("title") and h1 != str(m.get("title")):
            out.append(("warn", where, "заголовок H1 не совпадает с title"))
        for name, text in _sections(note.body).items():
            if not text:
                out.append(("warn", where, f"пустой раздел «{name}» — заполни или убери"))
        if m.get("status") == "needs-verification":
            last = note.date("updated") or note.date("date")
            if last and (today() - last).days > VERIFY_DAYS:
                out.append(("warn", where, f"needs-verification дольше {VERIFY_DAYS} дней — проверь или закрой"))
        slugs.setdefault(note.id[11:], []).append(note.id)
        for link in re.findall(r"\]\(([^)\s#]+)(?:#[^)]*)?\)", note.body):
            if "://" in link or link.startswith(("mailto:", "~", "/")) or re.match(r"^[A-Za-z]:", link):
                continue
            if not (note.path.parent / link).exists():
                out.append(("warn", where, f"битая ссылка: {link}"))
        for label, pattern in SECRET_PATTERNS:
            if pattern.search(note.text):
                out.append(("error", where, f"похоже на секрет ({label}) — замаскируй"))
    for slug, same in slugs.items():
        if len(same) > 1:
            out.append(("warn", "notes/", f"один slug '{slug}' у {', '.join(same)} — обновляй одну заметку"))
    if ctx.index_path.is_file() or notes:
        current = ctx.index_path.read_text(encoding="utf-8") if ctx.index_path.is_file() else ""
        if render_index(notes, current) != current.replace("\r\n", "\n"):
            out.append(("error", "INDEX.md", "индекс устарел — `fieldnotes.py index`"))
    return out


# ---------------------------------------------------------------------------
# индекс
# ---------------------------------------------------------------------------

INDEX_HEAD = """# Field Notes

Инженерные находки, которые переживают отдельный проект: root cause, workaround, грабли
инструментов, кандидаты в скиллы. Общее хранилище для всех агентов на машине.
Как вести — скилл `field-notes`. Текст над маркером — ручной, таблицу ниже собирает скрипт.
"""


def _cell(text):
    return str(text or "").replace("|", "\\|").replace("\n", " ").strip()


def _upstream_ref(url):
    m = re.search(r"github\.com/([^/]+/[^/]+)/(?:issues|pull)/(\d+)", str(url or ""))
    if m:
        return f"[{m.group(1)}#{m.group(2)}]({url})"
    return f"[ссылка]({url})" if url else ""


def _index_head(current):
    """Текст над таблицей: всё выше маркера; у индекса, который вели руками, — всё выше первой
    строки-шапки таблицы (без заголовка «## Индекс» прямо над ней); иначе — шапка по умолчанию."""
    current = current.replace("\r\n", "\n")
    if INDEX_MARKER in current:
        return current.split(INDEX_MARKER)[0]
    lines = current.split("\n")
    for i, line in enumerate(lines):
        if re.match(r"^\|\s*(date|дата)\s*\|", line, re.IGNORECASE):
            head = "\n".join(lines[:i]).rstrip()
            head = re.sub(r"\n#+\s*(Индекс|Index)\s*$", "", head).rstrip()
            return head + "\n" if head else INDEX_HEAD
    return current if current.strip() else INDEX_HEAD


def render_index(notes, current=""):
    head = _index_head(current)
    rows = []
    for note in sorted(notes, key=lambda n: (str(n.get("date") or ""), n.id), reverse=True):
        date = str(note.get("date") or "?")
        if note.get("updated") and str(note.get("updated")) != date:
            date += f" · обн. {str(note.get('updated'))[5:]}"
        rows.append(f"| {date} | [{_cell(note.title)}](notes/{note.path.name}) | {_cell(note.get('area'))} | "
                    f"{_cell(note.status)} | {_upstream_ref(note.get('upstream'))} | "
                    f"{_cell(note.get('candidate_skill')) or '—'} | {_cell(note.get('summary'))} |")
    table = ["| Date | Note | Area | Status | Upstream | Candidate skill | Summary |",
             "|---|---|---|---|---|---|---|", *rows]
    return head.rstrip("\n") + "\n\n" + INDEX_MARKER + "\n\n" + "\n".join(table) + "\n"


def write_index(ctx):
    notes = load_notes(ctx)
    current = ctx.index_path.read_text(encoding="utf-8") if ctx.index_path.is_file() else ""
    text = render_index(notes, current)
    changed = text != current.replace("\r\n", "\n")
    if changed:
        atomic_write(ctx.index_path, text)
    return len(notes), changed


# ---------------------------------------------------------------------------
# поиск
# ---------------------------------------------------------------------------

WEIGHTS = (("title", 5), ("tags", 4), ("area", 3), ("summary", 3), ("body", 1))


def _words(terms):
    out = []
    for term in terms:
        tokens = (t.strip(".:/-") for t in re.findall(r"[\w.:/+#-]+", term.casefold()))
        out.extend(t for t in tokens if t)
    return out


def _is_exact(word):
    """Короткие слова и слова с + или # ищутся целым словом: иначе «r» совпадёт с любым текстом,
    а «c++» — с любым «c»."""
    return len(word) <= 2 or bool(re.search(r"[+#]", word))


def _count(text, word):
    if _is_exact(word):
        return len(re.findall(r"(?<![\w+#])" + re.escape(word) + r"(?![\w+#])", text))
    return text.count(word)


def _variants(word):
    """Слово и его основа: «таймзоны» найдёт «таймзона». Грубая замена морфологии."""
    if _is_exact(word):
        return (word,)
    if len(word) >= 6 and re.search(r"[а-яё]", word):
        return (word, word[:max(4, len(word) - 2)])
    if len(word) >= 7:
        return (word, word[:len(word) - 2])
    return (word,)


def _field_text(note, field):
    if field == "body":
        return note.body
    if field == "tags":
        tags = note.get("tags") or []
        return " ".join(tags) if isinstance(tags, list) else str(tags)
    return str(note.get(field) or "")


def _snippet(body, variants):
    for line in body.split("\n"):
        low = line.casefold()
        if line.strip() and not line.startswith("#") and any(_count(low, v) for vs in variants for v in vs):
            line = line.strip()
            return line[:200] + ("…" if len(line) > 200 else "")
    return ""


def search(notes, terms, limit=10, status=None, area=None):
    words = _words(terms)
    if not words:
        return []
    variants = [_variants(w) for w in words]
    hits = []
    for note in notes:
        if status and note.status != status:
            continue
        if area and area.casefold() not in str(note.get("area") or "").casefold():
            continue
        fields = [(_field_text(note, f).casefold(), w) for f, w in WEIGHTS]
        score, matched = 0, 0
        for vs in variants:
            word_score = 0
            for text, weight in fields:
                exact = _count(text, vs[0])
                stem = _count(text, vs[-1]) - exact if len(vs) > 1 else 0
                word_score += weight * (2 * exact + stem)
            if word_score:
                matched += 1
                score += word_score
        if matched == len(variants):
            hits.append((score, note))
    hits.sort(key=lambda h: (-h[0], h[1].id))
    return [(score, note, _snippet(note.body, variants)) for score, note in hits[:limit]]


def _stems(text):
    return {_variants(w)[-1] for w in _words([text]) if len(w) > 2}


def _similar(notes, title, limit=3):
    words = _stems(title)
    scored = []
    for n in notes:
        other = _stems(n.title + " " + str(n.get("summary") or ""))
        shared = words & other
        if len(shared) >= 3 or (len(shared) >= 2 and len(shared) / len(words) >= 0.5):
            scored.append((len(shared) / len(words), n))
    return [n for _, n in sorted(scored, key=lambda x: -x[0])[:limit]]


# ---------------------------------------------------------------------------
# черновик issue
# ---------------------------------------------------------------------------

def mask(text):
    text = PEM_BLOCK.sub("<redacted private key>", text)
    for _, pattern in SECRET_PATTERNS:
        text = pattern.sub("<redacted>", text)
    for pattern, repl in MASKS:
        text = pattern.sub(repl, text)
    return text


def _pick(sections, *prefixes):
    for key, value in sections.items():
        low = key.casefold()
        if any(low.startswith(p) for p in prefixes) and value:
            return value
    return ""


def issue_draft(note):
    sec = _sections(note.body)
    version = str(note.get("tool_version") or "").strip()
    parts = [
        "<!-- ЧЕРНОВИК от field-notes. Ничего не опубликовано. Маска ловит только очевидное "
        "(ключи, токены, домашние пути, IPv4, email, chat id) — прочитай каждую строку до публикации. "
        "Для англоязычного трекера переведи. -->",
        f"## {note.title}", "",
        f"**Version:** {version or '_укажи версию инструмента_'}", "",
        "### Context", _pick(sec, "контекст", "context") or "_окружение: ОС, версии, как запускали_", "",
        "### Symptom", _pick(sec, "симптом", "symptom") or "_что наблюдали, дословно_", "",
        "### Root cause", _pick(sec, "root cause", "причина") or "_не установлена_", "",
        "### How to reproduce / verify", _pick(sec, "как проверить", "как воспроизвести", "how to",
                                                "проверка") or "_шаги_", "",
        "### Workaround", _pick(sec, "фикс", "workaround", "fix", "обход") or "_нет_", "",
    ]
    return mask("\n".join(parts).rstrip() + "\n")


# ---------------------------------------------------------------------------
# миграция старого формата (строка **Date:** · **Area:** · **Status:** + индекс, который вели руками)
# ---------------------------------------------------------------------------

_STATUS_MAP = {"fixed locally": "workaround", "workaround": "workaround", "needs verification": "needs-verification",
               "needs-verification": "needs-verification", "obsolete": "obsolete", "promoted": "promoted",
               "promoted to skill": "promoted", "active": "active", "deferred": "active",
               "fixed upstream": "fixed-upstream", "fixed-upstream": "fixed-upstream", "fixed": "workaround"}
# старый формат: первая непустая строка — `# Заголовок`, следующая непустая — строка метаданных;
# в любом другом месте (пример в блоке кода, цитата) такую строку не трогаем
_LEGACY_HEAD = re.compile(r"\A\s*(#[ \t]+[^\n]+)\n(?:[ \t]*\n)*(-\s+\*\*Date:\*\*[^\n]*)(?:\n|\Z)")


def _map_status(raw):
    raw = str(raw or "").strip().lower()
    for key in sorted(_STATUS_MAP, key=len, reverse=True):
        if raw.startswith(key):
            return _STATUS_MAP[key]
    return "active"


def _clean_md(text):
    return re.sub(r"\s+", " ", str(text or "")).strip()


def read_legacy_index(index_path):
    """{id: {колонка: значение}} из таблицы индекса, который вели руками."""
    rows, header = {}, None
    try:
        lines = Path(index_path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return rows
    for line in lines:
        if not line.startswith("|"):
            continue
        cells = [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", line.strip().strip("|"))]
        if cells and cells[0].lower() in ("date", "дата"):
            header = [c.lower() for c in cells]
            continue
        m = re.search(r"\]\((?:notes/)?([^)]+?)\.md\)", line)
        if header and m and len(cells) >= len(header):
            if len(cells) > len(header):  # неэкранированный '|' в последней колонке (summary)
                cells = cells[:len(header) - 1] + [" | ".join(cells[len(header) - 1:])]
            rows[Path(m.group(1)).name] = dict(zip(header, cells))
    return rows


def _dates_after(base, texts):
    """Самая поздняя дата правки из строк вида «обн. 10-04», «Обновлено: 2026-10-06»,
    «дополнения 06.09, 11.09», «## Обновление 13.09.2026». Год по умолчанию — год base,
    а месяц раньше месяца base означает следующий год."""
    found = []
    for text in texts:
        for y, mo, d in re.findall(r"\b(\d{4})-(\d{2})-(\d{2})\b", text):
            found.append((int(y), int(mo), int(d)))
        for d, mo, y in re.findall(r"\b(\d{2})\.(\d{2})(?:\.(\d{4}))?\b", text):
            found.append((int(y) if y else None, int(mo), int(d)))
        for mo, d in re.findall(r"обн\.\s*(\d{2})-(\d{2})", text):
            found.append((None, int(mo), int(d)))
    best = None
    for y, mo, d in found:
        if y is None:
            y = base.year + (1 if mo < base.month else 0)
        try:
            value = dt.date(y, mo, d)
        except ValueError:
            continue
        if value > base and (best is None or value > best):
            best = value
    return best


def migrate_note(path, index_rows):
    """(новый текст или None, проблемы) для заметки старого формата; уже мигрированная — (None, [])."""
    text = Path(path).read_text(encoding="utf-8").replace("\r\n", "\n").lstrip("\ufeff")
    stem = Path(path).stem
    if re.match(r"---[ \t]*$", text.split("\n", 1)[0]):
        # уже frontmatter (или битый frontmatter) — не переписываем, битый отдаём как проблему
        _, _, _, errors = split_frontmatter(text)
        return None, errors or []
    problems = []
    row = index_rows.get(stem, {})
    head = _LEGACY_HEAD.match(text)
    meta_line = head.group(2) if head else None
    m = re.search(r"\*\*Area:\*\*\s*([^\n]*?)\s*·\s*\*\*Status:\*\*\s*(.+)$", meta_line) if meta_line else None
    first = re.match(r"\A\s*#[ \t]+([^\n]+)", text)
    title = (first.group(1).strip() if first else "") \
        or _clean_md(re.sub(r"\[(.*)\]\(.*\)", r"\1", row.get("note", ""))) or stem
    date = stem[:10] if _DATE_RE.match(stem[:10]) else ""
    status_raw = m.group(2) if m else row.get("status", "")
    meta = {
        "schema_version": SCHEMA_VERSION,
        "id": stem,
        "title": title,
        "date": date,
        "area": _clean_md(m.group(1) if m else row.get("area", "")) or "other",
        "status": _map_status(status_raw),
        "summary": _clean_md(row.get("summary", "")),
    }
    try:
        base = dt.date.fromisoformat(date)
        meta_text = meta_line or ""
        heads = re.findall(r"^##\s+Обновлени[ея].*$", text, re.MULTILINE)
        updated = _dates_after(base, [meta_text.split("**Area:**")[0], row.get("date", ""), *heads])
        if updated:
            meta["updated"] = updated.isoformat()
    except ValueError:
        problems.append(f"дата '{date}' в имени файла не YYYY-MM-DD")
    candidate = _clean_md(row.get("candidate skill", ""))
    skill_in_status = re.search(r"`([^`]+)`", status_raw or "")
    if (not candidate or candidate == "—") and skill_in_status:
        candidate = skill_in_status.group(1)
    if candidate and candidate != "—":
        meta["candidate_skill"] = candidate
    if not meta["summary"]:
        problems.append("нет summary — допиши")
    if not meta_line:
        problems.append("нет строки **Date:** · **Area:** · **Status:** — area/status по индексу")
    body = text
    if head:
        # вырезаем ровно найденную строку метаданных в начале; остальное тело — байт в байт
        body = head.group(1) + "\n\n" + text[head.end():].lstrip("\n")
    return dump_frontmatter(meta) + "\n" + body.lstrip("\n"), problems


# ---------------------------------------------------------------------------
# команды
# ---------------------------------------------------------------------------

def out_json(data):
    print(json.dumps(data, ensure_ascii=False, indent=1, default=str))


def cmd_root(ctx, args):
    if args.json:
        out_json({"root": str(ctx.store), "exists": ctx.notes_dir.is_dir()})
    else:
        print(ctx.store)
    return EXIT_OK


def cmd_init(ctx, args):
    ctx.require_writable("создавать хранилище")
    ctx.notes_dir.mkdir(parents=True, exist_ok=True)
    if not ctx.index_path.is_file():
        atomic_write(ctx.index_path, render_index([], ""))
        print(f"создан {ctx.index_path}", file=sys.stderr)
    print(ctx.store)
    return EXIT_OK


def cmd_new(ctx, args):
    ctx.require_writable("создавать заметку")
    if not ctx.notes_dir.is_dir():
        ctx.notes_dir.mkdir(parents=True, exist_ok=True)
    slug = args.slug.strip().lower()
    if not re.match(r"^[a-z0-9][a-z0-9-]{1,60}$", slug):
        raise FieldNotesError("slug: латиница в нижнем регистре, цифры и '-', 2–61 символ")
    with store_lock(ctx):
        notes = load_notes(ctx)
        same = [n for n in notes if n.id[11:] == slug]
        if same:
            print(f"заметка с таким slug уже есть: {same[0].path} — это обновление, а не новая заметка",
                  file=sys.stderr)
            return EXIT_EXISTS
        if args.title and not args.force:
            similar = _similar(notes, args.title)
            if similar:
                print("есть похожие заметки — может, это обновление одной из них? Иначе повтори с --force:",
                      file=sys.stderr)
                for n in similar:
                    print(f"  {n.path}\n    {n.title}", file=sys.stderr)
                return EXIT_EXISTS
        date = today().isoformat()
        note_id = f"{date}-{slug}"
        title = args.title or "<Заголовок-утверждение: что именно неверно и что из-за этого происходит>"
        text = TEMPLATE.read_text(encoding="utf-8").replace("\r\n", "\n")
        values = {"id": note_id, "date": date, "area_yaml": format_scalar(args.area or "<инструмент / область>"),
                  "title_yaml": format_scalar(title), "title": title}
        for key, value in values.items():
            text = text.replace("{{" + key + "}}", value)
        path = ctx.notes_dir / f"{note_id}.md"
        try:
            with open(path, "x", encoding="utf-8", newline="\n") as fh:  # никогда не перезаписывает
                fh.write(text)
        except FileExistsError:
            print(f"заметка с таким именем только что появилась: {path}", file=sys.stderr)
            return EXIT_EXISTS
    print(path)
    print("дальше: заполни заметку, потом `fn.sh index` и `fn.sh lint`", file=sys.stderr)
    return EXIT_OK


def cmd_touch(ctx, args):
    """Отметить обновление заметки: updated = сегодня, индекс пересобирается."""
    require_store(ctx)
    ctx.require_writable("менять заметку")
    with store_lock(ctx):
        note = find_note(ctx, args.id)
        if note.errors:
            raise FieldNotesError(f"{note.path.name}: {'; '.join(note.errors)}")
        meta = dict(note.meta)
        meta["updated"] = today().isoformat()
        if args.status:
            meta["status"] = args.status
        if args.upstream:
            meta["upstream"] = args.upstream
        note.save(meta)
        write_index(ctx)
    print(note.path)
    return EXIT_OK


def cmd_index(ctx, args):
    require_store(ctx)
    ctx.require_writable("писать INDEX.md")
    with store_lock(ctx):
        count, changed = write_index(ctx)
    print(f"INDEX.md: {count} заметок" + ("" if changed else " — уже актуален"))
    return EXIT_OK


def cmd_lint(ctx, args):
    require_store(ctx)
    notes = load_notes(ctx)
    items = lint(ctx, notes)
    if args.json:
        out_json([{"level": a, "where": b, "message": c} for a, b, c in items])
    else:
        for level, where, msg in items:
            print(f"{level:5} {where}: {msg}")
        errors = sum(1 for i in items if i[0] == "error")
        print(f"lint: {len(notes)} заметок · ошибок {errors} · предупреждений {len(items) - errors}")
    return EXIT_ERR if any(i[0] == "error" for i in items) else EXIT_OK


def cmd_search(ctx, args):
    notes = load_notes(ctx)
    hits = search(notes, args.terms, args.limit, args.status, args.area)
    if args.json:
        out_json([{"id": n.id, "path": str(n.path), "score": s, "status": n.status, "title": n.title,
                   "summary": str(n.get("summary") or ""), "snippet": snip} for s, n, snip in hits])
        return EXIT_OK
    if not hits:
        print(f"совпадений нет в {len(notes)} заметках: {' '.join(args.terms)}")
        return EXIT_NOTFOUND
    for _, note, snip in hits:
        summary = str(note.get("summary") or "")
        summary = summary[:400] + ("…" if len(summary) > 400 else "")
        print(f"[{note.status}] notes/{note.path.name}\n    {note.title}\n    {summary}")
        if snip:
            print(f"    › {snip}")
    print(f"-- {len(hits)} из {len(notes)} заметок · хранилище {ctx.store}")
    return EXIT_OK


def cmd_list(ctx, args):
    notes = sorted(load_notes(ctx), key=lambda n: (str(n.get("updated") or n.get("date") or ""), n.id),
                   reverse=True)[:args.limit]
    if args.json:
        out_json([{"id": n.id, "status": n.status, "title": n.title, "updated": n.get("updated") or n.get("date")}
                  for n in notes])
        return EXIT_OK
    for n in notes:
        print(f"{str(n.get('updated') or n.get('date')):10}  {n.status:18} {n.id}")
    return EXIT_OK


def cmd_issue(ctx, args):
    require_store(ctx)
    print(issue_draft(find_note(ctx, args.id)))
    return EXIT_OK


def cmd_migrate(ctx, args):
    src = Path(_native(args.source)).expanduser()
    notes_src = src / "notes" if (src / "notes").is_dir() else src
    index_src = (src if notes_src != src else src.parent) / "INDEX.md"
    files = sorted(p for p in notes_src.glob("*.md") if p.name.upper() not in ("INDEX.MD", "README.MD"))
    if not files:
        raise FieldNotesError(f"заметок нет в {notes_src}", EXIT_NOTFOUND)
    apply = args.apply
    if apply:
        ctx.require_writable("переписывать заметки")
        ctx.notes_dir.mkdir(parents=True, exist_ok=True)
    rows = read_legacy_index(index_src)
    stats = {"write": 0, "done": 0, "skip": 0}
    lock = store_lock(ctx) if apply else None
    if lock:
        lock.__enter__()
    try:
        for path in files:
            text, problems = migrate_note(path, rows)
            dest = ctx.notes_dir / path.name
            if text is None:
                state = "уже в новом формате" if not problems else "ПРОПУЩЕНА: битый frontmatter"
                stats["done" if not problems else "skip"] += 1
            elif dest.exists() and dest.resolve() != path.resolve():
                state = "ПРОПУЩЕНА: в хранилище уже есть файл с этим именем"
                stats["skip"] += 1
            else:
                state = "переписана" if apply else "будет переписана"
                stats["write"] += 1
                if apply:
                    atomic_write(dest, text)
            extra = f" · {'; '.join(problems)}" if problems else ""
            print(f"{path.name}: {state}{extra}")
        if apply:
            write_index(ctx)
    finally:
        if lock:
            lock.__exit__(None, None, None)
    print(f"-- {len(files)} заметок: к записи {stats['write']} · уже готовы {stats['done']} · "
          f"пропущено {stats['skip']}" + ("" if apply else " · пробный прогон, ничего не записано (--apply)"))
    return EXIT_ERR if stats["skip"] else EXIT_OK


def build_parser():
    ap = argparse.ArgumentParser(prog="fieldnotes.py", description=__doc__.split("\n\n")[0])
    ap.add_argument("--version", action="version", version=f"field-notes {VERSION}")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--root", help="хранилище (по умолчанию $FIELD_NOTES_DIR или ~/.claude/field-notes)")
    common.add_argument("--read-only", action="store_true", help="ничего не записывать")
    common.add_argument("--json", action="store_true", help="вывод для машины")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("root", parents=[common], help="путь к хранилищу").set_defaults(fn=cmd_root)
    sub.add_parser("init", parents=[common], help="создать пустое хранилище").set_defaults(fn=cmd_init)
    p = sub.add_parser("new", parents=[common], help="новая заметка по шаблону с сегодняшней датой")
    p.add_argument("slug")
    p.add_argument("--title", help="заголовок-утверждение; по нему ищутся похожие заметки")
    p.add_argument("--area", help="инструмент / область")
    p.add_argument("--force", action="store_true", help="создать, даже если есть похожие")
    p.set_defaults(fn=cmd_new)
    p = sub.add_parser("touch", parents=[common], help="отметить обновление заметки (updated = сегодня)")
    p.add_argument("id")
    p.add_argument("--status", choices=STATUSES)
    p.add_argument("--upstream", help="ссылка на issue/PR у автора инструмента")
    p.set_defaults(fn=cmd_touch)
    sub.add_parser("index", parents=[common], help="пересобрать INDEX.md").set_defaults(fn=cmd_index)
    sub.add_parser("lint", parents=[common], help="проверить заметки и индекс").set_defaults(fn=cmd_lint)
    p = sub.add_parser("search", parents=[common], help="поиск с ранжированием")
    p.add_argument("terms", nargs="+")
    p.add_argument("--limit", type=int, default=8)
    p.add_argument("--status", choices=STATUSES)
    p.add_argument("--area")
    p.set_defaults(fn=cmd_search)
    p = sub.add_parser("list", parents=[common], help="последние заметки по дате правки")
    p.add_argument("--limit", type=int, default=20)
    p.set_defaults(fn=cmd_list)
    p = sub.add_parser("issue-draft", parents=[common], help="черновик issue из заметки (stdout, с маской)")
    p.add_argument("id")
    p.set_defaults(fn=cmd_issue)
    p = sub.add_parser("migrate", parents=[common], help="перевести заметки старого формата во frontmatter")
    p.add_argument("--from", dest="source", required=True, help="хранилище или его notes/")
    p.add_argument("--apply", action="store_true")
    p.set_defaults(fn=cmd_migrate)
    return ap


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    args = build_parser().parse_args(argv)
    try:
        return args.fn(Context(args), args)
    except FieldNotesError as exc:
        print(f"fieldnotes: {exc}", file=sys.stderr)
        return exc.code


if __name__ == "__main__":
    sys.exit(main())
