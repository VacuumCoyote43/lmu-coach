"""Panel en el móvil o la tablet: el coach sirve una página web en tu red de casa (solo lectura).

Abre en el navegador del móvil la dirección que enseña Ajustes › General (o escanea el QR). La página pide los
datos al coach unas 7 veces por segundo. Solo funciona mientras el modo coach está abierto.
"""
import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DEFAULT_PORT = 8765


def local_ips() -> list[str]:
    """Direcciones de este PC en la red local (la principal primero)."""
    ips = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("192.168.1.1", 9))          # no envía nada: solo elige la interfaz de salida
        ips.append(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
            if ip not in ips and not ip.startswith("127.") and not ip.startswith("169.254."):
                ips.append(ip)
    except OSError:
        pass
    return ips


def urls(port: int = DEFAULT_PORT) -> list[str]:
    return [f"http://{ip}:{port}" for ip in local_ips()]


class Dashboard:
    def __init__(self, port: int = DEFAULT_PORT):
        self.port = port
        self.state: dict = {"status": "Esperando a Le Mans Ultimate…"}
        self._server = None
        self.error = None

    def start(self) -> bool:
        if self._server:
            return True
        dash = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path.startswith("/state"):
                    body = json.dumps(dash.state, ensure_ascii=False, default=_jsonable).encode("utf-8")
                    ctype = "application/json; charset=utf-8"
                elif self.path in ("/", "/index.html"):
                    body, ctype = PAGE.encode("utf-8"), "text/html; charset=utf-8"
                else:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        try:
            self._server = ThreadingHTTPServer(("0.0.0.0", self.port), Handler)
        except OSError as e:
            self.error = f"No se pudo abrir el puerto {self.port}: {e}"
            return False
        self._server.daemon_threads = True
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        return True

    def stop(self):
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self._server = None


def _jsonable(o):
    if hasattr(o, "__dict__"):
        return {k: v for k, v in vars(o).items() if not k.startswith("_")}
    return str(o)


def snapshot(st: dict, extra: dict) -> dict:
    """Lo que enseña el panel, a partir de lo que dibuja el overlay y algunos datos más."""
    if st.get("status"):
        return {"status": st["status"], "sub": st.get("substatus", "")}
    sec = st.get("sectors") or {}
    flash = st.get("lap_flash") or {}
    temps = st.get("temps") or {}
    cue = st.get("cue")
    out = {
        "lap": st.get("lap"), "speed": round(st.get("speed") or 0), "gear": st.get("gear"),
        "delta": st.get("delta"), "trend": st.get("trend"), "ref": st.get("ref_time"),
        "invalid": bool(st.get("lap_invalid")),
        "sectors": [{"t": s.time, "d": s.diff, "c": s.color} if s else None for s in (sec.get("cur") or [])],
        "ideal": sec.get("ideal"),
        "last": flash.get("time"), "last_diff": flash.get("diff"), "last_best": flash.get("best"),
        "fuel": st.get("fuel") or {}, "race": st.get("race"), "pit": st.get("pit"),
        "tyres": temps.get("tyre"), "tyre_state": temps.get("tyre_state"), "brakes": temps.get("brake"),
        "brake_state": temps.get("brake_state"), "spot": st.get("spot"), "damage": st.get("damage"),
        "cue": None if cue is None else {"dist": round(cue.dist_to), "braking": cue.braking,
                                         "over": round(cue.speed_diff)},
    }
    out.update(extra)
    return out


PAGE = r"""<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#0d0e12"><meta name="apple-mobile-web-app-capable" content="yes">
<title>LMU Coach · Panel</title>
<style>
:root{--bg:#0d0e12;--panel:#1a1c22;--fg:#e6e7ea;--muted:#8b8f99;--green:#2ecc71;--red:#ff5a5a;--amber:#ffb020;
--purple:#b07cff;--blue:#3fb6ff}
*{box-sizing:border-box}html,body{margin:0;background:var(--bg);color:var(--fg);font-family:system-ui,-apple-system,
"Segoe UI",Roboto,sans-serif;height:100%;overflow:hidden}
#app{display:grid;grid-template-rows:auto 1fr auto;height:100%;padding:10px 14px;gap:10px;position:relative}
.top{display:flex;justify-content:space-between;align-items:center;color:var(--muted);font-size:15px}
.top b{color:var(--fg)}
.center{display:grid;grid-template-columns:1fr 1fr;gap:10px;align-content:start}
.tile{background:var(--panel);border-radius:12px;padding:10px 12px;min-height:72px}
.tile .k{font-size:11px;letter-spacing:1px;color:var(--muted);text-transform:uppercase}
.tile .v{font-size:28px;font-weight:700;margin-top:2px;font-variant-numeric:tabular-nums}
.tile .s{font-size:13px;color:var(--muted)}
.wide{grid-column:1/-1}
#delta{font-size:min(22vw,110px);font-weight:800;text-align:center;line-height:1;font-variant-numeric:tabular-nums}
#deltaRow{grid-column:1/-1;background:var(--panel);border-radius:14px;padding:12px 8px}
#deltaSub{text-align:center;color:var(--muted);font-size:15px;margin-top:6px}
.sectors{display:flex;gap:6px;margin-top:8px}.sectors div{flex:1;height:10px;border-radius:5px;background:#2a2d35}
.wheels{display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-top:6px}
.wheels div{border-radius:8px;padding:6px;text-align:center;font-weight:700;font-size:18px;background:#2a2d35}
.cold{background:#1f4f7a!important}.ok{background:#1f6b3f!important}.warm{background:#7a5a12!important}
.hot{background:#8a2a2a!important}
#spotL,#spotR{position:fixed;top:0;bottom:0;width:18px;background:var(--red);opacity:0;transition:opacity .1s}
#spotL{left:0}#spotR{right:0}
#banner{display:none;border-radius:10px;padding:10px;text-align:center;font-weight:800;font-size:22px}
#status{display:none;position:absolute;inset:0;align-items:center;justify-content:center;flex-direction:column;
text-align:center;padding:20px;background:var(--bg)}
#status h1{font-size:22px}#status p{color:var(--muted)}
button{background:var(--panel);color:var(--fg);border:1px solid #2e313a;border-radius:8px;padding:6px 10px;font-size:14px}
</style></head><body>
<div id="spotL"></div><div id="spotR"></div>
<div id="app">
 <div class="top"><span>Vuelta <b id="lap">–</b> · <b id="speed">–</b> km/h · M<b id="gear">–</b></span>
  <span id="pos"></span><button id="fs">⛶</button></div>
 <div class="center">
  <div id="deltaRow"><div id="delta">–</div><div class="sectors" id="sectors"></div><div id="deltaSub"></div></div>
  <div id="banner" class="wide"></div>
  <div class="tile"><div class="k">Última vuelta</div><div class="v" id="last">–</div><div class="s" id="lastSub"></div></div>
  <div class="tile"><div class="k">Referencia</div><div class="v" id="ref">–</div><div class="s" id="ideal"></div></div>
  <div class="tile"><div class="k">Combustible</div><div class="v" id="fuel">–</div><div class="s" id="ve"></div></div>
  <div class="tile"><div class="k">Delante / detrás</div><div class="v" id="gaps">–</div><div class="s" id="names"></div></div>
  <div class="tile wide" id="pitTile" style="display:none"><div class="k">Estrategia</div><div class="v" id="pit"></div></div>
  <div class="tile"><div class="k">Neumáticos °C</div><div class="wheels" id="tyres"></div></div>
  <div class="tile"><div class="k">Frenos °C</div><div class="wheels" id="brakes"></div></div>
 </div>
 <div class="top"><span id="cue"></span><span id="dmg"></span></div>
 <div id="status"><h1 id="st1"></h1><p id="st2"></p></div>
</div>
<script>
const $=id=>document.getElementById(id);
const fmt=t=>{if(!t||t<=0)return"–";const m=Math.floor(t/60),s=t-m*60;return(m?m+":":"")+(m&&s<10?"0":"")+s.toFixed(3)};
const sgn=(x,d=2)=>x==null?"–":(x>0?"+":x<0?"−":"±")+Math.abs(x).toFixed(d);
const COL={purple:"var(--purple)",green:"var(--green)",yellow:"var(--amber)",grey:"#555"};
function wheels(el,vals,states){el.innerHTML="";(vals||[null,null,null,null]).forEach((v,i)=>{const d=document.createElement("div");
 d.textContent=v==null?"–":Math.round(v);const s=states&&states[i];if(s)d.className=s;el.appendChild(d)})}
async function tick(){
 let s;try{s=await(await fetch("/state",{cache:"no-store"})).json()}catch(e){show("Sin conexión con el coach","¿Está abierto el modo coach en el PC?");return}
 if(s.status){show(s.status,s.sub||"");return}$("status").style.display="none";
 $("lap").textContent=s.lap??"–";$("speed").textContent=s.speed??"–";$("gear").textContent=s.gear??"–";
 const d=s.delta;$("delta").textContent=d==null?"–":sgn(d);$("delta").style.color=d==null?"var(--fg)":d<0?"var(--green)":"var(--red)";
 $("deltaSub").textContent=s.invalid?"VUELTA INVALIDADA":(s.trend!=null&&Math.abs(s.trend)>0.02?(s.trend<0?"ganando ":"perdiendo ")+Math.abs(s.trend).toFixed(2):"");
 $("deltaSub").style.color=s.invalid?"var(--red)":"var(--muted)";
 const sec=$("sectors");sec.innerHTML="";(s.sectors||[]).forEach(x=>{const e=document.createElement("div");if(x)e.style.background=COL[x.c]||"#2a2d35";sec.appendChild(e)});
 $("last").textContent=fmt(s.last);$("last").style.color=s.last_best?"var(--purple)":"var(--fg)";
 $("lastSub").textContent=s.last_diff!=null?sgn(s.last_diff,3)+" vs ref":"";
 $("ref").textContent=fmt(s.ref);$("ideal").textContent=s.ideal?"ideal "+fmt(s.ideal):"";
 const f=s.fuel||{};$("fuel").textContent=f.fuel_laps!=null?f.fuel_laps.toFixed(1)+" v":"–";
 $("fuel").style.color=f.fuel_laps!=null&&f.fuel_laps<2?"var(--red)":f.fuel_laps<4?"var(--amber)":"var(--fg)";
 $("ve").textContent=f.ve_laps!=null?"energía "+f.ve_laps.toFixed(1)+" v":"";
 const r=s.race;if(r){$("pos").innerHTML="P<b>"+r.pos+"</b>/"+r.of+" "+(r.cls||"");
  $("gaps").textContent=(r.ahead!=null?"▲"+r.ahead.toFixed(1):"–")+"  "+(r.behind!=null?"▼"+r.behind.toFixed(1):"–");
  $("gaps").style.color=r.behind!=null&&r.behind<1?"var(--amber)":"var(--fg)";
  $("names").textContent=[r.ahead_name,r.behind_name].filter(Boolean).join(" · ")}else{$("pos").textContent="";$("gaps").textContent="–";$("names").textContent=""}
 const p=s.pit;if(p&&p.stop_in!=null){$("pitTile").style.display="";$("pit").textContent=(p.stop_in==0?"BOX ESTA VUELTA":"BOX en "+p.stop_in+" v")+
  (p.add_fuel?" · +"+Math.ceil(p.add_fuel)+" L":"")+(p.ve_target?" · "+Math.ceil(p.ve_target)+" %":"")+(p.rejoin?" · vuelves P"+p.rejoin:"");
  $("pit").style.color=p.stop_in==0?"var(--red)":"var(--amber)"}else $("pitTile").style.display="none";
 wheels($("tyres"),s.tyres,s.tyre_state);wheels($("brakes"),s.brakes,s.brake_state);
 const sp=s.spot||{};$("spotL").style.opacity=sp.left?0.9:0;$("spotR").style.opacity=sp.right?0.9:0;
 const b=$("banner"),fl=s.flag;if(fl){b.style.display="";b.textContent=fl.text;b.style.background=fl.color;b.style.color="#111"}else b.style.display="none";
 const c=s.cue;$("cue").textContent=c?(c.braking?"frenando":"frenada en "+c.dist+" m"+(c.over>3?" · "+c.over+" km/h más rápido":"")):"";
 const dm=s.damage;$("dmg").textContent=dm&&(dm.level||dm.flat||dm.detached||dm.overheating)?"⚠ DAÑOS":"";$("dmg").style.color="var(--red)";
}
function show(a,b){$("status").style.display="flex";$("st1").textContent=a;$("st2").textContent=b}
$("fs").onclick=()=>{const e=document.documentElement;(e.requestFullscreen||e.webkitRequestFullscreen||function(){}).call(e)};
setInterval(tick,150);tick();
</script></body></html>
"""
