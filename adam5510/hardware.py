# -*- coding: utf-8 -*-
"""Модель оборудования ADAM-5510M.

Состав (как на схеме подключений):
  * 2 x ADAM-5050  - цифровые каналы, по 16 штук (в окне: два столбца по 8 кнопок);
  * ADAM-5024      - 4 аналоговых выхода;
  * ADAM-5017      - 8 аналоговых входов;
  * двухкоординатный плоттер на двух шаговых двигателях.

Подключение плоттера (из схемы):
  слот 0 (ADAM-5050 №0): каналы 0..3 - обмотки A,B,C,D двигателя X,
                         канал 4     - Work (перо: 1 = опущено, 0 = поднято)
  слот 1 (ADAM-5050 №1): каналы 0..3 - обмотки A,B,C,D двигателя Y,
                         канал 4     - Stand_by (кнопка, читается программой)
"""
import threading
import time

ABIT, ABYTE, AWORD = 0, 1, 2

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
        if not self.plotter_attached:
            return
        pl = self.plotter
        if slot in (0, 1) and any(c < 4 for c in bits):
            pl.motor_update(slot, self.dio[slot][0:4])
        if slot == 0 and 4 in bits:
            pl.set_pen(self.dio[0][4])

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

    # ---- ADAM-5024 / ADAM-5017 ----
    def write_ao(self, ch, val):
        if not 0 <= ch < 4:
            raise HwError("неверный канал ADAM-5024: %d" % ch)
        self.ao[ch] = val
        self.comm_ts = time.time()

    def read_ai(self, ch):
        if not 0 <= ch < 8:
            raise HwError("неверный канал ADAM-5017: %d" % ch)
        self.comm_ts = time.time()
        return self.ai[ch]
