# -*- coding: utf-8 -*-
"""
SplitCode 2.5 — умное разделение файлов на части. Мобильная версия.

Поддержка: .py, .js, .mjs, .bat, .cmd, .html, .htm, .txt,
           .css, .json, .xml, .yaml, .yml, .md, .markdown

Изменения в 2.5:
  • Удалён флаг pad: padding имён теперь всегда включён
    (part01, part02, … part10, part11). Параметр убран из make_part_name,
    do_split и CLI. Галочка «pad» удалена из интерфейса.

Изменения в 2.4:
  • Padding был введён как опция.

Изменения в 2.3:
  • Убраны все эмодзи и типографские символы (ASCII-вывод).
  • Компактный интерфейс под мобильные экраны.
  • Самопроверка сохраняет отчёт в файл, статус — краткий.
  • Исправлен HTML-сканер (учёт кавычек внутри тега).
  • Заголовки не портят JSON; YAML получает '#'-комментарий.

Запуск:
    python split_code.py                 — графический интерфейс
    python split_code.py file.py -n 3    — CLI: разбить на 3 части
    python split_code.py file.py --preview
    python split_code.py --selftest
"""

import os
import re
import sys
import shutil

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
    TK_OK = True
except ImportError:
    TK_OK = False


APP_VERSION = "2.5"
APP_NAME = "SplitCode"

SUPPORTED_EXT = (
    ".py", ".js", ".mjs", ".bat", ".cmd", ".html", ".htm", ".txt",
    ".css", ".json", ".xml", ".yaml", ".yml", ".md", ".markdown",
)

BOM_UTF8 = b"\xef\xbb\xbf"
ENCODINGS = ("utf-8", "cp1251", "cp866")

LANG_NAMES = {
    ".py": "Python", ".js": "JavaScript", ".mjs": "JavaScript",
    ".bat": "Batch", ".cmd": "Batch",
    ".html": "HTML", ".htm": "HTML",
    ".txt": "Text", ".css": "CSS", ".json": "JSON",
    ".xml": "XML", ".yaml": "YAML", ".yml": "YAML",
    ".md": "Markdown", ".markdown": "Markdown",
}

ENCODING_DISPLAY = {
    "utf-8": "UTF-8", "utf-8-sig": "UTF-8 BOM",
    "cp1251": "CP1251", "cp866": "CP866",
}


# ---------------------------------------------------------------------------
# Чтение и запись
# ---------------------------------------------------------------------------
def read_text(path):
    """Читает файл, подбирая кодировку. Возвращает (текст, кодировка)."""
    with open(path, "rb") as f:
        raw = f.read()
    if raw.startswith(BOM_UTF8):
        return raw.decode("utf-8-sig"), "utf-8-sig"
    for enc in ENCODINGS:
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace"), "utf-8"


def _read_with(path, enc):
    """Читает файл в заданной кодировке (для проверки целостности)."""
    with open(path, "rb") as f:
        raw = f.read()
    try:
        return raw.decode(enc)
    except UnicodeDecodeError:
        return raw.decode("utf-8", errors="replace")


def detect_newline(text):
    """Определяет тип окончания строк: CRLF, CR или LF."""
    if "\r\n" in text:
        return "\r\n"
    if "\r" in text:
        return "\r"
    return "\n"


def make_part_name(base, num, total, ext):
    """Имя части с обязательным padding.

    Ширина номера = max(2, len(str(total))). Например:
        total=3    -> part01, part02, part03
        total=12   -> part01 … part12
        total=1000 -> part0001 … part1000
    """
    width = max(2, len(str(total)))
    num_str = str(num).zfill(width)
    return "{}_part{}{}".format(base, num_str, ext)


def human_size(n):
    """Форматирует размер в удобочитаемый вид."""
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return "{:.1f} {}".format(n, unit)
        n /= 1024.0
    return "{:.1f} TB".format(n)


def _skip_quoted(line, i, quote):
    """Пропускает однострочную строку в кавычках (i указывает на кавычку)."""
    n = len(line)
    i += 1
    while i < n:
        if line[i] == "\\":
            i += 2
            continue
        if line[i] == quote:
            return i + 1
        i += 1
    return n


def _find_tag_end(line, start):
    """Находит '>' в теге, пропуская кавычки (для HTML)."""
    i, n = start, len(line)
    while i < n:
        ch = line[i]
        if ch in ('"', "'"):
            i = _skip_quoted(line, i, ch)
            continue
        if ch == ">":
            return i
        i += 1
    return -1
    # ---------------------------------------------------------------------------
# Сканеры состояний
# ---------------------------------------------------------------------------
def py_scan(lines):
    """Python: (внутри многострочного литерала?, баланс скобок)."""
    inside = None
    depth = 0
    in_str, depths = [], []

    for line in lines:
        in_str.append(inside is not None)
        depths.append(depth)

        i, n = 0, len(line)
        while i < n:
            if inside:
                if line.startswith(inside, i):
                    i += len(inside)
                    inside = None
                    continue
                i += 1
                continue

            triple = line[i:i + 3]
            if triple == '"""' or triple == "'''":
                inside = triple
                i += 3
                continue

            ch = line[i]
            if ch == "#":
                break
            if ch in ('"', "'"):
                i = _skip_quoted(line, i, ch)
                continue
            if ch in "([{":
                depth += 1
            elif ch in ")]}":
                depth = max(0, depth - 1)
            i += 1

    return in_str, depths


def js_scan(lines):
    """JS/CSS: комментарии, шаблонные строки, скобки."""
    in_block = False
    in_template = False
    depth = 0
    in_str, depths = [], []

    for line in lines:
        in_str.append(in_block or in_template)
        depths.append(depth)

        i, n = 0, len(line)
        while i < n:
            if in_block:
                if line.startswith("*/", i):
                    in_block = False
                    i += 2
                    continue
                i += 1
                continue

            if in_template:
                if line[i] == "\\":
                    i += 2
                    continue
                if line[i] == "`":
                    in_template = False
                    i += 1
                    continue
                i += 1
                continue

            if line.startswith("//", i):
                break
            if line.startswith("/*", i):
                in_block = True
                i += 2
                continue

            ch = line[i]
            if ch == "`":
                in_template = True
                i += 1
                continue
            if ch in ('"', "'"):
                i = _skip_quoted(line, i, ch)
                continue
            if ch in "([{":
                depth += 1
            elif ch in ")]}":
                depth = max(0, depth - 1)
            i += 1

    return in_str, depths


HTML_VOID = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
}
RAW_TAGS = {"script", "style"}


def html_scan(lines):
    """HTML/XML: комментарии, <script>/<style>, баланс тегов."""
    in_comment = False
    in_raw = None
    depth = 0
    open_names = []
    in_str, depths, opens = [], [], []

    for line in lines:
        in_str.append(in_comment or in_raw is not None)
        depths.append(depth)
        opens.append(tuple(open_names))

        i, n = 0, len(line)
        while i < n:
            if in_raw:
                m = re.search(r"</\s*" + in_raw + r"\b", line[i:], re.I)
                if m:
                    i += m.start()
                    in_raw = None
                    continue
                break

            if in_comment:
                if line.startswith("-->", i):
                    in_comment = False
                    i += 3
                    continue
                i += 1
                continue

            if line.startswith("<!--", i):
                in_comment = True
                i += 4
                continue

            if line.startswith("<!", i):
                end = _find_tag_end(line, i)
                i = n if end == -1 else end + 1
                continue

            if line.startswith("<", i):
                m = re.match(r"<\s*(/?)\s*([a-zA-Z][\w-]*)", line[i:])
                if m:
                    closing, name = m.group(1), m.group(2).lower()
                    end = _find_tag_end(line, i)

                    if end == -1:
                        if not closing and name not in HTML_VOID:
                            depth += 1
                            if name in RAW_TAGS:
                                in_raw = name
                        break

                    self_closing = line[i:end].rstrip().endswith("/")

                    if closing:
                        depth = max(0, depth - 1)
                        if name in open_names:
                            open_names.reverse()
                            open_names.remove(name)
                            open_names.reverse()
                    elif name not in HTML_VOID and not self_closing:
                        depth += 1
                        open_names.append(name)
                        if name in RAW_TAGS:
                            in_raw = name

                    i = end + 1
                    continue

            i += 1

    return in_str, depths, opens
    # ---------------------------------------------------------------------------
# Определение безопасных строк
# ---------------------------------------------------------------------------
PY_BAD_START = re.compile(r"^(else|elif|except|finally|case)\b")
JS_BAD_START = re.compile(r"^(else|catch|finally|case|default)\b")


def py_safe(lines):
    """Python: строка верхнего уровня вне строк/скобок."""
    in_str, depth = py_scan(lines)
    safe = []
    prev_continues = False

    for i, line in enumerate(lines):
        stripped = line.strip()
        indent = len(line) - len(line.lstrip(" \t"))
        ok = (
            depth[i] == 0
            and not in_str[i]
            and bool(stripped)
            and indent == 0
            and not prev_continues
            and not PY_BAD_START.match(stripped)
        )
        safe.append(ok)
        prev_continues = stripped.endswith("\\")

    # Декоратор нельзя отрывать от следующего определения
    for i, line in enumerate(lines):
        if line.strip().startswith("@") and i + 1 < len(lines):
            safe[i + 1] = False

    return safe


def js_safe(lines):
    """JS/CSS: вне строк/комментариев, при балансе скобок 0."""
    in_str, depth = js_scan(lines)
    safe = []
    prev_continues = False

    for i, line in enumerate(lines):
        stripped = line.strip()
        ok = (
            depth[i] == 0
            and not in_str[i]
            and bool(stripped)
            and not stripped.startswith(
                ("}", ")", "]", ".", ",", ";", ":", "?", "=>"))
            and not JS_BAD_START.match(stripped)
            and not prev_continues
        )
        safe.append(ok)
        prev_continues = stripped.endswith("\\")

    return safe


def bat_safe(lines):
    """Batch: после пустой строки, перед меткой или после REM."""
    safe = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        prev_blank = i == 0 or not lines[i - 1].strip()
        ok = (
            bool(stripped)
            and (prev_blank
                 or stripped.startswith(":")
                 or stripped.lower().startswith("rem"))
        )
        safe.append(ok)
    return safe


HTML_SKELETON = {"html", "head", "body"}


def html_safe(lines):
    """HTML/XML: только когда открыты лишь html/head/body или ничего."""
    in_str, depth, opens = html_scan(lines)
    safe = []
    for i, line in enumerate(lines):
        ok = not in_str[i] and all(name in HTML_SKELETON
                                    for name in opens[i])
        safe.append(ok)
    return safe


def txt_safe(lines):
    """Текст: перед началом абзаца (после пустой строки)."""
    safe = []
    for i, line in enumerate(lines):
        prev_blank = i == 0 or not lines[i - 1].strip()
        safe.append(bool(line.strip()) and prev_blank)
    return safe


def md_safe(lines):
    """Markdown: перед заголовком, списком, блоком кода или абзацем."""
    safe = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            safe.append(False)
            continue
        prev_blank = i == 0 or not lines[i - 1].strip()
        is_heading = stripped.startswith("#")
        is_fence = stripped.startswith("```") or stripped.startswith("~~~")
        is_list = bool(re.match(r"^[-*+]\s", stripped))
        safe.append(prev_blank or is_heading or is_fence or is_list)
    return safe


def yaml_safe(lines):
    """YAML: только строки верхнего уровня с ключом."""
    safe = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            safe.append(False)
            continue
        indent = len(line) - len(line.lstrip(" "))
        is_key = bool(re.match(r"^[a-zA-Z_][\w-]*\s*:", stripped))
        safe.append(indent == 0 and is_key)
    return safe


def compute_safe(lines, ext):
    ext = ext.lower()
    if ext == ".py":
        return py_safe(lines)
    if ext in (".js", ".mjs", ".css"):
        return js_safe(lines)
    if ext in (".html", ".htm", ".xml"):
        return html_safe(lines)
    if ext in (".bat", ".cmd"):
        return bat_safe(lines)
    if ext in (".md", ".markdown"):
        return md_safe(lines)
    if ext in (".yaml", ".yml"):
        return yaml_safe(lines)
    return txt_safe(lines)
    # ---------------------------------------------------------------------------
# Приоритет границ
# ---------------------------------------------------------------------------
PY_GOOD = re.compile(r"^(async\s+def\b|def\b|class\b|@)")
JS_GOOD = re.compile(
    r"^(export\b|import\b|async\s+function\b|function\b|class\b|"
    r"const\b|let\b|var\b)"
)
HTML_GOOD = re.compile(
    r"^<\s*(html|head|body|main|header|footer|nav|section|article|div|"
    r"form|table|ul|ol|script|style|h[1-6])\b", re.I,
)
BAT_GOOD = re.compile(r"^:")
MD_GOOD = re.compile(r"^(#{1,6}\s|```|~~~)")
YAML_GOOD = re.compile(r"^[a-zA-Z_][\w-]*\s*:")
CSS_GOOD = re.compile(r"^[.#a-zA-Z@]")


def smart_score(line, ext):
    s = line.strip()
    if not s:
        return 0
    if ext == ".py":
        return 3 if PY_GOOD.match(s) else 0
    if ext in (".js", ".mjs"):
        return 3 if JS_GOOD.match(s) else 0
    if ext == ".css":
        return 2 if CSS_GOOD.match(s) else 0
    if ext in (".html", ".htm", ".xml"):
        return 3 if HTML_GOOD.match(s) else 0
    if ext in (".bat", ".cmd"):
        return 2 if BAT_GOOD.match(s) else 0
    if ext in (".md", ".markdown"):
        return 3 if MD_GOOD.match(s) else 0
    if ext in (".yaml", ".yml"):
        return 3 if YAML_GOOD.match(s) else 0
    return 0


def choose_boundaries(n, safe, parts, lines, ext):
    """Возвращает список индексов границ: [0, ..., n]."""
    if parts <= 1 or n <= 1:
        return [0, n]

    base, rem = divmod(n, parts)
    window = max(4, base // 3)
    boundaries = [0]
    start = 0

    for k in range(1, parts):
        target = k * base + min(k, rem)
        min_rest = parts - k

        lo = max(start + 1, target - window)
        hi = min(n - min_rest, target + window)

        candidates = []
        if lo <= hi:
            candidates = [j for j in range(lo, hi + 1) if safe[j]]

        if not candidates:
            lo2, hi2 = start + 1, n - min_rest
            if lo2 <= hi2:
                candidates = [j for j in range(lo2, hi2 + 1) if safe[j]]

        if candidates:
            def key(j):
                score = smart_score(lines[j], ext) if 0 <= j < len(lines) else 0
                return (abs(j - target), -score, j)
            best = min(candidates, key=key)
        else:
            best = target

        best = min(max(best, start + 1), n - min_rest)
        boundaries.append(best)
        start = best

    result = sorted(set(boundaries + [n]))

    if len(result) < parts + 1:
        result = [0]
        for k in range(1, parts):
            result.append(max(result[-1] + 1, int(k * n / parts)))
        result.append(n)

    return result


# ---------------------------------------------------------------------------
# HTML: закрытие/переоткрытие тегов на границах
# ---------------------------------------------------------------------------
def html_affixes(lines, bounds):
    """Возвращает список (prefix_tags, suffix_tags) для каждой части."""
    n = len(lines)
    try:
        _in_str, _depth, opens = html_scan(lines)
    except Exception:
        return [([], [])] * (len(bounds) - 1)

    affixes = []
    last = len(bounds) - 2
    for p in range(len(bounds) - 1):
        s, e = bounds[p], bounds[p + 1]
        prefix, suffix = [], []

        if p > 0 and s < n:
            for tag in opens[s]:
                prefix.append("<{}>".format(tag))

        if p < last and e < n:
            for tag in reversed(opens[e]):
                if tag not in HTML_VOID:
                    suffix.append("</{}>".format(tag))

        affixes.append((prefix, suffix))
    return affixes


def compute_affixes(lines, bounds, ext):
    if ext.lower() in (".html", ".htm"):
        return html_affixes(lines, bounds)
    return [([], [])] * (len(bounds) - 1)
    # ---------------------------------------------------------------------------
# Заголовки
# ---------------------------------------------------------------------------
def _header_prefix(ext):
    ext = ext.lower()
    if ext == ".py":
        return "# "
    if ext in (".js", ".mjs", ".css"):
        return "// "
    if ext in (".bat", ".cmd"):
        return "REM "
    if ext in (".html", ".htm", ".xml", ".md", ".markdown"):
        return "<!-- "
    if ext in (".yaml", ".yml"):
        return "# "
    return ""


def _header_suffix(ext):
    if ext.lower() in (".html", ".htm", ".xml", ".md", ".markdown"):
        return " -->"
    return ""


def make_header(ext, base_name, part_num, total, start, end, newline="\n"):
    """Заголовок-комментарий. Пустой список, если формат не поддерживает."""
    prefix = _header_prefix(ext)
    if not prefix:
        return []
    title = "Часть {} из {} | {} | строки {}-{}".format(
        part_num, total, base_name, start, end)
    bar = "=" * 10
    line = "{}{} {} {}{}".format(
        prefix, bar, title, bar, _header_suffix(ext))
    return [line + newline, newline]


# ---------------------------------------------------------------------------
# Предпросмотр
# ---------------------------------------------------------------------------
def preview_boundaries(path, parts):
    """Возвращает сведения о будущих частях без записи файлов."""
    if not os.path.isfile(path):
        raise FileNotFoundError("Файл не найден: {}".format(path))

    text, enc = read_text(path)
    lines = text.splitlines(keepends=True)
    if not lines:
        raise ValueError("Файл пуст — нечего разделять.")
    if len(lines) == 1 and parts > 1:
        raise ValueError("В файле всего 1 строка — разделить нельзя.")

    base, ext = os.path.splitext(os.path.basename(path))
    if parts > len(lines):
        parts = len(lines)

    safe = compute_safe(lines, ext)
    bounds = choose_boundaries(len(lines), safe, parts, lines, ext)

    info = []
    for p in range(len(bounds) - 1):
        s, e = bounds[p], bounds[p + 1]
        size = sum(len(l) for l in lines[s:e])
        info.append({
            "num": p + 1, "start": s + 1, "end": e,
            "lines": e - s, "bytes": size,
        })

    return {
        "bounds": bounds, "parts": info, "encoding": enc,
        "newline": detect_newline(text), "total_lines": len(lines),
        "ext": ext, "base": base,
    }


# ---------------------------------------------------------------------------
# Основная операция
# ---------------------------------------------------------------------------
def do_split(path, parts, with_headers=True, out_dir=None,
             progress_cb=None):
    """Разделяет файл на части. Возвращает dict с результатом.

    Имена частей всегда с padding: part01, part02, … part10, part11.
    """
    if not os.path.isfile(path):
        raise FileNotFoundError("Файл не найден: {}".format(path))

    text, enc = read_text(path)
    lines = text.splitlines(keepends=True)
    newline = detect_newline(text)

    if not lines:
        raise ValueError("Файл пуст — нечего разделять.")
    if len(lines) == 1 and parts > 1:
        raise ValueError("В файле всего 1 строка — разделить нельзя.")

    base, ext = os.path.splitext(os.path.basename(path))
    if out_dir is None:
        out_dir = os.path.dirname(os.path.abspath(path))
    else:
        out_dir = os.path.abspath(out_dir)
        os.makedirs(out_dir, exist_ok=True)

    warn = ""
    if parts > len(lines):
        parts = len(lines)
        warn = "Частей больше, чем строк: разделено на {}.".format(parts)

    safe = compute_safe(lines, ext)
    bounds = choose_boundaries(len(lines), safe, parts, lines, ext)
    total = len(bounds) - 1
    if total != parts:
        extra = "Не удалось выдержать запрос, сделано {}.".format(total)
        warn = (warn + " " + extra).strip()

    affixes = compute_affixes(lines, bounds, ext)
    can_header = with_headers and bool(_header_prefix(ext))
    out_enc = enc
    created, written_encs, written_sizes = [], [], []

    for p in range(total):
        s, e = bounds[p], bounds[p + 1]
        header = (make_header(ext, base, p + 1, total, s + 1, e, newline)
                  if can_header else [])

        prefix_tags, suffix_tags = affixes[p]
        prefix_lines = [t + newline for t in prefix_tags]
        suffix_lines = [t + newline for t in suffix_tags]

        chunk = header + prefix_lines + lines[s:e] + suffix_lines
        name = make_part_name(base, p + 1, total, ext)
        full = os.path.join(out_dir, name)
        cur_enc = "utf-8" if (out_enc == "utf-8-sig" and p > 0) else out_enc

        try:
            with open(full, "w", encoding=cur_enc, newline="") as f:
                f.write("".join(chunk))
        except UnicodeEncodeError:
            cur_enc = "utf-8"
            with open(full, "w", encoding=cur_enc, newline="") as f:
                f.write("".join(chunk))

        created.append(name)
        written_encs.append(cur_enc)
        written_sizes.append(os.path.getsize(full))

        if progress_cb:
            progress_cb(int((p + 1) / total * 100))

    # Проверка целостности: снимаем заголовки/аффиксы, сверяем с оригиналом
    integrity = True
    try:
        pieces = []
        for p, name in enumerate(created):
            full = os.path.join(out_dir, name)
            back = _read_with(full, written_encs[p])
            blines = back.splitlines(keepends=True)

            if can_header and len(blines) >= 2:
                blines = blines[2:]

            prefix_n = len(affixes[p][0])
            suffix_n = len(affixes[p][1])
            if prefix_n > 0 and len(blines) >= prefix_n:
                blines = blines[prefix_n:]
            if suffix_n > 0 and len(blines) >= suffix_n:
                blines = blines[:-suffix_n]

            pieces.append("".join(blines))
        integrity = "".join(pieces) == text
    except Exception:
        integrity = False

    return {
        "files": created,
        "paths": [os.path.join(out_dir, n) for n in created],
        "integrity": integrity,
        "encoding": out_enc,
        "warn": warn,
        "total": total,
        "out_dir": out_dir,
        "sizes": written_sizes,
    }


# ---------------------------------------------------------------------------
# Обратная сборка
# ---------------------------------------------------------------------------
def recombine(paths, out_path, strip_headers=True):
    """Собирает части обратно в один файл."""
    if not paths:
        raise ValueError("Список файлов пуст.")

    parts = []
    enc_used = None
    for p in paths:
        if not os.path.isfile(p):
            raise FileNotFoundError("Файл не найден: {}".format(p))
        text, enc = read_text(p)
        if enc_used is None:
            enc_used = enc
        lines = text.splitlines(keepends=True)
        if (strip_headers and lines
                and "Часть " in lines[0] and " из " in lines[0]):
            lines = lines[2:] if len(lines) >= 2 else []
        parts.append("".join(lines))

    result = "".join(parts)
    out_dir = os.path.dirname(os.path.abspath(out_path)) or "."
    os.makedirs(out_dir, exist_ok=True)
    with open(out_path, "w", encoding=enc_used or "utf-8",
              newline="") as f:
        f.write(result)
    return out_path
    # ---------------------------------------------------------------------------
# Самопроверка
# ---------------------------------------------------------------------------
class Report(object):
    __slots__ = ("group", "name", "ok", "detail", "ms")

    def __init__(self, group, name, ok, detail="", ms=0.0):
        self.group = group
        self.name = name
        self.ok = ok
        self.detail = detail
        self.ms = ms


def _build_cases(tmp):
    cases = []

    def add(group, name):
        def deco(fn):
            cases.append((group, name, fn))
            return fn
        return deco

    def write(fname, text, enc="utf-8"):
        path = os.path.join(tmp, fname)
        with open(path, "w", encoding=enc, newline="") as f:
            f.write(text)
        return path

    G_PARSE = "Парсеры"
    G_BOUNDS = "Границы"
    G_FILES = "Файлы"
    G_ERRORS = "Ошибки"
    G_HEAD = "Заголовки"
    G_EXTRA = "Дополнительно"

    PY = (
        "import os\n\n"
        "def a():\n    return 1\n\n"
        "def b():\n    return 2\n\n"
        "def c():\n    return 3\n"
    )
    JS = (
        "const a = 1;\n\n"
        "function b() {\n    return 2;\n}\n\n"
        "function c() {\n    return 3;\n}\n"
    )
    HTML = (
        "<!DOCTYPE html>\n<html>\n<head>\n<title>t</title>\n</head>\n"
        "<body>\n<p>1</p>\n<p>2</p>\n</body>\n</html>\n"
    )
    BAT = "@echo off\nrem part 1\necho one\n\nrem part 2\necho two\n"
    TXT = "Первый абзац.\n\nВторой абзац.\n\nТретий абзац.\n"
    CSS = "body {\n    color: red;\n}\n\n.header {\n    font-size: 12px;\n}\n"

    @add(G_PARSE, "Python: многострочный литерал")
    def _():
        lines = ['x = """\n', "abc\n", '"""\n', "y = 1\n"]
        in_str, _d = py_scan(lines)
        assert in_str == [False, True, True, False], in_str

    @add(G_PARSE, "Python: скобки не режутся")
    def _():
        lines = ["data = {\n", '    "a": 1,\n', "}\n", "x = 2\n"]
        safe = py_safe(lines)
        assert safe == [True, False, False, True], safe

    @add(G_PARSE, "Python: декоратор не отрывается")
    def _():
        lines = ["@deco\n", "def f():\n", "    return 1\n", "\n", "x = 2\n"]
        safe = py_safe(lines)
        assert safe[0] is True and safe[1] is False, safe

    @add(G_PARSE, "JavaScript: шаблонная строка")
    def _():
        lines = ["let a = `x\n", "y`;\n", "let b = 1;\n"]
        in_str, _d = js_scan(lines)
        assert in_str == [False, True, False], in_str

    @add(G_PARSE, "JavaScript: блочный комментарий")
    def _():
        lines = ["/* start\n", "text\n", "end */\n", "let a = 1;\n"]
        in_str, _d = js_scan(lines)
        assert in_str == [False, True, True, False], in_str

    @add(G_PARSE, "HTML: комментарий")
    def _():
        lines = ["<!--\n", "x\n", "-->\n", "<p>ok</p>\n"]
        in_str, _d, _o = html_scan(lines)
        assert in_str == [False, True, True, False], in_str

    @add(G_PARSE, "HTML: блок <script>")
    def _():
        lines = ["<script>\n", "var a = 1;\n", "</script>\n", "<p>x</p>\n"]
        in_str, _d, opens = html_scan(lines)
        assert in_str[:3] == [False, True, True], in_str
        assert "script" not in opens[3], opens[3]

    @add(G_PARSE, "HTML: > внутри кавычек")
    def _():
        lines = ['<div title="a > b">\n', "</div>\n", "<p>x</p>\n"]
        in_str, depth, opens = html_scan(lines)
        assert "div" in opens[1], opens[1]
        assert "div" not in opens[2], opens[2]

    @add(G_BOUNDS, "Индексы границ корректны")
    def _():
        lines = PY.splitlines(True)
        safe = py_safe(lines)
        b = choose_boundaries(len(lines), safe, 3, lines, ".py")
        assert b[0] == 0 and b[-1] == len(lines), b
        assert all(b[i] < b[i + 1] for i in range(len(b) - 1)), b

    @add(G_BOUNDS, "Границы не рвут конструкцию")
    def _():
        lines = PY.splitlines(True)
        safe = py_safe(lines)
        b = choose_boundaries(len(lines), safe, 3, lines, ".py")
        for idx in b[1:-1]:
            assert safe[idx], "граница {} внутри".format(idx)

    @add(G_BOUNDS, "Части покрывают файл без пропусков")
    def _():
        lines = PY.splitlines(True)
        safe = py_safe(lines)
        b = choose_boundaries(len(lines), safe, 3, lines, ".py")
        joined = "".join("".join(lines[b[i]:b[i + 1]])
                        for i in range(len(b) - 1))
        assert joined == PY, "части не совпадают"

    def check_file(fname, content, enc, parts):
        path = write(fname, content, enc)
        result = do_split(path, parts, True)
        assert len(result["files"]) == parts, \
            "частей: {} вместо {}".format(len(result["files"]), parts)
        assert result["integrity"], "целостность не совпала"
        assert result["encoding"] == enc, \
            "кодировка: {} вместо {}".format(result["encoding"], enc)

    @add(G_FILES, ".py -> 3 части")
    def _():
        check_file("t.py", PY, "utf-8", 3)

    @add(G_FILES, ".js -> 2 части")
    def _():
        check_file("t.js", JS, "utf-8", 2)

    @add(G_FILES, ".html -> 2 части")
    def _():
        check_file("t.html", HTML, "utf-8", 2)

    @add(G_FILES, ".bat -> 2 части")
    def _():
        check_file("t.bat", BAT, "utf-8", 2)

    @add(G_FILES, ".css -> 2 части")
    def _():
        check_file("t.css", CSS, "utf-8", 2)

    @add(G_FILES, "UTF-8 BOM")
    def _():
        check_file("bom.txt", "Alpha\nBeta\n", "utf-8-sig", 2)

    @add(G_FILES, "CP1251")
    def _():
        check_file("cp.txt", "Щедрый щавель.\nВторая строка.\n", "cp1251", 2)

    @add(G_ERRORS, "Пустой файл -> ValueError")
    def _():
        path = write("empty.py", "")
        try:
            do_split(path, 2, True)
        except ValueError:
            return
        raise AssertionError("ожидался ValueError")

    @add(G_ERRORS, "1 строка и 2 части -> ValueError")
    def _():
        path = write("one.py", "only\n")
        try:
            do_split(path, 2, True)
        except ValueError:
            return
        raise AssertionError("ожидался ValueError")

    @add(G_ERRORS, "Частей больше строк -> предупреждение")
    def _():
        path = write("two.py", "a\nb\n")
        result = do_split(path, 5, True)
        assert result["warn"] and len(result["files"]) == 2
        assert result["integrity"]

    @add(G_HEAD, "Заголовок для форматов с комментариями")
    def _():
        expected = {
            ".py": "#", ".js": "//", ".bat": "REM ",
            ".html": "<!--", ".css": "//", ".yaml": "#",
        }
        for ext, prefix in expected.items():
            head = make_header(ext, "f", 1, 2, 1, 5)[0]
            assert head.startswith(prefix), head
            assert "Часть 1 из 2" in head, head

    @add(G_HEAD, "JSON без заголовка (нет комментариев)")
    def _():
        assert make_header(".json", "f", 1, 2, 1, 5) == []

    @add(G_EXTRA, "Padding имён всегда включён")
    def _():
        assert make_part_name("file", 1, 12, ".py") == "file_part01.py"
        assert make_part_name("file", 9, 12, ".py") == "file_part09.py"
        assert make_part_name("file", 1, 3, ".py") == "file_part01.py"
        assert make_part_name("file", 3, 3, ".py") == "file_part03.py"
        assert make_part_name("file", 1, 100, ".py") == "file_part001.py"

    @add(G_EXTRA, "CRLF сохраняется")
    def _():
        path = write("crlf.txt", "one\r\ntwo\r\nthree\r\n")
        result = do_split(path, 2, True)
        with open(result["paths"][0], "rb") as f:
            content = f.read()
        assert b"\r\n" in content, "CRLF потерян"

    @add(G_EXTRA, "Предпросмотр")
    def _():
        path = write("pv.py", PY)
        info = preview_boundaries(path, 3)
        assert len(info["parts"]) == 3
        assert info["total_lines"] == len(PY.splitlines())

    @add(G_EXTRA, "Recombine восстанавливает файл")
    def _():
        path = write("rc.py", PY)
        result = do_split(path, 3, False)
        out = os.path.join(tmp, "rc_joined.py")
        recombine(result["paths"], out, strip_headers=False)
        with open(out, "r", encoding="utf-8", newline="") as f:
            joined = f.read()
        assert joined == PY, "recombine не восстановил"

    return cases


def selftest(progress_cb=None):
    """Самопроверка во временной папке. Возвращает (reports, время)."""
    import tempfile
    import time

    started = time.time()
    tmp = tempfile.mkdtemp(prefix="splitcode_selftest_")
    reports = []

    try:
        cases = _build_cases(tmp)
        total = len(cases)
        for idx, (group, name, fn) in enumerate(cases):
            t0 = time.time()
            ok, detail = True, ""
            try:
                fn()
            except AssertionError as exc:
                ok, detail = False, str(exc) or "условие не выполнено"
            except Exception as exc:
                ok, detail = False, "{}: {}".format(type(exc).__name__, exc)
            reports.append(Report(group, name, ok, detail,
                                  (time.time() - t0) * 1000.0))
            if progress_cb:
                progress_cb(idx + 1, total)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    return reports, time.time() - started


def save_selftest_report(reports, elapsed, out_path):
    """Сохраняет отчёт в файл. Возвращает (путь, ошибка_или_None)."""
    bad = [r for r in reports if not r.ok]
    lines = ["{} {} - самопроверка".format(APP_NAME, APP_VERSION),
             "=" * 60, ""]
    group = None
    for r in reports:
        if r.group != group:
            group = r.group
            lines.append("")
            lines.append("[{}]".format(group))
        status = "OK  " if r.ok else "FAIL"
        lines.append("  [{}] {} ({:.1f} ms)".format(status, r.name, r.ms))
        if not r.ok:
            lines.append("       -> " + r.detail)

    lines.append("")
    lines.append("=" * 60)
    lines.append("Итог: {} из {} пройдено за {:.2f} с".format(
        len(reports) - len(bad), len(reports), elapsed))

    try:
        with open(out_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
    except OSError as e:
        return None, str(e)
    return out_path, None


def _cli_report(reports, elapsed):
    bad = [r for r in reports if not r.ok]
    bar = "-" * 60
    out = ["{} {} - самопроверка".format(APP_NAME, APP_VERSION), bar]

    group = None
    for r in reports:
        if r.group != group:
            group = r.group
            out.append("")
            out.append(group)
        mark = "[v]" if r.ok else "[x]"
        out.append("  {} {:<44} {:>7.1f} ms".format(mark, r.name, r.ms))
        if not r.ok:
            out.append("      -> {}".format(r.detail))

    out.append("")
    out.append(bar)
    out.append("Итог: {} из {} пройдено за {:.2f} с".format(
        len(reports) - len(bad), len(reports), elapsed))

    try:
        print("\n".join(out))
    except UnicodeEncodeError:
        print("\n".join(out).encode("ascii", "replace").decode("ascii"))

    return 0 if not bad else 1


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _cli_split(argv):
    import argparse
    parser = argparse.ArgumentParser(
        prog=os.path.basename(sys.argv[0]) or "split_code.py",
        description="{} {} - умное разделение файлов.".format(
            APP_NAME, APP_VERSION),
    )
    parser.add_argument("file", help="Исходный файл")
    parser.add_argument("-n", "--parts", type=int, default=2,
                        help="Число частей (по умолчанию 2)")
    parser.add_argument("-o", "--out", help="Папка для результата")
    parser.add_argument("--no-headers", action="store_true",
                        help="Не добавлять заголовки")
    parser.add_argument("--preview", action="store_true",
                        help="Только показать границы")
    args = parser.parse_args(argv)

    if args.preview:
        info = preview_boundaries(args.file, args.parts)
        print("Файл: {} | {} | строк: {}".format(
            args.file,
            ENCODING_DISPLAY.get(info["encoding"], info["encoding"]),
            info["total_lines"]))
        print("-" * 60)
        for p in info["parts"]:
            print("  Часть {:>2}: строки {}-{}  ({} строк, {})".format(
                p["num"], p["start"], p["end"], p["lines"],
                human_size(p["bytes"])))
        return 0

    result = do_split(
        args.file, args.parts,
        with_headers=not args.no_headers,
        out_dir=args.out,
    )
    print("Готово: {} файлов в {}".format(
        len(result["files"]), result["out_dir"]))
    print("Кодировка: {}".format(
        ENCODING_DISPLAY.get(result["encoding"], result["encoding"])))
    print("Целостность: {}".format(
        "OK" if result["integrity"] else "ОШИБКА"))
    if result["warn"]:
        print("Внимание: {}".format(result["warn"]))
    for name in result["files"]:
        print("  - {}".format(name))
    return 0 if result["integrity"] else 2
    # ---------------------------------------------------------------------------
# Графический интерфейс — часть 7a: темы, стили, каркас, справка
# ---------------------------------------------------------------------------
if TK_OK:

    THEMES = {
        "light": {
            "bg": "#F5F7FB", "card": "#FFFFFF", "border": "#E3E8F0",
            "text": "#1F2937", "muted": "#6B7280", "accent": "#4F7CF7",
            "accent_hover": "#3D6BE5", "ok": "#16A34A", "err": "#DC2626",
            "warn": "#D97706",
            "progress_bg": "#E3E8F0",
        },
        "dark": {
            "bg": "#0F172A", "card": "#1E293B", "border": "#334155",
            "text": "#E2E8F0", "muted": "#94A3B8", "accent": "#60A5FA",
            "accent_hover": "#3B82F6", "ok": "#4ADE80", "err": "#F87171",
            "warn": "#FBBF24",
            "progress_bg": "#334155",
        },
    }


    class CodeSplitterApp:
        def __init__(self, root):
            self.root = root
            self.theme = "light"
            self.file_path = ""
            self.out_dir = ""
            self.is_processing = False
            self._st_busy = False

            root.title("{} {}".format(APP_NAME, APP_VERSION))
            root.minsize(320, 560)
            self._center(380, 680)
            root.configure(bg=THEMES[self.theme]["bg"])

            self._build_style()
            self._build_ui()
            self._apply_theme()

            root.bind("<F1>", lambda e: self.show_help())

        def _center(self, w, h):
            self.root.update_idletasks()
            x = max(0, (self.root.winfo_screenwidth() - w) // 2)
            y = max(0, (self.root.winfo_screenheight() - h) // 2)
            self.root.geometry("{}x{}+{}+{}".format(w, h, x, y))

        def _build_style(self):
            style = ttk.Style()
            try:
                style.theme_use("clam")
            except tk.TclError:
                pass
            self.style = style

        def _apply_theme(self):
            t = THEMES[self.theme]
            self.root.configure(bg=t["bg"])
            s = self.style
            s.configure(".", background=t["bg"], foreground=t["text"],
                        font=("Segoe UI", 9))
            s.configure("TFrame", background=t["bg"])
            s.configure("CardWrapper.TFrame", background=t["border"])
            s.configure("Card.TFrame", background=t["card"])
            s.configure("TLabel", background=t["bg"], foreground=t["text"])
            s.configure("Card.TLabel", background=t["card"],
                        foreground=t["text"])
            s.configure("CardTitle.TLabel", background=t["card"],
                        foreground=t["text"],
                        font=("Segoe UI", 10, "bold"))
            s.configure("CardMuted.TLabel", background=t["card"],
                        foreground=t["muted"], font=("Segoe UI", 8))
            s.configure("Muted.TLabel", foreground=t["muted"],
                        font=("Segoe UI", 8))
            s.configure("Title.TLabel", font=("Segoe UI", 13, "bold"),
                        foreground=t["text"])
            s.configure("Subtitle.TLabel", font=("Segoe UI", 9),
                        foreground=t["muted"])
            s.configure("Accent.TButton", font=("Segoe UI", 10, "bold"),
                        foreground="white", background=t["accent"],
                        padding=(10, 7), relief="flat", borderwidth=0)
            s.map("Accent.TButton", background=[
                ("disabled", t["border"]),
                ("pressed", t["accent_hover"]),
                ("active", t["accent_hover"]),
            ])
            s.configure("TButton", font=("Segoe UI", 9), padding=(8, 5))
            s.configure("Small.TButton", font=("Segoe UI", 8),
                        padding=(6, 3))
            s.configure("TCheckbutton", background=t["card"],
                        foreground=t["text"], font=("Segoe UI", 9))
            s.map("TCheckbutton", background=[("active", t["card"])])
            s.configure("TSpinbox", fieldbackground=t["card"],
                        foreground=t["text"], arrowsize=10)
            s.configure("Horizontal.TProgressbar",
                        troughcolor=t["progress_bg"], background=t["accent"],
                        thickness=8, borderwidth=0)
            s.configure("Treeview", rowheight=22, background=t["card"],
                        fieldbackground=t["card"], foreground=t["text"],
                        borderwidth=0, font=("Segoe UI", 8))
            s.configure("Treeview.Heading", background=t["border"],
                        foreground=t["text"], font=("Segoe UI", 8, "bold"),
                        padding=(4, 3))

        def _make_card(self, parent, title=None):
            wrapper = ttk.Frame(parent, style="CardWrapper.TFrame")
            inner = ttk.Frame(wrapper, style="Card.TFrame")
            inner.pack(fill="both", expand=True, padx=1, pady=1)
            body = ttk.Frame(inner, style="Card.TFrame")
            body.pack(fill="both", expand=True, padx=10, pady=8)
            if title:
                ttk.Label(body, text=title,
                          style="CardTitle.TLabel").pack(
                    anchor="w", pady=(0, 5))
            return wrapper, body

        def _build_ui(self):
            top = ttk.Frame(self.root)
            top.pack(fill="x", padx=10, pady=(8, 4))
            ttk.Label(top, text="{} {}".format(APP_NAME, APP_VERSION),
                      style="Title.TLabel").pack(anchor="w")
            ttk.Label(top,
                      text="Умное разделение кода и текста",
                      style="Subtitle.TLabel").pack(anchor="w")

            wrap = ttk.Frame(self.root)
            wrap.pack(fill="both", expand=True, padx=10, pady=4)

            # Файл
            fw, fb = self._make_card(wrap, "Файл")
            fw.pack(fill="x", pady=(0, 6))
            row = ttk.Frame(fb, style="Card.TFrame")
            row.pack(fill="x")
            ttk.Button(row, text="Выбрать...",
                       command=self.browse_file).pack(side="left")
            self.file_display = ttk.Entry(row, state="readonly",
                                          font=("Consolas", 8))
            self.file_display.pack(side="left", fill="x", expand=True,
                                   padx=(6, 0))
            self.info_label = ttk.Label(fb, text="Файл не выбран",
                                        style="CardMuted.TLabel")
            self.info_label.pack(anchor="w", pady=(4, 0))

            # Параметры
            ow, ob = self._make_card(wrap, "Параметры")
            ow.pack(fill="x", pady=(0, 6))

            r1 = ttk.Frame(ob, style="Card.TFrame")
            r1.pack(fill="x", pady=(0, 5))
            ttk.Label(r1, text="Частей:",
                      style="Card.TLabel").pack(side="left")
            try:
                self.parts_spin = ttk.Spinbox(r1, from_=1, to=999, width=4,
                                              font=("Segoe UI", 9, "bold"))
            except AttributeError:
                self.parts_spin = tk.Spinbox(r1, from_=1, to=999, width=4,
                                             font=("Segoe UI", 9, "bold"))
            self.parts_spin.set("3")
            self.parts_spin.pack(side="left", padx=(6, 10))
            self.header_var = tk.BooleanVar(value=True)
            ttk.Checkbutton(r1, text="Заголовки",
                            variable=self.header_var).pack(side="left")

            r2 = ttk.Frame(ob, style="Card.TFrame")
            r2.pack(fill="x", pady=(0, 5))
            ttk.Label(r2, text="Куда:",
                      style="Card.TLabel").pack(side="left")
            self.out_display = ttk.Entry(r2, state="readonly",
                                         font=("Consolas", 8))
            self.out_display.pack(side="left", fill="x", expand=True,
                                  padx=(6, 4))
            self.out_display.configure(state="normal")
            self.out_display.insert(0, "рядом с файлом")
            self.out_display.configure(state="readonly")
            ttk.Button(r2, text="...", style="Small.TButton",
                       command=self.browse_out_dir).pack(side="left")

            r3 = ttk.Frame(ob, style="Card.TFrame")
            r3.pack(fill="x", pady=(4, 0))
            self.preview_btn = ttk.Button(r3, text="Preview",
                                          command=self.do_preview,
                                          state="disabled")
            self.preview_btn.pack(side="left")
            self.split_btn = ttk.Button(r3, text="Разделить",
                                        style="Accent.TButton",
                                        command=self.split_file,
                                        state="disabled")
            self.split_btn.pack(side="left", padx=(6, 0),
                                fill="x", expand=True)

            # Preview
            pw, pb = self._make_card(wrap, "Предпросмотр")
            pw.pack(fill="both", expand=True, pady=(0, 6))
            tree_wrap = ttk.Frame(pb, style="Card.TFrame")
            tree_wrap.pack(fill="both", expand=True)
            self.preview_tree = ttk.Treeview(
                tree_wrap, columns=("range", "lines", "size"),
                show="tree headings", height=3)
            self.preview_tree.heading("#0", text="#")
            self.preview_tree.heading("range", text="Строки")
            self.preview_tree.heading("lines", text="Л")
            self.preview_tree.heading("size", text="Размер")
            self.preview_tree.column("#0", width=28, anchor="w")
            self.preview_tree.column("range", width=110, anchor="w")
            self.preview_tree.column("lines", width=36, anchor="e")
            self.preview_tree.column("size", width=60, anchor="e")
            vsb = ttk.Scrollbar(tree_wrap, orient="vertical",
                                command=self.preview_tree.yview)
            self.preview_tree.configure(yscrollcommand=vsb.set)
            self.preview_tree.pack(side="left", fill="both", expand=True)
            vsb.pack(side="right", fill="y")
            self.preview_hint = ttk.Label(
                pb, text="Выберите файл.",
                style="CardMuted.TLabel")
            self.preview_hint.pack(anchor="w", pady=(3, 0))

            # Статус
            self.progress = ttk.Progressbar(wrap, mode="determinate",
                                            style="Horizontal.TProgressbar")
            self.progress.pack(fill="x", pady=(2, 4))
            self.status = ttk.Label(wrap, text="-  Готов к работе",
                                    style="Muted.TLabel", wraplength=340)
            self.status.pack(anchor="w", pady=(0, 4))

            # Кнопки
            bottom = ttk.Frame(wrap)
            bottom.pack(fill="x", pady=(2, 0))
            self.st_btn = ttk.Button(bottom, text="Selftest",
                                     command=self.run_selftest)
            self.st_btn.pack(side="left")
            ttk.Button(bottom, text="Help", style="Small.TButton",
                       command=self.show_help).pack(side="left",
                                                    padx=(4, 0))
            ttk.Button(bottom, text="Theme", style="Small.TButton",
                       command=self.toggle_theme).pack(side="left",
                                                       padx=(4, 0))
            ttk.Button(bottom, text="?", style="Small.TButton",
                       command=self.show_about).pack(side="left",
                                                     padx=(4, 0))

        def toggle_theme(self):
            self.theme = "dark" if self.theme == "light" else "light"
            self._apply_theme()

        # -------------------------------------------------------------------
        # Справка
        # -------------------------------------------------------------------
        def _doc_window(self, title, w, h):
            t = THEMES[self.theme]
            win = tk.Toplevel(self.root)
            win.title(title)
            win.configure(bg=t["bg"])
            win.transient(self.root)
            win.update_idletasks()
            x = max(0, (win.winfo_screenwidth() - w) // 2)
            y = max(0, (win.winfo_screenheight() - h) // 2)
            win.geometry("{}x{}+{}+{}".format(w, h, x, y))

            btn_frame = ttk.Frame(win)
            btn_frame.pack(side="bottom", fill="x")
            ttk.Button(btn_frame, text="Закрыть",
                       command=win.destroy).pack(pady=4)

            frame = ttk.Frame(win)
            frame.pack(side="top", fill="both", expand=True)
            txt = tk.Text(frame, wrap="word", bg=t["bg"], fg=t["text"],
                          font=("Segoe UI", 9), padx=12, pady=10,
                          relief="flat", cursor="arrow", borderwidth=0)
            sb = ttk.Scrollbar(frame, orient="vertical",
                               command=txt.yview)
            txt.configure(yscrollcommand=sb.set)
            txt.pack(side="left", fill="both", expand=True)
            sb.pack(side="right", fill="y")

            txt.tag_configure("h1", font=("Segoe UI", 13, "bold"),
                              foreground=t["text"], spacing1=2, spacing3=4)
            txt.tag_configure("h2", font=("Segoe UI", 10, "bold"),
                              foreground=t["accent"],
                              spacing1=8, spacing3=2)
            txt.tag_configure("body", font=("Segoe UI", 9),
                              foreground=t["text"])
            return win, txt

        def show_help(self):
            win, txt = self._doc_window("Справка", 340, 520)
            def H(s): txt.insert("end", s + "\n", "h2")
            def P(s): txt.insert("end", s + "\n", "body")

            txt.insert("end", "{} {}\n".format(APP_NAME, APP_VERSION), "h1")
            P("Умное разделение файлов с проверкой целостности.")

            H("Как это работает")
            P("1. Определяется кодировка: UTF-8 BOM, UTF-8, CP1251, CP866.")
            P("2. Парсер разбирает структуру файла.")
            P("3. Границы выбираются только на безопасных строках.")
            P("4. Приоритет у строк, начинающих блок.")
            P("5. Заголовок-комментарий в каждой части.")
            P("6. Части перечитываются и сверяются с оригиналом.")

            H("Форматы")
            P("Python: .py")
            P("JavaScript: .js .mjs")
            P("CSS: .css")
            P("Batch: .bat .cmd")
            P("HTML / XML: .html .htm .xml")
            P("Данные: .json .yaml .yml")
            P("Текст: .md .markdown .txt")

            H("Кнопки")
            P("Выбрать - открыть файл.")
            P("Preview - показать границы.")
            P("Разделить - выполнить разбивку.")
            P("Selftest - встроенные тесты. Отчёт сохраняется рядом с файлом.")
            P("Theme - светлая/тёмная тема.")
            P("F1 - эта справка.")

            H("Имена файлов")
            P("Padding включён всегда: part01, part02, ... part10.")

            H("CLI")
            P("python split_code.py file.py -n 3 -o out/")
            P("python split_code.py file.py --preview")
            P("python split_code.py --selftest")
            txt.config(state="disabled")

        def show_about(self):
            messagebox.showinfo(
                "О программе",
                "{} {}\n\n"
                "Умное разделение файлов на части.\n"
                "Парсеры: Python, JS, CSS, HTML/XML, Batch, "
                "YAML, Markdown.\n"
                "Автоопределение кодировки, проверка целостности.\n"
                "Предпросмотр, автопаддинг имён, тёмная тема.".format(
                    APP_NAME, APP_VERSION))
                            # -------------------------------------------------------------------
        # Файлы
        # -------------------------------------------------------------------
        def browse_file(self):
            filetypes = [
                ("Все поддерживаемые",
                 " ".join("*" + e for e in SUPPORTED_EXT)),
                ("Python", "*.py"),
                ("JavaScript", "*.js *.mjs"),
                ("Batch", "*.bat *.cmd"),
                ("HTML / XML", "*.html *.htm *.xml"),
                ("CSS / JSON / YAML", "*.css *.json *.yaml *.yml"),
                ("Markdown / Текст", "*.md *.markdown *.txt"),
                ("Все файлы", "*.*"),
            ]
            name = filedialog.askopenfilename(
                title="Выберите файл", filetypes=filetypes)
            if not name:
                return
            self.file_path = name
            self.out_dir = ""
            self.file_display.config(state="normal")
            self.file_display.delete(0, "end")
            self.file_display.insert(0, os.path.basename(name))
            self.file_display.config(state="readonly")
            self.out_display.config(state="normal")
            self.out_display.delete(0, "end")
            self.out_display.insert(0, "рядом с файлом")
            self.out_display.config(state="readonly")
            self._refresh_info()
            self.split_btn.config(state="normal")
            self.preview_btn.config(state="normal")
            self._set_status("-", "Файл выбран. Preview или Разделить.",
                             THEMES[self.theme]["muted"])
            self.do_preview()

        def browse_out_dir(self):
            if not self.file_path:
                return
            d = filedialog.askdirectory(title="Папка для результата")
            if not d:
                return
            self.out_dir = d
            self.out_display.config(state="normal")
            self.out_display.delete(0, "end")
            self.out_display.insert(0, d)
            self.out_display.config(state="readonly")

        def _refresh_info(self):
            ext = os.path.splitext(self.file_path)[1].lower()
            lang = LANG_NAMES.get(ext, "Другой")
            try:
                text, enc = read_text(self.file_path)
                n = len(text.splitlines())
                size = os.path.getsize(self.file_path)
                self.info_label.config(
                    text="{} | {} строк | {} | {}".format(
                        lang, n, human_size(size),
                        ENCODING_DISPLAY.get(enc, enc)))
            except OSError as e:
                self.info_label.config(text="Ошибка чтения: {}".format(e))

        def _set_status(self, icon, text, color):
            self.status.config(
                text="{}  {}".format(icon, text), foreground=color)

        # -------------------------------------------------------------------
        # Preview
        # -------------------------------------------------------------------
        def _parse_parts(self):
            try:
                v = int(self.parts_spin.get())
                return v if v >= 1 else None
            except (ValueError, tk.TclError):
                return None

        def do_preview(self):
            if not self.file_path:
                return
            parts = self._parse_parts()
            if parts is None:
                self._set_status("X", "Число частей должно быть > 0.",
                                 THEMES[self.theme]["err"])
                return
            try:
                info = preview_boundaries(self.file_path, parts)
            except Exception as e:
                self._set_status("X", "Preview: {}".format(e),
                                 THEMES[self.theme]["err"])
                return

            for item in self.preview_tree.get_children():
                self.preview_tree.delete(item)
            for p in info["parts"]:
                self.preview_tree.insert(
                    "", "end",
                    text=str(p["num"]),
                    values=("{}–{}".format(p["start"], p["end"]),
                            p["lines"], human_size(p["bytes"])))
            self.preview_hint.config(
                text="{} частей, {} строк, {}".format(
                    len(info["parts"]), info["total_lines"],
                    ENCODING_DISPLAY.get(info["encoding"],
                                         info["encoding"])))
            self._set_status(
                "v",
                "Preview: {} частей".format(len(info["parts"])),
                THEMES[self.theme]["muted"])

        # -------------------------------------------------------------------
        # Разделение
        # -------------------------------------------------------------------
        def _on_progress(self, frac):
            self.progress["value"] = frac
            self.root.update_idletasks()

        def split_file(self):
            if self.is_processing:
                return
            parts = self._parse_parts()
            if parts is None:
                self._set_status("X", "Число частей > 0.",
                                 THEMES[self.theme]["err"])
                return
            if not self.file_path or not os.path.isfile(self.file_path):
                self._set_status("X", "Файл не найден.",
                                 THEMES[self.theme]["err"])
                return

            self.is_processing = True
            self.split_btn.config(state="disabled")
            self.preview_btn.config(state="disabled")
            self.progress["value"] = 0
            self._set_status("...", "Разделение...",
                             THEMES[self.theme]["warn"])
            self.root.update_idletasks()

            try:
                result = do_split(
                    self.file_path, parts,
                    with_headers=self.header_var.get(),
                    out_dir=self.out_dir or None,
                    progress_cb=self._on_progress)

                self.progress["value"] = 100
                ok = result["integrity"]
                color = THEMES[self.theme]["ok" if ok else "err"]
                icon = "OK" if ok else "X"
                self._set_status(
                    icon,
                    "Готово: {} файлов | целостность {}".format(
                        len(result["files"]), "OK" if ok else "СБОЙ"),
                    color)

                msg = ("Файл разделён на {} частей.\n\n"
                       "Папка: {}\nКодировка: {}\n\n"
                       "Целостность: {}").format(
                    len(result["files"]), result["out_dir"],
                    ENCODING_DISPLAY.get(result["encoding"],
                                         result["encoding"]),
                    "пройдена" if ok else "ОШИБКА!")
                if result["warn"]:
                    msg = result["warn"] + "\n\n" + msg

                if ok:
                    messagebox.showinfo("Готово", msg)
                else:
                    messagebox.showerror("Целостность", msg)
            except Exception as e:
                self._set_status("X", "Ошибка: {}".format(e),
                                 THEMES[self.theme]["err"])
                messagebox.showerror("Ошибка", str(e))
            finally:
                self.is_processing = False
                self.split_btn.config(state="normal")
                if self.file_path:
                    self.preview_btn.config(state="normal")

        # -------------------------------------------------------------------
        # Самопроверка
        # -------------------------------------------------------------------
        def run_selftest(self):
            if self._st_busy:
                return
            import threading

            self._st_busy = True
            self.st_btn.config(state="disabled")
            self.progress["value"] = 0
            self._set_status("...", "Самопроверка...",
                             THEMES[self.theme]["warn"])
            self.root.update_idletasks()

            box = {"done": 0, "total": 1}

            def cb(done, total):
                box["done"] = done
                box["total"] = max(1, total)

            def worker():
                try:
                    box["res"] = selftest(progress_cb=cb)
                except Exception as exc:
                    box["err"] = exc

            threading.Thread(target=worker, daemon=True).start()

            def poll():
                if "res" in box or "err" in box:
                    self._st_busy = False
                    self.st_btn.config(state="normal")
                    self.progress["value"] = 100

                    if "err" in box:
                        self._set_status(
                            "X",
                            "Самопроверка упала: {}".format(box["err"]),
                            THEMES[self.theme]["err"])
                        return

                    reports, elapsed = box["res"]
                    bad = [r for r in reports if not r.ok]
                    passed = len(reports) - len(bad)
                    path, err = self._save_report(reports, elapsed)

                    if err:
                        self._set_status(
                            "X", "Отчёт не сохранён: {}".format(err),
                            THEMES[self.theme]["err"])
                    else:
                        self._set_status(
                            "OK" if not bad else "X",
                            "Самопроверка: {}/{} | отчёт: {}".format(
                                passed, len(reports), path),
                            THEMES[self.theme]["ok" if not bad else "err"])
                else:
                    self.progress["value"] = min(
                        95.0, box["done"] * 100.0 / box["total"])
                    self.root.after(60, poll)

            self.root.after(60, poll)

        def _save_report(self, reports, elapsed):
            if self.file_path:
                base_dir = os.path.dirname(os.path.abspath(self.file_path))
            else:
                base_dir = os.getcwd()
            out_path = os.path.join(base_dir, "splitcode_selftest.txt")
            return save_selftest_report(reports, elapsed, out_path)


# ---------------------------------------------------------------------------
# Точка входа
# ---------------------------------------------------------------------------
def main():
    args = sys.argv[1:]
    if args:
        first = args[0]
        if first in ("--selftest", "--test", "-t"):
            reports, elapsed = selftest()
            sys.exit(_cli_report(reports, elapsed))
        sys.exit(_cli_split(args))

    if not TK_OK:
        print("tkinter недоступен - графический интерфейс не запустить.")
        sys.exit(1)

    root = tk.Tk()
    CodeSplitterApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()