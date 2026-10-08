# -*- coding: utf-8 -*-
"""Запуск эмулятора ADAM-5510M.

  python main.py                    - окно эмулятора
  python main.py программа.c        - окно + сразу загрузить файл
  python main.py программа.c --headless [--svg out.svg]
                                    - без окна: выполнить программу и вывести результат
"""
import argparse
import sys
import threading


def run_headless(path, svg, speed, field):
    from adam5510.hardware import Hardware
    from adam5510.cinterp import (Program, Interpreter, CompileError, RunError, StopRun,
                                  read_source)
    hw = Hardware()
    hw.plotter.set_field(*field)
    hw.dio[1][4] = 1                       # "нажата" кнопка Stand_By
    try:
        prog = Program(read_source(path))
    except CompileError as e:
        for line, msg in e.errors:
            print(("Строка %d: %s" % (line, msg)) if line else msg)
        return 1
    it = Interpreter(prog, hw, lambda s: sys.stdout.write(s), speed)
    try:
        it.run()
        print("Программа завершена.")
    except RunError as e:
        print("Runtime-ошибка (строка %s): %s" % (e.line, e.msg))
        return 2
    except StopRun:
        print("Остановлено.")
    pl = hw.plotter
    print("Позиция: X=%.2f мм, Y=%.2f мм; отрезков: %d; перескоков через фазу: %d%s" % (
        pl.pos[0] / pl.spm, pl.pos[1] / pl.spm, len(pl.segments), pl.skipped,
        "; УПОР" if pl.hit_limit else ""))
    if svg:
        from adam5510.svg import write_svg
        write_svg(svg, pl)
        print("SVG сохранён:", svg)
    return 0


def main():
    ap = argparse.ArgumentParser(description="Эмулятор ADAM-5510M")
    ap.add_argument("program", nargs="?", help="файл с программой на C")
    ap.add_argument("--headless", action="store_true", help="выполнить без окна")
    ap.add_argument("--svg", help="(с --headless) сохранить рисунок в SVG")
    ap.add_argument("--speed", type=float, default=0.0, help="(с --headless) 0 = без задержек")
    ap.add_argument("--field", default="600x400", help="размер поля плоттера, мм (по умолчанию 600x400)")
    args = ap.parse_args()
    try:
        w, h = [float(x) for x in args.field.lower().split("x")]
    except ValueError:
        ap.error("--field нужно в виде 600x400")

    if args.headless:
        if not args.program:
            ap.error("для --headless нужен файл программы")
        sys.exit(run_headless(args.program, args.svg, args.speed, (w, h)))

    sys.setrecursionlimit(20000)
    try:
        threading.stack_size(64 * 1024 * 1024)
    except (ValueError, RuntimeError):
        pass
    from adam5510.gui import run_gui
    run_gui(args.program, (w, h))


if __name__ == "__main__":
    main()
