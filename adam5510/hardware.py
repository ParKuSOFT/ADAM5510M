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

Остальные каналы ADAM-5050 заняты периферией стенда (см. STAND_CHANNELS).
Аналоговые модули (см. AO_DEVICES / AI_DEVICES):
  ADAM-5024 (слот 2) - аналоговые выходы: два двигателя, динамик, "Cool_Extreme";
  ADAM-5017 (слот 3) - аналоговые входы: терморезистор, датчики света/звука,
                       аварийный датчик, счётчик охлаждения, два резистора.
"""
import math
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
    (0, 10): ("Place_2_3", "in", "Датчик наличия Place 2-3"),
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
    (1, 9): ("Place_1_3", "in", "Датчик наличия Place 1-3"),
    (1, 10): ("Place_2_1", "in", "Датчик наличия Place 2-1"),
    (1, 11): ("Place_2_2", "in", "Датчик наличия Place 2-2"),
    (1, 12): ("Cool", "out", "Вентилятор (охлаждение)"),
    (1, 13): ("Seg_e", "seg", "Семисегментный индикатор, сегмент e"),
    (1, 14): ("Seg_f", "seg", "Семисегментный индикатор, сегмент f"),
    (1, 15): ("Seg_g", "seg", "Семисегментный индикатор, сегмент g"),
}

# --------------------------------------------------------------------------- #
#  Аналоговые модули (по схеме)
#  ADAM-5024 - аналоговые ВЫХОДЫ, стоит в слоте 2: kind: motor - двигатель
#        (число = скорость), speaker - динамик (частота тона), cooler - охладитель.
#  ADAM-5017 - аналоговые ВХОДЫ, стоит в слоте 3: kind: thermistor - терморезистор
#        (управляется ползунком + нагревом от AO0), sensor - датчик (ползунок 0..10 В),
#        resistor - подстроечный резистор: +V -> R2 (стрелка в резистор от плюса),
#        GND -> R1 (стрелка в резистор от земли).
# --------------------------------------------------------------------------- #
AO_SLOT = 2          # слот ADAM-5024 (аналоговые выходы)
AI_SLOT = 3          # слот ADAM-5017 (аналоговые входы)

AO_DEVICES = {
    0: ("Analog_Motor_1", "motor", "Двигатель M1: число 0..100 = скорость вращения"),
    1: ("Analog_Motor_2", "motor", "Двигатель M2: число 0..100 = скорость вращения"),
    2: ("Speaker", "speaker", "Динамик: число = частота звука, Гц (0 = тихо)"),
    3: ("Cool_Extreme", "cooler", "Охладитель A/M: 0..10 В, охлаждает терморезистор №1"),
}

AI_DEVICES = {
    0: ("Temp", "thermistor", "Терморезистор (NTC): 10 В = холодный, 0 В = горячий"),
    1: ("Light_Sensor_1", "sensor", "Датчик света U1 (ΔU1): напряжение 0..10 В"),
    2: ("Sound_Sensor", "sensor", "Датчик звука (микрофон): напряжение 0..10 В"),
    3: ("Light_Sensor_2", "sensor", "Датчик света U2 (ΔU2): напряжение 0..10 В"),
    4: ("Alarm_Sensor", "sensor", "Аварийный датчик (ΔU): напряжение 0..10 В"),
    5: ("Counter_Cool_Extreme", "sensor", "Счётчик охлаждения (ΔN0): показание 0..10"),
    6: ("Rezistor_2", "resistor", "Резистор R2: стрелка от +V (напряжение делителя 0..10 В)"),
    7: ("Rezistor_1", "resistor", "Резистор R1: стрелка от GND (напряжение делителя 0..10 В)"),
}

# Терморезисторы (NTC) на аналоговых входах ADAM-5017 (по схеме):
#   Thermistor_1 -> вход 0 (Temp),        нагрев выходом AO0;
#   Thermistor_2 -> вход 3 (Light_Sensor_2 - второй терморезистор в цепи ΔU2),
#                  нагрев выходом AO3 (Cool_Extreme).
THERMISTORS = [(0, "Thermistor_1"), (3, "Thermistor_2")]

# Входы ADAM-5017, которыми можно управлять ползунком (кроме терморезисторов):
MANUAL_AI = [1, 2, 4, 5, 6, 7]     # Light_Sensor_1/2, Sound, Alarm, Counter, R2, R1

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

# --------------------------------------------------------------------------- #
#  Подъёмные механизмы стенда: мотор + груз на нитке + датчики положения.
#  kind "hoist": аналоговый двигатель ADAM-5024 наматывает/сматывает нитку;
#    направление задаёт знак скорости (SetMotor(№, +-скорость));
#    три датчика наличия Place_N_1..3 выдают 1, когда груз напротив них;
#  kind "stepper_hoist": шаговый двигатель ADAM-5050 (обмотки A..D),
#    Direct_M_N = направление (0 - сматывает, груз опускается; 1 - наматывает);
#    шаг двигателя = подъём/опускание груза на STEP_MM мм.
# --------------------------------------------------------------------------- #
HOIST_TRAVEL_MM = 180.0     # ход груза вдоль линейки датчиков, мм
STEP_MM = 0.25              # один шаг ШД = 0.25 мм (4 шага = 1 мм)

# Груз изначально в самом НИЖНЕМ положении - напротив нижнего датчика Place_N_3.
HOISTS = [
    {"name": "Hoist_1", "kind": "stepper_hoist", "slot": 0, "dir_ch": 5,
     "couster": (0, 6), "coils": (0, 0),        # обмотки A_X..D_X (слот 0, каналы 0..3)
     "sensors": [(0, 8), (0, 9), (1, 9)],       # Place_1_1 (верх), _1_2, _1_3 (низ)
     "desc": "Лифт M1: шаговый двигатель X (слот 0, каналы 0..3), "
             "Direct_M_1 - направление, Couster_1 считает шаги, "
             "датчики Place_1_1..Place_1_3"},
    {"name": "Hoist_2", "kind": "stepper_hoist", "slot": 1, "dir_ch": 5,
     "couster": (1, 6), "coils": (1, 0),        # обмотки A_Y..D_Y (слот 1, каналы 0..3)
     "sensors": [(1, 10), (1, 11), (0, 10)],    # Place_2_1 (верх), _2_2, _2_3 (низ)
     "desc": "Лифт M2: шаговый двигатель Y (слот 1, каналы 0..3), "
             "Direct_M_2 - направление, Couster_2 считает шаги, "
             "датчики Place_2_1..Place_2_3"},
]


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


class Axis(object):
    """Один шаговый двигатель: по состоянию обмоток считает шаги."""

    def __init__(self, on_step=None):
        self.phase = None   # последняя известная фаза
        self.last_dir = 1   # направление последнего шага
        self.skipped = 0    # перескоки через фазу (3 -> 1, 0 -> 2 и т.п.)
        self.on_step = on_step      # колбэк on_step(направление), вызывается из Hardware

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


class Plotter(object):
    """Каретка с пером. Координаты хранятся в шагах (steps_per_mm шагов на мм)."""

    def __init__(self, width_mm=600, height_mm=400, steps_per_mm=4, on_step=None):
        self.lock = threading.Lock()
        self.spm = steps_per_mm
        self.width = width_mm
        self.height = height_mm
        self.on_step = on_step      # on_step(motor, d): шаги ШД ещё и тянут груз M2
        self.axes = [Axis(), Axis()]
        self.pos = [0, 0]
        self.pen_down = False
        self.segments = []      # (x0, y0, x1, y1) в шагах
        self.version = 0        # растёт при очистке рисунка
        self.hit_limit = False

    def max_steps(self, m):
        return int((self.width if m == 0 else self.height) * self.spm)

    def motor_update(self, m, bits):
        """Обновить каретку по состоянию обмоток; вернуть число шагов (со знаком)."""
        with self.lock:
            d = self.axes[m].apply(bits)
            if d == 0:
                return 0
            new = self.pos[m] + d
            # люфт ~1 мм допускаем; дальше - упор, каретка не едет
            if new < -self.spm or new > self.max_steps(m) + self.spm:
                self.hit_limit = True
                return d
            x0, y0 = self.pos
            self.pos[m] = new
            if self.pen_down:
                self.segments.append((x0, y0, self.pos[0], self.pos[1]))
        if self.on_step is not None:
            self.on_step(m, d)
        return d

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


class Hoist(object):
    """"Лифт" стенда: шаговый двигатель сверху, груз на нитке, датчики положения.

    position - высота груза в мм (0 = нижняя точка, travel = верхняя).
    Привод - шаговый двигатель ADAM-5050 (обмотки A..D):
      * каждый шаг смещает груз на STEP_MM мм (4 шага = 1 мм);
      * направление задаёт канал Direct_M_N: 1 = наматывает (груз едет вверх),
        0 = сматывает (груз опускается);
      * каждый шаг - импульс на счётчик Couster_N;
      * три датчика Place_N_1 (верх) / Place_N_2 (середина) / Place_N_3 (низ)
        выдают 1, когда груз стоит напротив них; изначально груз внизу.
    """

    def __init__(self, cfg, hw):
        self.hw = hw
        self.name = cfg["name"]
        self.kind = cfg["kind"]
        self.sensors = list(cfg["sensors"])       # [верхний, средний, нижний]
        self.travel = HOIST_TRAVEL_MM
        self.position = 0.0                       # старт: НИЖНИЙ датчик (Place_N_3)
        self.speed = 0.0                          # для аналогового: со знаком
        self.steps = 0                            # всего сделано шагов (со знаком)
        self.last_step_ts = 0.0                   # антидребезг счётчика импульсов
        self.ao_ch = cfg.get("ao_ch")
        self.slot = cfg.get("slot")
        self.dir_ch = cfg.get("dir_ch")
        self.couster = cfg.get("couster")
        self.coils = cfg.get("coils")             # (slot, first_ch) обмоток A..D
        self.axis = Axis()                        # считает шаги по состоянию обмоток
        self._last_steps = 0                      # для индикации скорости мотора
        self._sensor_cache = [None, None, None]

    # ---- движение ----
    def move(self, dmm):
        if dmm:
            self.position = max(0.0, min(self.travel, self.position + dmm))

    def coils_update(self, bits):
        """Hardware вызывает при каждом изменении каналов-обмоток этого лифта.

        bits - состояния A,B,C,D (0/1). Переход к соседней фазе = один шаг."""
        d = self.axis.apply(bits)
        if d:
            self.stepper_step(d)

    def stepper_step(self, d):
        """d = +-1 (или +-2 при перескоке фазы) шагов двигателя."""
        self.steps += d
        self.move(d * STEP_MM)
        self._count_pulse(d)

    def set_speed(self, v):
        """Скорость мотора для визуализации: число шагов за последний такт."""
        self.speed = max(-100.0, min(100.0, float(v)))

    def _count_pulse(self, n):
        """Каждый шаг двигателя = один импульс на счётчик Couster_N.

        Значение канала-счётчика при этом переключается (фронт 0->1), как и
        полагается счётному входу; программа может сбросить счётчик
        (ResetCounter / кнопка «Сброс» на стенде)."""
        if self.couster is None:
            return
        self.hw.counters[self.couster] = \
            self.hw.counters.get(self.couster, 0) + abs(n)
        slot, ch = self.couster
        self.hw.dio[slot][ch] = 1 if self.hw.dio[slot][ch] else 0

    # ---- физика и датчики ----
    def tick(self, dt):
        """Вызывается из Hardware._tick(): обновить индикацию скорости мотора."""
        moved = abs(self.steps - self._last_steps)
        self._last_steps = self.steps
        self.set_speed(moved / max(dt, 1e-6) * 0.5)   # сглаженная "оборотистость"

    def update_sensors(self, dio):
        """Датчик выдаёт 1, если груз напротив него (плюс-минут зона срабатывания)."""
        for i, (slot, ch) in enumerate(self.sensors):
            h = self.travel * (1.0 - i / 2.0)      # 1-й сверху, 3-й снизу
            on = 1 if abs(self.position - h) <= 7.0 else 0
            if self._sensor_cache[i] != on:
                self._sensor_cache[i] = on
                dio[slot][ch] = on


class Thermistor(object):
    """Терморезистор (NTC) с делителем на входе ADAM-5017.

    Ползунок задаёт "нагрев" 0..100%; напряжение на входе 0..10 В:
    холодный терморезистор -> высокое напряжение, горячий -> низкое.
    Дополнительно нагревается выходом ADAM-5024 (heater_ao), охлаждается
    охладителем (cooler_ao) и цифровым вентилятором Cool (канал 1:12).
    """

    def __init__(self, channel, name, heater_ao=None, cooler_ao=None):
        self.ch = channel
        self.name = name
        self.power = 0.0        # нагрев от внешних цепей, %
        self.level = 50.0       # показание ползунка, %
        self.vref = 10.0
        self.heater_ao = heater_ao      # выход ADAM-5024, греющий этот терморезистор
        self.cooler_ao = cooler_ao      # выход ADAM-5024, охлаждающий его
        self.fan_ch = (1, 12)           # цифровой канал "Cool" (вентилятор)

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
        self.motors = {ch: {"speed": 0.0, "angle": 0.0, "steps_done": 0,
                            "last": time.time()}
                       for ch in AO_DEVICES if AO_DEVICES[ch][1] == "motor"}
        self.plotter = Plotter()
        self.plotter_attached = True
        self.comm_ts = 0.0
        self.running = False
        self.led_on = True
        # ---- стенд ----
        self.counters = {(0, 6): 0, (1, 6): 0}     # Couster_1, Couster_2
        self.seg_digit = None                      # цифра на индикаторе или None
        # грузы на нитках: M1 - аналоговый мотор, M2 - шаговый двигатель
        self.hoists = [Hoist(cfg, self) for cfg in HOISTS]
        # терморезисторы: Thermistor_1 греется AO0 и охлаждается вентилятором Cool;
        # Thermistor_2 - "экстремальный": его же охладитель Cool_Extreme (AO3)
        # одновременно и греет (полярность условная).
        self.thermistors = [
            Thermistor(0, "Thermistor_1", heater_ao=0),
            Thermistor(3, "Thermistor_2", heater_ao=3),
        ]
        self.stand_observers = []                  # колбэки: что-то изменилось
        # ---- аналоговая периферия ADAM-5024 / ADAM-5017 ----
        self.speaker_hz = 0.0                      # частота тона на Speaker (AO2)
        self.cool_extreme = 0.0                    # показание охладителя A/M (AO3)
        self.sensor_levels = {1: 5.0, 2: 0.0, 4: 0.0, 5: 0.0,   # AI: датчики
                              6: 5.0, 7: 5.0}                   # AI: резисторы R2/R1
        self._t = time.time()
        self._timer = None
        self._start_sim()

    # ---- физика стенда: моторы крутятся, грузы едут, терморезисторы остывают ----
    def _start_sim(self):
        self._tick()

    def _plotter_step(self, motor, d):
        """Шаг шагового двигателя плоттера: двигатель Y тянет груз M2 на стенде."""
        if motor == 1:
            self.hoists[1].stepper_step(d)

    def _tick(self):
        now = time.time()
        dt = min(1.0, max(0.0, now - self._t))
        self._t = now
        changed = False
        with self.lock:
            # аналоговые двигатели: скорость 0..100 -> обороты
            for m in self.motors.values():
                if m["speed"]:
                    m["angle"] += m["speed"] * 3.6 * dt
                    changed = True
            # грузы на нитках: наматывание/сматывание + датчики положения
            for h in self.hoists:
                p0 = h.position
                h.tick(dt)
                if h.position != p0:
                    changed = True
                h.update_sensors(self.dio)
        # терморезисторы: нагрев от выходов ADAM-5024, остывание (вент. Cool ускоряет)
        fan = bool(self.dio[1][12])
        for t in self.thermistors:
            ext = 0.0
            if t.heater_ao is not None:
                v = float(self.ao[t.heater_ao])
                # 0..10 В трактуем как 0..100 % нагрева
                ext += v * 10.0 if 0.0 <= v <= 10.0 else max(0.0, min(100.0, v))
            cool = 0.0
            if t.cooler_ao is not None:
                cool = max(0.0, min(100.0, float(self.ao[t.cooler_ao])))
            tgt = min(100.0, ext)
            k = (2.5 + 6.0 * fan + 3.0 * cool / 100.0) * dt
            if abs(t.power - tgt) > 0.01:
                t.power += (tgt - t.power) * min(1.0, k)
                changed = True
            elif t.power != tgt:
                t.power = tgt
                changed = True
        if changed:
            self.refresh_sensors()
            self._notify()
        self._timer = threading.Timer(0.1, self._tick)
        self._timer.daemon = True
        self._timer.start()

    def stop_sim(self):
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def motor_angle(self, ch):
        m = self.motors.get(ch)
        return m["angle"] if m else 0.0

    def refresh_sensors(self):
        """Пересчитать напряжения всех аналоговых входов ADAM-5017."""
        for t in self.thermistors:
            t.update(self.ai)
        for ch, lvl in self.sensor_levels.items():
            self.ai[ch] = round(float(lvl), 3)

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
        """bits: {канал: 0/1}. Сначала меняем все биты, потом оповещаем лифты/плоттер.

        Каждый шаг обмоток (A..D) одновременно:
          * тянет нитку соответствующего "лифта" - груз смещается (4 шага = 1 мм);
          * двигает каретку плоттера (тот же двигатель используется для рисования)."""
        for ch, v in bits.items():
            self.dio[slot][ch] = 1 if v else 0
        # счётчики Couster_N считают импульсы, если канал 6 меняется вручную
        if 6 in bits and (slot, 6) in self.counters and \
                not any(h.couster == (slot, 6) for h in self.hoists):
            self.counters[(slot, 6)] += 1
        moved = False
        if slot in (0, 1) and any(c < 4 for c in bits):
            coil_bits = self.dio[slot][0:4]
            for h in self.hoists:                    # лифт этого же двигателя
                if h.coils and h.coils[0] == slot:
                    p0 = h.position
                    h.coils_update(coil_bits)
                    if h.position != p0:
                        moved = True
            if self.plotter_attached:
                d = self.plotter.motor_update(slot, coil_bits)
                if d:
                    moved = True
        if slot == 0 and 4 in bits and self.plotter_attached:
            self.plotter.set_pen(self.dio[0][4])
        return moved

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
        for h in self.hoists:
            if h.couster == (slot, 6):
                h.steps = 0
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

    def set_sensor(self, ch, val):
        """Ползунок датчика/резистора ADAM-5017 в окне стенда (0..10 В)."""
        if not 0 <= ch < 8:
            raise HwError("неверный канал ADAM-5017: %d" % ch)
        if AI_DEVICES[ch][1] == "thermistor":
            # вход Temp занят терморезистором - ползунком задаём его температуру
            for t in self.thermistors:
                if t.ch == ch:
                    return self.set_thermistor(self.thermistors.index(t), val * 10.0)
        self.sensor_levels[ch] = max(0.0, min(10.0, float(val)))
        self.ai[ch] = round(self.sensor_levels[ch], 3)
        self._notify()

    def refresh_thermistors(self):
        for t in self.thermistors:
            t.update(self.ai)

    def write_dio(self, slot, ch, val, mode=ABIT):
        with self.lock:
            if mode == ABIT:
                self._check(slot, ch)
                moved = self._set_bits(slot, {ch: val})
            elif mode == ABYTE:
                self._check(slot, ch, 2)
                moved = self._set_bits(
                    slot, {ch * 8 + b: (int(val) >> b) & 1 for b in range(8)})
            elif mode == AWORD:
                self._check(slot, 0, 1)
                moved = self._set_bits(slot, {b: (int(val) >> b) & 1 for b in range(16)})
            else:
                raise HwError("неизвестный режим %d" % mode)
            if moved:
                self._sync_hoists()
        self.comm_ts = time.time()
        if moved:
            self._notify()

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
            moved = self._set_bits(slot, {ch: 0 if self.dio[slot][ch] else 1})
            if moved:
                self._sync_hoists()
        self.comm_ts = time.time()
        self._notify()

    # ---- груз на нитке ("лифт") ----
    def _sync_hoists(self):
        """После шага обмоток: пересчитать датчики положения грузов."""
        for h in self.hoists:
            h.update_sensors(self.dio)

    # ---- ADAM-5024 (слот 2, аналоговые выходы) ----
    def write_ao(self, ch, val):
        if not 0 <= ch < 4:
            raise HwError("неверный канал ADAM-5024: %d" % ch)
        self.ao[ch] = val
        v = float(val)
        kind = AO_DEVICES[ch][1]
        if kind == "motor":                      # Analog_Motor_N: скорость +-100
            m = self.motors.get(ch)
            if m is not None:
                m["speed"] = max(-100.0, min(100.0, v))
            # тот же выход приводит в движение груз на нитке (Hoist_1)
            for h in self.hoists:
                if h.kind == "hoist" and h.ao_ch == ch:
                    h.set_speed(v)
        elif kind == "speaker":                  # Speaker: частота тона, Гц
            self.speaker_hz = max(0.0, v)
        elif kind == "cooler":                   # Cool_Extreme: показание A/M
            self.cool_extreme = v
        # нагрев терморезисторов происходит в _tick() по значениям ao[]
        self.comm_ts = time.time()
        self._notify()

    def speaker_tone(self):
        """Текущий тон динамика: (частота Гц, длительность изменения)."""
        return self.speaker_hz

    # ---- ADAM-5017 (слот 3, аналоговые входы) ----
    def read_ai(self, ch):
        if not 0 <= ch < 8:
            raise HwError("неверный канал ADAM-5017: %d" % ch)
        self.comm_ts = time.time()
        return self.ai[ch]

    def set_ai(self, ch, val):
        """Ручная установка аналогового входа (ползунок в окне)."""
        if not 0 <= ch < 8:
            raise HwError("неверный канал ADAM-5017: %d" % ch)
        kind = AI_DEVICES[ch][1]
        if kind == "thermistor":
            for i, t in enumerate(self.thermistors):
                if t.ch == ch:
                    return self.set_thermistor(i, float(val) * 10.0)
        self.sensor_levels[ch] = max(0.0, min(10.0, float(val)))
        self.ai[ch] = round(self.sensor_levels[ch], 3)
        self._notify()

    # ---- грузы на нитках (стенд) ----
    def hoist(self, n):
        """Груз №n (0 или 1)."""
        if not 0 <= n < len(self.hoists):
            raise HwError("нет груза %d (бывает 1 или 2)" % (n + 1))
        return self.hoists[n]

    def set_hoist_position(self, n, mm):
        """Ручная установка высоты груза (ползунок в окне стенда), мм.

        Заодно подтягиваем счётчик шагов Couster_N и позицию каретки
        плоттера, чтобы модель оставалась непротиворечивой."""
        h = self.hoist(n)
        with self.lock:
            h.position = max(0.0, min(h.travel, float(mm)))
            steps = int(round(h.position / STEP_MM))
            if h.couster is not None:
                self.counters[h.couster] = abs(steps)
            if h.coils is not None and self.plotter_attached:
                m = h.coils[0]
                h.axis.phase = None
                h.axis.last_dir = 1
                h.axis.skipped = 0
                self.plotter.axes[m].phase = None
                self.plotter.pos[m] = steps
                self.plotter.hit_limit = False
            h.update_sensors(self.dio)
        self._notify()

    def hoist_place(self, n):
        """Высота груза над нижней точкой, мм."""
        return self.hoist(n).position
