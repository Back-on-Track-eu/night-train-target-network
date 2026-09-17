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

Since 2026-09-16 the page carries the launch press text and one slideshow: the
walkthrough video followed by the builder screenshots, advancing on its own. The
media files live next to this module in ``gate_media/`` and are served by
``gate.py`` under ``MEDIA_URL`` — a path Caddy already leaves open (``@open path
/gate /gate/*``), so nothing about the deploy had to change. ``GALLERY`` below is
the single list the page, the tests and the handover refer to.

The media is not in git: ``scripts/fetch_gate_media.py`` puts it there from Drive
at image build (and by hand for a host-run stack). A slide whose file is absent is
left out, and with nothing on disk the slideshow section is left out altogether —
a failed fetch degrades to the text, never to broken pictures.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta, timezone
from html import escape
from pathlib import Path
from typing import NamedTuple

from api.gate_logo import BOT_LOGO_B64

# Launch: the tool opens publicly at InnoTrans. Held here as one aware datetime so
# the server and the browser cannot disagree about it — the countdown is rendered
# client-side, but whether the page is in its "counting down" or "open" state is
# decided here, so a visitor with a wrong clock still sees the right page. Every
# date the page *says* ("22 September", the <title>, the hero line) is derived
# from this constant too, so moving the launch is a one-line change.
LAUNCH = datetime(2026, 9, 22, 10, 0, tzinfo=timezone(timedelta(hours=2), "CEST"))

# Media the page embeds. Files sit in gate_media/ beside this module (gitignored,
# fetched by scripts/fetch_gate_media.py); gate.py serves that directory at
# MEDIA_URL. Both are here rather than in gate.py so the page, its tests and the
# fetch script can check the files without importing Flask.
MEDIA_DIR = Path(__file__).with_name("gate_media")
MEDIA_URL = "/gate/media"


class GalleryItem(NamedTuple):
    """One screenshot, ``<stem>.jpg`` in gate_media/."""

    stem: str
    caption: str


# Slideshow order after the video: the order a user meets the screens, from the
# landing page through a sketched route to the figures behind it. Captions describe
# what the screen shows, not what it costs — numbers on screenshots change with
# every calibration.
GALLERY: tuple[GalleryItem, ...] = (
    GalleryItem(
        "landing",
        "The landing page: suggest a route, or browse what others have drawn.",
    ),
    GalleryItem(
        "sketch",
        "Sketch a route on the real rail map — here Paris to Vienna, stop by stop.",
    ),
    GalleryItem(
        "evaluating", "Evaluate: the tool builds the timetable and runs the numbers."
    ),
    GalleryItem(
        "evaluated",
        "Done in seconds: the CO₂ saved per year, and the choice to keep the proposal or carry on as a guest.",
    ),
    GalleryItem(
        "proposal",
        "The proposal: a timetable for every stop, route statistics, both directions.",
    ),
    GalleryItem(
        "scenarios",
        "Scenario and main figures: journey time, passengers, public money needed, CO₂ saved — compared across scenarios.",
    ),
    GalleryItem(
        "infrastructure",
        "Infrastructure: track access, station charges, parking and energy, line by line.",
    ),
    GalleryItem(
        "composition",
        "Train composition: twelve to choose from, with the full operating costs behind each.",
    ),
)

# The walkthrough opens the slideshow: walkthrough.mp4 + walkthrough-poster.jpg.
VIDEO = GalleryItem(
    "walkthrough", "Berlin to Oslo: pick the stops, evaluate, read the numbers."
)

# Seconds an image slide stays before the show moves on. The video slide moves on
# when the video ends (or after this long if the browser refused to play it).
SLIDE_SECONDS = 6


def media_files() -> list[str]:
    """Every file name the page references, for the on-disk check in the tests."""
    return [f"{VIDEO.stem}.mp4", f"{VIDEO.stem}-poster.jpg"] + [
        f"{item.stem}.jpg" for item in GALLERY
    ]


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
<title>Target Network — opens __DAY__</title>
<meta name="description" content="Back-on-Track's Night Train Target Network Tool opens __WHEN__, live from InnoTrans in Berlin. Free, open source, and anyone can draw a night train route on the real European rail map.">
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
 h2{margin:0 0 1rem;font-weight:600;letter-spacing:-.01em;line-height:1.25;
    font-size:clamp(1.3rem,2.4vw,1.7rem)}
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
 .lead{max-width:44rem;margin:4rem auto 0;text-align:center}
 .lead p{margin:0;color:var(--ink);font-size:clamp(1.05rem,1.8vw,1.22rem);line-height:1.55}
 .story{max-width:44rem;margin:0 auto}
 .story section{margin:3.75rem 0 0}
 .story p{margin:0 0 1rem;color:var(--ink-2);font-size:1.02rem}
 .story a{text-decoration:none;border-bottom:1px solid var(--green);padding-bottom:2px}
 blockquote{margin:1.6rem 0;padding:1.1rem 1.3rem;border-left:3px solid var(--yellow);
            background:var(--surface);border-radius:0 .7rem .7rem 0}
 blockquote p{margin:0 0 .6rem;color:var(--ink);font-size:1.05rem;line-height:1.5}
 blockquote footer{margin:0;padding:0;border:0;display:block;font-size:.86rem;color:var(--muted)}
 figure{margin:0}
 figcaption{margin-top:.55rem;font-size:.84rem;color:var(--muted);line-height:1.45}
 /* The slideshow. Without JavaScript every slide is laid out in turn (a plain
    stacked gallery); the html.js class switches to one slide at a time. */
 .show{margin:3.25rem 0 0}
 .stage{position:relative;border-radius:.8rem;overflow:hidden;background:var(--surface);
        border:1px solid var(--line)}
 .js .stage{height:0;padding-bottom:66.667%}
 .slide{margin:0}
 .js .slide{position:absolute;inset:0}
 .js .slide:not(.active){display:none}
 .slide img,.slide video{display:block;width:100%;height:auto}
 .js .slide img,.js .slide video{height:100%;object-fit:contain;background:var(--surface)}
 .js .slide figcaption{display:none}
 .caption{min-height:2.6em}
 .nav{display:none;align-items:center;gap:.9rem;margin-top:.7rem}
 .js .nav{display:flex}
 .nav button{background:var(--surface-2);border:1px solid var(--line);color:var(--ink);
             width:2.4rem;height:2.4rem;border-radius:50%;cursor:pointer;font-family:inherit;
             font-size:1.1rem;line-height:1}
 .nav button:hover{border-color:var(--blue-lift)}
 .dots{display:flex;gap:.45rem;flex-wrap:wrap;margin:0 auto 0 .3rem;padding:0;list-style:none}
 .dots button{width:.62rem;height:.62rem;padding:0;border:0;border-radius:50%;
              background:var(--muted);cursor:pointer}
 .dots button[aria-current="true"]{background:var(--yellow)}
 .nav .count{font-size:.8rem;color:var(--muted);font-variant-numeric:tabular-nums}
 footer.site{margin:5.5rem 0 0;border-top:1px solid var(--line);padding:1.9rem 0 4.5rem;
        display:flex;flex-wrap:wrap;gap:1.1rem;justify-content:space-between;align-items:center}
 footer.site .left{font-size:.86rem;color:var(--muted)}
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
 @media (max-width:34rem){.clock{gap:.25rem}footer.site{flex-direction:column;align-items:flex-start}
                          .gallery{grid-template-columns:1fr}}
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

  <section class="lead">
    <p>On __DAY__, the first day of InnoTrans, Back-on-Track will launch the public
       beta of its Night Train Target Network Tool. The tool is free and open source.
       Anyone can use it to draw night train routes on a real map of the European rail
       network. The tool then shows right away what each route would cost and how much
       CO<sub>2</sub> it would save. The best designs will feed into a study for a
       European night train network in 2032. The study will be presented to the
       European Commission (DG MOVE) and to national transport authorities.</p>
  </section>

__SHOW__
  <div class="story">

    <section>
      <h2>Double the connections, triple the passengers</h2>
      <p>Back-on-Track wants to double the number of night train connections in Europe,
         from about 150 today to 300, and to triple the number of night train passengers
         by 2032. Night trains are the best choice for many journeys between 500 and
         3,000&nbsp;km. If Europe reaches these goals, night trains could avoid around
         0.3% of the total greenhouse gas emissions of the EU.</p>
      <p><a href="https://back-on-track.eu/back-on-track-europes-general-position-paper/">Read
         the position paper behind these numbers</a></p>
      <blockquote>
        <p>“The tracks exist and the demand exists. 70% of Europeans are ready to swap
           the plane for a night train. What is missing is a good network design and the
           political will to build it. Our tool shows which routes Europe should add.”</p>
        <footer>Juri Maier, Chairperson Back-on-Track Europe</footer>
      </blockquote>
      <p>The tool was built by ten Back-on-Track volunteers from across Europe. It is
         published under a GPL licence, so anyone can check every number and every step
         of the model. While the rail industry meets at InnoTrans in Berlin, a team of
         volunteers is publishing a planning tool that everyone can use for free.</p>
    </section>

    <section>
      <h2>Network planning as a game</h2>
      <p>The beta turns network planning into a game. Users take the role of a network
         planner. They draw routes on a real map of the rail network. The tool then
         creates realistic timetables and tests twelve different train compositions. It
         shows the full operating costs, the public money needed, and the CO<sub>2</sub>
         that would be saved. Users can compare results across standard scenarios and
         share them with the community. The goal behind the game is serious: a study with
         open data and an open method that decision makers can trust.</p>
      <blockquote>
        <p>“Crowdsourcing is the key. The knowledge for this network does not sit in one
           office. Travellers know which connections Europe is missing. Operators and
           infrastructure experts carry knowledge that no consultancy could bring together
           alone. And a proposal the community built is one the community will defend.”</p>
        <footer>David Wedekind, Project Lead Target Network</footer>
      </blockquote>
    </section>

    <section>
      <h2>The first of five steps</h2>
      <p>The tool is the first step of a five step process. From __DAY__, Back-on-Track
         will collect route designs from users. The next steps are feedback, the choice of
         the strongest routes as the backbone of the target network, and a final study with
         a public interactive map. All contributors will be credited. Through 2026, the
         tool will get new features, such as the planned 2032 rail network, policy
         simulations, and full network analysis.</p>
    </section>

  </div>

  <footer class="site">
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
  document.documentElement.classList.add("js");
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

  // The slideshow. Images hold for SLIDE_SECONDS; the video plays through once
  // (muted, so browsers allow it) and the show moves on when it ends. Any tap on
  // the controls hands the wheel to the reader: the timer stops for good. With a
  // reduced-motion preference nothing moves by itself and the video waits for its
  // play button.
  var show = document.getElementById("show");
  if (show) {
    var slides = show.querySelectorAll(".slide"),
        caption = document.getElementById("caption"),
        dots = document.getElementById("dots"),
        count = document.getElementById("count"),
        hold = Number(show.dataset.seconds) * 1000,
        still = window.matchMedia("(prefers-reduced-motion: reduce)").matches,
        auto = !still, current = 0, timer = null,
        each = function(list, fn){ Array.prototype.forEach.call(list, fn); };
    each(slides, function(_, i){
      var li = document.createElement("li"), b = document.createElement("button");
      b.type = "button";
      b.setAttribute("aria-label", "Picture " + (i + 1));
      b.addEventListener("click", function(){ auto = false; go(i); });
      li.appendChild(b); dots.appendChild(li);
    });
    var later = function(){
      clearTimeout(timer);
      if (auto) timer = setTimeout(function(){ go(current + 1); }, hold);
    };
    var go = function(n){
      clearTimeout(timer);
      var leaving = slides[current].querySelector("video");
      if (leaving) leaving.pause();
      current = (n + slides.length) % slides.length;
      each(slides, function(s, i){ s.classList[i === current ? "add" : "remove"]("active"); });
      each(dots.querySelectorAll("button"), function(b, i){
        b.setAttribute("aria-current", i === current ? "true" : "false");
      });
      caption.textContent = slides[current].querySelector("figcaption").textContent;
      count.textContent = (current + 1) + " / " + slides.length;
      var video = slides[current].querySelector("video");
      if (!video) return later();
      video.currentTime = 0;
      video.onended = function(){ if (auto) go(current + 1); };
      if (still) return;
      var playing = video.play();
      // A refused autoplay (data saver, a strict browser) must not stall the show.
      if (playing && playing.catch) playing.catch(later);
    };
    document.getElementById("prev").addEventListener("click", function(){ auto = false; go(current - 1); });
    document.getElementById("next").addEventListener("click", function(){ auto = false; go(current + 1); });
    go(0);
  }

  var t = document.getElementById("toggle"), codebox = document.getElementById("codebox");
  t.addEventListener("click", function(){
    var open = codebox.classList.toggle("open");
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
    <p class="when">{when} — live from <em>InnoTrans, Berlin</em></p>
    <div class="clock" id="clock" data-target="{target}" aria-live="off">
      <div class="unit"><b id="d">–</b><small>days</small></div>
      <div class="sep">:</div>
      <div class="unit"><b id="h">–</b><small>hours</small></div>
      <div class="sep">:</div>
      <div class="unit"><b id="m">–</b><small>minutes</small></div>
      <div class="sep">:</div>
      <div class="unit"><b id="s">–</b><small>seconds</small></div>
    </div>
    <p class="live">Come back on {day} — no sign-up needed to look around.</p>"""

# Launched. Rendered server-side so it does not depend on the visitor's clock, and so
# the page still says the right thing with JavaScript disabled.
_HERO_OPEN = """<h1>The Target Network is open</h1>
    <p class="when">Sketch a night train Europe is missing, and run the numbers on it.</p>
    <a class="open" href="/">Open the Target Network</a>"""

# The slideshow section. Emitted only when at least one slide has its files.
_SHOW = """
  <section class="show" id="show" data-seconds="{seconds}" aria-roledescription="slideshow"
           aria-label="The tool in pictures">
    <div class="stage">{slides}
    </div>
    <p class="caption" id="caption"></p>
    <div class="nav">
      <button type="button" id="prev" aria-label="Previous">&#8249;</button>
      <button type="button" id="next" aria-label="Next">&#8250;</button>
      <ul class="dots" id="dots"></ul>
      <span class="count" id="count"></span>
    </div>
  </section>
"""

_IMAGE_SLIDE = """
      <figure class="slide">
        <img src="{src}" alt="{caption}" decoding="async">
        <figcaption>{caption}</figcaption>
      </figure>"""

# No autoplay attribute: the script starts it when its slide is up, and without
# the script it is a poster with a play button.
_VIDEO_SLIDE = """
      <figure class="slide">
        <video src="{src}" poster="{poster}" controls muted playsinline preload="metadata"
               aria-label="{caption}"></video>
        <figcaption>{caption}</figcaption>
      </figure>"""


def launch_day() -> str:
    """'22 September' — the day as the page writes it."""
    return f"{LAUNCH.day} {LAUNCH:%B}"


def launch_when() -> str:
    """'22 September 2026, 10:00 CEST' — the moment as the page writes it."""
    return f"{launch_day()} {LAUNCH:%Y, %H:%M} {LAUNCH.tzname()}"


def _show_html(media_dir: Path) -> str:
    """The slideshow: the video first, then the screenshots in GALLERY order —
    each only if its file is on disk. Empty when nothing is."""
    slides = ""
    if all(
        (media_dir / f"{VIDEO.stem}{ext}").is_file() for ext in (".mp4", "-poster.jpg")
    ):
        slides += _VIDEO_SLIDE.format(
            src=f"{MEDIA_URL}/{VIDEO.stem}.mp4",
            poster=f"{MEDIA_URL}/{VIDEO.stem}-poster.jpg",
            caption=escape(VIDEO.caption, quote=True),
        )
    slides += "".join(
        _IMAGE_SLIDE.format(
            src=f"{MEDIA_URL}/{item.stem}.jpg",
            caption=escape(item.caption, quote=True),
        )
        for item in GALLERY
        if (media_dir / f"{item.stem}.jpg").is_file()
    )
    return _SHOW.format(seconds=SLIDE_SECONDS, slides=slides) if slides else ""


def slideshow_enabled() -> bool:
    """Whether the page embeds the slideshow at all.

    Off unless ``GATE_SLIDESHOW=on`` (Coolify env). Decided 2026-09-17 with Juri:
    the launch gate carries the press text only; the video and screenshots go
    out in the media package instead. The files stay on disk and stay served
    under ``MEDIA_URL`` either way, so the press package can link them.
    """
    return os.environ.get("GATE_SLIDESHOW", "off").strip().lower() in (
        "on",
        "1",
        "true",
        "yes",
    )


def page_html(
    error: str | None = None,
    now: datetime | None = None,
    media_dir: Path = MEDIA_DIR,
    show: bool | None = None,
) -> str:
    """The gate page.

    ``now`` is injectable so the countdown/launched switch is testable without
    waiting for September; ``media_dir`` so both slideshow states are testable
    whatever happens to be on disk; ``show`` overrides the ``GATE_SLIDESHOW``
    switch (see ``slideshow_enabled``). An error opens the code box, because
    that is what the reader was doing when it happened.
    """
    if show is None:
        show = slideshow_enabled()
    moment = now or datetime.now(UTC)
    hero = (
        _HERO_COUNTDOWN.format(
            target=LAUNCH.isoformat(), when=launch_when(), day=launch_day()
        )
        if moment < LAUNCH
        else _HERO_OPEN
    )
    block = f'<div class="err">{escape(error)}</div>' if error else ""
    return (
        _PAGE.replace("__HERO__", hero)
        .replace("__SHOW__", _show_html(media_dir) if show else "")
        .replace("__DAY__", launch_day())
        .replace("__WHEN__", launch_when())
        .replace("__ERROR__", block)
        .replace("__LOGO__", BOT_LOGO_B64)
        .replace("__OPENCLS__", " open" if error else "")
        .replace("__EXPANDED__", "true" if error else "false")
    )
