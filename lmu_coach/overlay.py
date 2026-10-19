"""Overlay en pantalla (tkinter): siempre encima, sin bordes, arrastrable."""
import time
import tkinter as tk

from .coach import BrakeCue, Feedback
from .laps import fmt_time

BG = "#101114"
FG = "#e8e8ea"
MUTED = "#8a8d96"
GREEN = "#2ecc71"
RED = "#ff4d4d"
AMBER = "#ffb020"
BLUE = "#4da3ff"
TRACK = "#2a2c33"
PURPLE_FG = "#c39bff"
# color de fondo y de texto de cada sector (claves de coach.SectorResult.color)
SECTOR_BG = {
    "purple": ("#8e44ff", "#ffffff"),
    "green": ("#1fa85a", "#ffffff"),
    "yellow": ("#e0b000", "#1a1a1a"),
    "grey": ("#4a4d55", "#d0d0d4"),
}

W, H = 300, 172
TEMPS_H = 30          # franja de temperaturas debajo (se puede ocultar)
TEMP_COL = {"ok": GREEN, "warm": AMBER, "hot": RED, "cold": BLUE, None: "#3a3d46"}
PAD = 8
SECTORS_Y = 50
BODY_Y = 86
FEEDBACK_Y = 134


class Overlay:
    def __init__(self, cfg: dict, on_close, on_voice=None, voice_menu=None, on_temps=None, on_engineer=None,
                 on_spotter=None):
        self.cfg = cfg
        self.on_close = on_close
        self.on_voice = on_voice
        self.on_temps = on_temps
        self.on_engineer = on_engineer
        self.on_spotter = on_spotter
        self.show_temps = bool(cfg.get("temps", True))
        self.namer = lambda z: f"F{z.idx}"   # nombre de cada frenada (lo pone el coach)
        self.focus = lambda z: None          # objetivo del plan de entrenamiento para esa frenada
        self.voice_menu = voice_menu    # (opciones(), elegir_voz(nombre), elegir_velocidad(v))
        self.root = tk.Tk()
        self.root.title("LMU Coach")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", cfg.get("opacity", 0.88))
        x, y = cfg.get("x", 60), cfg.get("y", 60)
        h = H + (TEMPS_H if self.show_temps else 0)
        self.root.geometry(f"{W}x{h}+{x}+{y}")
        self.root.configure(bg=BG)
        self.c = tk.Canvas(self.root, width=W, height=h, bg=BG, highlightthickness=0)
        self.c.pack()
        self._drag = None
        self.c.bind("<ButtonPress-1>", self._start_drag)
        self.c.bind("<B1-Motion>", self._do_drag)
        self.c.bind("<ButtonRelease-1>", self._end_drag)
        self.c.bind("<Button-3>", self._menu)
        self.root.bind("<Escape>", lambda e: self.on_close())
        self._toast = None  # (texto, color, hasta)

    # --- ventana ---------------------------------------------------------

    def _start_drag(self, e):
        self._drag = (e.x, e.y)

    def _do_drag(self, e):
        if self._drag:
            x = self.root.winfo_x() + e.x - self._drag[0]
            y = self.root.winfo_y() + e.y - self._drag[1]
            self.root.geometry(f"+{x}+{y}")

    def _end_drag(self, e):
        self._drag = None
        self.cfg["x"], self.cfg["y"] = self.root.winfo_x(), self.root.winfo_y()

    def _menu(self, e):
        m = tk.Menu(self.root, tearoff=0)
        if self.on_voice:
            voice = tk.BooleanVar(value=bool(self.cfg.get("voice", True)))
            m.add_checkbutton(label="Avisos por voz", variable=voice,
                              command=lambda: self.on_voice(voice.get()))
            if self.voice_menu:
                choices, pick_voice, pick_rate = self.voice_menu
                voices, current, rates, rate = choices()
                vm = tk.Menu(m, tearoff=0)
                self._voice_var = tk.StringVar(value=current or "")
                for name in voices:
                    vm.add_radiobutton(label=name, value=name, variable=self._voice_var,
                                       command=lambda n=name: pick_voice(n))
                if not voices:
                    vm.add_command(label="(buscando voces…)", state="disabled")
                m.add_cascade(label="Voz", menu=vm)
                rm = tk.Menu(m, tearoff=0)
                self._rate_var = tk.DoubleVar(value=rate)
                for label, r in rates:
                    rm.add_radiobutton(label=label, value=r, variable=self._rate_var,
                                       command=lambda r=r: pick_rate(r))
                m.add_cascade(label="Velocidad de la voz", menu=rm)
            m.add_separator()
        if self.on_engineer:
            eng = tk.BooleanVar(value=bool(self.cfg.get("engineer", True)))
            m.add_checkbutton(label="Ingeniero de carrera", variable=eng,
                              command=lambda: self.on_engineer(eng.get()))
        if self.on_spotter:
            spot = tk.BooleanVar(value=bool(self.cfg.get("spotter", True)))
            m.add_checkbutton(label="Spotter (coches a los lados)", variable=spot,
                              command=lambda: self.on_spotter(spot.get()))
        if self.on_temps:
            temps = tk.BooleanVar(value=self.show_temps)
            m.add_checkbutton(label="Temperaturas de gomas y frenos", variable=temps,
                              command=lambda: self.on_temps(temps.get()))
            m.add_separator()
        m.add_command(label="Salir", command=self.on_close)
        m.tk_popup(e.x_root, e.y_root)

    def move_to(self, x: int, y: int):
        self.root.geometry(f"+{int(x)}+{int(y)}")
        self.cfg["x"], self.cfg["y"] = int(x), int(y)

    def set_temps(self, on: bool):
        self.show_temps = on
        h = H + (TEMPS_H if on else 0)
        self.c.configure(height=h)
        self.root.geometry(f"{W}x{h}")

    def toast(self, text, color=FG, seconds=4.0):
        self._toast = (text, color, time.monotonic() + seconds)

    # --- dibujo ----------------------------------------------------------

    def draw(self, st: dict):
        c = self.c
        c.delete("all")
        if st.get("status"):
            c.create_text(W / 2, H / 2 - 8, text=st["status"], fill=MUTED, font=("Segoe UI", 11))
            if st.get("substatus"):
                c.create_text(W / 2, H / 2 + 12, text=st["substatus"], fill=MUTED, font=("Segoe UI", 8),
                              width=W - 2 * PAD, justify="center")
            self._draw_toast()
            return

        sec = st.get("sectors") or {}
        flash = st.get("lap_flash")
        if flash:
            self._lap_flash(flash)
        else:
            self._header(st, sec)
            self._delta(st)
        self._sectors(sec, flash, y0=SECTORS_Y)

        # Pedales: tú (relleno) vs referencia (línea)
        self._pedal(PAD, BODY_Y, st["thr"], st.get("ref_thr"), GREEN)
        self._pedal(PAD + 14, BODY_Y, st["brk"], st.get("ref_brk"), RED)

        # Aviso de frenada
        self._brake_cue(st.get("cue"), x0=PAD + 32, y0=BODY_Y)

        # Feedback de la última curva
        self._feedback(st.get("feedback"))
        if self.show_temps:
            self._temps(st.get("temps"), st.get("damage"))
        self._spot(st.get("spot"))
        self._draw_toast()

    def _header(self, st, sec):
        c = self.c
        race = st.get("race")
        if race:
            # en carrera: posición en tu clase y diferencias (▲ delante, ▼ detrás)
            parts = [f"P{race['pos']}/{race['of']}"]
            if race.get("ahead") is not None:
                parts.append(f"▲{race['ahead']:.1f}")
            if race.get("behind") is not None:
                parts.append(f"▼{race['behind']:.1f}")
            close = race.get("behind") is not None and race["behind"] < 1.0
            c.create_text(W - PAD, 6, anchor="ne", fill=AMBER if close else FG, font=("Segoe UI Semibold", 8),
                          text="  ".join(parts) + f"  ·  V{st['lap']}")
        else:
            ref = f"V{st['lap']}  ·  Ref {fmt_time(st['ref_time'])}" if st["ref_time"] else f"V{st['lap']}  ·  sin ref"
            c.create_text(W - PAD, 6, anchor="ne", fill=MUTED, font=("Segoe UI", 8), text=ref)
        fuel = st.get("fuel") or {}
        parts = []
        for key, icon in (("fuel_laps", "⛽"), ("ve_laps", "⚡")):
            if fuel.get(key) is not None:
                parts.append((f"{icon} {fuel[key]:.1f} v", fuel[key]))
        if st.get("lap_invalid"):
            c.create_text(W - PAD, 22, anchor="ne", fill=RED, font=("Segoe UI Semibold", 8), text="INVALIDADA")
        elif parts:
            low = min(v for _, v in parts)
            col = RED if low < 1.5 else AMBER if low < 3 else FG
            c.create_text(W - PAD, 22, anchor="ne", fill=col, font=("Segoe UI Semibold", 8),
                          text="   ".join(p for p, _ in parts))
        elif sec.get("ideal"):
            c.create_text(W - PAD, 22, anchor="ne", fill=PURPLE_FG, font=("Segoe UI", 8),
                          text=f"Ideal {fmt_time(sec['ideal'])}")
        else:
            c.create_text(W - PAD, 22, anchor="ne", fill=MUTED, font=("Segoe UI", 8),
                          text=f"{st['speed']:.0f} km/h · M{st['gear']}")

    def _delta(self, st):
        c = self.c
        delta = st.get("delta")
        if delta is None:
            c.create_text(PAD, 22, anchor="w", text="Haz una vuelta limpia\npara crear la referencia",
                          fill=FG, font=("Segoe UI", 9))
            return
        col = GREEN if delta < 0 else RED
        c.create_text(PAD, 22, anchor="w", text=f"{delta:+.3f}", fill=col, font=("Segoe UI Semibold", 22))
        trend = st.get("trend", 0.0)
        if abs(trend) > 0.02:
            c.create_text(118, 24, anchor="w", text="▼" if trend < 0 else "▲",
                          fill=GREEN if trend < 0 else RED, font=("Segoe UI", 10))
        # Barra de delta (±1 s)
        cx, y0, half = W / 2, 42, W / 2 - PAD
        c.create_rectangle(PAD, y0, W - PAD, y0 + 4, fill=TRACK, width=0)
        frac = max(-1.0, min(1.0, delta / 1.0))
        c.create_rectangle(cx, y0, cx + frac * half, y0 + 4, fill=col, width=0)
        c.create_line(cx, y0 - 2, cx, y0 + 6, fill=FG)

    def _lap_flash(self, f):
        """Tiempo de la vuelta recién terminada, en grande."""
        c = self.c
        if not f["valid"]:
            bg, fg, tag = "#2a2c33", MUTED, f"NO VÁLIDA · {f['reason']}"
        elif f["best"]:
            bg, fg, tag = "#3a1f66", "#ffffff", "¡NUEVA MEJOR VUELTA!"
        else:
            bg, fg, tag = "#1c1e24", FG, "VUELTA"
        c.create_rectangle(0, 0, W, 46, fill=bg, width=0)
        c.create_text(PAD, 5, anchor="nw", text=tag, fill=AMBER if f["best"] else MUTED,
                      font=("Segoe UI Semibold", 7))
        c.create_text(PAD, 29, anchor="w", text=fmt_time(f["time"]), fill=fg, font=("Segoe UI Black", 20))
        if f["diff"] is not None:
            col = GREEN if f["diff"] < 0 else RED
            c.create_text(W - PAD, 27, anchor="e", text=f"{f['diff']:+.3f}", fill=col if f["valid"] else MUTED,
                          font=("Segoe UI Semibold", 14))

    def _sectors(self, sec, flash, y0, h=30):
        """Tres cajas S1/S2/S3 al estilo F1."""
        c = self.c
        if not sec.get("has"):
            c.create_text(W / 2, y0 + h / 2, text="Sectores tras una vuelta completa",
                          fill=MUTED, font=("Segoe UI", 8))
            return
        cur = flash["sectors"] if flash else sec["cur"]
        idx = 3 if flash else sec["idx"]
        gap = 4
        w = (W - 2 * PAD - 2 * gap) / 3
        for i in range(3):
            x = PAD + i * (w + gap)
            r = cur[i]
            label = f"S{i + 1}"
            if r is not None:
                bg, fg = SECTOR_BG[r.color]
                c.create_rectangle(x, y0, x + w, y0 + h, fill=bg, width=0)
                c.create_text(x + 4, y0 + 2, anchor="nw", text=label, fill=fg, font=("Segoe UI Semibold", 6))
                c.create_text(x + w / 2 + 4, y0 + 11, text=f"{r.time:.3f}", fill=fg, font=("Segoe UI Semibold", 10))
                if r.diff is not None:
                    c.create_text(x + w / 2 + 4, y0 + 23, text=f"{r.diff:+.3f}", fill=fg, font=("Segoe UI", 7))
            elif i == idx:
                # sector en curso: delta en directo
                live = sec.get("live")
                c.create_rectangle(x, y0, x + w, y0 + h, fill="#1c1e24", outline=BLUE, width=1)
                c.create_text(x + 4, y0 + 2, anchor="nw", text=label, fill=BLUE, font=("Segoe UI Semibold", 6))
                if live is not None:
                    c.create_text(x + w / 2 + 4, y0 + h / 2, text=f"{live:+.2f}", fill=GREEN if live < 0 else RED,
                                  font=("Segoe UI Semibold", 10))
            else:
                # sector por llegar: el de la vuelta anterior, apagado
                p = sec["prev"][i] if sec.get("prev") else None
                c.create_rectangle(x, y0, x + w, y0 + h, fill="#16171b", outline=TRACK, width=1)
                c.create_text(x + 4, y0 + 2, anchor="nw", text=label, fill=MUTED, font=("Segoe UI Semibold", 6))
                if p is not None:
                    c.create_text(x + w / 2 + 4, y0 + h / 2, text=f"{p.time:.3f}",
                                  fill=SECTOR_BG[p.color][0], font=("Segoe UI", 9))

    def _pedal(self, x, y, val, ref, color, h=42, w=10):
        c = self.c
        c.create_rectangle(x, y, x + w, y + h, fill=TRACK, width=0)
        fill = max(0.0, min(1.0, val))
        c.create_rectangle(x, y + h * (1 - fill), x + w, y + h, fill=color, width=0)
        if ref is not None:
            ry = y + h * (1 - max(0.0, min(1.0, ref)))
            c.create_line(x - 2, ry, x + w + 2, ry, fill=FG, width=2)

    def _brake_cue(self, cue: BrakeCue | None, x0, y0, h=42):
        c = self.c
        w = W - x0 - PAD
        c.create_rectangle(x0, y0, x0 + w, y0 + h, outline=TRACK, width=1)
        if cue is None:
            c.create_text(x0 + w / 2, y0 + h / 2, text="Sin frenada próxima", fill=MUTED, font=("Segoe UI", 8))
            return
        z = cue.zone
        name = self.namer(z)
        if -40 < cue.dist_to <= 0 and not cue.braking:
            c.create_rectangle(x0, y0, x0 + w, y0 + h, fill=RED, width=0)
            c.create_text(x0 + w / 2, y0 + h / 2, text=f"¡FRENA!  {name}", fill="white", font=("Segoe UI Black", 15))
            return
        if cue.braking or cue.dist_to <= 0:
            col, title = BLUE, f"{name}: vértice ref {z.min_speed:.0f} km/h"
        else:
            col, title = AMBER, f"{name}: frena en {max(0, cue.dist_to):.0f} m"
        c.create_text(x0 + 6, y0 + 10, anchor="w", text=title, fill=col, font=("Segoe UI Semibold", 10))
        # Barra que se vacía según te acercas
        frac = max(0.0, min(1.0, cue.dist_to / 250.0))
        c.create_rectangle(x0 + 6, y0 + 20, x0 + w - 6, y0 + 24, fill=TRACK, width=0)
        c.create_rectangle(x0 + 6, y0 + 20, x0 + 6 + (w - 12) * frac, y0 + 24, fill=col, width=0)
        goal = self.focus(z)
        if goal:
            c.create_text(x0 + 6, y0 + 34, anchor="w", text=f"🎯 {goal}", fill=AMBER, font=("Segoe UI Semibold", 8))
            return
        sd = cue.speed_diff
        txt = f"Llegas {sd:+.0f} km/h vs ref"
        if sd > 4 and not cue.braking:
            txt += "  → frena antes"
        c.create_text(x0 + 6, y0 + 34, anchor="w", text=txt, fill=AMBER if sd > 4 else MUTED, font=("Segoe UI", 8))

    def _feedback(self, fb: Feedback | None):
        c = self.c
        if fb is None or time.monotonic() - fb.created > 8:
            return
        col = GREEN if fb.time_diff <= 0 else RED
        c.create_text(PAD, FEEDBACK_Y, anchor="nw", fill=col, font=("Segoe UI Semibold", 9),
                      text=f"{self.namer(fb.zone)}  {fb.time_diff:+.2f} s")
        c.create_text(PAD, FEEDBACK_Y + 16, anchor="nw", fill=FG, font=("Segoe UI", 8), width=W - PAD * 2,
                      text=" · ".join(fb.messages))

    def _spot(self, spot):
        """Barras en los bordes del coach cuando hay un coche a tu lado."""
        if not spot:
            return
        h = H + (TEMPS_H if self.show_temps else 0)
        if spot.get("left"):
            self.c.create_rectangle(0, 0, 5, h, fill=AMBER, width=0)
        if spot.get("right"):
            self.c.create_rectangle(W - 5, 0, W, h, fill=AMBER, width=0)

    def _temps(self, t, damage=None):
        """Franja inferior: 4 gomas (DI DD / TI TD) y 4 frenos, coloreados según su estado."""
        c = self.c
        y0 = H + 2
        c.create_line(PAD, y0 - 2, W - PAD, y0 - 2, fill=TRACK)
        if not t:
            c.create_text(W / 2, y0 + TEMPS_H / 2 - 2, text="Temperaturas: sin datos todavía", fill=MUTED,
                          font=("Segoe UI", 8))
            return

        def block(x, label, vals, states, fmt):
            c.create_text(x, y0 + 13, anchor="w", text=label, fill=MUTED, font=("Segoe UI Semibold", 7))
            bw, bh, gap = 30, 11, 2
            for i, (v, st) in enumerate(zip(vals, states)):
                bx = x + 30 + (i % 2) * (bw + gap)
                by = y0 + 2 + (i // 2) * (bh + gap)
                c.create_rectangle(bx, by, bx + bw, by + bh, fill="#1c1e24", outline=TEMP_COL[st], width=1)
                c.create_text(bx + bw / 2, by + bh / 2, text=fmt(v),
                              fill=TEMP_COL[st] if st else FG, font=("Segoe UI Semibold", 7))

        block(PAD, "Gomas", t["tyre"], t["tyre_state"], lambda v: f"{v:.0f}°")
        block(PAD + 106, "Frenos", t["brake"], t["brake_state"], lambda v: f"{v:.0f}")
        note, col = (f"ópt. {t['opt']:.0f}°" if t.get("opt") else ""), MUTED
        if damage and (damage["level"] or damage["detached"] or damage["flat"] or damage["overheating"]):
            serious = damage["level"] >= 2 or damage["flat"] or damage["detached"]
            note, col = "⚠ DAÑOS", RED if serious else AMBER
        c.create_text(W - PAD, y0 + 13, anchor="e", text=note, fill=col, font=("Segoe UI Semibold", 7))

    def _draw_toast(self):
        if not self._toast:
            return
        text, color, until = self._toast
        if time.monotonic() > until:
            self._toast = None
            return
        self.c.create_rectangle(0, H - 20, W, H, fill="#1c1e24", width=0)
        self.c.create_text(W / 2, H - 10, text=text, fill=color, font=("Segoe UI Semibold", 8))
