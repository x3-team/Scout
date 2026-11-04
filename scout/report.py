"""Deterministic JSON and offline SVG replay, with atomic file replacement."""
import json
import os
from pathlib import Path
import tempfile


def atomic_write(path: str | Path, content: str):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n",
                                         dir=path.parent, delete=False) as stream:
            temporary = stream.name
            stream.write(content)
        os.replace(temporary, path)
    finally:
        if temporary is not None and os.path.exists(temporary):
            os.unlink(temporary)


def write_json(report: dict, path: str | Path):
    atomic_write(path, json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def write_html(report: dict, path: str | Path):
    data = json.dumps(report, ensure_ascii=False, allow_nan=False).replace("<", "\\u003c")
    atomic_write(path, HTML.replace("__REPORT_JSON__", data))


HTML = r'''<!doctype html>
<html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Scout — цифровая инспекция</title>
<style>
:root{color-scheme:dark;font:16px/1.5 system-ui;background:#101820;color:#e7eef4}
*{box-sizing:border-box}body{margin:0;padding:28px;max-width:1200px;margin-inline:auto}
header{display:flex;justify-content:space-between;align-items:center;gap:16px;flex-wrap:wrap}
h1{font-size:30px;margin:0}h2{font-size:18px;margin:0 0 14px}.muted{color:#a4b7c6}
.tag{font-size:13px;background:#5b461d;color:#ffdc8c;padding:7px 12px;border-radius:8px}
main{display:grid;grid-template-columns:minmax(0,1.6fr) minmax(260px,1fr);gap:20px;margin-top:22px}
section{background:#19252f;border:1px solid #30424f;border-radius:14px;padding:20px}
svg{width:100%;height:auto;background:#101b24;border-radius:8px;display:block}
button{background:#7ce0c1;color:#10251f;border:0;border-radius:7px;padding:9px 16px;font:inherit;cursor:pointer}
input{width:100%;accent-color:#7ce0c1;margin:14px 0}dl{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin:0}
dt{color:#a4b7c6;font-size:13px}dd{margin:0;font-size:21px}ul{padding-left:21px}li{margin:10px 0}
.legend{font-size:13px;color:#bccbd5;margin:12px 0}.warning{color:#ffdc8c}footer{margin:20px 0;font-size:13px}
@media(max-width:730px){body{padding:16px}main{grid-template-columns:1fr}section{padding:16px}h1{font-size:25px}}
</style>
<header><div><h1>SCOUT / 01</h1><div class="muted">Лабораторная цифровая инспекция</div></div>
<div class="tag">СИНТЕТИЧЕСКИЙ СТЕНД · CPU</div></header>
<main><section><h2 id="scenario"></h2><svg id="arena" role="img" aria-label="Полигон, препятствия и траектория робота"></svg>
<div class="legend">Бирюзовый — траектория · серый — препятствия · янтарный — подготовленные отклонения</div>
<button id="play">Воспроизвести</button> <span id="time" aria-live="polite"></span>
<input id="scrub" aria-label="Положение на траектории" type="range" min="0" value="0" step="1">
<div id="state" class="muted"></div></section>
<section><h2 id="status"></h2><dl id="metrics"></dl><h2 style="margin-top:24px">Контрольные точки</h2>
<ul id="stations"></ul><p id="reason" class="warning"></p><button id="download">Скачать JSON</button></section></main>
<footer class="muted">Это воспроизведение завершённого расчёта. Отклонения заданы сценарием, компьютерное зрение не выполнялось.
Положение идеализировано, торможение мгновенное; физическая безопасность этим запуском не подтверждается.</footer>
<script type="application/json" id="data">__REPORT_JSON__</script>
<script>
'use strict';
const r=JSON.parse(document.getElementById('data').textContent), w=r.world;
const $=id=>document.getElementById(id), ns='http://www.w3.org/2000/svg';
const svg=$('arena'), scale=180, pad=32, X=x=>pad+x*scale, Y=y=>pad+(w.height-y)*scale;
svg.setAttribute('viewBox','0 0 '+(w.width*scale+2*pad)+' '+(w.height*scale+2*pad));
function draw(tag,attrs,text){
  const el=document.createElementNS(ns,tag);
  for(const[k,v]of Object.entries(attrs))el.setAttribute(k,v);
  if(text!==undefined)el.textContent=text;
  svg.append(el);return el;
}
draw('rect',{x:pad,y:pad,width:w.width*scale,height:w.height*scale,fill:'none',stroke:'#657785','stroke-width':2});
for(const o of w.obstacles)draw('rect',{x:X(o.x),y:Y(o.y+o.height),width:o.width*scale,height:o.height*scale,fill:'#526573',rx:3});
for(const s of w.stations){
  draw('circle',{cx:X(s.x),cy:Y(s.y),r:8,fill:s.deviations.length?'#ffce71':'#81a2ba'});
  draw('text',{x:X(s.x)+12,y:Y(s.y)+5,fill:'#e7eef4','font-size':15},s.id);
}
draw('circle',{cx:X(w.start.x),cy:Y(w.start.y),r:5,fill:'#7ce0c1'});
draw('text',{x:X(w.start.x)-18,y:Y(w.start.y)+32,fill:'#bdd0dd','font-size':12},'START');
const trail=draw('polyline',{points:'',fill:'none',stroke:'#7ce0c1','stroke-width':2,opacity:.7});
const body=draw('circle',{r:w.robot.radius_m*scale,fill:'#7ce0c1',stroke:'#e7fff7','stroke-width':2});
const nose=draw('line',{stroke:'#163d30','stroke-width':3});
draw('text',{x:12,y:18,fill:'#a4b7c6','font-size':11},'метры · вид сверху');
$('scenario').textContent=r.scenario;$('status').textContent=r.status;
$('reason').textContent=r.reason;
for(const[label,value]of [
  ['Точки',r.metrics.visited_count+' / 3'],
  ['Путь',r.metrics.distance_m.toFixed(2)+' м'],
  ['Время модели',r.metrics.duration_s.toFixed(1)+' с'],
  ['Изменённые точки',r.metrics.changed_station_count]
]){
  const cell=document.createElement('div'),dt=document.createElement('dt'),dd=document.createElement('dd');
  dt.textContent=label;dd.textContent=value;cell.append(dt,dd);$('metrics').append(cell);
}
for(const s of w.stations){
  const item=document.createElement('li'),i=r.inspections.find(i=>i.station_id===s.id);
  item.textContent=s.id+': '+(i?(i.result==='CHANGED'?'ИЗМЕНЕНИЕ — '+i.deviations.join(', '):'без отклонений'):'не посещена');
  if(i&&i.synthetic)item.append(document.createTextNode(' [синтетика]'));
  $('stations').append(item);
}
const slider=$('scrub');slider.max=r.trace.length-1;let timer=null;
function frame(){
  const index=Number(slider.value),p=r.trace[index];
  body.setAttribute('cx',X(p.x));body.setAttribute('cy',Y(p.y));
  nose.setAttribute('x1',X(p.x));nose.setAttribute('y1',Y(p.y));
  nose.setAttribute('x2',X(p.x)+Math.cos(p.heading)*w.robot.radius_m*scale);
  nose.setAttribute('y2',Y(p.y)-Math.sin(p.heading)*w.robot.radius_m*scale);
  trail.setAttribute('points',r.trace.slice(0,index+1).map(p=>X(p.x)+','+Y(p.y)).join(' '));
  $('time').textContent=p.time_s.toFixed(1)+' с';$('state').textContent=p.state;
}
function pause(){clearInterval(timer);timer=null;$('play').textContent='Воспроизвести'}
slider.addEventListener('input',()=>{pause();frame()});
$('play').addEventListener('click',()=>{
  if(timer){pause();return}
  if(Number(slider.value)>=Number(slider.max))slider.value=0;
  $('play').textContent='Пауза';
  timer=setInterval(()=>{
    slider.value=Math.min(Number(slider.value)+2,Number(slider.max));
    frame();if(slider.value===slider.max)pause();
  },40);
});
$('download').addEventListener('click',()=>{
  const url=URL.createObjectURL(new Blob([JSON.stringify(r,null,2)+'\n'],{type:'application/json'}));
  const a=document.createElement('a');a.href=url;a.download='scout-report.json';a.click();
  setTimeout(()=>URL.revokeObjectURL(url),1000);
});
frame();
</script></html>
'''
