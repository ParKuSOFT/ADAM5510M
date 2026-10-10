# -*- coding: utf-8 -*-
"""Окна эмулятора: главное (ADAM-5510) и Plotter. Только стандартный tkinter."""
import os
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from .hardware import Hardware, STAND_CHANNELS, THERMISTORS
from .cinterp import (Program, Interpreter, CompileError, RunError, StopRun, read_source)

SPEEDS = [("×1 (реальное время)", 1.0), ("×5", 5.0), ("×20", 20.0), ("×100", 100.0),
          ("Максимум", 0.0)]
ON_BG, OFF_BG = "#8ee08e", "#f0f0f0"

# Кнопки основной формы, которые "физически" принадлежат стенду:
#   in  - нажимаются мышкой (кнопка/датчик); out - загораются, когда программа пишет 1.
STAND_BUTTONS = {"in": ("Stand_by",),
                 "out": ("Hot", "Wait", "Hot_Extreme", "Alarm_Saund", "Cool")}


class App(object):
    def __init__(self, root, hw, path=None):
        self.root, self.hw = root, hw
        self.path = None
        self.interp = None
        self.thread = None
        self.out_q = queue.Queue()
        self.plotter_win = None
        self.stand_win = None
        self.sel_ai = 0

        root.title("ADAM-5510M — эмулятор")
        self._build_menu()
        self._build_ui()
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.bind("<Control-o>", lambda e: self.open_file())
        root.bind("<F5>", lambda e: self.toggle_run())
        self._dio_shadow = [[None] * 16 for _ in range(2)]
        self._ao_shadow = [None] * 4
        self._ai_shadow = [None] * 8
        if path:
            self.load(path)
        self.poll()

    # ------------------------------------------------------------------ UI
    def _build_menu(self):
        m = tk.Menu(self.root)
        f = tk.Menu(m, tearoff=0)
        f.add_command(label="Открыть программу…  Ctrl+O", command=self.open_file)
        f.add_separator()
        f.add_command(label="Выход", command=self.on_close)
        m.add_cascade(label="Файл", menu=f)
        m.add_command(label="Авторы", command=lambda: messagebox.showinfo(
            "Авторы", "Учебный эмулятор ADAM-5510M\n(Python + tkinter, интерпретатор подмножества C)"))
        self.root.config(menu=m)

    def _build_ui(self):
        r = self.root
        top = tk.Frame(r)
        top.pack(fill="x", padx=8, pady=(8, 2))
        self.plotter_kind = ttk.Combobox(top, state="readonly", width=24,
                                         values=["Произвольная", "Двухкоординатный (ШД)"])
        self.plotter_kind.current(1)
        self.plotter_kind.pack(side="left")
        self.plotter_kind.bind("<<ComboboxSelected>>", self.on_kind)
        self.kind_label = tk.Label(top, text="")
        self.kind_label.pack(side="left", padx=8)
        self.on_kind()

        mid = tk.Frame(r)
        mid.pack(padx=8, pady=4)
        self.dio_btn = [[None] * 16 for _ in range(2)]
        self.dio_lbl = {}
        name_by_key = {k: v[0] for k, v in STAND_CHANNELS.items()}
        kind_by_key = {k: v[1] for k, v in STAND_CHANNELS.items()}
        led_names = set(STAND_BUTTONS["out"]) | {"Work"}
        for slot in range(2):
            lf = tk.LabelFrame(mid, text="ADAM-5050 (№%d)" % slot)
            lf.grid(row=0, column=slot, sticky="n", padx=4)
            for row in range(8):
                tk.Label(lf, text=str(row), fg="#888", font=("TkDefaultFont", 7)).grid(row=row, column=0)
                for col in range(2):
                    ch = row + 8 * col
                    nm = name_by_key.get((slot, ch), "")
                    if nm in led_names:                 # светодиод стенда (загорается от 1)
                        b = tk.Button(lf, text="", width=3, relief="raised",
                                      command=lambda s=slot, c=ch: self.hw.toggle_dio(s, c))
                    elif kind_by_key.get((slot, ch)) == "in":   # кнопка / датчик наличия
                        b = tk.Button(lf, text="0", width=3, bg=OFF_BG,
                                      command=lambda s=slot, c=ch: self.hw.set_input(
                                          s, c, 0 if self.hw.dio[s][c] else 1))
                    else:                               # обмотки, перо, направление и т.п.
                        b = tk.Button(lf, text="0", width=3, bg=OFF_BG,
                                      command=lambda s=slot, c=ch: self.hw.toggle_dio(s, c))
                    b.grid(row=row, column=1 + col, padx=2, pady=2)
                    self.dio_btn[slot][ch] = b
                    if nm:                              # подпись с именем канала справа
                        lbl = tk.Label(lf, text=nm, anchor="w", fg="#333",
                                       font=("TkDefaultFont", 7))
                        lbl.grid(row=row, column=3, sticky="w")
                        self.dio_lbl[(slot, ch)] = lbl
        lf = tk.LabelFrame(mid, text="ADAM-5024")
        lf.grid(row=0, column=2, sticky="n", padx=4)
        self.ao_lbl = []
        for ch in range(4):
            v = tk.Label(lf, text="0")
            v.pack(pady=(8, 0))
            tk.Button(lf, text="Канал %d" % ch, width=10,
                      command=lambda c=ch: self.hw.write_ao(c, 0)).pack(padx=6)
            self.ao_lbl.append(v)

        lf = tk.LabelFrame(mid, text="ADAM-5017")
        lf.grid(row=0, column=3, sticky="n", padx=4)
        self.ai_ent = []
        for ch in range(8):
            tk.Label(lf, text=str(ch)).grid(row=ch, column=0)
            e = tk.Entry(lf, width=7, justify="center", state="readonly",
                         readonlybackground="white", cursor="arrow")
            e.grid(row=ch, column=1, padx=2, pady=2)
            e.bind("<Button-1>", lambda ev, c=ch: self.select_ai(c))
            self.ai_ent.append(e)
        self.ai_scale = tk.Scale(lf, from_=10, to=0, resolution=0.1, orient="vertical",
                                 showvalue=False, length=190, command=self.on_scale)
        self.ai_scale.grid(row=0, column=2, rowspan=8, padx=4)
        tk.Label(lf, text="Значение").grid(row=0, column=3, columnspan=2, padx=4)
        self.ai_val = tk.Entry(lf, width=8)
        self.ai_val.grid(row=1, column=3, columnspan=2, padx=4)
        tk.Button(lf, text="Применить", command=self.apply_ai).grid(row=7, column=3, columnspan=2, padx=4)
        self.select_ai(0)

        lights = tk.Canvas(mid, width=90, height=300, highlightthickness=0)
        lights.grid(row=0, column=4, padx=6, sticky="n")
        self.lights = {}
        for i, (name, on, off) in enumerate([("POWER", "#ff2a2a", "#ffb8b8"), ("RUN", "#22dd22", "#b8ffb8"),
                                             ("COMM", "#ffee22", "#ffffc0"), ("BAT", "#ffa060", "#ffd8c0")]):
            y = 12 + i * 72
            lights.create_text(45, y, text=name, font=("TkDefaultFont", 10, "bold"))
            self.lights[name] = (lights, lights.create_oval(20, y + 12, 70, y + 62, fill=off, outline=""), on, off)

        tk.Button(r, text="Плоттер", width=12, command=self.open_plotter).pack(pady=2)

        tk.Label(r, text="Консоль", anchor="w").pack(fill="x", padx=8)
        cf = tk.Frame(r)
        cf.pack(fill="both", expand=True, padx=8)
        self.console = tk.Text(cf, height=10, width=95, state="disabled", wrap="word")
        sb = tk.Scrollbar(cf, command=self.console.yview)
        self.console.config(yscrollcommand=sb.set)
        self.console.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        inp = tk.Frame(r)
        inp.pack(fill="x", padx=8, pady=4)
        self.input_ent = tk.Entry(inp)
        self.input_ent.pack(side="left", fill="x", expand=True)
        self.input_ent.bind("<Return>", lambda e: self.send_input())
        tk.Button(inp, text="Ввод", width=10, command=self.send_input).pack(side="left", padx=(8, 0))

        bot = tk.Frame(r)
        bot.pack(fill="x", padx=8, pady=(2, 8))
        self.led_btn = tk.Button(bot, text="LED", width=12, fg="white", command=self.toggle_led)
        self.led_btn.pack(side="left")
        self.file_lbl = tk.Label(bot, text="программа не загружена", fg="#555")
        self.file_lbl.pack(side="left", padx=10)
        tk.Button(bot, text="Открыть…", command=self.open_file).pack(side="left")
        self.run_btn = tk.Button(bot, text="Пуск", width=12, bg="#22bb22", fg="white", command=self.toggle_run)
        self.run_btn.pack(side="right")
        self.speed = ttk.Combobox(bot, state="readonly", width=20, values=[s[0] for s in SPEEDS])
        self.speed.current(2)
        self.speed.pack(side="right", padx=8)
        self.speed.bind("<<ComboboxSelected>>", self.on_speed)
        tk.Label(bot, text="Скорость:").pack(side="right")
        self.toggle_led(initial=True)

    # ------------------------------------------------------------ handlers
    def on_kind(self, event=None):
        two = self.plotter_kind.current() == 1
        self.hw.plotter_attached = two
        self.kind_label.config(text="Плоттер: двухкоординатный на ШД" if two else "Плоттер не выбран")

    def select_ai(self, ch):
        self.sel_ai = ch
        for i, e in enumerate(self.ai_ent):
            e.config(readonlybackground="#cfe8ff" if i == ch else "white")
        v = self.hw.ai[ch]
        self.ai_scale.set(v)
        self.ai_val.delete(0, "end")
        self.ai_val.insert(0, "%g" % v)

    def on_scale(self, value):
        self.ai_val.delete(0, "end")
        self.ai_val.insert(0, "%g" % float(value))

    def apply_ai(self):
        try:
            v = float(self.ai_val.get().replace(",", "."))
        except ValueError:
            return
        v = max(0.0, min(10.0, v))
        self.hw.ai[self.sel_ai] = v
        self.ai_scale.set(v)

    def toggle_led(self, initial=False):
        if not initial:
            self.hw.led_on = not self.hw.led_on
        self.led_btn.config(bg="#e02020" if self.hw.led_on else "#707070",
                            activebackground="#e02020" if self.hw.led_on else "#707070")

    def log(self, text):
        self.out_q.put(text + "\n")

    def send_input(self):
        text = self.input_ent.get()
        self.input_ent.delete(0, "end")
        self.out_q.put(">> " + text + "\n")
        if self.interp is not None:
            self.interp.feed_input(text)

    def on_speed(self, event=None):
        if self.interp is not None:
            self.interp.speed = SPEEDS[self.speed.current()][1]

    def open_plotter(self):
        if self.plotter_win is not None:
            self.plotter_win.lift()
            return
        self.plotter_win = PlotterWindow(self.root, self.hw, self._plotter_closed)

    def _plotter_closed(self):
        self.plotter_win = None

    def open_file(self):
        p = filedialog.askopenfilename(
            title="Загрузить программу",
            filetypes=[("Программы на C", "*.c *.C"), ("Все файлы", "*.*")])
        if p:
            self.load(p)

    def load(self, path):
        self.path = path
        self.file_lbl.config(text=os.path.basename(path))
        self.log("Загружен файл: " + path)

    # ----------------------------------------------------------- запуск
    def toggle_run(self):
        if self.thread is not None and self.thread.is_alive():
            if self.interp is not None:
                self.interp.stop = True
            return
        if not self.path:
            self.open_file()
            if not self.path:
                return
        try:
            src = read_source(self.path)
        except OSError as e:
            self.log("Не удалось прочитать файл: %s" % e)
            return
        self.log("--- Компиляция: %s ---" % os.path.basename(self.path))
        try:
            prog = Program(src)
        except CompileError as e:
            for line, msg in e.errors:
                self.log(("Строка %d: %s" % (line, msg)) if line else msg)
            self.log("Компиляция не удалась.")
            return
        self.log("Компиляция успешна. Запуск.")
        self.interp = Interpreter(prog, self.hw, self.out_q.put, SPEEDS[self.speed.current()][1])
        self.thread = threading.Thread(target=self._worker, args=(self.interp,), daemon=True)
        self.hw.running = True
        self.run_btn.config(text="Стоп", bg="#cc2222")
        self.thread.start()

    def _worker(self, interp):
        try:
            interp.run()
            self.out_q.put("--- Программа завершена ---\n")
        except StopRun:
            self.out_q.put("--- Остановлено ---\n")
        except RunError as e:
            self.out_q.put("Runtime-ошибка (строка %s): %s\n" % (e.line, e.msg))
        except RecursionError:
            self.out_q.put("Runtime-ошибка: слишком глубокая вложенность\n")
        except Exception as e:                      # ошибка самого эмулятора
            self.out_q.put("Внутренняя ошибка эмулятора: %r\n" % (e,))
        finally:
            self.hw.running = False

    # ------------------------------------------------------------ опрос
    def poll(self):
        hw = self.hw
        for slot in range(2):
            row, sh = hw.dio[slot], self._dio_shadow[slot]
            for ch in range(16):
                v = row[ch]
                if v != sh[ch]:
                    sh[ch] = v
                    self.dio_btn[slot][ch].config(text=str(v), bg=ON_BG if v else OFF_BG)
        for ch in range(4):
            v = hw.ao[ch]
            if v != self._ao_shadow[ch]:
                self._ao_shadow[ch] = v
                self.ao_lbl[ch].config(text="%g" % v)
        for ch in range(8):
            v = hw.ai[ch]
            if v != self._ai_shadow[ch]:
                self._ai_shadow[ch] = v
                e = self.ai_ent[ch]
                e.config(state="normal")
                e.delete(0, "end")
                e.insert(0, "%g" % v)
                e.config(state="readonly")
        states = {"POWER": True, "RUN": hw.running, "COMM": time.time() - hw.comm_ts < 0.15, "BAT": False}
        for name, (cv, item, on, off) in self.lights.items():
            cv.itemconfig(item, fill=on if states[name] else off)

        chunks = []
        try:
            while True:
                chunks.append(self.out_q.get_nowait())
        except queue.Empty:
            pass
        if chunks:
            self.console.config(state="normal")
            self.console.insert("end", "".join(chunks))
            self.console.see("end")
            self.console.config(state="disabled")
        if not hw.running and self.run_btn.cget("text") == "Стоп":
            self.run_btn.config(text="Пуск", bg="#22bb22")
        if self.plotter_win is not None:
            self.plotter_win.poll()
        self.root.after(40, self.poll)

    def on_close(self):
        if self.interp is not None:
            self.interp.stop = True
        self.root.destroy()


class PlotterWindow(tk.Toplevel):
    MARGIN = 20

    def __init__(self, master, hw, on_close):
        tk.Toplevel.__init__(self, master)
        self.title("Plotter")
        self.geometry("900x560")
        self.hw, self.pl, self._on_close = hw, hw.plotter, on_close
        self.cv = tk.Canvas(self, bg="#ececec", highlightthickness=0)
        self.cv.pack(side="left", fill="both", expand=True)

        side = tk.Frame(self, width=190)
        side.pack(side="right", fill="y", padx=6, pady=6)
        tk.Button(side, text="Сброс", width=16, command=self.reset).pack(pady=(0, 4))
        tk.Button(side, text="Сохранить SVG…", width=16, command=self.save_svg).pack(pady=2)
        self.lbl_x = tk.Label(side, text="X: 0.0 мм", anchor="w")
        self.lbl_y = tk.Label(side, text="Y: 0.0 мм", anchor="w")
        self.lbl_pen = tk.Label(side, text="Перо: поднято", anchor="w")
        self.lbl_warn = tk.Label(side, text="", anchor="w", fg="#b00000", justify="left")
        for w in (self.lbl_x, self.lbl_y, self.lbl_pen, self.lbl_warn):
            w.pack(fill="x", pady=2)
        tk.Label(side, text="Поле, мм (ширина × высота):", anchor="w").pack(fill="x", pady=(14, 0))
        fr = tk.Frame(side)
        fr.pack(fill="x")
        self.e_w, self.e_h = tk.Entry(fr, width=6), tk.Entry(fr, width=6)
        self.e_w.insert(0, "%g" % self.pl.width)
        self.e_h.insert(0, "%g" % self.pl.height)
        self.e_w.pack(side="left")
        tk.Label(fr, text=" × ").pack(side="left")
        self.e_h.pack(side="left")
        tk.Button(fr, text="ОК", command=self.apply_field).pack(side="left", padx=4)

        self.runs = []          # [x0, y0, x1, y1] в шагах
        self.items = []
        self.drawn = 0
        self.ver = -1
        self.marker = None
        self.scale, self.ox, self.oy = 1.0, 0, 0
        self._cfg = None
        self.cv.bind("<Configure>", self.on_resize)
        self.protocol("WM_DELETE_WINDOW", self.close)

    def close(self):
        self._on_close()
        self.destroy()

    def reset(self):
        self.pl.clear(home=True)

    def apply_field(self):
        try:
            w, h = float(self.e_w.get().replace(",", ".")), float(self.e_h.get().replace(",", "."))
        except ValueError:
            return
        if w >= 10 and h >= 10:
            self.pl.set_field(w, h)
            self.redraw_all()

    def save_svg(self):
        from .svg import write_svg
        p = filedialog.asksaveasfilename(defaultextension=".svg", filetypes=[("SVG", "*.svg")])
        if p:
            write_svg(p, self.pl)

    # --- геометрия ---
    def calc_scale(self):
        cw, ch = max(self.cv.winfo_width(), 50), max(self.cv.winfo_height(), 50)
        m = self.MARGIN
        self.scale = min((cw - 2 * m) / self.pl.width, (ch - 2 * m) / self.pl.height)
        self.ox = m
        self.oy = ch - m

    def to_px(self, xs, ys):
        k = self.scale / self.pl.spm
        return self.ox + xs * k, self.oy - ys * k

    def on_resize(self, event):
        if self._cfg is not None:
            self.after_cancel(self._cfg)
        self._cfg = self.after(80, self.redraw_all)

    def redraw_all(self):
        self._cfg = None
        cv = self.cv
        cv.delete("all")
        self.calc_scale()
        w, h, s = self.pl.width, self.pl.height, self.scale
        x0, y0 = self.ox, self.oy
        cv.create_rectangle(x0, y0 - h * s, x0 + w * s, y0, fill="white", outline="#888")
        step = 50 if w <= 800 else 100
        for gx in range(step, int(w) + 1, step):
            cv.create_line(x0 + gx * s, y0, x0 + gx * s, y0 - h * s, fill="#ececec")
            if gx % (2 * step) == 0:
                cv.create_text(x0 + gx * s, y0 + 9, text=str(gx), fill="#777", font=("TkDefaultFont", 7))
        for gy in range(step, int(h) + 1, step):
            cv.create_line(x0, y0 - gy * s, x0 + w * s, y0 - gy * s, fill="#ececec")
            if gy % (2 * step) == 0:
                cv.create_text(x0 - 10, y0 - gy * s, text=str(gy), fill="#777", font=("TkDefaultFont", 7))
        self.items = []
        for r in self.runs:
            self.items.append(self._line(r))
        self.marker = cv.create_oval(0, 0, 0, 0, outline="#d00000", width=2)
        self.update_marker()

    def _line(self, r):
        a, b = self.to_px(r[0], r[1])
        c, d = self.to_px(r[2], r[3])
        return self.cv.create_line(a, b, c, d, fill="black")

    def update_marker(self):
        _, _, pos, pen, _ = self.pl.snapshot(10 ** 9)
        px, py = self.to_px(pos[0], pos[1])
        rad = 5
        self.cv.coords(self.marker, px - rad, py - rad, px + rad, py + rad)
        self.cv.itemconfig(self.marker, fill="#d00000" if pen else "")
        self.cv.tag_raise(self.marker)

    def add_seg(self, s):
        if self.runs:
            r = self.runs[-1]
            if (r[2], r[3]) == (s[0], s[1]) and (r[2] - r[0]) * (s[3] - s[1]) == (r[3] - r[1]) * (s[2] - s[0]) \
                    and (r[2] - r[0]) * (s[2] - s[0]) + (r[3] - r[1]) * (s[3] - s[1]) > 0:
                r[2], r[3] = s[2], s[3]
                a, b = self.to_px(r[0], r[1])
                c, d = self.to_px(r[2], r[3])
                self.cv.coords(self.items[-1], a, b, c, d)
                return
        r = list(s)
        self.runs.append(r)
        self.items.append(self._line(r))

    def poll(self):
        ver, new, pos, pen, limit = self.pl.snapshot(self.drawn)
        if ver != self.ver:
            self.ver = ver
            self.drawn = 0
            self.runs = []
            self.redraw_all()
            ver, new, pos, pen, limit = self.pl.snapshot(0)
        if self.marker is None:
            return
        for s in new:
            self.add_seg(s)
        self.drawn += len(new)
        if self.items:
            self.cv.tag_raise(self.marker)
        k = 1.0 / self.pl.spm
        self.lbl_x.config(text="X: %.2f мм" % (pos[0] * k))
        self.lbl_y.config(text="Y: %.2f мм" % (pos[1] * k))
        self.lbl_pen.config(text="Перо: опущено" if pen else "Перо: поднято")
        warn = []
        if limit:
            warn.append("Каретка упёрлась в край поля!")
        if self.pl.skipped:
            warn.append("Перескоков через фазу: %d" % self.pl.skipped)
        self.lbl_warn.config(text="\n".join(warn))
        self.update_marker()


def run_gui(path=None, field=(600, 400)):
    hw = Hardware()
    hw.plotter.set_field(*field)
    root = tk.Tk()
    App(root, hw, path)
    root.mainloop()
