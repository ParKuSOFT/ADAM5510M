# -*- coding: utf-8 -*-
"""Интерпретатор подмножества языка C для эмулятора ADAM-5510M.

Поддерживается: int/short/char/unsigned/float, массивы (одномерные), указатели на
переменные и элементы массивов (&x, &a[i], *p, p[i]), функции с параметрами и
рекурсией, if/else, for, while, do-while, switch, break/continue/return,
все обычные операторы, #define без параметров, printf/puts, математические
функции из math.h (sin, cos, tan, asin, acos, atan, atan2, sqrt, pow, fabs,
exp, log, log10, ceil, floor, sinh, cosh, tanh).
Не поддерживается: struct/union/enum/typedef, goto, многомерные массивы, #define с параметрами.
"""
import math
import re
import time
import queue

from pycparser import c_parser, c_ast
try:                                    # pycparser 3.x
    from pycparser.c_parser import ParseError
except ImportError:                     # pycparser 2.x
    from pycparser.plyparser import ParseError

from .hardware import (HwError, ABIT, ABYTE, AWORD, STAND_CHANNELS,
                       THERMISTORS, segment_value)

MAX_CALL_DEPTH = 64


class CompileError(Exception):
    def __init__(self, errors):
        Exception.__init__(self, "ошибки компиляции")
        self.errors = errors        # [(строка или None, текст)]


class RunError(Exception):
    def __init__(self, msg, line=None):
        Exception.__init__(self, msg)
        self.msg = msg
        self.line = line


class StopRun(Exception):
    pass


class _Break(Exception):
    pass


class _Continue(Exception):
    pass


class _Return(Exception):
    def __init__(self, value):
        Exception.__init__(self)
        self.value = value


# Списки стандартных математических функций (math.h), которые понимает интерпретатор.
_MATH_NAMES = ["sin", "cos", "tan", "asin", "acos", "atan", "sinh", "cosh",
               "tanh", "sqrt", "exp", "log", "log10", "log2", "fabs", "floor",
               "ceil", "trunc"]
_MATH2_NAMES = ["atan2", "pow", "fmod"]

# Объявления этих функций добавляются перед текстом программы при разборе,
# чтобы парсер их распознавал. Номера строк не сдвигаются: столько же пустых
# строк вставляется в начало текста.
_MATH_PROTOTYPES = "\n".join(
    ["double %s(double x);" % n for n in _MATH_NAMES] +
    ["double %s(double x, double y);" % n for n in _MATH2_NAMES])
_MATH_PROTO_LINES = _MATH_PROTOTYPES.count("\n") + 1


# --------------------------------------------------------------------------- #
#  Данные времени выполнения
# --------------------------------------------------------------------------- #
class Ptr(object):
    """Указатель: список-хранилище + индекс."""
    __slots__ = ("lst", "idx", "ct")

    def __init__(self, lst, idx, ct):
        self.lst, self.idx, self.ct = lst, idx, ct


class Var(object):
    __slots__ = ("data", "ct", "arr")

    def __init__(self, data, ct, arr):
        self.data, self.ct, self.arr = data, ct, arr


class Frame(object):
    __slots__ = ("scopes",)

    def __init__(self):
        self.scopes = []


_WRAP = {"int": (32, True), "uint": (32, False), "short": (16, True),
         "ushort": (16, False), "char": (8, True), "uchar": (8, False)}


def coerce(kind, v):
    if kind == "ptr" or kind == "void":
        return v
    if isinstance(v, Ptr):
        raise RunError("нельзя записать указатель в числовую переменную")
    if isinstance(v, str):
        raise RunError("нельзя записать строку в числовую переменную")
    if kind == "float":
        return float(v)
    if isinstance(v, float):
        v = int(v)
    if kind == "int" and -2147483648 <= v <= 2147483647:
        return v
    bits, signed = _WRAP[kind]
    v &= (1 << bits) - 1
    if signed and v >> (bits - 1):
        v -= 1 << bits
    return v


def zero(kind):
    return 0.0 if kind == "float" else 0


def kind_of_names(names):
    s = set(names)
    uns = "unsigned" in s
    if "void" in s:
        return "void"
    if "float" in s or "double" in s:
        return "float"
    if "char" in s:
        return "uchar" if uns else "char"
    if "short" in s:
        return "ushort" if uns else "short"
    return "uint" if uns else "int"


def type_kind(t):
    if isinstance(t, (c_ast.PtrDecl, c_ast.ArrayDecl)):
        return "ptr"
    if isinstance(t, c_ast.TypeDecl):
        if isinstance(t.type, c_ast.IdentifierType):
            return kind_of_names(t.type.names)
        raise RunError("структуры и перечисления не поддерживаются")
    if isinstance(t, c_ast.Typename):
        return type_kind(t.type)
    raise RunError("неподдерживаемый тип")


def truth(v):
    if isinstance(v, Ptr):
        return True
    return v != 0


_ESC = {"n": "\n", "t": "\t", "r": "\r", "0": "\0", "\\": "\\", '"': '"', "'": "'",
        "a": "\a", "b": "\b", "f": "\f", "v": "\v"}


def unescape(s):
    out, i = [], 0
    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s):
            i += 1
            out.append(_ESC.get(s[i], s[i]))
        else:
            out.append(c)
        i += 1
    return "".join(out)


# --------------------------------------------------------------------------- #
#  Препроцессор
# --------------------------------------------------------------------------- #
def strip_comments(src):
    out, i, n = [], 0, len(src)
    while i < n:
        c = src[i]
        if c == '"' or c == "'":
            q = c
            out.append(c)
            i += 1
            while i < n and src[i] != q and src[i] != "\n":
                if src[i] == "\\" and i + 1 < n:
                    out.append(src[i])
                    i += 1
                out.append(src[i])
                i += 1
            if i < n and src[i] == q:
                out.append(q)
                i += 1
        elif src.startswith("//", i):
            while i < n and src[i] != "\n":
                i += 1
        elif src.startswith("/*", i):
            j = src.find("*/", i + 2)
            if j < 0:
                j = n - 2
            out.append("\n" * src.count("\n", i, j + 2))
            i = j + 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


def preprocess(src):
    """Убирает комментарии и директивы, сохраняя номера строк."""
    src = strip_comments(src.replace("\r\n", "\n").replace("\r", "\n"))
    lines = src.split("\n")
    macros, errors = {}, []
    for k, line in enumerate(lines):
        s = line.strip()
        if s.startswith("#"):
            m = re.match(r"#\s*define\s+([A-Za-z_]\w*)(.*)$", s)
            if m:
                rest = m.group(2)
                if rest.startswith("("):
                    errors.append((k + 1, "макросы с параметрами не поддерживаются"))
                else:
                    macros[m.group(1)] = rest.strip()
            lines[k] = ""
    for name, val in macros.items():
        pat = re.compile(r"\b%s\b" % re.escape(name))
        lines = [pat.sub(val, ln) for ln in lines]
    text = "\n".join(lines)
    return text, errors


def read_source(path):
    with open(path, "rb") as f:
        data = f.read()
    for enc in ("utf-8-sig", "cp1251"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            pass
    return data.decode("latin-1")


# --------------------------------------------------------------------------- #
#  Встроенные функции драйвера (5510drv.h) и константы
# --------------------------------------------------------------------------- #
CONSTS = {"ABit": ABIT, "AByte": ABYTE, "AWord": AWORD, "NULL": 0,
          "PI": math.pi, "M_PI": math.pi, "E": math.e, "M_E": math.e}

# Именованные константы каналов стенда: <Имя>_SLOT и <Имя>_CH.
# Пример: Set5050(&v, Hot_SLOT, Hot_CH, ABit);
for (_s, _c), (_nm, _kind, _desc) in STAND_CHANNELS.items():
    CONSTS[_nm + "_SLOT"] = _s
    CONSTS[_nm + "_CH"] = _c
for _i, (_ch, _nm) in enumerate(THERMISTORS):
    CONSTS[_nm + "_AI"] = _ch        # вход ADAM-5017 с терморезистором
    CONSTS[_nm + "_AO"] = _ch        # выход ADAM-5024, нагревающий его
del _i, _ch, _nm, _s, _c, _kind, _desc


def _int(a, what="аргумент"):
    if isinstance(a, (Ptr, str)):
        raise RunError("%s: ожидалось число" % what)
    return int(a)


def _val(a):
    if isinstance(a, Ptr):
        if not 0 <= a.idx < len(a.lst):
            raise RunError("выход за границы массива")
        return a.lst[a.idx]
    return a


def _store(p, v):
    if not isinstance(p, Ptr):
        raise RunError("ожидался указатель (&переменная)")
    if not 0 <= p.idx < len(p.lst):
        raise RunError("выход за границы массива")
    p.lst[p.idx] = coerce(p.ct, v)


def _pystr(a):
    if isinstance(a, str):
        return a
    if isinstance(a, Ptr):
        chars, i = [], a.idx
        while i < len(a.lst) and a.lst[i] != 0:
            chars.append(chr(a.lst[i] & 0xFF))
            i += 1
        return "".join(chars)
    return str(a)


_FMT = re.compile(r"%([-+ 0#]*)(\d+)?(?:\.(\d+))?(?:ll|l|h)?([diuxXcsfFeEgG%])")


def c_format(fmt, args):
    it = iter(args)

    def rep(m):
        flags, width, prec, conv = m.groups()
        if conv == "%":
            return "%"
        try:
            a = next(it)
        except StopIteration:
            raise RunError("printf: не хватает аргументов")
        spec = "%" + flags + (width or "") + ("." + prec if prec else "")
        if conv in "diu":
            return (spec + "d") % int(_val(a))
        if conv in "xX":
            return (spec + conv) % int(_val(a))
        if conv == "c":
            return (spec + "s") % chr(int(_val(a)) & 0xFF)
        if conv == "s":
            return (spec + "s") % _pystr(a)
        return (spec + conv) % float(_val(a))

    return _FMT.sub(rep, fmt)


def b_Set5050(it, a):
    if len(a) != 4:
        raise RunError("Set5050: нужно 4 аргумента (&значение, слот, канал, режим)")
    it.hw.write_dio(_int(a[1], "слот"), _int(a[2], "канал"), _int(_val(a[0])), _int(a[3], "режим"))
    it.spin = 0
    return 0


def b_Get5050(it, a):
    if len(a) != 4:
        raise RunError("Get5050: нужно 4 аргумента (слот, канал, режим, &переменная)")
    _store(a[3], it.hw.read_dio(_int(a[0], "слот"), _int(a[1], "канал"), _int(a[2], "режим")))
    it.poll_wait()
    return 0


def b_Set5024(it, a):
    if len(a) < 2:
        raise RunError("Set5024: нужно (&значение, канал, ...)")
    it.hw.write_ao(_int(a[1], "канал"), _val(a[0]))
    return 0


def b_Get5017(it, a):
    ptrs = [x for x in a if isinstance(x, Ptr)]
    nums = [x for x in a if not isinstance(x, Ptr)]
    if not ptrs or not nums:
        raise RunError("Get5017: нужно (&переменная, канал)")
    _store(ptrs[0], it.hw.read_ai(_int(nums[0], "канал")))
    it.poll_wait()
    return 0


def b_noop(it, a):
    return 0


def b_delay(it, a):
    if len(a) != 1:
        raise RunError("ADAMdelay: нужен 1 аргумент (миллисекунды)")
    it.delay(_int(a[0], "время"))
    return 0


def b_printf(it, a):
    if not a:
        raise RunError("printf: нужна строка формата")
    it.out(c_format(_pystr(a[0]), a[1:]))
    return 0


def b_puts(it, a):
    it.out(_pystr(a[0]) + "\n")
    return 0


def b_putchar(it, a):
    it.out(chr(_int(a[0]) & 0xFF))
    return a[0]


def b_ReadInt(it, a):
    return it.read_int()


def b_abs(it, a):
    return abs(_val(a[0]))


# ---- функции учебного стенда (кнопки, светодиоды, счётчики, индикатор) ----
def _slot_ch(it, a, nargs, fname):
    if len(a) != nargs:
        raise RunError("%s: нужно %d аргумента" % (fname, nargs))
    return _int(a[0], "слот"), _int(a[1], "канал")


def b_GetCounter(it, a):
    """GetCounter(слот, &переменная) - число импульсов на Couster_N."""
    slot = _int(a[0], "слот")
    _store(a[1], it.hw.counter_value(slot))
    it.poll_wait()
    return 0


def b_ResetCounter(it, a):
    it.hw.reset_counter(_int(a[0], "слот"))
    return 0


def b_PulseCounter(it, a):
    """Послать один импульс на счётчик (то же, что кнопка «+1» на стенде)."""
    it.hw.pulse_counter(_int(a[0], "слот"))
    it.spin = 0
    return 0


def b_SetDigit(it, a):
    """SetDigit(n) - показать цифру 0..9 на семисегментном индикаторе."""
    d = _int(_val(a[0]), "цифра")
    if not 0 <= d <= 9:
        raise RunError("SetDigit: цифра должна быть 0..9")
    it.hw.set_seg_digit(d)
    it.spin = 0
    return 0


def b_SetSegments(it, a):
    """SetSegments(маска) - включить сегменты вручную (бит 0 = a ... бит 6 = g)."""
    m = _int(_val(a[0]), "маска") & 0x7F
    for bit, (s, c) in enumerate([(0, 11), (0, 12), (0, 13), (0, 14),
                                  (1, 13), (1, 14), (1, 15)]):
        it.hw.dio[s][c] = (m >> bit) & 1
    it.hw.seg_digit = None
    it.hw._notify()
    it.spin = 0
    return 0


def b_GetSegments(it, a):
    _store(a[0], it.hw.seg_mask())
    it.poll_wait()
    return 0


def b_ClearDisplay(it, a):
    it.hw.set_seg_digit(" ")
    return 0


def b_SetStandby(it, a):
    """SetStandby(0/1) - программно нажать/отпустить кнопку Stand_by."""
    it.hw.set_input(1, 4, _int(_val(a[0]), "состояние"))
    return 0


def b_GetThermistor(it, a):
    """GetThermistor(номер 0/1, &переменная) - напряжение терморезистора, В."""
    n = _int(a[0], "терморезистор")
    if not 0 <= n < len(it.hw.thermistors):
        raise RunError("нет терморезистора %d" % n)
    _store(a[1], it.hw.thermistors[n].volts)
    it.poll_wait()
    return 0


def b_SetThermistor(it, a):
    """SetThermistor(номер 0/1, нагрев %) - задать температуру вручную."""
    n = _int(a[0], "терморезистор")
    if not 0 <= n < len(it.hw.thermistors):
        raise RunError("нет терморезистора %d" % n)
    it.hw.set_thermistor(n, float(_val(a[1])))
    return 0


# ---- математические функции (math.h) ----
def _num(a, name):
    v = _val(a)
    if isinstance(v, str):
        raise RunError("%s: ожидалось число" % name)
    return float(v)


def _make_math(name, nargs):
    fn = getattr(math, name)

    def impl(it, a):
        args = [_num(x, name) for x in a[:nargs]]
        try:
            return float(fn(*args))
        except ValueError:
            raise RunError("%s(%s): значение вне области определения" % (
                name, ", ".join(repr(x) for x in args)))
        except OverflowError:
            raise RunError("%s(%s): переполнение" % (
                name, ", ".join(repr(x) for x in args)))
        except ZeroDivisionError:
            raise RunError("%s(%s): ошибка аргумента" % (
                name, ", ".join(repr(x) for x in args)))
    return impl


BUILTINS = {
    "Set5050": (b_Set5050, 4, 4), "Get5050": (b_Get5050, 4, 4),
    "Set5024": (b_Set5024, 2, 4), "Get5017": (b_Get5017, 2, 3),
    "Init5024": (b_noop, 0, 9), "Init5017": (b_noop, 0, 9), "Init5050": (b_noop, 0, 9),
    "LED_init": (b_noop, 0, 0), "ADAMdelay": (b_delay, 1, 1),
    "printf": (b_printf, 1, 99), "puts": (b_puts, 1, 1), "putchar": (b_putchar, 1, 1),
    "ReadInt": (b_ReadInt, 0, 0), "abs": (b_abs, 1, 1),
    # ---- стенд ----
    "GetCounter": (b_GetCounter, 2, 2), "ResetCounter": (b_ResetCounter, 1, 1),
    "PulseCounter": (b_PulseCounter, 1, 1),
    "SetDigit": (b_SetDigit, 1, 1), "SetSegments": (b_SetSegments, 1, 1),
    "GetSegments": (b_GetSegments, 1, 1), "ClearDisplay": (b_ClearDisplay, 0, 0),
    "SetStandby": (b_SetStandby, 1, 1),
    "GetThermistor": (b_GetThermistor, 2, 2), "SetThermistor": (b_SetThermistor, 2, 2),
}
for _n in _MATH_NAMES:
    BUILTINS[_n] = (_make_math(_n, 1), 1, 1)
for _n in _MATH2_NAMES:
    BUILTINS[_n] = (_make_math(_n, 2), 2, 2)
del _n


# --------------------------------------------------------------------------- #
#  Программа: разбор и проверка
# --------------------------------------------------------------------------- #
class UserFunc(object):
    def __init__(self, node):
        self.node = node
        self.name = node.decl.name
        ft = node.decl.type
        self.ret = type_kind(ft.type)
        self.params = []
        if ft.args is not None:
            for p in ft.args.params:
                if isinstance(p, c_ast.Decl) and p.name:
                    self.params.append((p.name, type_kind(p.type)))
        self.body = node.body


class Program(object):
    def __init__(self, source):
        text, errors = preprocess(source)
        if errors:
            raise CompileError(errors)
        try:
            # в начало добавляем объявления math-функций и столько же пустых строк,
            # чтобы номера строк исходника не сдвинулись
            pad = "\n" * _MATH_PROTO_LINES
            ast = c_parser.CParser().parse(_MATH_PROTOTYPES + pad + text,
                                           filename="<prog>")
        except ParseError as e:
            m = re.search(r":(\d+):(\d+): (.*)", str(e))
            if m:
                raise CompileError([(max(1, int(m.group(1)) - _MATH_PROTO_LINES),
                                     "синтаксическая ошибка: " + m.group(3))])
            raise CompileError([(None, "синтаксическая ошибка: %s" % e)])
        self.funcs, self.protos, self.global_decls = {}, set(), []
        errs = []
        for ext in ast.ext:
            if isinstance(ext, c_ast.Decl) and isinstance(ext.type, c_ast.FuncDecl) \
                    and ext.coord is not None and ext.coord.line <= _MATH_PROTO_LINES:
                continue                        # наши служебные объявления math.h
            if isinstance(ext, c_ast.FuncDef):
                try:
                    self.funcs[ext.decl.name] = UserFunc(ext)
                except RunError as e:
                    errs.append((ext.coord.line, e.msg))
            elif isinstance(ext, c_ast.Decl):
                if isinstance(ext.type, c_ast.FuncDecl):
                    self.protos.add(ext.name)
                else:
                    self.global_decls.append(ext)
            elif isinstance(ext, c_ast.Pragma):
                pass
            else:
                errs.append((ext.coord.line if ext.coord else None,
                             "конструкция не поддерживается: " + ext.__class__.__name__))
        self.global_names = set(d.name for d in self.global_decls)
        for f in list(self.funcs.values()):
            self._check_func(f, errs)
        for d in self.global_decls:
            self._check_global(d, errs)
        if "main" not in self.funcs:
            errs.append((None, "Критическая ошибка - функция main() не найдена"))
        if errs:
            errs.sort(key=lambda e: (e[0] is None, e[0] or 0))
            raise CompileError(errs)

    # ---- проверка имён ----
    def _check_global(self, d, errs):
        try:
            type_kind(d.type)
        except RunError as e:
            errs.append((d.coord.line, e.msg))
        if d.init is not None:
            self._chk(d.init, [set()], errs)

    def _check_func(self, f, errs):
        scopes = [set(n for n, _ in f.params)]
        self._chk(f.body, scopes, errs)

    def _known(self, name, scopes):
        for s in scopes:
            if name in s:
                return True
        return name in self.global_names or name in CONSTS

    def _chk(self, n, scopes, errs):
        t = n.__class__
        line = n.coord.line if n.coord else None
        if t is c_ast.Compound:
            scopes.append(set())
            for it in (n.block_items or []):
                self._chk(it, scopes, errs)
            scopes.pop()
        elif t is c_ast.For:
            scopes.append(set())
            for part in (n.init, n.cond, n.next, n.stmt):
                if part is not None:
                    self._chk(part, scopes, errs)
            scopes.pop()
        elif t is c_ast.DeclList:
            for d in n.decls:
                self._chk(d, scopes, errs)
        elif t is c_ast.Decl:
            if isinstance(n.type, c_ast.FuncDecl):
                return
            try:
                type_kind(n.type)
            except RunError as e:
                errs.append((line, e.msg))
            if isinstance(n.type, c_ast.ArrayDecl) and n.type.dim is not None:
                self._chk(n.type.dim, scopes, errs)
            scopes[-1].add(n.name)
            if n.init is not None:
                self._chk(n.init, scopes, errs)
        elif t is c_ast.ID:
            if not self._known(n.name, scopes):
                errs.append((line, "неизвестная переменная '%s'" % n.name))
        elif t is c_ast.FuncCall:
            if isinstance(n.name, c_ast.ID):
                name = n.name.name
                args = n.args.exprs if n.args else []
                if name in self.funcs:
                    if len(args) != len(self.funcs[name].params):
                        errs.append((line, "неверное число аргументов в вызове '%s'" % name))
                elif name in BUILTINS:
                    lo, hi = BUILTINS[name][1], BUILTINS[name][2]
                    if not lo <= len(args) <= hi:
                        errs.append((line, "неверное число аргументов в вызове '%s'" % name))
                elif name in self.protos:
                    errs.append((line, "функция '%s' объявлена, но не определена" % name))
                else:
                    errs.append((line, "неизвестная функция '%s'" % name))
                for a in args:
                    self._chk(a, scopes, errs)
            else:
                errs.append((line, "вызов через указатель не поддерживается"))
        elif t in (c_ast.StructRef, c_ast.Struct, c_ast.Union, c_ast.Enum, c_ast.Typedef,
                   c_ast.Goto, c_ast.Label):
            errs.append((line, "конструкция не поддерживается: " + t.__name__))
        elif t in (c_ast.Constant, c_ast.Typename, c_ast.IdentifierType, c_ast.TypeDecl):
            return
        else:
            for _, c in n.children():
                self._chk(c, scopes, errs)


# --------------------------------------------------------------------------- #
#  Исполнение
# --------------------------------------------------------------------------- #
class Interpreter(object):
    def __init__(self, program, hw, out, speed=0.0):
        self.prog = program
        self.hw = hw
        self.out = out              # функция вывода в консоль (str)
        self.speed = speed          # 0 = без задержек, иначе во сколько раз быстрее реального
        self.stop = False
        self.line = 0
        self.depth = 0
        self.spin = 0
        self.pending = 0.0
        self.input = queue.Queue()
        self.globals = {}
        self._cc = {}
        self._ev = {
            c_ast.ID: self.ev_ID, c_ast.Constant: self.ev_Constant,
            c_ast.BinaryOp: self.ev_BinaryOp, c_ast.UnaryOp: self.ev_UnaryOp,
            c_ast.Assignment: self.ev_Assignment, c_ast.FuncCall: self.ev_FuncCall,
            c_ast.ArrayRef: self.ev_ArrayRef, c_ast.TernaryOp: self.ev_TernaryOp,
            c_ast.Cast: self.ev_Cast, c_ast.ExprList: self.ev_ExprList,
        }
        self._ex = {
            c_ast.Compound: self.ex_Compound, c_ast.Decl: self.ex_Decl,
            c_ast.DeclList: self.ex_DeclList, c_ast.If: self.ex_If, c_ast.For: self.ex_For,
            c_ast.While: self.ex_While, c_ast.DoWhile: self.ex_DoWhile,
            c_ast.Return: self.ex_Return, c_ast.Break: self.ex_Break,
            c_ast.Continue: self.ex_Continue, c_ast.EmptyStatement: self.ex_Empty,
            c_ast.Switch: self.ex_Switch,
        }

    # ---- сервис ----
    def tick(self):
        if self.stop:
            raise StopRun()

    def poll_wait(self):
        """Чтобы цикл ожидания кнопки не грузил процессор на 100%."""
        self.spin += 1
        if self.spin > 20:
            self.spin = 0
            time.sleep(0.005)
        self.tick()

    def delay(self, ms):
        self.tick()
        if self.speed > 0:
            self.pending += ms / 1000.0 / self.speed
            if self.pending >= 0.02:
                end = time.time() + self.pending
                self.pending = 0.0
                while True:
                    rem = end - time.time()
                    if rem <= 0:
                        break
                    if self.stop:
                        raise StopRun()
                    time.sleep(min(rem, 0.02))

    def read_int(self):
        while True:
            self.tick()
            try:
                return int(self.input.get(timeout=0.05))
            except queue.Empty:
                pass
            except ValueError:
                pass

    def feed_input(self, text):
        for tok in text.split():
            self.input.put(tok)

    def run(self):
        fr = Frame()
        try:
            for d in self.prog.global_decls:
                self.globals[d.name] = self.make_var(d, fr)
            self.call(self.prog.funcs["main"], [])
        except RunError as e:
            if e.line is None:
                e.line = self.line
            raise

    # ---- переменные ----
    def make_var(self, d, fr):
        t = d.type
        init = d.init
        if isinstance(t, c_ast.ArrayDecl):
            kind = type_kind(t.type)
            size = int(self.ev(t.dim, fr)) if t.dim is not None else None
            if isinstance(init, c_ast.InitList):
                vals = [coerce(kind, self.ev(e, fr)) for e in init.exprs]
            elif isinstance(init, c_ast.Constant) and init.type == "string":
                vals = [ord(c) & 0xFF for c in unescape(init.value[1:-1])] + [0]
            elif init is None:
                vals = []
            else:
                raise RunError("неверный инициализатор массива '%s'" % d.name)
            if size is None:
                if not vals:
                    raise RunError("не указан размер массива '%s'" % d.name)
                size = len(vals)
            if len(vals) > size:
                raise RunError("слишком много значений для массива '%s'" % d.name)
            return Var(vals + [zero(kind)] * (size - len(vals)), kind, True)
        kind = type_kind(t)
        v = zero(kind) if kind != "ptr" else 0
        if init is not None:
            v = coerce(kind, self.ev(init, fr))
        return Var([v], kind, False)

    def find(self, fr, name):
        sc = fr.scopes
        for i in range(len(sc) - 1, -1, -1):
            v = sc[i].get(name)
            if v is not None:
                return v
        return self.globals.get(name)

    # ---- вызов функции ----
    def call(self, f, args):
        if len(args) != len(f.params):
            raise RunError("неверное число аргументов в вызове '%s'" % f.name)
        if self.depth >= MAX_CALL_DEPTH:
            raise RunError("переполнение стека (слишком глубокая рекурсия)")
        nf = Frame()
        sc = {}
        for (pn, kind), a in zip(f.params, args):
            sc[pn] = Var([coerce(kind, a)], kind, False)
        nf.scopes.append(sc)
        self.depth += 1
        ret = 0
        try:
            try:
                self.ex(f.body, nf)
            except _Return as r:
                ret = r.value
        finally:
            self.depth -= 1
        if f.ret not in ("void", "ptr"):
            ret = coerce(f.ret, ret)
        return ret

    # ---- вычисление выражений ----
    def ev(self, n, fr):
        f = self._ev.get(n.__class__)
        if f is None:
            raise RunError("выражение не поддерживается: " + n.__class__.__name__)
        return f(n, fr)

    def ev_ID(self, n, fr):
        v = self.find(fr, n.name)
        if v is None:
            if n.name in CONSTS:
                return CONSTS[n.name]
            raise RunError("неизвестная переменная '%s'" % n.name)
        if v.arr:
            return Ptr(v.data, 0, v.ct)
        return v.data[0]

    def ev_Constant(self, n, fr):
        c = self._cc.get(n)
        if c is not None:
            return c
        t, s = n.type, n.value
        if t == "string":
            c = unescape(s[1:-1])
        elif t == "char":
            c = ord(unescape(s[1:-1])[0]) if len(s) > 2 else 0
        elif "float" in t or "double" in t:
            c = float(s.rstrip("fFlL"))
        else:
            s = s.rstrip("uUlL")
            if s.lower().startswith("0x"):
                c = int(s, 16)
            elif len(s) > 1 and s.startswith("0"):
                c = int(s, 8)
            else:
                c = int(s)
        self._cc[n] = c
        return c

    def ev_ExprList(self, n, fr):
        v = 0
        for e in n.exprs:
            v = self.ev(e, fr)
        return v

    def ev_TernaryOp(self, n, fr):
        return self.ev(n.iftrue if truth(self.ev(n.cond, fr)) else n.iffalse, fr)

    def ev_Cast(self, n, fr):
        v = self.ev(n.expr, fr)
        kind = type_kind(n.to_type)
        if kind == "ptr" or kind == "void":
            return v
        return coerce(kind, v)

    def ev_FuncCall(self, n, fr):
        name = n.name.name
        args = [self.ev(a, fr) for a in n.args.exprs] if n.args else []
        f = self.prog.funcs.get(name)
        if f is not None:
            return self.call(f, args)
        b = BUILTINS.get(name)
        if b is None:
            raise RunError("неизвестная функция '%s'" % name)
        try:
            return b[0](self, args)
        except HwError as e:
            raise RunError("%s: %s" % (name, e))

    def lval(self, n, fr):
        t = n.__class__
        if t is c_ast.ID:
            v = self.find(fr, n.name)
            if v is None:
                raise RunError("неизвестная переменная '%s'" % n.name)
            if v.arr:
                raise RunError("нельзя присвоить значение массиву '%s'" % n.name)
            return v.data, 0, v.ct
        if t is c_ast.ArrayRef:
            base = self.ev(n.name, fr)
            i = self.ev(n.subscript, fr)
            if not isinstance(base, Ptr) or isinstance(i, (Ptr, str)):
                raise RunError("индексация не массива")
            k = base.idx + int(i)
            if not 0 <= k < len(base.lst):
                raise RunError("выход за границы массива (индекс %d)" % int(i))
            return base.lst, k, base.ct
        if t is c_ast.UnaryOp and n.op == "*":
            p = self.ev(n.expr, fr)
            if not isinstance(p, Ptr):
                raise RunError("разыменование не указателя")
            if not 0 <= p.idx < len(p.lst):
                raise RunError("выход за границы массива")
            return p.lst, p.idx, p.ct
        raise RunError("недопустимое выражение слева от присваивания")

    def ev_ArrayRef(self, n, fr):
        lst, k, _ = self.lval(n, fr)
        return lst[k]

    def ev_Assignment(self, n, fr):
        lst, k, kind = self.lval(n.lvalue, fr)
        v = self.ev(n.rvalue, fr)
        if n.op != "=":
            v = self.binop(n.op[:-1], lst[k], v)
        v = coerce(kind, v)
        lst[k] = v
        return v

    def ev_UnaryOp(self, n, fr):
        op = n.op
        if op == "&":
            e = n.expr
            if e.__class__ is c_ast.ID:
                v = self.find(fr, e.name)
                if v is None:
                    raise RunError("неизвестная переменная '%s'" % e.name)
                return Ptr(v.data, 0, v.ct)
            lst, k, kind = self.lval(e, fr)
            return Ptr(lst, k, kind)
        if op == "*":
            lst, k, _ = self.lval(n, fr)
            return lst[k]
        if op in ("p++", "p--", "++", "--"):
            lst, k, kind = self.lval(n.expr, fr)
            old = lst[k]
            d = 1 if "+" in op else -1
            new = Ptr(old.lst, old.idx + d, old.ct) if isinstance(old, Ptr) else coerce(kind, old + d)
            lst[k] = new
            return old if op[0] == "p" else new
        if op == "sizeof":
            e = n.expr
            if isinstance(e, c_ast.Typename):
                kind = type_kind(e)
                return {"char": 1, "uchar": 1, "short": 2, "ushort": 2}.get(kind, 4)
            if isinstance(e, c_ast.ID):
                v = self.find(fr, e.name)
                if v is not None:
                    sz = {"char": 1, "uchar": 1, "short": 2, "ushort": 2}.get(v.ct, 4)
                    return sz * (len(v.data) if v.arr else 1)
            return 4
        v = self.ev(n.expr, fr)
        if isinstance(v, (Ptr, str)):
            if op == "!":
                return 0
            raise RunError("операция '%s' неприменима к указателю" % op)
        if op == "-":
            return -v
        if op == "+":
            return v
        if op == "!":
            return 0 if v else 1
        if op == "~":
            return ~int(v)
        raise RunError("неподдерживаемая операция '%s'" % op)

    def ev_BinaryOp(self, n, fr):
        op = n.op
        if op == "&&":
            return 1 if truth(self.ev(n.left, fr)) and truth(self.ev(n.right, fr)) else 0
        if op == "||":
            return 1 if truth(self.ev(n.left, fr)) or truth(self.ev(n.right, fr)) else 0
        return self.binop(op, self.ev(n.left, fr), self.ev(n.right, fr))

    def binop(self, op, a, b):
        if isinstance(a, Ptr) or isinstance(b, Ptr):
            return self.ptr_binop(op, a, b)
        if isinstance(a, str) or isinstance(b, str):
            raise RunError("операции со строками не поддерживаются")
        if op == "+":
            return a + b
        if op == "-":
            return a - b
        if op == "<":
            return 1 if a < b else 0
        if op == "==":
            return 1 if a == b else 0
        if op == "*":
            return a * b
        if op == ">":
            return 1 if a > b else 0
        if op == "<=":
            return 1 if a <= b else 0
        if op == ">=":
            return 1 if a >= b else 0
        if op == "!=":
            return 1 if a != b else 0
        if op == "/":
            if b == 0:
                raise RunError("деление на ноль")
            if isinstance(a, int) and isinstance(b, int):
                q = abs(a) // abs(b)
                return -q if (a < 0) != (b < 0) else q
            return a / b
        if op == "%":
            if b == 0:
                raise RunError("деление на ноль")
            r = abs(int(a)) % abs(int(b))
            return -r if a < 0 else r
        a2, b2 = int(a), int(b)
        if op == "&":
            return a2 & b2
        if op == "|":
            return a2 | b2
        if op == "^":
            return a2 ^ b2
        if op == "<<":
            return a2 << b2
        if op == ">>":
            return a2 >> b2
        raise RunError("неподдерживаемая операция '%s'" % op)

    def ptr_binop(self, op, a, b):
        if op == "+" and isinstance(a, Ptr) and not isinstance(b, Ptr):
            return Ptr(a.lst, a.idx + int(b), a.ct)
        if op == "+" and isinstance(b, Ptr) and not isinstance(a, Ptr):
            return Ptr(b.lst, b.idx + int(a), b.ct)
        if op == "-" and isinstance(a, Ptr):
            if isinstance(b, Ptr):
                return a.idx - b.idx
            return Ptr(a.lst, a.idx - int(b), a.ct)
        if op in ("==", "!="):
            same = (isinstance(a, Ptr) and isinstance(b, Ptr) and a.lst is b.lst and a.idx == b.idx)
            return 1 if same == (op == "==") else 0
        raise RunError("недопустимая операция '%s' с указателем" % op)

    # ---- операторы ----
    def ex(self, n, fr):
        c = n.coord
        if c is not None:
            self.line = c.line
        f = self._ex.get(n.__class__)
        if f is not None:
            f(n, fr)
            return
        f = self._ev.get(n.__class__)
        if f is None:
            raise RunError("конструкция не поддерживается: " + n.__class__.__name__)
        f(n, fr)

    def ex_Compound(self, n, fr):
        items = n.block_items
        if not items:
            return
        fr.scopes.append({})
        try:
            for it in items:
                self.ex(it, fr)
        finally:
            fr.scopes.pop()

    def ex_Decl(self, n, fr):
        if isinstance(n.type, c_ast.FuncDecl):
            return
        fr.scopes[-1][n.name] = self.make_var(n, fr)

    def ex_DeclList(self, n, fr):
        for d in n.decls:
            self.ex_Decl(d, fr)

    def ex_Empty(self, n, fr):
        pass

    def ex_If(self, n, fr):
        if truth(self.ev(n.cond, fr)):
            self.ex(n.iftrue, fr)
        elif n.iffalse is not None:
            self.ex(n.iffalse, fr)

    def ex_For(self, n, fr):
        fr.scopes.append({})
        try:
            if n.init is not None:
                self.ex(n.init, fr)
            while True:
                if n.cond is not None and not truth(self.ev(n.cond, fr)):
                    break
                try:
                    self.ex(n.stmt, fr)
                except _Break:
                    break
                except _Continue:
                    pass
                if n.next is not None:
                    self.ev(n.next, fr)
                if self.stop:
                    raise StopRun()
        finally:
            fr.scopes.pop()

    def ex_While(self, n, fr):
        while truth(self.ev(n.cond, fr)):
            try:
                self.ex(n.stmt, fr)
            except _Break:
                break
            except _Continue:
                pass
            if self.stop:
                raise StopRun()

    def ex_DoWhile(self, n, fr):
        while True:
            try:
                self.ex(n.stmt, fr)
            except _Break:
                break
            except _Continue:
                pass
            if self.stop:
                raise StopRun()
            if not truth(self.ev(n.cond, fr)):
                break

    def ex_Return(self, n, fr):
        raise _Return(self.ev(n.expr, fr) if n.expr is not None else 0)

    def ex_Break(self, n, fr):
        raise _Break()

    def ex_Continue(self, n, fr):
        raise _Continue()

    def ex_Switch(self, n, fr):
        val = self.ev(n.cond, fr)
        items = n.stmt.block_items or [] if isinstance(n.stmt, c_ast.Compound) else [n.stmt]
        start = None
        for i, it in enumerate(items):
            if isinstance(it, c_ast.Case) and self.ev(it.expr, fr) == val:
                start = i
                break
        if start is None:
            for i, it in enumerate(items):
                if isinstance(it, c_ast.Default):
                    start = i
                    break
        if start is None:
            return
        fr.scopes.append({})
        try:
            for it in items[start:]:
                if isinstance(it, (c_ast.Case, c_ast.Default)):
                    for s in it.stmts:
                        self.ex(s, fr)
                else:
                    self.ex(it, fr)
        except _Break:
            pass
        finally:
            fr.scopes.pop()
