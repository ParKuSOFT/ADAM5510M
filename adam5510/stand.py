# -*- coding: utf-8 -*-
"""Окно учебного стенда.

Вкладка «Стенд» (по запросу перерисована): терморезистор с ползунком
температуры, светодиоды Hot / Hot_Extreme / Wait / Work, семисегментный
индикатор, вентилятор Cool, звуковой сигнал Alarm_Sound и кнопка Stand_by.

Вкладка «Лифты (моторы и грузы)» - визуализация двух подъёмников:
аналоговый мотор ADAM-5024 сверху, груз на нитке, датчики Place_N_1..3.

Вкладка «Схема подключений» - таблица всех каналов (не трогать).

Состояние хранится в Hardware, окна только его отображают и умеют менять.
"""
import math
import threading
import tkinter as tk
from tkinter import ttk

from .hardware import (STAND_CHANNELS, THERMISTORS, SEG_ORDER, HOIST_TRAVEL_MM,
                       thermistor_resistance)

LED_ON = {
    "Hot": "#ff8c00",           # оранжевый
    "Hot_Extreme": "#e00000",   # красный
    "Wait": "#1e9e3a",          # зелёный
    "Work": "#20b0ff",          # голубой
    "Alarm_Saund": "#ff2020", "Cool": "#40c0ff",
}
LED_OFF = "#d8d8d8"

SEG_BITS = [(0, 11), (0, 12), (0, 13), (0, 14), (1, 13), (1, 14), (1, 15)]


# --------------------------------------------------------------------------- #
#  Визуализация "лифтов": аналоговый мотор ADAM-5024 сверху, груз на нитке,
#  три датчика положения Place_N_1..3. Направление задаёт знак скорости
#  (SetMotor(N, +-v)), сигнал Direct_M_N добавляет индикацию направления.
# --------------------------------------------------------------------------- #


class HoistView(object):
    """Один "лифт" на canvas: барабан-мотор, нитка, груз, датчики Place_N_1..3."""

    W = 270                     # ширина области лифта
    MOTOR_CY = 46               # центр барабана мотора
    TOP_Y = 78                  # край рамки, откуда свисает нитка
    LINE_X = 150                # вертикальная линия нитки
    TRAVEL_PX = 300             # ход груза в пикселах
    LOAD_W, LOAD_H = 46, 30     # размер груза

    def __init__(self, cv, hw, index):
        self.cv, self.hw, self.index = cv, hw, index
        h = hw.hoists[index]
        self.title = "Лифт M%d — Analog_Motor_%d" % (index + 1, index + 1)
        x = self.LINE_X
        top = self.TOP_Y
        bot = top + self.TRAVEL_PX

        cv.create_text(135, 12, text=self.title, anchor="w",
                       font=("TkDefaultFont", 10, "bold"))
        cv.create_text(135, 28, anchor="w", fill="#666",
                       text="ADAM-5024 кн.%d, Direct_M_%d — направление"
                            % (h.motor_ao, index + 1))

        # ---- мотор (барабан) сверху ----
        cx, cy, r = x, self.MOTOR_CY, 22
        self.motor_body = cv.create_oval(cx - r, cy - r, cx + r, cy + r,
                                         fill="#e8e8e8", outline="#555", width=2)
        self.spokes = [cv.create_line(cx, cy, cx, cy - r + 4, fill="#777", width=2)
                       for _ in range(4)]
        cv.create_oval(cx - 3, cy - 3, cx + 3, cy + 3, fill="#555", outline="")
        # индикатор работы мотора (горит, когда программа крутит двигатель)
        self.motor_led = cv.create_oval(x + 40, cy - 8, x + 56, cy + 8,
                                       fill=LED_OFF, outline="#888")
        self.motor_txt = cv.create_text(x + 48, cy + 22, text="стоп", fill="#666")
        # направление вращения (стрелка вокруг барабана)
        self.arrow = cv.create_arc(cx - r - 8, cy - r - 8, cx + r + 8, cy + r + 8,
                                   start=40, extent=90, style="arc", outline="#c0c0c0",
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

        # мотор: скорость со знаком (Analog_Motor_N), едет ли груз?
        moving = abs(h.velocity) > 0.05
        if moving:
            self._angle = (getattr(self, "_angle", 0.0)
                           + h.velocity * 2.0) % 360.0
        col = "#1e9e3a" if moving else LED_OFF
        self.cv.itemconfig(self.motor_led, fill=col)
        self.cv.itemconfig(self.motor_txt,
                           text="v=%+.0f" % h.speed if h.speed else "стоп")
        # спицы барабана
        cx, cy, r = x, self.MOTOR_CY, 22
        a0 = getattr(self, "_angle", 0.0)
        for k, sp in enumerate(self.spokes):
            a = math.radians(a0 + k * 90.0)
            self.cv.coords(sp, cx, cy, cx + (r - 4) * math.sin(a),
                           cy - (r - 4) * math.cos(a))
        # стрелка направления: вверх при подъёме (скорость > 0 или Direct_M_N = 1)
        d = h.direction()
        self.cv.itemconfig(self.arrow,
                           start=40 if d >= 0 else 130,
                           extent=90 if d >= 0 else -90,
                           outline="#2b7de9" if d else "#c0c0c0")

        # датчики
        for (slot, ch, body, led) in self.sensors:
            on = bool(dio[slot][ch])
            self.cv.itemconfig(led, fill="#ff3b30" if on else LED_OFF,
                               outline="#888")
            self.cv.itemconfig(body, fill="#ffe2d6" if on else "#dfe6ee")

        self.cv.itemconfig(self.pos_lbl,
                           text="высота %.1f мм · путь %.0f мм · имп.: %d"
                                % (h.position, h.mm_traveled, h.steps))
        if abs(self.slider.get() - h.position) > 0.5:
            self._updating_slider = True
            self.slider.set(int(round(h.position)))
            self._updating_slider = False


# --------------------------------------------------------------------------- #
#  Схематичные элементы вкладки «Стенд»
# --------------------------------------------------------------------------- #


class LedWidget(tk.Frame):
    """Светодиод: лампа + подпись; горит, когда в канал записана 1."""

    def __init__(self, parent, name, color, size=26):
        tk.Frame.__init__(self, parent, bg="white")
        self.name, self.color, self.size = name, color, size
        self.canvas = tk.Canvas(self, width=size, height=size, bg="white",
                                highlightthickness=0)
        self.canvas.pack(side="left")
        pad = 2
        self.body = self.canvas.create_oval(pad, pad, size - pad, size - pad,
                                            fill=LED_OFF, outline="#777", width=2)
        self.glow = None
        self.lbl = tk.Label(self, text=name, bg="white", anchor="w", width=12)
        self.lbl.pack(side="left", padx=4)

    def set(self, on):
        self.canvas.itemconfig(self.body,
                               fill=self.color if on else LED_OFF,
                               outline="#555" if on else "#777")
        if on and self.glow is None:
            s = self.size
            self.glow = self.canvas.create_oval(0, 0, s, s, outline=self.color)
        elif not on and self.glow is not None:
            self.canvas.delete(self.glow)
            self.glow = None


class FanWidget(tk.Frame):
    """Вентилятор Cool: крыльчатка, которая крутится, когда на канале 1."""

    def __init__(self, parent, name="Cool", size=92):
        tk.Frame.__init__(self, parent, bg="white")
        self.size = size
        self.canvas = tk.Canvas(self, width=size, height=size, bg="white",
                                highlightthickness=0)
        self.canvas.pack()
        c = size / 2.0
        r = size / 2.0 - 6
        self.canvas.create_oval(c - r, c - r, c + r, c + r, outline="#555", width=2,
                                fill="#eef4fb")
        self.blades = []
        for k in range(3):
            self.blades.append(self.canvas.create_polygon(self._blade_pts(0),
                                                          fill="#9fb6cc", outline="#555"))
        self.canvas.create_oval(c - 5, c - 5, c + 5, c + 5, fill="#555", outline="")
        tk.Label(self, text=name, bg="white").pack()
        self.angle = 0.0
        self.spinning = False
        self._job = None

    def _blade_pts(self, ang):
        c = self.size / 2.0
        r = self.size / 2.0 - 10
        pts = []
        for da, rr in ((-18, 0.25), (-6, 1.0), (14, 0.95), (26, 0.25)):
            a = math.radians(ang + da)
            pts.extend([c + rr * r * math.cos(a), c + rr * r * math.sin(a)])
        return pts

    def set_on(self, on):
        """1 -> крыльчатка начинает вращаться, 0 -> останавливается."""
        if on and not self.spinning:
            self.spinning = True
            self._spin()
        elif not on:
            self.spinning = False

    def _spin(self):
        if not self.spinning or not self.winfo_exists():
            return
        self.angle = (self.angle + 24.0) % 360.0
        for k, item in enumerate(self.blades):
            self.canvas.coords(item, self._blade_pts(self.angle + k * 120.0))
        self._job = self.after(50, self._spin)


class BuzzerWidget(tk.Frame):
    """Alarm_Sound: пищалка (полукруг с контактами); при 1 гудит и мигает."""

    def __init__(self, parent, name="Alarm_Sound"):
        tk.Frame.__init__(self, parent, bg="white")
        self.canvas = tk.Canvas(self, width=64, height=44, bg="white",
                                highlightthickness=0)
        self.canvas.pack()
        self.body = self.canvas.create_arc(8, 4, 56, 44, start=180, extent=180,
                                           style="chord", fill="#f2d24b",
                                           outline="#555", width=2)
        self.canvas.create_line(14, 38, 14, 44, fill="#555", width=3)
        self.canvas.create_line(50, 38, 50, 44, fill="#555", width=3)
        self.wave = self.canvas.create_text(35, 12, text="", fill="#c0392b",
                                            font=("TkDefaultFont", 10, "bold"))
        tk.Label(self, text=name, bg="white").pack()
        self.sounding = False
        self._job = None

    def set_on(self, on):
        if on and not self.sounding:
            self.sounding = True
            self._beep(True)
        elif not on:
            self.sounding = False
            self.canvas.itemconfig(self.body, fill="#f2d24b")
            self.canvas.itemconfig(self.wave, text="")

    def _beep(self, hi):
        if not self.sounding or not self.winfo_exists():
            return
        self.canvas.itemconfig(self.body, fill="#ffb300" if hi else "#f2d24b")
        self.canvas.itemconfig(self.wave, text="♪ ♫" if hi else "")
        if hi:
            self._sound()
        self._job = self.after(250, lambda: self._beep(not hi))

    def _sound(self):
        try:                                    # Windows: системный «щелчок»
            import winsound
            winsound.Beep(2200, 120)
        except Exception:
            pass


class ButtonWidget(tk.Frame):
    """Кнопка без фиксации: нажал -> в канал 1, отпустил -> 0."""

    def __init__(self, parent, name, command_press, command_release, size=48):
        tk.Frame.__init__(self, parent, bg="white")
        self.canvas = tk.Canvas(self, width=size, height=size, bg="white",
                                highlightthickness=0)
        self.canvas.pack()
        self.canvas.create_oval(4, 8, size - 4, size - 2, fill="#888", outline="#444")
        self.cap = self.canvas.create_oval(6, 4, size - 6, size - 8, fill="#e05a4a",
                                           outline="#444", width=2)
        tk.Label(self, text=name, bg="white").pack()
        self.pressed = False
        self.canvas.tag_bind(self.cap, "<ButtonPress-1>", self._press)
        self.canvas.tag_bind(self.cap, "<ButtonRelease-1>", self._release)
        self.canvas.bind("<ButtonRelease-1>", self._release)   # отпускание вне кнопки
        self._cmd_press, self._cmd_release = command_press, command_release

    def _press(self, _e):
        self.pressed = True
        self.canvas.itemconfig(self.cap, fill="#a03c30")
        self.canvas.move(self.cap, 0, 3)
        self._cmd_press()

    def _release(self, _e):
        if not self.pressed:
            return
        self.pressed = False
        self.canvas.itemconfig(self.cap, fill="#e05a4a")
        self.canvas.move(self.cap, 0, -3)
        self._cmd_release()

    def set(self, pressed):
        """Внешняя установка состояния (например программой через SetStandby)."""
        if pressed == self.pressed:
            return
        if pressed:
            self._press(None)
        else:
            self._release(None)


class SevenSeg(tk.Frame):
    """Семисегментный индикатор: сегменты a..g загораются по каналам ADAM-5050."""

    def __init__(self, parent, w=90, h=150, t=9):
        tk.Frame.__init__(self, parent, bg="#202020")
        self.canvas = tk.Canvas(self, width=w + 40, height=h + 20, bg="#202020",
                                highlightthickness=0)
        self.canvas.pack(padx=4, pady=4)
        x, y = 20, 10
        pts = {
            "a": (x + t, y, x + w - t, y),
            "b": (x + w, y + t, x + w, y + h / 2 - t),
            "c": (x + w, y + h / 2 + t, x + w, y + h - t),
            "d": (x + t, y + h, x + w - t, y + h),
            "e": (x, y + h / 2 + t, x, y + h - t),
            "f": (x, y + t, x, y + h / 2 - t),
            "g": (x + t, y + h / 2, x + w - t, y + h / 2),
        }
        self.items = {}
        for name, (x0, y0, x1, y1) in pts.items():
            self.items[name] = self.canvas.create_line(x0, y0, x1, y1,
                                                       fill="#3a3a3a", width=8,
                                                       capstyle="round")
        self.mask_lbl = self.canvas.create_text(x + w + 18, y + h / 2, text="",
                                                angle=90, fill="#666", anchor="center")

    def set_mask(self, mask):
        for i, name in enumerate(SEG_ORDER):
            on = bool(mask & (1 << i))
            self.canvas.itemconfig(self.items[name],
                                   fill="#ff3b30" if on else "#3a3a3a")


class ThermistorWidget(tk.Frame):
    """Терморезистор (схемотично: чёрный капля-датчик с трубкой) + ползунок °C.

    Ползунок задаёт температуру; окно само пересчитывает её в напряжение
    по закону NTC (hw.set_thermistor) и подаёт на вход ADAM-5017.
    """

    MIN_C, MAX_C = -40, 150

    def __init__(self, parent, hw, index):
        tk.Frame.__init__(self, parent, bg="white")
        self.hw, self.index = hw, index
        self.t = hw.thermistors[index]
        self._updating = False

        head = tk.Frame(self, bg="white")
        head.pack(fill="x")
        tk.Label(head, text="%s → ADAM-5017 AI%d" % (self.t.name, self.t.ch),
                 bg="white", font=("TkDefaultFont", 9, "bold")).pack(anchor="w")

        row = tk.Frame(self, bg="white")
        row.pack(fill="x", padx=4)

        # ---- схематичный терморезистор ----
        self.canvas = tk.Canvas(row, width=86, height=96, bg="white",
                                highlightthickness=0)
        self.canvas.grid(row=0, column=0, rowspan=2, padx=(0, 8))
        self._draw_symbol()

        # ---- ползунок температуры ----
        self.scale = tk.Scale(row, from_=self.MIN_C, to=self.MAX_C,
                              orient="horizontal", length=170, showvalue=False,
                              bg="white", troughcolor="#dfe6ee",
                              label="температура, °C", font=("TkDefaultFont", 8))
        self.scale.grid(row=0, column=1, sticky="w")
        self.scale.set(int(round(self.t.level)))
        self.scale.configure(command=self._on_scale)

        info = tk.Frame(row, bg="white")
        info.grid(row=1, column=1, sticky="w")
        self.val_lbl = tk.Label(info, text="", bg="white", fg="#333", anchor="w",
                                font=("TkDefaultFont", 9))
        self.val_lbl.pack(anchor="w")
        self.r_lbl = tk.Label(info, text="", bg="white", fg="#666", anchor="w")
        self.r_lbl.pack(anchor="w")
        self.show()

    def _draw_symbol(self):
        cv = self.canvas
        # корпус: чёрный кружок с «каплей» и трубкой-выводами снизу
        cv.create_line(30, 78, 30, 94, fill="#555", width=2)
        cv.create_line(56, 78, 56, 94, fill="#555", width=2)
        cv.create_rectangle(24, 70, 62, 80, fill="#bbb", outline="#555")  # трубка/цоколь
        cv.create_oval(20, 18, 66, 74, fill="#111111", outline="#000", width=2)
        cv.create_line(43, 74, 43, 88, fill="#111", width=3)              # «трубка» вниз
        # блик на корпусе меняет цвет при нагреве
        self.bead = cv.create_oval(30, 30, 44, 44, fill="#4a4a4a", outline="")
        cv.create_text(43, 92, text="NTC", font=("TkDefaultFont", 7), fill="#666")

    def _on_scale(self, value):
        if self._updating:
            return
        self.hw.set_thermistor(self.index, float(value))
        self.show()

    def show(self):
        t = self.t
        hotness = max(0.0, min(1.0, (t.temp_c - 20.0) / 100.0))
        r = int(74 + hotness * 181)
        g = int(74 + (1 - hotness) * 30)
        b = 74
        self.canvas.itemconfig(self.bead, fill="#%02x%02x%02x" % (r, g, b))
        self.val_lbl.config(text="%.1f В  (%.0f °C)" % (t.volts, t.temp_c))
        self.r_lbl.config(text="R = %.1f кОм" % (thermistor_resistance(t.temp_c) / 1000.0))
        if not self._updating:
            cur = self.scale.get()
            want = int(round(t.level))
            if abs(cur - want) > 0:
                self._updating = True
                self.scale.set(want)
                self._updating = False


# --------------------------------------------------------------------------- #


class StandWindow(tk.Toplevel):
    def __init__(self, master, hw, on_close=None):
        tk.Toplevel.__init__(self, master)
        self.hw = hw
        self._on_close_cb = on_close
        self.title("Учебный стенд")
        self.geometry("980x640")
        self.minsize(760, 480)

        self.inputs = {}          # (slot,ch) -> виджет-переключатель
        self.counter_lbl = {}
        self.shadow_dio = [[None] * 16 for _ in range(2)]
        self.shadow_ai = [None] * 8
        self._steps_cache = {}          # номер лифта -> h.steps на прошлом опросе
        self._dirty = True

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=6, pady=6)

        stand_fr = tk.Frame(nb, bg="white")
        nb.add(stand_fr, text="Стенд")
        hoist_fr = tk.Frame(nb)
        nb.add(hoist_fr, text="Лифты (моторы и грузы)")
        map_fr = tk.Frame(nb)
        nb.add(map_fr, text="Схема подключений")

        self._build_main(stand_fr)
        self._build_hoists(hoist_fr)
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
            "Привод - аналоговый двигатель Analog_Motor_1/2 (ADAM-5024): SetMotor(N, v),\n"
            "v > 0 - подъём, v < 0 - спуск, |v| - скорость. Direct_M_N = 1 тоже задаёт подъём.\n"
            "Couster_N получает по импульсу на каждый пройденный грузом миллиметр.\n"
            "Датчики Place_N_1 (верх), Place_N_2 (середина), Place_N_3 (низ) выдают 1, когда груз напротив.\n"
            "Ползунком слева можно переставить груз вручную.")).grid(row=1, column=0, columnspan=2, sticky="w", pady=8)

    def _build_main(self, parent):
        """Вкладка «Стенд»: только запрошенная периферия."""
        root = tk.Frame(parent, bg="white")
        root.pack(fill="both", expand=True, padx=10, pady=8)

        left = tk.Frame(root, bg="white")
        left.pack(side="left", fill="y", padx=(0, 14))
        mid = tk.Frame(root, bg="white")
        mid.pack(side="left", fill="y", padx=(0, 14))
        right = tk.Frame(root, bg="white")
        right.pack(side="left", fill="both", expand=True)

        # ---- 1. терморезистор + ползунок температуры -----------------------
        lf = tk.LabelFrame(left, text="Терморезистор (ADAM-5017)", bg="white")
        lf.pack(fill="x", pady=4)
        self.therm_widgets = []
        for i in range(min(1, len(self.hw.thermistors))):
            w = ThermistorWidget(lf, self.hw, i)
            w.pack(fill="x", padx=6, pady=6)
            self.therm_widgets.append(w)

        # ---- 9. кнопка без фиксации Stand_by ------------------------------
        btn_fr = tk.LabelFrame(left, text="Кнопка без фиксации", bg="white")
        btn_fr.pack(fill="x", pady=8)
        self.stand_btn = ButtonWidget(
            btn_fr, "Stand_by (слот 1, кн. 4)",
            command_press=lambda: self.hw.set_input(1, 4, 1),
            command_release=lambda: self.hw.set_input(1, 4, 0))
        self.stand_btn.pack(padx=8, pady=6)

        # ---- 2..5 светодиоды ----------------------------------------------
        led_fr = tk.LabelFrame(right, text="Светодиоды", bg="white")
        led_fr.pack(fill="x", pady=4)
        grid = tk.Frame(led_fr, bg="white")
        grid.pack(fill="x", padx=8, pady=8)
        self.led_widgets = {}
        leds = [("Hot", (0, 7)), ("Hot", None),        # два Hot
                ("Hot_Extreme", (1, 7)), ("Hot_Extreme", None),
                ("Wait", (0, 15)), ("Work", (0, 4))]
        r = c = 0
        seen = {}
        for name, _src in leds:
            seen[name] = seen.get(name, 0) + 1
            cap = "%s #%d" % (name, seen[name]) if seen[name] == 2 else name
            w = LedWidget(grid, cap, LED_ON[name])
            w.grid(row=r, column=c, sticky="w", padx=10, pady=6)
            self.led_widgets.setdefault(name, []).append(w)
            c += 1
            if c == 2:
                c, r = 0, r + 1

        # ---- 7. вентилятор Cool + 8. Alarm_Sound --------------------------
        fan_fr = tk.LabelFrame(right, text="Исполнительные устройства", bg="white")
        fan_fr.pack(fill="x", pady=6)
        row = tk.Frame(fan_fr, bg="white")
        row.pack(fill="x", padx=10, pady=8)
        self.fan = FanWidget(row, "Cool (слот 1, кн. 12)")
        self.fan.grid(row=0, column=0, padx=16)
        self.buzzer = BuzzerWidget(row, "Alarm_Sound (слот 1, кн. 8)")
        self.buzzer.grid(row=0, column=1, padx=16)

        # ---- 6. семисегментный индикатор ----------------------------------
        seg_fr = tk.LabelFrame(mid, text="Семисегментный индикатор\n"
                                        "(каналы 11–14 слота 0 и 13–15 слота 1)",
                               bg="white")
        seg_fr.pack(fill="x", pady=4)
        self.seg = SevenSeg(seg_fr)
        self.seg.pack(padx=6, pady=6)
        row = tk.Frame(seg_fr, bg="white")
        row.pack(pady=(0, 8))
        for d in range(10):
            tk.Button(row, text=str(d), width=2, bg="white",
                      command=lambda v=d: self.hw.set_seg_digit(v)).grid(
                          row=0, column=d % 5, padx=1)
        tk.Button(seg_fr, text="Погасить", bg="white",
                  command=lambda: self.hw.set_seg_digit(" ")).pack(pady=2)

        tk.Label(right, justify="left", bg="white", fg="#555", text=(
            "Терморезистор: ползунок задаёт температуру (°C), окно само переводит её\n"
            "в напряжение по закону NTC и подаёт на вход ADAM-5017 (Temp).\n"
            "Светодиоды горят, когда программа записала 1 в канал (Set5050).\n"
            "Индикатор показывается по уровням сегментных каналов; кнопки 0-9 - ручная проверка.\n"
            "Cool - вентилятор (крутится при 1), Alarm_Sound - пищалка (гудит при 1),\n"
            "Stand_by - кнопка без фиксации: нажата = 1, отпущена = 0.")).pack(anchor="w", padx=8, pady=6)

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
                         "Терморезистор NTC: холодный -> больше В, горячий -> меньше В"))
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
    def _mark_dirty(self):
        self._dirty = True

    def refresh(self):
        """Обновление всех виджетов по состоянию Hardware."""
        hw = self.hw
        with hw.lock:
            dio = [list(hw.dio[s]) for s in range(2)]
        # светодиоды: две пары Hot/Hot_Extreme загораются от одного канала
        for name in ("Hot", "Hot_Extreme", "Wait", "Work"):
            src = {"Hot": (0, 7), "Hot_Extreme": (1, 7),
                   "Wait": (0, 15), "Work": (0, 4)}[name]
            on = bool(dio[src[0]][src[1]])
            for w in self.led_widgets.get(name, []):
                w.set(on)
        # вентилятор / пищалка
        self.fan.set_on(bool(dio[1][12]))
        self.buzzer.set_on(bool(dio[1][8]))
        # кнопка Stand_by (если её изменила программа - синхронизируем вид)
        self.stand_btn.set(bool(dio[1][4]))
        # семисегментный индикатор по каналам сегментов
        mask = 0
        for bit, (s, c) in enumerate(SEG_BITS):
            if dio[s][c]:
                mask |= 1 << bit
        self.seg.set_mask(mask)
        # терморезисторы (ползунок мог двигать нагрев из _tick)
        for w in self.therm_widgets:
            w.show()
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
        if self.fan.spinning:
            self.fan.set_on(False)
        if self.buzzer.sounding:
            self.buzzer.set_on(False)
        if self._on_close_cb:
            self._on_close_cb()
        self.destroy()
