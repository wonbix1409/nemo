"""Немо — прячет персональные данные перед отправкой текста в нейросеть
и возвращает их обратно в ответ. Всё работает локально, без интернета.

Запуск: python app.py
"""
from __future__ import annotations

import os
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from nemo_core.anonymizer import AI_HINT, RE_TOKEN, Session
from nemo_core.detectors import NatashaNER
from nemo_core.files import read_text_file

APP_NAME = "Немо"
VERSION = "0.1.0"
KIND_NAMES = {
    "PER": "Человек", "ORG": "Организация", "LOC": "Место", "ADDR": "Адрес",
    "INN": "ИНН", "SNILS": "СНИЛС", "OGRN": "ОГРН", "KPP": "КПП", "BIK": "БИК",
    "ACCOUNT": "Счёт", "CARD": "Карта", "PHONE": "Телефон", "EMAIL": "Почта",
    "PASSPORT": "Паспорт", "CUSTOM": "Словарь / вручную",
}

# Палитра
BG = "#0f1720"
PANEL = "#16212d"
FG = "#e6edf3"
MUTED = "#8b9bab"
ACCENT = "#2bb3a3"      # бирюзовый — «вода, глубина»
TOKEN_BG = "#1f4a45"


def data_dir() -> Path:
    base = os.environ.get("APPDATA")
    d = Path(base) / "Nemo" if base else Path.home() / ".nemo"
    d.mkdir(parents=True, exist_ok=True)
    return d


class NemoApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.dir = data_dir()
        self.session_path = self.dir / "session.json"
        self.dict_path = self.dir / "dictionary.txt"
        if not self.dict_path.exists():
            self.dict_path.write_text(
                "# Словарь Немо: по одной фразе в строке — она будет скрываться всегда.\n"
                "# Например, названия ваших клиентов, проектов, внутренние коды.\n",
                encoding="utf-8",
            )
        self.session = Session.load(self.session_path)
        self.ner = NatashaNER()
        self.hint_var = tk.BooleanVar(value=True)
        self.status_var = tk.StringVar(value="Загружаю модель распознавания имён…")

        self._build_style()
        self._build_ui()
        self._refresh_table()
        threading.Thread(target=self._load_ner, daemon=True).start()

    # ------------------------------------------------------------------ вид
    def _build_style(self):
        r = self.root
        r.title(f"{APP_NAME} — ваши данные остаются у вас")
        r.geometry("1180x760")
        r.minsize(900, 560)
        r.configure(bg=BG)
        st = ttk.Style(r)
        st.theme_use("clam")
        base = ("Segoe UI", 10)
        st.configure(".", background=BG, foreground=FG, font=base, fieldbackground=PANEL)
        st.configure("TFrame", background=BG)
        st.configure("Panel.TFrame", background=PANEL)
        st.configure("TLabel", background=BG, foreground=FG)
        st.configure("Muted.TLabel", foreground=MUTED)
        st.configure("Title.TLabel", font=("Segoe UI Semibold", 20), foreground=ACCENT)
        st.configure("Cap.TLabel", font=("Segoe UI Semibold", 10), foreground=MUTED)
        st.configure("TButton", background=PANEL, foreground=FG, borderwidth=0, padding=(12, 6))
        st.map("TButton", background=[("active", "#22313f")])
        st.configure("Accent.TButton", background=ACCENT, foreground="#05201d",
                     font=("Segoe UI Semibold", 10), padding=(14, 7))
        st.map("Accent.TButton", background=[("active", "#3cc9b8")])
        st.configure("TCheckbutton", background=BG, foreground=FG)
        st.map("TCheckbutton", background=[("active", BG)])
        st.configure("TNotebook", background=BG, borderwidth=0)
        st.configure("TNotebook.Tab", background=PANEL, foreground=MUTED, padding=(16, 7))
        st.map("TNotebook.Tab", background=[("selected", BG)], foreground=[("selected", ACCENT)])
        st.configure("Treeview", background=PANEL, fieldbackground=PANEL, foreground=FG,
                     rowheight=24, borderwidth=0)
        st.configure("Treeview.Heading", background=BG, foreground=MUTED,
                     font=("Segoe UI Semibold", 9))

    def _text(self, parent) -> ScrolledText:
        t = ScrolledText(parent, wrap="word", undo=True, font=("Segoe UI", 10),
                         bg=PANEL, fg=FG, insertbackground=FG, relief="flat",
                         padx=10, pady=8, selectbackground="#2d4f6c", borderwidth=0)
        t.tag_configure("token", background=TOKEN_BG, foreground="#9ff3e6")
        t.tag_configure("restored", background="#3a3320", foreground="#ffe7a3")
        return t

    def _build_ui(self):
        top = ttk.Frame(self.root, padding=(16, 12, 16, 4))
        top.pack(fill="x")
        ttk.Label(top, text="◖ Немо", style="Title.TLabel").pack(side="left")
        ttk.Label(top, text="  прячет ФИО, реквизиты и контакты перед отправкой в нейросеть",
                  style="Muted.TLabel").pack(side="left", pady=(8, 0))

        bar = ttk.Frame(self.root, padding=(16, 4))
        bar.pack(fill="x")
        ttk.Button(bar, text="Открыть файл…", command=self.open_file).pack(side="left")
        ttk.Button(bar, text="Словарь…", command=self.edit_dictionary).pack(side="left", padx=6)
        ttk.Button(bar, text="Новый сеанс", command=self.new_session).pack(side="left")
        ttk.Checkbutton(bar, text="Добавлять подсказку для нейросети",
                        variable=self.hint_var).pack(side="left", padx=16)

        nb = ttk.Notebook(self.root)
        nb.pack(fill="both", expand=True, padx=16, pady=8)
        self.nb = nb

        # --- вкладка 1: скрыть
        t1 = ttk.Frame(nb, padding=8)
        nb.add(t1, text="① Скрыть")
        panes = ttk.PanedWindow(t1, orient="horizontal")
        panes.pack(fill="both", expand=True)
        left, right = ttk.Frame(panes), ttk.Frame(panes)
        panes.add(left, weight=1)
        panes.add(right, weight=1)
        ttk.Label(left, text="ИСХОДНЫЙ ТЕКСТ — вставьте документ или письмо",
                  style="Cap.TLabel").pack(anchor="w", pady=(0, 4))
        self.src = self._text(left)
        self.src.pack(fill="both", expand=True, padx=(0, 6))
        ttk.Label(right, text="ТЕКСТ ДЛЯ НЕЙРОСЕТИ — данные заменены метками",
                  style="Cap.TLabel").pack(anchor="w", pady=(0, 4))
        self.masked = self._text(right)
        self.masked.pack(fill="both", expand=True, padx=(6, 0))

        b1 = ttk.Frame(t1)
        b1.pack(fill="x", pady=(8, 0))
        ttk.Button(b1, text="Вставить из буфера",
                   command=lambda: self._paste(self.src)).pack(side="left")
        ttk.Button(b1, text="Скрыть выделенное", command=self.hide_selection).pack(side="left", padx=6)
        ttk.Button(b1, text="Скопировать для нейросети", style="Accent.TButton",
                   command=self.copy_masked).pack(side="right")
        ttk.Button(b1, text="Скрыть данные  →  (Ctrl+Enter)", style="Accent.TButton",
                   command=self.anonymize).pack(side="right", padx=6)

        # --- вкладка 2: вернуть
        t2 = ttk.Frame(nb, padding=8)
        nb.add(t2, text="② Вернуть")
        panes2 = ttk.PanedWindow(t2, orient="horizontal")
        panes2.pack(fill="both", expand=True)
        l2, r2 = ttk.Frame(panes2), ttk.Frame(panes2)
        panes2.add(l2, weight=1)
        panes2.add(r2, weight=1)
        ttk.Label(l2, text="ОТВЕТ НЕЙРОСЕТИ — вставьте сюда",
                  style="Cap.TLabel").pack(anchor="w", pady=(0, 4))
        self.answer = self._text(l2)
        self.answer.pack(fill="both", expand=True, padx=(0, 6))
        ttk.Label(r2, text="РЕЗУЛЬТАТ — с настоящими данными",
                  style="Cap.TLabel").pack(anchor="w", pady=(0, 4))
        self.result = self._text(r2)
        self.result.pack(fill="both", expand=True, padx=(6, 0))

        b2 = ttk.Frame(t2)
        b2.pack(fill="x", pady=(8, 0))
        ttk.Button(b2, text="Вставить из буфера",
                   command=lambda: (self._paste(self.answer), self.restore())).pack(side="left")
        ttk.Button(b2, text="Скопировать результат", style="Accent.TButton",
                   command=self.copy_result).pack(side="right")
        ttk.Button(b2, text="Вернуть данные  →", style="Accent.TButton",
                   command=self.restore).pack(side="right", padx=6)

        # --- вкладка 3: таблица меток
        t3 = ttk.Frame(nb, padding=8)
        nb.add(t3, text="Метки сеанса")
        cols = ("token", "kind", "value", "variants")
        tv = ttk.Treeview(t3, columns=cols, show="headings")
        for c, title, w in (("token", "Метка", 160), ("kind", "Тип", 140),
                            ("value", "Подставится обратно", 320), ("variants", "Как встречалось", 420)):
            tv.heading(c, text=title)
            tv.column(c, width=w, anchor="w")
        tv.pack(fill="both", expand=True)
        self.table = tv
        ttk.Label(t3, text="Таблица хранится только на этом компьютере: "
                           f"{self.session_path}", style="Muted.TLabel").pack(anchor="w", pady=(6, 0))

        status = ttk.Frame(self.root, padding=(16, 2, 16, 8))
        status.pack(fill="x")
        ttk.Label(status, textvariable=self.status_var, style="Muted.TLabel").pack(side="left")
        ttk.Label(status, text=f"v{VERSION} · локально, без интернета",
                  style="Muted.TLabel").pack(side="right")

        self.root.bind("<Control-Return>", lambda e: self.anonymize())

    # ------------------------------------------------------------------ логика
    def _load_ner(self):
        ok = self.ner.load()
        msg = ("Готово. Имена, организации и адреса распознаются." if ok else
               "Модель имён не загрузилась — работают только шаблоны (ИНН, телефоны, счета…).")
        self.root.after(0, self.status_var.set, msg)

    def _custom_words(self) -> list[str]:
        try:
            lines = self.dict_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        return [l.strip() for l in lines if l.strip() and not l.lstrip().startswith("#")]

    def _set(self, widget: ScrolledText, text: str):
        widget.delete("1.0", "end")
        widget.insert("1.0", text)

    def _highlight(self, widget: ScrolledText, tag: str, spans: list[tuple[int, int]]):
        widget.tag_remove(tag, "1.0", "end")
        for a, b in spans:
            widget.tag_add(tag, f"1.0+{a}c", f"1.0+{b}c")

    def _paste(self, widget: ScrolledText):
        try:
            self._set(widget, self.root.clipboard_get())
        except tk.TclError:
            pass

    def _copy(self, text: str, what: str):
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.status_var.set(f"Скопировано: {what}.")

    def anonymize(self):
        text = self.src.get("1.0", "end-1c")
        if not text.strip():
            self.status_var.set("Вставьте текст слева.")
            return
        ner = self.ner if self.ner.ready else None
        masked, ents = self.session.anonymize(text, ner=ner, custom_words=self._custom_words())
        self._set(self.masked, masked)
        self._highlight(self.masked, "token",
                        [(m.start(), m.end()) for m in RE_TOKEN.finditer(masked)])
        self.session.save(self.session_path)
        self._refresh_table()
        note = "" if ner else " (модель имён ещё не готова — скрыты только шаблоны)"
        self.status_var.set(f"Скрыто фрагментов: {len(ents)}.{note} Проверьте текст справа перед отправкой.")
        return masked

    def hide_selection(self):
        try:
            sel = self.src.get("sel.first", "sel.last").strip()
        except tk.TclError:
            self.status_var.set("Выделите слово или фразу в исходном тексте.")
            return
        if len(sel) < 2:
            return
        if sel not in self.session.manual:
            self.session.manual.append(sel)
        self.anonymize()

    def copy_masked(self):
        text = self.masked.get("1.0", "end-1c")
        if not text.strip():
            text = self.anonymize() or ""
        if self.hint_var.get() and text:
            text = AI_HINT + text
        self._copy(text, "текст для нейросети")
        self.nb.select(1)

    def restore(self):
        text = self.answer.get("1.0", "end-1c")
        out, n, missing = self.session.restore(text)
        self._set(self.result, out)
        # подсветка подставленных значений
        spans = []
        for it in self.session.items.values():
            start = 0
            while (i := out.find(it.value, start)) != -1 and it.value:
                spans.append((i, i + len(it.value)))
                start = i + len(it.value)
        self._highlight(self.result, "restored", spans)
        msg = f"Возвращено значений: {n}."
        if missing:
            msg += f" Не нашлось в сеансе: {', '.join(sorted(set(missing))[:5])}."
        self.status_var.set(msg)

    def copy_result(self):
        self._copy(self.result.get("1.0", "end-1c"), "результат")

    def _refresh_table(self):
        self.table.delete(*self.table.get_children())
        for it in self.session.items.values():
            self.table.insert("", "end", values=(
                it.token, KIND_NAMES.get(it.kind, it.kind), it.value, " | ".join(it.variants)))

    def new_session(self):
        if self.session.items and not messagebox.askyesno(
                APP_NAME, "Начать новый сеанс? Старые метки забудутся, и вернуть по ним данные "
                          "в старых ответах нейросети будет нельзя."):
            return
        self.session = Session()
        self.session.save(self.session_path)
        for w in (self.src, self.masked, self.answer, self.result):
            self._set(w, "")
        self._refresh_table()
        self.status_var.set("Новый сеанс начат.")

    def open_file(self):
        path = filedialog.askopenfilename(
            title="Открыть документ",
            filetypes=[("Документы", "*.docx *.txt *.md *.csv"), ("Все файлы", "*.*")])
        if not path:
            return
        try:
            self._set(self.src, read_text_file(path))
        except Exception as e:
            messagebox.showerror(APP_NAME, f"Не удалось открыть файл:\n{e}")
            return
        self.nb.select(0)
        self.anonymize()

    def edit_dictionary(self):
        win = tk.Toplevel(self.root)
        win.title("Словарь Немо")
        win.geometry("560x460")
        win.configure(bg=BG)
        ttk.Label(win, text="Фразы, которые скрываются всегда (по одной в строке):",
                  padding=(12, 10, 12, 4)).pack(anchor="w")
        t = self._text(win)
        t.pack(fill="both", expand=True, padx=12)
        t.insert("1.0", self.dict_path.read_text(encoding="utf-8"))

        def save():
            self.dict_path.write_text(t.get("1.0", "end-1c"), encoding="utf-8")
            self.status_var.set("Словарь сохранён.")
            win.destroy()

        ttk.Button(win, text="Сохранить", style="Accent.TButton", command=save).pack(pady=10)


def _fix_frozen_paths():
    """В собранном .exe pymorphy2 не видит словари через entry points — подсказываем путь."""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        dicts = Path(base) / "pymorphy2_dicts_ru" / "data"
        if dicts.exists():
            os.environ.setdefault("PYMORPHY2_DICT_PATH", str(dicts))


def selftest() -> int:
    """python app.py --selftest — проверка без окна (удобно после сборки)."""
    lines = []

    def out(*a):
        lines.append(" ".join(str(x) for x in a))
        print(*a)

    ner = NatashaNER()
    ok = ner.load()
    out("Модель имён:", "OK" if ok else f"НЕ ЗАГРУЖЕНА {ner.error}")
    s = Session()
    text = ("ООО «Ромашка» (ИНН 7707083893) в лице директора Иванова Ивана Петровича, "
            "тел. +7 912 345-67-89, г. Пермь, ул. Ленина, д. 50.")
    masked, _ = s.anonymize(text, ner=ner if ok else None)
    out("Скрыто:  ", masked)
    out("Обратно: ", s.restore(masked)[0])
    log = data_dir() / "selftest.log"
    log.write_text("\n".join(lines), encoding="utf-8")
    print("Лог:", log)
    return 0 if ok else 1


def main():
    _fix_frozen_paths()
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    if sys.platform == "win32":
        try:  # чёткие шрифты на экранах с масштабированием
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    root = tk.Tk()
    NemoApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
