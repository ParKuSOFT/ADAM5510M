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
import math
import tkinter as tk
from tkinter import ttk

from .hardware import (STAND_CHANNELS, THERMISTORS, SEG_ORDER, HOIST_TRAVEL_MM,
                       STEP_MM)

LED_ON = {
    "Hot": "#ff5030", "Hot_Extreme": "#ff9020", "Wait": "#ffe020",
    "Alarm_Saund": "#ff2020", "Cool": "#40c0ff", "Work": "#60e060",
}
LED_OFF = "#d8d8d8"

# --------------------------------------------------------------------------- #
#  Визуализация "лифтов": мотор сверху, груз на нитке снизу, три датчика.
# --------------------------------------------------------------------------- #
PHASE_SEQ = [(1, 0, 0, 1), (1, 1, 0, 0), (0, 1, 1, 0), (0, 0, 1, 1)]


class HoistView(object):
    """Один "лифт" на canvas: барабан-мотор, нитка, груз, датчики Place_N_1..3."""

    W = 270                     # ширина области лифта
    MOTOR_CY = 46               # центр барабана мотора
    TOP_Y = 78                  # край рамки, откуда свисает нитка
    LINE_X = 150                # вертикальная линия нитки
    TRAVEL_PX = 300             # ход груза в пикселах
    LOAD_W, LOAD_H = 46, 30     # размер груза
    SENSOR_ZONE_PX = 12         # зона срабатывания датчика (≈7 мм модели)

    def __init__(self, cv, hw, index):
        self.cv, self.hw, self.index = cv, hw, index
        h = hw.hoists[index]
        self.title = "Лифт M%d — ШД %s" % (index + 1, "X" if index == 0 else "Y")
        x = self.LINE_X
        top = self.TOP_Y
        bot = top + self.TRAVEL_PX

        cv.create_text(135, 12, text=self.title, anchor="w", font=("TkDefaultFont", 10, "bold"))
        cv.create_text(135, 28, anchor="w", fill="#666",
                       text="шаг = %.2f мм (4 шага = 1 мм)" % STEP_MM)

        # ---- мотор (барабан) сверху ----
        cx, cy, r = x, self.MOTOR_CY, 22
        self.motor_body = cv.create_oval(cx - r, cy - r, cx + r, cy + r,
                                         fill="#e8e8e8", outline="#555", width=2)
        self.spokes = [cv.create_line(cx, cy, cx, cy - r + 4, fill="#777", width=2)
                       for _ in range(4)]
        cv.create_oval(cx - 3, cy - 3, cx + 3, cy + 3, fill="#555", outline="")
        # индикатор работы мотора (горит/мигает, когда программа крутит обмотки)
        self.motor_led = cv.create_oval(x + 40, cy - 8, x + 56, cy + 8,
                                        fill=LED_OFF, outline="#888")
        cv.create_text(x + 48, cy + 22, text="M", fill="#666")
        # направление вращения (стрелка вокруг барабана)
        self.arrow = cv.create_arc(cx - r - 8, cy - r - 8, cx + r + 8, cy + r + 8,
                                   start=40, extent=90, style="arc", outline="#2b7de9",
                                   width=2)

        # ---- рамка и нитка ----
        cv.create_rectangle(x - 60, top, x + 60, bot, fill="#fbfbfb", outline="#999")
        self.thread = cv.create_line(x, self.MOTOR_CY, x, top + 6, fill="#444", width=2)
        self.winding = cv.create_line(x - 14, self.MOTOR_CY + r - 2, x + 14,
                                      self.MOTOR_CY + r - 2, fill="#888", width=3)

        # ---- груз ----
        self.load = cv.create_rectangle(x - self.LOAD_W / 2.0, bot - self.LOAD_H,
                                        x + self.LOAD_W / 2.0, bot,
                                        fill="#7f8fa6", outline="#333")
        self.load_txt = cv.create_text(x, bot - self.LOAD_H / 2.0, text="груз",
                                       fill="white")

        # ---- датчики: верхний Place_N_1, средний _N_2, нижний _N_3 ----
        self.sensors = []
        names = ["Place_%d_1" % (index + 1), "Place_%d_2" % (index + 1),
                 "Place_%d_3" % (index + 1)]
        for i, ((slot, ch), nm) in enumerate(zip(h.sensors, names)):
            sy = top + i * self.TRAVEL_PX / 2.0          # 0 - верх, 1 - середина, 2 - низ
            sx = x + 60                                   # справа от нитки
            body = cv.create_rectangle(sx, sy - 9, sx + 26, sy + 9,
                                       fill="#dfe6ee", outline="#555")
            led = cv.create_oval(sx + 30, sy - 6, sx + 42, sy + 6,
                                 fill=LED_OFF, outline="#888")
            txt = cv.create_text(sx + 62, sy, text=nm, anchor="w", fill="#333")
            self.sensors.append((slot, ch, body, led))

        # ---- ползунок ручного перемещения груза (вниз = меньше мм) ----
        self.slider = tk.Scale(cv, from_=int(HOIST_TRAVEL_MM), to=0, showvalue=True,
                               length=self.TRAVEL_PX - 20, orient="vertical",
                               label="мм", font=("TkDefaultFont", 8))
        self.slider.set(0)
        self.slider.configure(command=lambda v, idx=index: self._on_slider(idx, v))
        self._updating_slider = False
        cv.create_window(x - 88, (top + bot) / 2.0, window=self.slider)
        self.pos_lbl = cv.create_text(x, bot + 16, text="", fill="#333")

    def _on_slider(self, index, value):
        if self._updating_slider:
            return
        self.hw.set_hoist_position(index, float(value))

    def refresh(self, dio, steps_cache):
        h = self.hw.hoists[self.index]
        x = self.LINE_X
        top = self.TOP_Y
        bot = top + self.TRAVEL_PX
        frac = max(0.0, min(1.0, h.position / h.travel))
        y = bot - frac * self.TRAVEL_PX                  # y груза (0 мм = внизу)

        # нитка: от барабана до верха груза
        self.cv.coords(self.thread, x, self.MOTOR_CY, x, y - self.LOAD_H / 2.0)
        # намотка на барабан: толщина слоя растёт, когда груз поднят
        w = 6 + frac * 12
        self.cv.coords(self.winding, x - w, self.MOTOR_CY + 20, x + w, self.MOTOR_CY + 20)
        # груз
        self.cv.coords(self.load, x - self.LOAD_W / 2.0, y - self.LOAD_H / 2.0,
                       x + self.LOAD_W / 2.0, y + self.LOAD_H / 2.0)
        self.cv.coords(self.load_txt, x, y)

        # мотор: крутится ли? (шаги с прошлого опроса)
        moved = abs(h.steps - steps_cache.get(self.index, h.steps))
        steps_cache[self.index] = h.steps
        if moved:
            self._angle = (getattr(self, "_angle", 0.0) + moved * 30.0) % 360.0
            self._blink = not getattr(self, "_blink", False)
        col = ("#60e060" if getattr(self, "_blink", False) else "#1e9e3a") \
            if moved else LED_OFF
        self.cv.itemconfig(self.motor_led, fill=col)
        # спицы барабана
        cx, cy, r = x, self.MOTOR_CY, 22
        a0 = getattr(self, "_angle", 0.0)
        for k, sp in enumerate(self.spokes):
            a = math.radians(a0 + k * 90.0)
            self.cv.coords(sp, cx, cy, cx + (r - 4) * math.sin(a),
                           cy - (r - 4) * math.cos(a))
        # стрелка направления: Direct_M_* = 1 -> подъём (по часовой)
        d = dio[h.slot][h.dir_ch]
        self.cv.itemconfig(self.arrow,
                           start=40 if d else 130, extent=90 if d else -90,
                           outline="#2b7de9" if moved else "#c0c0c0")

        # датчики
        for (slot, ch, body, led) in self.sensors:
            on = bool(dio[slot][ch])
            self.cv.itemconfig(led, fill="#ff3b30" if on else LED_OFF,
                               outline="#888")
            self.cv.itemconfig(body, fill="#ffe2d6" if on else "#dfe6ee")

        self.cv.itemconfig(self.pos_lbl,
                           text="высота %.1f мм · шагов: %d" % (h.position, h.steps))
        if abs(self.slider.get() - h.position) > STEP_MM:
            self._updating_slider = True
            self.slider.set(int(round(h.position)))
            self._updating_slider = False


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
        self._steps_cache = {}          # номер лифта -> h.steps на прошлом опросе
        self._dirty = True

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=6, pady=6)

        hoist_fr = tk.Frame(nb)
        nb.add(hoist_fr, text="Лифты (моторы и грузы)")
        main_fr = tk.Frame(nb)
        nb.add(main_fr, text="Стенд")
        map_fr = tk.Frame(nb)
        nb.add(map_fr, text="Схема подключений")

        self._build_hoists(hoist_fr)
        self._build_main(main_fr)
        self._build_map(map_fr)

        hw.add_observer(self._mark_dirty)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.after(80, self.refresh)

    # ------------------------------------------------------------------ UI
    def _build_hoists(self, parent):
        """Вкладка «Лифты»: мотор сверху, груз на нитке, датчики Place_N_1..3."""
        fr = tk.Frame(parent)
        fr.pack(fill="both", expand=True, padx=6, pady=6)
        self.hoist_views = []
        for i in range(len(self.hw.hoists)):
            cv = tk.Canvas(fr, width=HoistView.W, height=430, bg="white",
                           highlightthickness=1, highlightbackground="#bbb")
            cv.grid(row=0, column=i, padx=8)
            self.hoist_views.append(HoistView(cv, self.hw, i))
        tk.Label(fr, justify="left", fg="#555", text=(
            "Мотор (барабан) наматывает нитку - груз поднимается; разматывает - опускается.\n"
            "Направление задаёт канал Direct_M_1 / Direct_M_2: 1 = подъём, 0 = спуск.\n"
            "Каждый шаг двигателя смещает груз на 0.25 мм (4 шага = 1 мм); Couster_N считает шаги.\n"
            "Датчики Place_N_1 (верх), Place_N_2 (середина), Place_N_3 (низ) выдают 1, когда груз напротив.\n"
            "Ползунком слева можно переставить груз вручную.")).grid(row=1, column=0, columnspan=2, sticky="w", pady=8)

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
        # лифты: моторы, нитки, грузы и датчики Place_N_1..3
        for v in getattr(self, "hoist_views", []):
            v.refresh(dio, self._steps_cache)
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
