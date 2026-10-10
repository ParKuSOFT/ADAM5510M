# -*- coding: utf-8 -*-
"""Модель оборудования ADAM-5510M.

Состав (как на схеме подключений):
  * 2 x ADAM-5050  - цифровые каналы, по 16 штук (в окне: два столбца по 8 кнопок);
  * ADAM-5024      - 4 аналоговых выхода;
  * ADAM-5017      - 8 аналоговых входов;
  * двухкоординатный плоттер на двух шаговых двигателях;
  * учебный стенд: кнопки, светодиоды, счётчики, датчики наличия,
    терморезисторы (входы ADAM-5017), семисегментный индикатор.

Подключение плоттера (из схемы):
  слот 0 (ADAM-5050 №0): каналы 0..3 - обмотки A,B,C,D двигателя X,
                         канал 4     - Work (перо: 1 = опущено, 0 = поднято)
  слот 1 (ADAM-5050 №1): каналы 0..3 - обмотки A,B,C,D двигателя Y,
                         канал 4     - Stand_by (кнопка, читается программой)

Остальные каналы заняты периферией стенда (см. STAND_CHANNELS).
"""
import threading
import time

ABIT, ABYTE, AWORD = 0, 1, 2

# --------------------------------------------------------------------------- #
#  Схема подключений учебного стенда (по номерам каналов ADAM-5050)
#  kind: out - выход (светодиод/обмотка/перо), in - вход (кнопка/датчик)
#        counter - счётчик: считает фронты (0 -> 1) этого канала
#        seg     - сегмент семисегментного индикатора
# --------------------------------------------------------------------------- #
STAND_CHANNELS = {
    (0, 0): ("A_X", "out", "Обмотка A шагового двигателя X"),
    (0, 1): ("B_X", "out", "Обмотка B шагового двигателя X"),
    (0, 2): ("C_X", "out", "Обмотка C шагового двигателя X"),
    (0, 3): ("D_X", "out", "Обмотка D шагового двигателя X"),
    (0, 4): ("Work", "out", "Перо плоттера (1 = опущено)"),
    (0, 5): ("Direct_M_1", "out", "Направление двигателя M1 (X)"),
    (0, 6): ("Couster_1", "counter", "Счётчик N1 (считает импульсы)" ),
    (0, 7): ("Hot", "out", "Светодиод Hot (нагрев)"),
    (0, 8): ("Place_1_1", "in", "Датчик наличия Place 1-1"),
    (0, 9): ("Place_1_2", "in", "Датчик наличия Place 1-2"),
    (0, 10): ("Place_1_3", "in", "Датчик наличия Place 1-3"),
    (0, 11): ("Seg_a", "seg", "Семисегментный индикатор, сегмент a"),
    (0, 12): ("Seg_b", "seg", "Семисегментный индикатор, сегмент b"),
    (0, 13): ("Seg_c", "seg", "Семисегментный индикатор, сегмент c"),
    (0, 14): ("Seg_d", "seg", "Семисегментный индикатор, сегмент d"),
    (0, 15): ("Wait", "out", "Светодиод Wait (ожидание)"),

    (1, 0): ("A_Y", "out", "Обмотка A шагового двигателя Y"),
    (1, 1): ("B_Y", "out", "Обмотка B шагового двигателя Y"),
    (1, 2): ("C_Y", "out", "Обмотка C шагового двигателя Y"),
    (1, 3): ("D_Y", "out", "Обмотка D шагового двигателя Y"),
    (1, 4): ("Stand_by", "in", "Кнопка Stand_by (без фиксации)"),
    (1, 5): ("Direct_M_2", "out", "Направление двигателя M2 (Y)"),
    (1, 6): ("Couster_2", "counter", "Счётчик N2 (считает импульсы)"),
    (1, 7): ("Hot_Extreme", "out", "Светодиод Hot_Extreme (парный к Hot)"),
    (1, 8): ("Alarm_Saund", "out", "Звуковой сигнал тревоги"),
    (1, 9): ("Place_2_1", "in", "Датчик наличия Place 2-1"),
    (1, 10): ("Place_2_2", "in", "Датчик наличия Place 2-2"),
    (1, 11): ("Place_2_3", "in", "Датчик наличия Place 2-3"),
    (1, 12): ("Cool", "out", "Вентилятор (охлаждение)"),
    (1, 13): ("Seg_e", "seg", "Семисегментный индикатор, сегмент e"),
    (1, 14): ("Seg_f", "seg", "Семисегментный индикатор, сегмент f"),
    (1, 15): ("Seg_g", "seg", "Семисегментный индикатор, сегмент g"),
}

# Терморезисторы (NTC) подключены к аналоговым входам ADAM-5017.
THERMISTORS = [(0, "Thermistor_1"), (1, "Thermistor_2")]

# Семисегментный индикатор: какой сегмент горит для цифры 0..9 (a..g).
SEG_PATTERNS = {
    0: "abcdef", 1: "bc", 2: "abged", 3: "abgcd", 4: "fgbc", 5: "afgcd",
    6: "afgedc", 7: "abc", 8: "abcdefg", 9: "abcdfg", "-": "g", " ": "",
}
SEG_ORDER = "abcdefg"


def segment_value(digit):
    """битовая маска a..g (бит 0 = сегмент a) для цифры 0..9 / '-' / ' '."""
    s = SEG_PATTERNS.get(digit)
    if s is None:
        s = SEG_PATTERNS[str(digit)] if str(digit) in SEG_PATTERNS else ""
    v = 0
    for ch in s:
        v |= 1 << SEG_ORDER.index(ch)
    return v

# Допустимые состояния обмоток (A B C D) -> номер фазы в цикле.
# Один шаг двигателя = переход к соседней фазе (+1 или -1 по кругу).
PATTERNS = {
    (1, 0, 0, 1): 0,
    (1, 1, 0, 0): 1,
    (0, 1, 1, 0): 2,
    (0, 0, 1, 1): 3,
}


class HwError(Exception):
    pass


class Axis:
    """Один шаговый двигатель: по состоянию обмоток считает шаги."""

    def __init__(self):
        self.phase = None   # последняя известная фаза
        self.last_dir = 1   # направление последнего шага
        self.skipped = 0    # перескоки через фазу (3 -> 1, 0 -> 2 и т.п.)

    def apply(self, bits):
        """Сколько шагов сделал двигатель: +1, -1, 0 (стоит) или +-2 (перескок).

        Перескок через одну фазу двигатель проходит по инерции в том же
        направлении, в котором двигался до этого."""
        idx = PATTERNS.get(tuple(bits))
        if idx is None:     # 0000 или промежуточная комбинация: ротор стоит
            return 0
        if self.phase is None:
            self.phase = idx
            return 0
        d = (idx - self.phase) % 4
        self.phase = idx
        if d == 1:
            self.last_dir = 1
            return 1
        if d == 3:
            self.last_dir = -1
            return -1
        if d == 2:
            self.skipped += 1
            return 2 * self.last_dir
        return 0


class Plotter:
    """Каретка с пером. Координаты хранятся в шагах (steps_per_mm шагов на мм)."""

    def __init__(self, width_mm=600, height_mm=400, steps_per_mm=4):
        self.lock = threading.Lock()
        self.spm = steps_per_mm
        self.width = width_mm
        self.height = height_mm
        self.axes = [Axis(), Axis()]
        self.pos = [0, 0]
        self.pen_down = False
        self.segments = []      # (x0, y0, x1, y1) в шагах
        self.version = 0        # растёт при очистке рисунка
        self.hit_limit = False

    def max_steps(self, m):
        return int((self.width if m == 0 else self.height) * self.spm)

    def motor_update(self, m, bits):
        with self.lock:
            d = self.axes[m].apply(bits)
            if d == 0:
                return
            new = self.pos[m] + d
            # люфт ~1 мм допускаем; дальше - упор, каретка не едет
            if new < -self.spm or new > self.max_steps(m) + self.spm:
                self.hit_limit = True
                return
            x0, y0 = self.pos
            self.pos[m] = new
            if self.pen_down:
                self.segments.append((x0, y0, self.pos[0], self.pos[1]))

    def set_pen(self, down):
        self.pen_down = bool(down)

    def clear(self, home=True):
        with self.lock:
            self.segments = []
            self.version += 1
            self.hit_limit = False
            if home:
                self.pos = [0, 0]

    def set_field(self, width_mm, height_mm):
        with self.lock:
            self.width, self.height = width_mm, height_mm

    @property
    def skipped(self):
        return self.axes[0].skipped + self.axes[1].skipped

    def snapshot(self, start):
        with self.lock:
            return (self.version, self.segments[start:], tuple(self.pos),
                    self.pen_down, self.hit_limit)


class Thermistor(object):
    """Терморезистор (NTC) с делителем на входе ADAM-5017.

    Ползунок задаёт "нагрев" 0..100%; напряжение на входе 0..10 В:
    холодный терморезистор -> высокое напряжение, горячий -> низкое.
    """

    def __init__(self, channel, name):
        self.ch = channel
        self.name = name
        self.power = 0.0        # нагрев от внешних цепей, %
        self.level = 50.0       # показание ползунка, %
        self.vref = 10.0

    @property
    def temp_pct(self):
        p = self.level + self.power
        return max(0.0, min(100.0, p))

    @property
    def volts(self):
        return round(self.vref * (1.0 - self.temp_pct / 100.0), 3)

    def update(self, ai_list):
        ai_list[self.ch] = self.volts


class Hardware:
    def __init__(self):
        self.lock = threading.RLock()
        self.dio = [[0] * 16 for _ in range(2)]
        self.ao = [0] * 4
        self.ai = [0.0] * 8
        self.plotter = Plotter()
        self.plotter_attached = True
        self.comm_ts = 0.0
        self.running = False
        self.led_on = True
        # ---- стенд ----
        self.counters = {(0, 6): 0, (1, 6): 0}     # Couster_1, Couster_2
        self.seg_digit = None                      # цифра на индикаторе или None
        self.thermistors = [Thermistor(ch, nm) for ch, nm in THERMISTORS]
        self.stand_observers = []                  # колбэки: что-то изменилось

    # ---- наблюдатели (окно стенда подписывается на изменения) ----
    def add_observer(self, fn):
        if fn not in self.stand_observers:
            self.stand_observers.append(fn)

    def remove_observer(self, fn):
        if fn in self.stand_observers:
            self.stand_observers.remove(fn)

    def _notify(self):
        for fn in list(self.stand_observers):
            try:
                fn()
            except Exception:
                pass

    # ---- ADAM-5050 ----
    def _check(self, slot, ch, limit=16):
        if not 0 <= slot < 2:
            raise HwError("нет модуля ADAM-5050 в слоте %d" % slot)
        if not 0 <= ch < limit:
            raise HwError("неверный номер канала %d" % ch)

    def _set_bits(self, slot, bits):
        """bits: {канал: 0/1}. Сначала меняем все биты, потом оповещаем плоттер."""
        for ch, v in bits.items():
            self.dio[slot][ch] = 1 if v else 0
        # счётчики Couster_1 / Couster_2 (канал 6) считают импульсы на своём канале
        if 6 in bits and (slot, 6) in self.counters:
            self.counters[(slot, 6)] += 1
        if not self.plotter_attached:
            return
        pl = self.plotter
        if slot in (0, 1) and any(c < 4 for c in bits):
            pl.motor_update(slot, self.dio[slot][0:4])
        if slot == 0 and 4 in bits:
            pl.set_pen(self.dio[0][4])

    def seg_mask(self):
        """Текущая маска сегментов a..g по состоянию каналов ADAM-5050."""
        m = 0
        for bit, (s, c) in enumerate([(0, 11), (0, 12), (0, 13), (0, 14),
                                      (1, 13), (1, 14), (1, 15)]):
            if self.dio[s][c]:
                m |= 1 << bit
        return m

    def set_seg_digit(self, digit):
        """Показать цифру на индикаторе: записать нужные уровни в каналы-сегменты."""
        m = segment_value(digit)
        with self.lock:
            bits = {}
            for bit, (s, c) in enumerate([(0, 11), (0, 12), (0, 13), (0, 14),
                                          (1, 13), (1, 14), (1, 15)]):
                bits[(s, c)] = (m >> bit) & 1
            for (s, c), v in bits.items():
                self.dio[s][c] = v
            self.seg_digit = digit
        self.comm_ts = time.time()
        self._notify()

    def counter_value(self, slot):
        return self.counters.get((slot, 6), 0)

    def reset_counter(self, slot):
        self.counters[(slot, 6)] = 0
        self._notify()

    def pulse_counter(self, slot):
        """Кнопка «+1» на стенде: послать один импульс на счётчик."""
        with self.lock:
            self.dio[slot][6] = 1
            self.counters[(slot, 6)] += 1
        self.comm_ts = time.time()
        self._notify()

    def set_input(self, slot, ch, val):
        """Установка входа стенда (датчик наличия / кнопка) из окна."""
        with self.lock:
            self._check(slot, ch)
            self.dio[slot][ch] = 1 if val else 0
        self.comm_ts = time.time()
        self._notify()

    def toggle_button(self, slot, ch):
        """Кнопка без фиксации на стенде: нажать (1), отпустить читается программой."""
        self.set_input(slot, ch, 0 if self.dio[slot][ch] else 1)

    def set_thermistor(self, index, level):
        t = self.thermistors[index]
        t.level = max(0.0, min(100.0, float(level)))
        t.update(self.ai)
        self._notify()

    def set_thermistor_power(self, index, power):
        """Нагрев терморезистора выходом ADAM-5024 (0..10 В -> 0..100 %)."""
        t = self.thermistors[index]
        t.power = max(0.0, min(100.0, float(power)))
        t.update(self.ai)
        self._notify()

    def refresh_thermistors(self):
        for t in self.thermistors:
            t.update(self.ai)

    def write_dio(self, slot, ch, val, mode=ABIT):
        with self.lock:
            if mode == ABIT:
                self._check(slot, ch)
                self._set_bits(slot, {ch: val})
            elif mode == ABYTE:
                self._check(slot, ch, 2)
                self._set_bits(slot, {ch * 8 + b: (int(val) >> b) & 1 for b in range(8)})
            elif mode == AWORD:
                self._check(slot, 0, 1)
                self._set_bits(slot, {b: (int(val) >> b) & 1 for b in range(16)})
            else:
                raise HwError("неизвестный режим %d" % mode)
        self.comm_ts = time.time()

    def read_dio(self, slot, ch, mode=ABIT):
        with self.lock:
            if mode == ABIT:
                self._check(slot, ch)
                v = self.dio[slot][ch]
            elif mode == ABYTE:
                self._check(slot, ch, 2)
                v = sum(self.dio[slot][ch * 8 + b] << b for b in range(8))
            elif mode == AWORD:
                self._check(slot, 0, 1)
                v = sum(self.dio[slot][b] << b for b in range(16))
            else:
                raise HwError("неизвестный режим %d" % mode)
        self.comm_ts = time.time()
        return v

    def toggle_dio(self, slot, ch):
        """Нажатие кнопки в окне эмулятора."""
        with self.lock:
            self._set_bits(slot, {ch: 0 if self.dio[slot][ch] else 1})
        self.comm_ts = time.time()
        self._notify()

    # ---- ADAM-5024 / ADAM-5017 ----
    def write_ao(self, ch, val):
        if not 0 <= ch < 4:
            raise HwError("неверный канал ADAM-5024: %d" % ch)
        self.ao[ch] = val
        # выходы ADAM-5024 нагревают терморезисторы стенда:
        #   0..10 В -> нагрев 0..100 %;  значения > 10 считаются условными
        #   единицами (0..100 %)
        v = float(val)
        pct = v * 10.0 if 0.0 <= v <= 10.0 else max(0.0, min(100.0, v))
        if ch in (0, 1):
            self.set_thermistor_power(ch, pct)
        self.comm_ts = time.time()
        self._notify()

    def read_ai(self, ch):
        if not 0 <= ch < 8:
            raise HwError("неверный канал ADAM-5017: %d" % ch)
        self.comm_ts = time.time()
        return self.ai[ch]

    def set_ai(self, ch, val):
        """Ручная установка аналогового входа (ползунок в окне)."""
        if not 0 <= ch < 8:
            raise HwError("неверный канал ADAM-5017: %d" % ch)
        self.ai[ch] = val
        self._notify()
