#!/usr/bin/env python3
"""
Visualise the 384-dim pgvector embeddings as a 2D map.

PCA (via numpy SVD) projects 384 dimensions onto 2 axes. Distances in the
projected plane are APPROXIMATE -- PCA keeps the highest-variance directions,
so nearby dots usually mean similar chunks, but it is not a faithful map.

Usage:  ./venv/bin/python scripts/visualize_embeddings.py [sample_per_law]
Writes: app/evaluation/embeddings_map.html  (self-contained, no server)
"""
import json
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import numpy as np
from app.retrieval.vector_store import get_conn

PER_LAW = int(sys.argv[1]) if len(sys.argv) > 1 else 60
OUT = os.path.join(os.path.dirname(__file__), "..", "app", "evaluation", "embeddings_map.html")

# Deterministic palette: distinct hues, similar lightness so no law dominates.
PALETTE = ["#e6194b", "#3cb44b", "#4363d8", "#f58231", "#911eb4",
           "#42d4f4", "#f032e6", "#bfef45", "#fabed4", "#469990",
           "#dcbeff", "#9a6324", "#800000", "#aaffc3", "#808000", "#ffd8b1"]


def main() -> None:
    with get_conn() as conn:
        laws = [r[0] for r in conn.execute(
            "SELECT DISTINCT law FROM documents ORDER BY law").fetchall()]
        total = conn.execute("SELECT count(*) FROM documents").fetchone()[0]

    print(f"documents total : {total}")
    print(f"distinct laws   : {len(laws)}")

    # --- pull a stratified sample, vectors as numpy -----------------------
    vecs, meta = [], []
    for li, law in enumerate(laws):
        with get_conn() as conn:
            rows = conn.execute(
                "SELECT id, article, left(content, 300), embedding "
                "FROM documents WHERE law = %s ORDER BY id LIMIT %s",
                (law, PER_LAW)).fetchall()
        for r in rows:
            vecs.append(np.array(json.loads(r[3]), dtype=np.float64))
            meta.append({"id": r[0], "article": r[1], "content": r[2],
                         "law": law, "law_idx": li})
    X = np.vstack(vecs)
    print(f"sampled         : {X.shape[0]} vectors x {X.shape[1]} dims")

    # --- PCA to 2D via SVD (no sklearn dependency) -------------------------
    Xc = X - X.mean(axis=0, keepdims=True)
    U, S, Vt = np.linalg.svd(Xc, full_matrices=False)
    P = U[:, :2] * S[:2]
    explained = (S[:2] ** 2 / (S ** 2).sum()) * 100
    print(f"variance kept   : PC1 {explained[0]:.1f}%  PC2 {explained[1]:.1f}%  "
          f"(total {explained.sum():.1f}%)")

    # --- sanity check: does PCA preserve nearest neighbours? --------------
    def top1(pick):
        q = X[pick]
        sims = Xc @ q / (np.linalg.norm(Xc, axis=1) * np.linalg.norm(q) + 1e-12)
        return int(np.argmax(sims))

    ok = 0
    for pick in range(0, min(40, len(X))):
        true_nn = top1(pick)
        d = ((P - P[pick]) ** 2).sum(axis=1)
        ok += int(np.argmin(d) == true_nn)
    print(f"PCA neighbour fidelity: {ok}/{min(40, len(X))} top-1 preserved")

    for m, p in zip(meta, P):
        m["x"], m["y"] = float(p[0]), float(p[1])

    payload = {"points": meta, "palette": PALETTE,
               "explained": [float(explained[0]), float(explained[1])],
               "fidelity": ok, "total": total, "sampled": len(meta)}

    with open(OUT, "w", encoding="utf-8") as f:
        f.write(HTML.replace("__DATA__", json.dumps(payload, ensure_ascii=False)))
    print(f"written         : {os.path.normpath(OUT)}")


HTML = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>Embedding map — 384-dim pgvector projected to 2D</title>
<style>
  body{margin:0;background:#0d1117;color:#e6edf3;font:14px/1.5 system-ui,sans-serif}
  header{padding:14px 20px;border-bottom:1px solid #30363d}
  h1{margin:0 0 4px;font-size:17px}
  .sub{color:#8b949e;font-size:12px}
  #wrap{display:flex}
  #plot{flex:1;position:relative}
  canvas{display:block;width:100%;height:100%}
  #side{width:300px;border-left:1px solid #30363d;padding:14px;overflow-y:auto;max-height:88vh}
  .law{display:flex;align-items:center;gap:8px;margin:5px 0;cursor:pointer;font-size:12px}
  .sw{width:11px;height:11px;border-radius:2px;flex:none}
  #tip{position:absolute;pointer-events:none;background:#161b22;border:1px solid #30363d;
       border-radius:6px;padding:8px 10px;max-width:330px;font-size:12px;display:none;z-index:9}
  .art{color:#58a6ff;font-weight:600}
  .txt{color:#8b949e;margin-top:4px;max-height:90px;overflow:hidden}
  .note{background:#1c2128;border-left:3px solid #d29922;padding:8px 10px;margin-top:12px;
        font-size:11px;color:#c9d1d9;border-radius:0 4px 4px 0}
</style></head><body>
<header>
  <h1>Embedding map — your 5,844 chunks, 384-dim &rarr; 2D</h1>
  <div class="sub" id="meta"></div>
</header>
<div id="wrap">
  <div id="plot"><canvas id="c"></canvas><div id="tip"></div></div>
  <div id="side"><div id="legend"></div><div class="note" id="warn"></div></div>
</div>
<script>
const D = __DATA__;
document.getElementById('meta').textContent =
  `showing ${D.sampled} of ${D.total} chunks (stratified sample) · ` +
  `PC1 ${D.explained[0].toFixed(1)}% + PC2 ${D.explained[1].toFixed(1)}% variance · ` +
  `PCA kept the true nearest neighbour in ${D.fidelity}/40 spot checks`;
document.getElementById('warn').innerHTML =
  '<b>Read this correctly.</b> PCA keeps the 2 highest-variance axes out of 384, ' +
  'so this is a lossy sketch, not a true map. Close dots = similar embeddings. ' +
  'Wide gaps = the model considers those chunks unrelated.';

const laws = [...new Set(D.points.map(p=>p.law))];
document.getElementById('legend').innerHTML = '<b>Laws (click to isolate)</b>' +
  laws.map((l,i)=>`<div class="law" data-i="${D.points.find(p=>p.law===l).law_idx}">
    <span class="sw" style="background:${D.palette[i%20]}"></span>
    <span>${l.replace(/</g,'&lt;')}</span></div>`).join('');

const cv=document.getElementById('c'), ctx=cv.getContext('2d'), tip=document.getElementById('tip');
let W,H,iso=new Set();
function fit(){
  const r=document.getElementById('plot').getBoundingClientRect();
  W=cv.width=r.width*devicePixelRatio; H=cv.height=r.height*devicePixelRatio;
  cv.style.height=r.height+'px'; draw();
}
const xs=D.points.map(p=>p.x), ys=D.points.map(p=>p.y);
const pad=40, mnx=Math.min(...xs), mxx=Math.max(...xs), mny=Math.min(...ys), mxy=Math.max(...ys);
const sx=v=>pad+(v-mnx)/((mxx-mnx)||1)*(W-2*pad), sy=v=>H-pad-(v-mny)/((mxy-mny)||1)*(H-2*pad);
function draw(){
  ctx.clearRect(0,0,W,H);
  for(const p of D.points){
    if(iso.size && !iso.has(p.law_idx)) continue;
    ctx.beginPath();
    ctx.arc(sx(p.x),sy(p.y),4*devicePixelRatio,0,7);
    ctx.fillStyle=D.palette[p.law_idx%20]+'cc'; ctx.fill();
  }
}
cv.addEventListener('mousemove',e=>{
  const r=cv.getBoundingClientRect(), mx=(e.clientX-r.left)*devicePixelRatio, my=(e.clientY-r.top)*devicePixelRatio;
  let best=null,bd=400;
  for(const p of D.points){
    if(iso.size && !iso.has(p.law_idx)) continue;
    const d=(sx(p.x)-mx)**2+(sy(p.y)-my)**2;
    if(d<bd){bd=d;best=p;}
  }
  if(best){
    tip.style.display='block'; tip.style.left=(e.clientX-r.left+14)+'px'; tip.style.top=(e.clientY-r.top+14)+'px';
    tip.innerHTML=`<span class="art">${best.law} — المادة ${best.article}</span>
      <div class="txt">${(best.content||'').replace(/</g,'&lt;').slice(0,240)}</div>`;
  } else tip.style.display='none';
});
cv.addEventListener('mouseleave',()=>tip.style.display='none');
document.getElementById('legend').onclick=e=>{
  const d=e.target.closest('.law'); if(!d) return;
  const i=+d.dataset.i;
  iso.has(i)?iso.delete(i):iso.add(i);
  d.style.opacity=iso.size&&!iso.has(i)?.35:1; draw();
};
addEventListener('resize',fit); fit();
</script></body></html>"""


if __name__ == "__main__":
    main()
