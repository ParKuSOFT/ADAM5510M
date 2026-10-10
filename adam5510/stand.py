# -*- coding: utf-8 -*-
"""Окно учебного стенда.

Периферия (см. STAND_CHANNELS в hardware.py):
  * кнопки без фиксации  - Stand_by;
  * датчики наличия      - Place_1_1..Place_2_3 (выдают 1, если перед ними что-то есть);
  * светодиоды           - Hot, Hot_Extreme, Wait, Alarm_Saund, Cool(вентилятор);
  * счётчики             - Couster_1 (слот 0), Couster_2 (слот 1);
  * терморезисторы       - Thermistor_1 / Thermistor_2 (входы ADAM-5017 0 и 1,
                           нагреваются выходами ADAM-5024 0 и 1);
  * семисегментный индикатор - сегменты a..g на каналах 11..14 слота 0 и 13..15 слота 1.

Все элементы можно трогать и из этого окна, и из основной формы (там же список
каналов) - состояние хранится в Hardware, окна только его отображают.
"""
import tkinter as tk
from tkinter import ttk

from .hardware import STAND_CHANNELS, THERMISTORS, SEG_ORDER, segment_value

LED_ON = {
    "Hot": "#ff5030", "Hot_Extreme": "#ff9020", "Wait": "#ffe020",
    "Alarm_Saund": "#ff2020", "Cool": "#40c0ff", "Work": "#60e060",
}
LED_OFF = "#d8d8d8"


class StandWindow(tk.Toplevel):
    def __init__(self, master, hw, on_close=None):
        tk.Toplevel.__init__(self, master)
        self.hw = hw
        self._on_close_cb = on_close
        self.title("Учебный стенд")
        self.geometry("980x620")
        self.minsize(760, 480)

        self.leds = {}            # имя -> (canvas, item, on_color)
        self.inputs = {}          # (slot,ch) -> виджет-переключатель
        self.counter_lbl = {}
        self.seg_items = {}
        self.seg_canvas = None
        self.shadow_dio = [[None] * 16 for _ in range(2)]
        self.shadow_ai = [None] * 8
        self._dirty = True

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=6, pady=6)

        main_fr = tk.Frame(nb)
        nb.add(main_fr, text="Стенд")
        map_fr = tk.Frame(nb)
        nb.add(map_fr, text="Схема подключений")

        self._build_main(main_fr)
        self._build_map(map_fr)

        hw.add_observer(self._mark_dirty)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.after(80, self.refresh)

    # ------------------------------------------------------------------ UI
    def _build_main(self, parent):
        left = tk.Frame(parent)
        left.pack(side="left", fill="y", padx=(4, 8), pady=4)
        right = tk.Frame(parent)
        right.pack(side="left", fill="both", expand=True, padx=8, pady=4)

        # ---- семисегментный индикатор ----
        lf = tk.LabelFrame(left, text="Индикатор (каналы 11-14 / 13-15)")
        lf.pack(fill="x", pady=4)
        cv = tk.Canvas(lf, width=140, height=180, bg="#202020", highlightthickness=0)
        cv.pack(padx=8, pady=8)
        self.seg_canvas = cv
        self.seg_items = {}
        w, h, x, y, t = 90, 140, 25, 18, 9
        pts = {
            "a": (x + t, y, x + w - t, y),
            "b": (x + w, y + t, x + w, y + h / 2 - t),
            "c": (x + w, y + h / 2 + t, x + w, y + h - t),
            "d": (x + t, y + h, x + w - t, y + h),
            "e": (x, y + h / 2 + t, x, y + h - t),
            "f": (x, y + t, x, y + h / 2 - t),
            "g": (x + t, y + h / 2, x + w - t, y + h / 2),
        }
        for name, (x0, y0, x1, y1) in pts.items():
            self.seg_items[name] = cv.create_line(x0, y0, x1, y1, fill="#3a3a3a", width=8,
                                                  capstyle="round")
        row = tk.Frame(lf)
        row.pack(pady=(0, 6))
        for d in range(10):
            tk.Button(row, text=str(d), width=2,
                      command=lambda v=d: self.hw.set_seg_digit(v)).grid(row=0, column=d % 5, padx=1)
        tk.Button(lf, text="Погасить", command=lambda: self.hw.set_seg_digit(" ")).pack(pady=2)

        # ---- терморезисторы ----
        lf = tk.LabelFrame(left, text="Терморезисторы (ADAM-5017)")
        lf.pack(fill="x", pady=6)
        self.therm_rows = []
        for i, (ch, name) in enumerate(THERMISTORS):
            fr = tk.Frame(lf)
            fr.pack(fill="x", padx=6, pady=3)
            tk.Label(fr, text="%s (AI%d)" % (name, ch), width=18, anchor="w").pack(side="left")
            sc = tk.Scale(fr, from_=0, to=100, orient="horizontal", showvalue=False, length=110)
            sc.set(50)
            sc.pack(side="left")
            val = tk.Label(fr, text="", width=14, anchor="w")
            val.pack(side="left", padx=4)
            sc.configure(command=lambda v, idx=i: self._on_therm(idx, v))
            self.therm_rows.append((sc, val))

        # ---- входные устройства ----
        lf = tk.LabelFrame(right, text="Входы: кнопки и датчики наличия "
                                       "(клик = изменить состояние)")
        lf.pack(fill="x", pady=4)
        grid = tk.Frame(lf)
        grid.pack(fill="x", padx=6, pady=6)
        r = c = 0
        for (slot, ch), (name, kind, desc) in sorted(STAND_CHANNELS.items()):
            if kind != "in":
                continue
            fr = tk.Frame(grid)
            fr.grid(row=r, column=c, sticky="w", padx=8, pady=3)
            tk.Label(fr, text=name, width=12, anchor="w").pack(side="left")
            var = tk.IntVar(value=self.hw.dio[slot][ch])
            cb = tk.Checkbutton(fr, variable=var, text="1",
                                command=lambda s=slot, cc=ch, v=var: self.hw.set_input(s, cc, v.get()))
            cb.pack(side="left")
            self.inputs[(slot, ch)] = (cb, var)
            c += 1
            if c == 3:
                c, r = 0, r + 1

        # ---- выходные устройства ----
        lf = tk.LabelFrame(right, text="Выходы: светодиоды и вентилятор")
        lf.pack(fill="x", pady=4)
        g2 = tk.Frame(lf)
        g2.pack(fill="x", padx=6, pady=6)
        outs = [(slot, ch, nm) for (slot, ch), (nm, kind, _d) in sorted(STAND_CHANNELS.items())
                if kind == "out" and ch >= 4]
        for i, (slot, ch, name) in enumerate(outs):
            fr = tk.Frame(g2)
            fr.grid(row=i // 3, column=i % 3, sticky="w", padx=8, pady=3)
            cv = tk.Canvas(fr, width=22, height=22, highlightthickness=0)
            cv.pack(side="left")
            item = cv.create_oval(3, 3, 19, 19, fill=LED_OFF, outline="#888")
            self.leds[name] = (cv, item, LED_ON.get(name, "#60e060"))
            tk.Label(fr, text="%s (%d:%d)" % (name, slot, ch), anchor="w").pack(side="left", padx=4)
            tk.Button(fr, text="ВКЛ", width=5,
                      command=lambda s=slot, cc=ch: self.hw.write_dio(s, cc, 1)).pack(side="left")
            tk.Button(fr, text="ОТКЛ", width=5,
                      command=lambda s=slot, cc=ch: self.hw.write_dio(s, cc, 0)).pack(side="left")

        # ---- счётчики ----
        lf = tk.LabelFrame(right, text="Счётчики импульсов (Couster_N)")
        lf.pack(fill="x", pady=4)
        g3 = tk.Frame(lf)
        g3.pack(fill="x", padx=6, pady=6)
        for slot, name in ((0, "Couster_1"), (1, "Couster_2")):
            fr = tk.Frame(g3)
            fr.pack(side="left", padx=12)
            tk.Label(fr, text=name, anchor="w").pack(anchor="w")
            lbl = tk.Label(fr, text="0", font=("TkDefaultFont", 16, "bold"), width=6,
                           relief="sunken", bg="white")
            lbl.pack(side="left")
            self.counter_lbl[slot] = lbl
            tk.Button(fr, text="+1", width=4,
                      command=lambda s=slot: self.hw.pulse_counter(s)).pack(side="left", padx=2)
            tk.Button(fr, text="Сброс", width=6,
                      command=lambda s=slot: self.hw.reset_counter(s)).pack(side="left")
        tk.Label(right, justify="left", fg="#555", text=(
            "Датчик выдаёт 1, если перед ним что-то стоит.\n"
            "Светодиоды горят, когда программа записала 1 в соответствующий канал.\n"
            "Терморезистор: ползунок задаёт температуру; выход ADAM-5024 №0/№1 нагревает его дополнительно.")).pack(
            anchor="w", padx=8, pady=4)

    def _build_map(self, parent):
        cols = ("Слот", "Канал", "Имя", "Тип", "Назначение")
        tv = ttk.Treeview(parent, columns=cols, show="headings", height=34)
        widths = (60, 60, 130, 80, 420)
        for col, wd in zip(cols, widths):
            tv.heading(col, text=col)
            tv.column(col, width=wd, anchor="w")
        rows = []
        for (slot, ch), (nm, kind, desc) in sorted(STAND_CHANNELS.items()):
            rows.append((slot, ch, nm, kind, desc))
        for ai, nm in THERMISTORS:
            rows.append(("ADAM-5017", ai, nm, "in",
                         "Терморезистор NTC: 10 В = холодный, 0 В = горячий"))
            rows.append(("ADAM-5024", ai, nm + "_heater", "out",
                         "Нагрев терморезистора %s (0..10 В)" % nm))
        rows.sort(key=lambda r: (str(r[0]), r[1]))
        for r in rows:
            tv.insert("", "end", values=r)
        sb = tk.Scrollbar(parent, command=tv.yview)
        tv.configure(yscrollcommand=sb.set)
        tv.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=6)
        sb.pack(side="right", fill="y", pady=6)

    # -------------------------------------------------------------- события
    def _on_therm(self, index, value):
        self.hw.set_thermistor(index, float(value))

    def _mark_dirty(self):
        self._dirty = True

    def refresh(self):
        """Обновление всех виджетов по состоянию Hardware (по вызовам poll)."""
        hw = self.hw
        with hw.lock:
            dio = [list(hw.dio[s]) for s in range(2)]
            ai = list(hw.ai)
        for (slot, ch), (cb, var) in self.inputs.items():
            v = dio[slot][ch]
            if var.get() != v:
                var.set(v)
        mask = 0
        for bit, (s, c) in enumerate([(0, 11), (0, 12), (0, 13), (0, 14),
                                      (1, 13), (1, 14), (1, 15)]):
            if dio[s][c]:
                mask |= 1 << bit
        for i, name in enumerate(SEG_ORDER):
            on = bool(mask & (1 << i))
            self.seg_canvas.itemconfig(self.seg_items[name],
                                       fill="#ff3b30" if on else "#3a3a3a")
        for slot, lbl in self.counter_lbl.items():
            lbl.config(text=str(hw.counter_value(slot)))
        for i, (sc, val) in enumerate(self.therm_rows):
            t = hw.thermistors[i]
            if abs(sc.get() - t.level) > 0.5:
                sc.set(t.level)
            val.config(text="%.1f B (%d%%)" % (t.volts, int(t.temp_pct)))
        # светодиоды: Work / Direct_M_* / обмотки показываем как "выход программы"
        out_names = {"Hot": (0, 7), "Wait": (0, 15), "Hot_Extreme": (1, 7),
                     "Alarm_Saund": (1, 8), "Cool": (1, 12), "Work": (0, 4)}
        for name, (s, c) in out_names.items():
            if name in self.leds:
                cv, item, oncol = self.leds[name]
                cv.itemconfig(item, fill=oncol if dio[s][c] else LED_OFF)
        self._dirty = False
        self.after(150, self._poll)

    def _poll(self):
        if not self.winfo_exists():
            return
        if self._dirty:
            self.refresh()
        self.after(150, self._poll)

    def close(self):
        self.hw.remove_observer(self._mark_dirty)
        if self._on_close_cb:
            self._on_close_cb()
        self.destroy()
