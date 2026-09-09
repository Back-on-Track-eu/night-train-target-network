"""gate_page.py — the HTML the gate serves.

Split out of ``gate.py`` for one reason: ``gate.py`` imports Flask, jwt and
psycopg2, so anything that touches it needs the whole backend environment. The
page is pure string assembly and has no business being that expensive to test —
``page_html()`` takes a clock and returns a document, and
``tests/test_76_gate_page.py`` exercises it with nothing but the standard library.

That matters here more than usual. The mockup this page came from shipped with a
strikethrough across its own slogan, a Google Fonts hotlink, and two public
figures that contradicted the repository, and none of it was caught because
nobody could cheaply render the thing and look at it.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from html import escape

from api.gate_logo import BOT_LOGO_B64

# Launch: the tool opens publicly at InnoTrans. Held here as one aware datetime so
# the server and the browser cannot disagree about it — the countdown is rendered
# client-side, but whether the page is in its "counting down" or "open" state is
# decided here, so a visitor with a wrong clock still sees the right page.
LAUNCH = datetime(2026, 9, 22, 10, 0, tzinfo=timezone(timedelta(hours=2)))  # 10:00 CEST

# Palette and type are taken from the app rather than invented: the hexes are
# frontend/src/style.css's @theme block (sapphire / sky-blue / sulphur-yellow), and
# the muted inks are opacities of --greenish-grey so nothing drifts off-palette.
#
# No webfont. The app's Mark Pro is bundled by Vite behind forward_auth, so this page
# cannot reach it, and a 150 KB base64 TTF in a Python module is a bad trade for one
# typeface on the page that has to render before anything else. Deliberately NOT
# Google Fonts: this is the most public URL Back-on-Track has and hotlinking
# fonts.gstatic.com would ship every visitor's IP to Google, which an AISBL acting as
# its own data controller should not do for a font.
_PAGE = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Target Network — opens 22 September</title>
<meta name="description" content="Back-on-Track's Target Network opens 22 September 2026, 10:00 CEST, live from InnoTrans in Berlin.">
<!-- No <link rel="icon">: the badge is already inlined once below, and this page is
     no-store, so a second copy would be 18 KB re-sent on every render for a favicon. -->
<style>
 :root{
   color-scheme:dark;
   --bg:#1d1e33; --surface:#23263d; --surface-2:#2b2e4a;
   --ink:#f1f3f6; --ink-2:rgba(241,243,246,.74); --muted:rgba(241,243,246,.52);
   --line:rgba(241,243,246,.14);
   --blue:#2271b3; --blue-lift:#2f88d2; --yellow:#eaf044; --green:#92d051;
 }
 *{box-sizing:border-box}
 body{margin:0;background:var(--bg);color:var(--ink);
      font:16px/1.6 system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
 .wrap{max-width:60rem;margin:0 auto;padding:0 1.75rem}
 a{color:inherit}
 header{display:flex;align-items:center;gap:1rem;padding:2.25rem 0 0}
 header img{width:3.25rem;height:3.25rem;flex:none;border-radius:50%}
 header b{display:block;font-size:1.2rem;letter-spacing:.01em}
 header span{display:block;font-size:.8rem;color:var(--muted);line-height:1.35}
 .hero{padding:4rem 0 .5rem;text-align:center}
 h1{margin:0 0 .8rem;font-weight:600;letter-spacing:-.01em;line-height:1.15;
    font-size:clamp(1.9rem,4.4vw,3rem)}
 .when{margin:0 0 2.4rem;color:var(--ink-2);font-size:clamp(.95rem,1.6vw,1.05rem)}
 .when em{font-style:normal;color:var(--yellow)}
 .clock{display:flex;justify-content:center;align-items:flex-start;gap:clamp(.5rem,3vw,2rem)}
 .unit{min-width:clamp(3.5rem,10vw,6.5rem)}
 .unit b{display:block;font-weight:500;font-variant-numeric:tabular-nums;line-height:1;
         letter-spacing:-.02em;font-size:clamp(2.6rem,9vw,5.2rem)}
 .unit small{display:block;margin-top:.6rem;font-size:.78rem;color:var(--muted)}
 .sep{color:var(--blue-lift);font-weight:300;line-height:1.15;font-size:clamp(1.8rem,6vw,3.4rem)}
 .live{margin:1.6rem 0 0;font-size:.82rem;color:var(--muted)}
 .open{display:inline-block;margin:.5rem 0 0;padding:.85rem 2rem;border-radius:.5rem;
       background:var(--blue);color:#fff;text-decoration:none;font-size:1.05rem}
 .open:hover{background:var(--blue-lift)}
 .vision{max-width:38rem;margin:4.5rem auto 0;text-align:center}
 .vision p{margin:0 0 1rem;color:var(--ink-2);font-size:1.02rem}
 .vision p:first-child{color:var(--ink);font-size:1.18rem;line-height:1.5}
 .vision a{text-decoration:none;border-bottom:1px solid var(--green);padding-bottom:2px}
 footer{margin:5.5rem 0 0;border-top:1px solid var(--line);padding:1.9rem 0 4.5rem;
        display:flex;flex-wrap:wrap;gap:1.1rem;justify-content:space-between;align-items:center}
 footer .left{font-size:.86rem;color:var(--muted)}
 .codelink{background:none;border:0;padding:0;cursor:pointer;font:inherit;font-size:.86rem;
           color:var(--muted);text-decoration:underline;text-underline-offset:4px}
 .codelink:hover{color:var(--ink-2)}
 .codebox{display:none;width:100%;margin-top:.5rem;background:var(--surface);
          border:1px solid var(--line);border-radius:.7rem;padding:1.1rem 1.2rem}
 .codebox.open{display:block}
 .codebox p{margin:0 0 .75rem;font-size:.84rem;color:var(--muted)}
 .codebox form{display:flex;gap:.6rem;flex-wrap:wrap}
 .codebox input{flex:1 1 14rem;background:var(--bg);border:1px solid var(--line);
                border-radius:.45rem;color:var(--ink);padding:.7rem .8rem;font:inherit;
                font-size:.95rem;letter-spacing:.04em}
 .codebox input::placeholder{color:var(--muted)}
 .codebox button{background:var(--blue);border:0;color:#fff;font:inherit;font-size:.95rem;
                 padding:.7rem 1.6rem;border-radius:.45rem;cursor:pointer}
 .codebox button:hover{background:var(--blue-lift)}
 .err{margin-top:.9rem;padding:.6rem .8rem;border-radius:.45rem;background:#3b1d22;
      border:1px solid #612b33;color:#f3c4c9;font-size:.88rem}
 :focus-visible{outline:2px solid var(--yellow);outline-offset:3px}
 @media (max-width:34rem){.clock{gap:.25rem}footer{flex-direction:column;align-items:flex-start}}
 @media (prefers-reduced-motion:reduce){*{transition:none!important;animation:none!important}}
</style></head><body>
<div class="wrap">

  <header>
    <img src="data:image/png;base64,__LOGO__" alt="Back-on-Track">
    <div>
      <b>Back-on-Track.eu</b>
      <span>European network to promote cross-border night trains</span>
    </div>
  </header>

  <section class="hero">__HERO__</section>

  <section class="vision">
    <p>Europe ran about 100 night train lines in 2025. Back-on-Track is working
       towards 300 by 2035 — enough to triple the number of night train passengers.</p>
    <p>The Target Network turns that goal into an actual network: routes carrying the
       timetable, the running costs and the emissions saved behind each one, running
       overwhelmingly on track that already exists. From 22 September you can sketch
       your own route, run the same numbers on it, and add it to the evidence.</p>
    <p><a href="https://back-on-track.eu/back-on-track-europes-general-position-paper/">Read
       the position paper behind these numbers</a></p>
  </section>

  <footer>
    <div class="left">Back-on-Track — <a href="https://back-on-track.eu">back-on-track.eu</a></div>
    <div>
      <button class="codelink" id="toggle" aria-expanded="__EXPANDED__" aria-controls="codebox">Testing the beta? Enter your code</button>
      <div class="codebox__OPENCLS__" id="codebox">
        <p>Closed beta access. Enter the testing code you were given — after the gate
           you sign in with your email, as a real user would.</p>
        <form method="POST" action="/api/gate/redeem">
          <input id="code" name="code" autocomplete="off" autocapitalize="off"
                 spellcheck="false" required placeholder="e.g. nt-4f7a2b"
                 aria-label="Testing code">
          <button type="submit">Enter</button>
        </form>
        __ERROR__
      </div>
    </div>
  </footer>

</div>
<script>
(function(){
  var clock = document.getElementById("clock");
  if (clock) {
    // Target is emitted by the server from gate.LAUNCH, so there is one source for it.
    var target = new Date(clock.dataset.target).getTime();
    var el = {d:"d",h:"h",m:"m",s:"s"};
    for (var k in el) el[k] = document.getElementById(el[k]);
    var pad = function(n){ return String(n).padStart(2,"0"); };
    var tick = function(){
      var left = Math.max(0, target - Date.now());
      var t = Math.floor(left/1000);
      el.d.textContent = Math.floor(t/86400);
      el.h.textContent = pad(Math.floor(t/3600)%24);
      el.m.textContent = pad(Math.floor(t/60)%60);
      el.s.textContent = pad(t%60);
      // David's note 1: at zero the block becomes a single way in, without a reload.
      if (left === 0) {
        clearInterval(timer);
        var hero = document.querySelector(".hero");
        if (hero) hero.innerHTML =
          '<h1>The Target Network is open</h1>' +
          '<p class="when">Sketch a night train Europe is missing, and run the numbers on it.</p>' +
          '<a class="open" href="/">Open the Target Network</a>';
      }
    };
    tick();
    var timer = setInterval(tick, 1000);
  }
  var t = document.getElementById("toggle"), box = document.getElementById("codebox");
  t.addEventListener("click", function(){
    var open = box.classList.toggle("open");
    t.setAttribute("aria-expanded", open);
    if (open) document.getElementById("code").focus();
  });
})();
</script>
</body></html>
"""

# Counting down. aria-live is off on purpose: a per-second live region makes a screen
# reader unusable, and the launch date is already stated in the sentence above it.
_HERO_COUNTDOWN = """<h1>Target Network opens in</h1>
    <p class="when">22 September 2026, 10:00 CEST — live from <em>InnoTrans, Berlin</em></p>
    <div class="clock" id="clock" data-target="{target}" aria-live="off">
      <div class="unit"><b id="d">–</b><small>days</small></div>
      <div class="sep">:</div>
      <div class="unit"><b id="h">–</b><small>hours</small></div>
      <div class="sep">:</div>
      <div class="unit"><b id="m">–</b><small>minutes</small></div>
      <div class="sep">:</div>
      <div class="unit"><b id="s">–</b><small>seconds</small></div>
    </div>
    <p class="live">Come back on the 22nd — no sign-up needed to look around.</p>"""

# Launched. Rendered server-side so it does not depend on the visitor's clock, and so
# the page still says the right thing with JavaScript disabled.
_HERO_OPEN = """<h1>The Target Network is open</h1>
    <p class="when">Sketch a night train Europe is missing, and run the numbers on it.</p>
    <a class="open" href="/">Open the Target Network</a>"""


def page_html(error: str | None = None, now: datetime | None = None) -> str:
    """The gate page.

    ``now`` is injectable so the countdown/launched switch is testable without
    waiting for September. An error opens the code box, because that is what the
    reader was doing when it happened.
    """
    moment = now or datetime.now(timezone.utc)
    hero = (
        _HERO_COUNTDOWN.format(target=LAUNCH.isoformat())
        if moment < LAUNCH
        else _HERO_OPEN
    )
    block = f'<div class="err">{escape(error)}</div>' if error else ""
    return (
        _PAGE.replace("__HERO__", hero)
        .replace("__ERROR__", block)
        .replace("__LOGO__", BOT_LOGO_B64)
        .replace("__OPENCLS__", " open" if error else "")
        .replace("__EXPANDED__", "true" if error else "false")
    )
