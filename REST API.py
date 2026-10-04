"""
Shelf - a reading-list REST API with a responsive UI.
 Python standard library (http.server + sqlite3). Run:  python app.py
Open http://localhost:8000

REST API
  GET    /api/books?status=&q=   list (filter/search)
  POST   /api/books              create  {title, author, status, rating}
  GET    /api/books/<id>         read
  PUT    /api/books/<id>         update (partial allowed)
  DELETE /api/books/<id>         delete
  GET    /api/stats              counts per status
"""
import json, re, sqlite3, os
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "shelf.db")
STATUSES = ("want", "reading", "done")


def db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con


def init():
    with db() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS books(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL, author TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'want',
            rating INTEGER NOT NULL DEFAULT 0,
            created TEXT DEFAULT CURRENT_TIMESTAMP)""")
        if c.execute("SELECT COUNT(*) FROM books").fetchone()[0] == 0:
            c.executemany("INSERT INTO books(title,author,status,rating) VALUES(?,?,?,?)", [
                ("The Left Hand of Darkness", "Ursula K. Le Guin", "done", 5),
                ("Piranesi", "Susanna Clarke", "reading", 0),
                ("Braiding Sweetgrass", "Robin Wall Kimmerer", "want", 0),
                ("Klara and the Sun", "Kazuo Ishiguro", "done", 4),
            ])


def validate(d, partial=False):
    out = {}
    if "title" in d or not partial:
        t = str(d.get("title", "")).strip()
        if not t:
            raise ValueError("Title is required.")
        out["title"] = t[:200]
    if "author" in d:
        out["author"] = str(d["author"]).strip()[:120]
    if "status" in d:
        if d["status"] not in STATUSES:
            raise ValueError("Status must be one of: " + ", ".join(STATUSES))
        out["status"] = d["status"]
    if "rating" in d:
        try:
            r = int(d["rating"])
        except (TypeError, ValueError):
            raise ValueError("Rating must be a number from 0 to 5.")
        if not 0 <= r <= 5:
            raise ValueError("Rating must be a number from 0 to 5.")
        out["rating"] = r
    return out


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        try:
            d = json.loads(self.rfile.read(n) or b"{}")
            if not isinstance(d, dict):
                raise ValueError
            return d
        except ValueError:
            raise ValueError("Body must be a JSON object.")

    def route(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path in ("/", "/index.html"):
            return self.send(200, PAGE.encode(), "text/html")
        if not u.path.startswith("/api/"):
            return self.send(404, {"error": "Not found"})
        m = re.fullmatch(r"/api/books(?:/(\d+))?/?", u.path)
        with db() as c:
            if u.path.rstrip("/") == "/api/stats" and self.command == "GET":
                rows = c.execute("SELECT status, COUNT(*) n FROM books GROUP BY status").fetchall()
                s = {k: 0 for k in STATUSES}
                s.update({r["status"]: r["n"] for r in rows})
                return self.send(200, s)
            if not m:
                return self.send(404, {"error": "Not found"})
            bid = m.group(1)
            try:
                if bid is None and self.command == "GET":
                    sql, args = "SELECT * FROM books WHERE 1=1", []
                    if q.get("status"):
                        sql += " AND status=?"; args.append(q["status"][0])
                    if q.get("q"):
                        sql += " AND (title LIKE ? OR author LIKE ?)"
                        args += ["%" + q["q"][0] + "%"] * 2
                    rows = c.execute(sql + " ORDER BY id DESC", args).fetchall()
                    return self.send(200, [dict(r) for r in rows])
                if bid is None and self.command == "POST":
                    d = validate(self.body())
                    cur = c.execute("INSERT INTO books(title,author,status,rating) VALUES(?,?,?,?)",
                                    (d["title"], d.get("author", ""), d.get("status", "want"), d.get("rating", 0)))
                    row = c.execute("SELECT * FROM books WHERE id=?", (cur.lastrowid,)).fetchone()
                    return self.send(201, dict(row))
                if bid is not None:
                    row = c.execute("SELECT * FROM books WHERE id=?", (bid,)).fetchone()
                    if not row:
                        return self.send(404, {"error": "Book not found."})
                    if self.command == "GET":
                        return self.send(200, dict(row))
                    if self.command == "PUT":
                        d = validate(self.body(), partial=True)
                        if d:
                            sets = ",".join(f"{k}=?" for k in d)
                            c.execute(f"UPDATE books SET {sets} WHERE id=?", [*d.values(), bid])
                        row = c.execute("SELECT * FROM books WHERE id=?", (bid,)).fetchone()
                        return self.send(200, dict(row))
                    if self.command == "DELETE":
                        c.execute("DELETE FROM books WHERE id=?", (bid,))
                        return self.send(200, {"deleted": int(bid)})
            except ValueError as e:
                return self.send(400, {"error": str(e)})
        self.send(405, {"error": "Method not allowed"})

    do_GET = do_POST = do_PUT = do_DELETE = do_HEAD = route


PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Shelf</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,400;12..96,600;12..96,800&display=swap" rel="stylesheet">
<style>
:root{--bg:#efeaf7;--ink:#1f1536;--mute:#6b6285;--card:#fff;--line:#dcd3ec;
--want:#e8a33d;--reading:#3b82c4;--done:#2f9e7a;--brand:#4a2c8f;--r:18px}
@media(prefers-color-scheme:dark){:root{--bg:#150f26;--ink:#f1ecfb;--mute:#a79ec4;--card:#211838;--line:#35294f;--brand:#a58bf0}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.5 "Bricolage Grotesque",system-ui,sans-serif}
.wrap{max-width:1040px;margin:0 auto;padding:clamp(16px,4vw,48px)}
h1{font-size:clamp(3rem,12vw,7.5rem);line-height:.85;margin:0;font-weight:800;letter-spacing:-.05em;color:var(--brand)}
.tag{color:var(--mute);max-width:34ch;margin:14px 0 28px}
.top{display:grid;gap:24px;grid-template-columns:1fr;align-items:end}
@media(min-width:760px){.top{grid-template-columns:1.3fr 1fr}}
.stats{display:flex;height:14px;border-radius:99px;overflow:hidden;background:var(--line)}
.stats i{display:block;transition:flex .5s}
.legend{display:flex;gap:16px;flex-wrap:wrap;margin-top:10px;color:var(--mute);font-size:.9rem}
.legend b{color:var(--ink)}
.dot{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:6px}
form.add{display:grid;gap:10px;grid-template-columns:1fr;margin:32px 0 20px;background:var(--card);padding:14px;border-radius:var(--r);border:1px solid var(--line)}
@media(min-width:760px){form.add{grid-template-columns:1.4fr 1fr auto auto}}
input,select,button{font:inherit;color:inherit}
input,select{padding:11px 14px;border-radius:12px;border:1px solid var(--line);background:var(--bg);min-width:0}
:focus-visible{outline:3px solid var(--brand);outline-offset:2px}
button{cursor:pointer;border:0;border-radius:12px;padding:11px 18px;background:var(--brand);color:#fff;font-weight:600}
@media(prefers-color-scheme:dark){button.primary{color:#150f26}}
button.ghost{background:transparent;color:var(--mute);padding:6px 10px}
button.ghost:hover{color:#d33}
.bar{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:20px}
.bar input{flex:1 1 200px}
.chip{background:var(--card);color:var(--ink);border:1px solid var(--line);padding:9px 16px}
.chip[aria-pressed=true]{background:var(--ink);color:var(--bg)}
.grid{display:grid;gap:16px;grid-template-columns:repeat(auto-fill,minmax(250px,1fr))}
.book{background:var(--card);border-radius:var(--r);padding:18px 18px 12px 26px;position:relative;border:1px solid var(--line);display:flex;flex-direction:column;gap:6px}
.book:before{content:"";position:absolute;left:0;top:0;bottom:0;width:10px;border-radius:var(--r) 0 0 var(--r);background:var(--c)}
.book h3{margin:0;font-size:1.25rem;line-height:1.15;letter-spacing:-.02em}
.book p{margin:0;color:var(--mute)}
.row{display:flex;justify-content:space-between;align-items:center;margin-top:auto;padding-top:10px;gap:8px}
.row select{padding:6px 10px;font-size:.85rem}
.stars button{background:none;padding:0 1px;color:var(--line);font-size:1.15rem}
.stars button.on{color:var(--want)}
.empty{grid-column:1/-1;text-align:center;color:var(--mute);padding:48px 12px;border:2px dashed var(--line);border-radius:var(--r)}
#toast{position:fixed;left:50%;bottom:22px;transform:translate(-50%,80px);background:var(--ink);color:var(--bg);padding:10px 18px;border-radius:99px;transition:transform .3s}
#toast.show{transform:translate(-50%,0)}
@media(prefers-reduced-motion:reduce){*{transition:none!important}}
</style></head><body><div class="wrap">
<div class="top"><div><h1>Shelf</h1><p class="tag">Track what you want to read, what you're in the middle of, and what you finished.</p></div>
<div><div class="stats" id="bar"></div><div class="legend" id="legend"></div></div></div>

<form class="add" id="f">
 <input name="title" placeholder="Book title" required aria-label="Title" maxlength="200">
 <input name="author" placeholder="Author" aria-label="Author" maxlength="120">
 <select name="status" aria-label="Status"><option value="want">Want to read</option><option value="reading">Reading</option><option value="done">Finished</option></select>
 <button class="primary">Add book</button>
</form>

<div class="bar"><input id="q" type="search" placeholder="Search title or author" aria-label="Search">
 <button class="chip" data-s="" aria-pressed="true">All</button>
 <button class="chip" data-s="want" aria-pressed="false">Want</button>
 <button class="chip" data-s="reading" aria-pressed="false">Reading</button>
 <button class="chip" data-s="done" aria-pressed="false">Finished</button></div>
<div class="grid" id="grid"></div></div><div id="toast" role="status"></div>
<script>
const COL={want:'var(--want)',reading:'var(--reading)',done:'var(--done)'},LBL={want:'Want to read',reading:'Reading',done:'Finished'};
let status='',timer;
const $=s=>document.querySelector(s);
const api=async(u,o={})=>{const r=await fetch(u,{headers:{'Content-Type':'application/json'},...o});const j=await r.json();if(!r.ok)throw Error(j.error||'Request failed');return j};
const toast=m=>{const t=$('#toast');t.textContent=m;t.classList.add('show');clearTimeout(timer);timer=setTimeout(()=>t.classList.remove('show'),2200)};
const esc=s=>s.replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
async function stats(){const s=await api('/api/stats'),t=Object.values(s).reduce((a,b)=>a+b,0)||1;
 $('#bar').innerHTML=Object.keys(LBL).map(k=>`<i style="flex:${s[k]/t};background:${COL[k]}"></i>`).join('');
 $('#legend').innerHTML=Object.keys(LBL).map(k=>`<span><span class="dot" style="background:${COL[k]}"></span><b>${s[k]}</b> ${LBL[k].toLowerCase()}</span>`).join('')}
async function load(){const p=new URLSearchParams({status,q:$('#q').value});const b=await api('/api/books?'+p);
 $('#grid').innerHTML=b.length?b.map(x=>`<article class="book" style="--c:${COL[x.status]}"><h3>${esc(x.title)}</h3><p>${esc(x.author)||'Unknown author'}</p>
 <div class="stars" aria-label="Rating">${[1,2,3,4,5].map(n=>`<button class="${n<=x.rating?'on':''}" onclick="up(${x.id},{rating:${x.rating===n?0:n}})" aria-label="${n} stars">★</button>`).join('')}</div>
 <div class="row"><select onchange="up(${x.id},{status:this.value})" aria-label="Status">${Object.keys(LBL).map(k=>`<option value="${k}" ${k===x.status?'selected':''}>${LBL[k]}</option>`).join('')}</select>
 <button class="ghost" onclick="del(${x.id})">Remove</button></div></article>`).join('')
 :'<div class="empty">Nothing here yet. Add a book above to start your shelf.</div>';stats()}
const up=(id,d)=>api('/api/books/'+id,{method:'PUT',body:JSON.stringify(d)}).then(load).catch(e=>toast(e.message));
const del=id=>api('/api/books/'+id,{method:'DELETE'}).then(()=>{toast('Book removed');load()});
$('#f').onsubmit=async e=>{e.preventDefault();const d=Object.fromEntries(new FormData(e.target));
 try{await api('/api/books',{method:'POST',body:JSON.stringify(d)});e.target.reset();toast('Book added');load()}catch(x){toast(x.message)}};
$('#q').oninput=()=>{clearTimeout(window.d);window.d=setTimeout(load,200)};
document.querySelectorAll('.chip').forEach(c=>c.onclick=()=>{status=c.dataset.s;document.querySelectorAll('.chip').forEach(o=>o.setAttribute('aria-pressed',o===c));load()});
load();
</script></body></html>"""

if __name__ == "__main__":
    init()
    print("Shelf running at http://localhost:8000  (Ctrl+C to stop)")
    ThreadingHTTPServer(("0.0.0.0", 8000), H).serve_forever()