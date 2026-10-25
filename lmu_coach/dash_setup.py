"""Editar el setup desde el móvil: la parte del panel que lista, abre y guarda reglajes (.svm) de LMU.

Solo si está permitido en Ajustes. Solo lee los .svm que encuentra la app (el cargado en LMU y los guardados
por circuito) y solo escribe .svm nuevos dentro de la carpeta de reglajes de LMU, con un nombre limpio.
"""
import threading

from . import lapstats, svm
from .log import log

_lock = threading.Lock()
_sessions = None
_stem_for = None


def _context():
    """Sesiones y reconocimiento de coches (para los límites), cargados una vez."""
    global _sessions, _stem_for
    with _lock:
        if _sessions is None:
            from .car_images import CarImages
            from .paths import IMPORTED_DIR, INDEX_PATH
            from .sessions import SessionIndex, find_lmu_dir, find_telemetry_dir
            _sessions = SessionIndex(find_telemetry_dir(), INDEX_PATH, IMPORTED_DIR).sessions
            _stem_for = CarImages(find_lmu_dir()).stem_for
    return _sessions, _stem_for


def _allowed(path: str):
    """El archivo pedido tiene que ser uno de los que lista la app (nada de rutas arbitrarias)."""
    for p in svm.find_setups():
        if str(p) == path:
            return p
    return None


def list_setups() -> dict:
    """Con el coche de cada uno: LMU solo enseña en el garaje los setups del coche que llevas."""
    out = []
    for p in svm.find_setups():
        try:
            f = svm.parse(p)
        except OSError:
            continue
        label = "Lo que tienes cargado en LMU" if p.name == "TempModFile.svm" else f"{p.parent.name} · {p.stem}"
        car = "coche de seguridad" if f.pace_car else f.vehicle_class
        out.append({"path": str(p), "label": f"{label} ({car})" if car else label, "pace_car": f.pace_car})
    out.sort(key=lambda s: s["pace_car"])          # los del coche de seguridad, al final
    return {"setups": out}


def load(path: str, track_hint: str | None = None) -> dict:
    p = _allowed(path)
    if p is None:
        return {"error": "Ese setup no está en la carpeta de LMU"}
    f = svm.parse(p)
    sessions, stem_for = _context()
    limits, car = svm.limits_from_sessions(f, sessions, stem_for)
    groups = {}
    for e in f.entries:
        if e.session_key is None:
            continue
        lim = limits.get(e.session_key)
        if not e.adjustable or (lim and lim[2] <= lim[1]):
            continue
        cat, name, order = lapstats.setup_label(e.session_key)
        eff = svm.EFFECTS.get(e.effect_key or "")
        groups.setdefault(cat, []).append({
            "key": e.session_key, "name": name, "text": e.text, "index": e.index,
            "lo": lim[1] if lim else 0, "hi": lim[2] if lim else None, "order": order,
            "up": eff[0] if eff else "", "down": eff[1] if eff else ""})
    cats = [{"cat": c, "items": sorted(v, key=lambda i: i["order"])} for c, v in groups.items()]
    cats.sort(key=lambda g: g["items"][0]["order"])
    folders = svm.track_folders()
    guess = svm.guess_track_folder(track_hint, folders) if track_hint else None
    if guess is None and p.parent.parent == svm.settings_dir():
        guess = p.parent.name
    warn = ("Es el setup del coche de seguridad, no el tuyo: LMU no lo enseñará para tu coche. Entra en el garaje "
            "con tu coche (o elige un setup suyo) y vuelve a abrir esta página.") if f.pace_car else ""
    return {"vehicle": f.vehicle_class, "limits_from": car, "groups": cats, "folders": folders,
            "folder": guess or (folders[0] if folders else None), "warning": warn}


def save(data: dict) -> dict:
    p = _allowed(str(data.get("path", "")))
    if p is None:
        return {"error": "Ese setup no está en la carpeta de LMU"}
    base = svm.settings_dir()
    folder = str(data.get("folder") or "")
    if base is None or folder not in svm.track_folders():
        return {"error": "Elige el circuito donde guardarlo"}
    name = "".join(c for c in str(data.get("name") or "").strip() if c not in '\\/:*?"<>|.').strip()[:60] or "Desde el movil"
    f = svm.parse(p)
    if f.pace_car:
        return {"error": "Ese es el setup del coche de seguridad: LMU no lo cargará en tu coche"}
    sessions, stem_for = _context()
    limits, _ = svm.limits_from_sessions(f, sessions, stem_for)
    changed = []
    for key, val in (data.get("changes") or {}).items():
        e = f.entry(str(key))
        if e is None or not e.adjustable:
            continue
        lim = limits.get(e.session_key)
        v = max(lim[1] if lim else 0, int(val))
        if lim:
            v = min(lim[2], v)
        if v != e.index:
            e.new_index = v
            changed.append(f"{lapstats.setup_label(e.session_key)[1]}: {e.index} → {v}")
    if not changed:
        return {"error": "No has cambiado nada"}
    dest = base / folder / f"{name}.svm"
    if dest.exists() and not data.get("overwrite"):
        return {"exists": True, "error": f"Ya hay un setup «{name}» en {folder}"}
    try:
        out = svm.save(f, dest, str(data.get("note") or "Desde el móvil (LMU Coach)")[:200])
    except OSError as e:
        log.warning("Setup desde el móvil: no se pudo guardar", exc_info=True)
        return {"error": f"No se pudo guardar: {e}"}
    return {"ok": True, "file": str(out), "name": name, "folder": folder, "changes": changed}


PAGE = r"""<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#0d0e12"><title>LMU Coach · Setup</title>
<style>
:root{--bg:#0d0e12;--panel:#1a1c22;--panel2:#22252d;--fg:#e6e7ea;--muted:#8b8f99;--green:#2ecc71;--red:#ff5a5a;
--amber:#ffb020;--blue:#3fb6ff}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font-family:system-ui,-apple-system,"Segoe UI",
Roboto,sans-serif;padding:12px 12px 140px}
a{color:var(--blue)}h1{font-size:20px;margin:4px 0 2px}.muted{color:var(--muted);font-size:13px}
select,input{width:100%;background:var(--panel2);color:var(--fg);border:1px solid #2e313a;border-radius:8px;padding:10px;
font-size:16px;margin:6px 0}
.cat{color:var(--muted);font-size:12px;letter-spacing:1px;text-transform:uppercase;margin:18px 2px 6px}
.row{background:var(--panel);border-radius:10px;padding:10px;margin:6px 0;display:grid;grid-template-columns:1fr auto;
gap:4px 8px;align-items:center}
.row.ch{outline:2px solid var(--amber)}
.name{font-weight:600}.now{color:var(--muted);font-size:13px}.eff{grid-column:1/-1;color:var(--amber);font-size:13px}
.ctl{display:flex;align-items:center;gap:6px}
.ctl button{width:44px;height:44px;border-radius:10px;border:1px solid #2e313a;background:var(--panel2);color:var(--fg);
font-size:22px}.ctl span{min-width:58px;text-align:center;font-variant-numeric:tabular-nums;font-weight:700}
.bar{position:fixed;left:0;right:0;bottom:0;background:#121318ee;border-top:1px solid #2e313a;padding:10px 12px}
.bar .grid{display:grid;grid-template-columns:1fr 1fr;gap:6px}
.save{width:100%;padding:13px;border:none;border-radius:10px;background:#1f7a45;color:white;font-size:17px;font-weight:700}
.msg{margin-top:6px;font-size:14px}.err{color:var(--red)}.ok{color:var(--green)}
</style></head><body>
<a href="/">‹ Panel</a>
<h1>🛠 Setup</h1>
<div class="muted">Cambia el reglaje y guárdalo en la carpeta del circuito. En LMU: garaje › Cargar setup.</div>
<select id="src"></select>
<div class="muted" id="info"></div>
<div class="msg err" id="warn"></div>
<div id="list"></div>
<div class="bar">
 <div class="grid"><input id="name" placeholder="Nombre del setup"><select id="folder"></select></div>
 <button class="save" id="save">💾 Guardar en LMU</button>
 <div class="msg" id="msg"></div>
</div>
<script>
const $=id=>document.getElementById(id);let data=null,changes={};
async function j(url,opt){const r=await fetch(url,opt);return r.json()}
async function init(){
 const l=await j("/api/setups");if(l.error){$("info").textContent=l.error;return}
 $("src").innerHTML=l.setups.map(s=>`<option value="${encodeURIComponent(s.path)}">${s.label}</option>`).join("");
 if(!l.setups.length){$("info").textContent="No hay setups: entra en el garaje de LMU con el coche.";return}
 load();
}
async function load(){
 changes={};$("msg").textContent="";$("info").textContent="Cargando…";
 data=await j("/api/setup?path="+$("src").value);
 $("warn").textContent="";
 if(data.error){$("info").textContent=data.error;return}
 $("warn").textContent=data.warning||"";
 $("info").textContent=(data.vehicle||"")+(data.limits_from?" · límites de tu sesión con "+data.limits_from:" · sin sesiones con este coche: límites desconocidos");
 $("folder").innerHTML=data.folders.map(f=>`<option ${f==data.folder?"selected":""}>${f}</option>`).join("");
 render();
}
function render(){
 $("list").innerHTML=data.groups.map(g=>`<div class="cat">${g.cat}</div>`+g.items.map(it=>{
  const v=changes[it.key]??it.index,d=v-it.index;
  const eff=d>0?it.up:d<0?it.down:"";
  return `<div class="row ${d?"ch":""}"><div><div class="name">${it.name}</div><div class="now">${it.text}${d?` → posición ${v}`:""}</div></div>
  <div class="ctl"><button onclick="step('${it.key}',-1)">−</button><span>${v}${it.hi!=null?"/"+it.hi:""}</span><button onclick="step('${it.key}',1)">+</button></div>
  ${d?`<div class="eff">${d>0?"+":""}${d} · ${eff||""}</div>`:""}</div>`}).join("")).join("");
}
function step(key,dir){
 for(const g of data.groups)for(const it of g.items)if(it.key==key){
  let v=(changes[key]??it.index)+dir;if(v<it.lo)v=it.lo;if(it.hi!=null&&v>it.hi)v=it.hi;
  if(v==it.index)delete changes[key];else changes[key]=v;}
 render();
}
async function save(overwrite){
 const body={path:decodeURIComponent($("src").value),changes,name:$("name").value,folder:$("folder").value,overwrite:!!overwrite};
 const r=await j("/api/setup/save",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
 if(r.exists&&confirm(r.error+". ¿Reemplazarlo?"))return save(true);
 $("msg").className="msg "+(r.ok?"ok":"err");
 $("msg").textContent=r.ok?`Guardado «${r.name}» en ${r.folder} (${r.changes.length} cambios). En LMU: garaje › Cargar setup (con ${data.vehicle}).`:r.error;
}
$("src").onchange=load;$("save").onclick=()=>save(false);init();
</script></body></html>
"""
