import os
import time
import json
import re
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

import requests
from flask import Flask, jsonify
from flask_cors import CORS

# =========================
# Config
# =========================
ODDS_API_KEY = os.getenv("ODDS_API_KEY", "d8ba5d45eca27e710d7ef2680d8cb452")
ODDS_BASE_URL = "https://api.the-odds-api.com/v4"

TEAM_PROJECTIONS_URL = os.getenv(
    "TEAM_PROJECTIONS_URL",
    "https://nfl-team-td-projections-production.up.railway.app/team-analysis",
)

BOOKMAKER_PRIORITY = [
    "fanduel", "betmgm", "caesars", "betrivers", "williamhill_us",
    "draftkings", "fanatics", "windcreek", "espnbet", "ballybet"
]

CACHE_TTL_SECS = int(os.getenv("CACHE_TTL_SECS", "3600"))  # 1 hour cache
UNKNOWN_TEAM_MODE = os.getenv("UNKNOWN_TEAM_MODE", "none").lower()  # none|average|home|away

# =========================
# Team name → abbreviation (support city+mascot AND nickname-only)
# =========================
TEAM_CITY_TO_ABBR = {
    "Arizona Cardinals":"ARI","Atlanta Falcons":"ATL","Baltimore Ravens":"BAL","Buffalo Bills":"BUF",
    "Carolina Panthers":"CAR","Chicago Bears":"CHI","Cincinnati Bengals":"CIN","Cleveland Browns":"CLE",
    "Dallas Cowboys":"DAL","Denver Broncos":"DEN","Detroit Lions":"DET","Green Bay Packers":"GB",
    "Houston Texans":"HOU","Indianapolis Colts":"IND","Jacksonville Jaguars":"JAX","Kansas City Chiefs":"KC",
    "Los Angeles Rams":"LAR","Miami Dolphins":"MIA","Minnesota Vikings":"MIN","New England Patriots":"NE",
    "New Orleans Saints":"NO","New York Giants":"NYG","New York Jets":"NYJ","Las Vegas Raiders":"LV",
    "Philadelphia Eagles":"PHI","Pittsburgh Steelers":"PIT","Los Angeles Chargers":"LAC",
    "San Francisco 49ers":"SF","Seattle Seahawks":"SEA","Tampa Bay Buccaneers":"TB",
    "Tennessee Titans":"TEN","Washington Commanders":"WAS",
}
TEAM_NICK_TO_ABBR = {
    "Cardinals":"ARI","Falcons":"ATL","Ravens":"BAL","Bills":"BUF","Panthers":"CAR","Bears":"CHI",
    "Bengals":"CIN","Browns":"CLE","Cowboys":"DAL","Broncos":"DEN","Lions":"DET","Packers":"GB",
    "Texans":"HOU","Colts":"IND","Jaguars":"JAX","Chiefs":"KC","Rams":"LAR","Dolphins":"MIA",
    "Vikings":"MIN","Patriots":"NE","Saints":"NO","Giants":"NYG","Jets":"NYJ","Raiders":"LV",
    "Eagles":"PHI","Steelers":"PIT","Chargers":"LAC","49ers":"SF","Seahawks":"SEA","Buccaneers":"TB",
    "Titans":"TEN","Commanders":"WAS",
}
TEAM_NAME_TO_ABBR = {**TEAM_CITY_TO_ABBR, **TEAM_NICK_TO_ABBR}

# =========================
# Embedded Top-200 (from your message)
# =========================
TOP200_BLOB = r"""
WR Ja'Marr Chase, Bengals
RB Bijan Robinson, Falcons
RB Saquon Barkley, Eagles
WR Justin Jefferson, Vikings
RB Jahmyr Gibbs, Lions
WR CeeDee Lamb, Cowboys
WR Amon-Ra St. Brown, Lions
WR Puka Nacua, Rams
WR Malik Nabers, Giants
RB Derrick Henry, Ravens
WR Nico Collins, Texans
RB De'Von Achane, Dolphins
RB Ashton Jeanty, Raiders
WR A.J. Brown, Eagles
RB Christian McCaffrey, 49ers
TE Brock Bowers, Raiders
WR Brian Thomas Jr., Jaguars
WR Jaxon Smith-Njigba, Seahawks
RB Chase Brown, Bengals
RB Jonathan Taylor, Colts
WR Ladd McConkey, Chargers
TE Trey McBride, Cardinals
RB Kyren Williams, Rams
RB Bucky Irving, Buccaneers
QB Lamar Jackson, Ravens
WR Drake London, Falcons
QB Jalen Hurts, Eagles
QB Jayden Daniels, Commanders
RB Josh Jacobs, Packers
QB Josh Allen, Bills
WR Terry McLaurin, Commanders
WR Tyreek Hill, Dolphins
WR Tee Higgins, Bengals
RB Breece Hall, Jets
TE George Kittle, 49ers
WR Mike Evans, Buccaneers
RB James Cook, Bills
WR Davante Adams, Rams
WR Garrett Wilson, Jets
RB Kenneth Walker III, Seahawks
WR DJ Moore, Bears
RB James Conner, Cardinals
WR Marvin Harrison Jr., Cardinals
WR DeVonta Smith, Eagles
RB Alvin Kamara, Saints
WR Courtland Sutton, Broncos
WR DK Metcalf, Steelers
WR Jameson Williams, Lions
RB Chuba Hubbard, Panthers
WR Zay Flowers, Ravens
RB Omarion Hampton, Chargers
RB Aaron Jones Sr., Vikings
QB Joe Burrow, Bengals
WR Xavier Worthy, Chiefs
RB David Montgomery, Lions
TE Sam LaPorta, Lions
RB D'Andre Swift, Bears
WR Chris Godwin, Buccaneers
RB RJ Harvey, Broncos
WR Jerry Jeudy, Browns
QB Kyler Murray, Cardinals
QB Patrick Mahomes, Chiefs
WR Rome Odunze, Bears
RB Tony Pollard, Titans
RB Kaleb Johnson, Steelers
TE T.J. Hockenson, Vikings
RB Isiah Pacheco, Chiefs
WR George Pickens, Cowboys
WR Tetairoa McMillan, Panthers
RB Tyrone Tracy Jr., Giants
RB TreVeyon Henderson, Patriots
WR Jaylen Waddle, Dolphins
Rashee Rice, Chiefs
TE Travis Kelce, Chiefs
Joe Mixon, Texans
RB Jaylen Warren, Steelers
QB Baker Mayfield, Buccaneers
WR Jakobi Meyers, Raiders
WR Calvin Ridley, Titans
QB Brock Purdy, 49ers
RB Najee Harris, Chargers
WR Chris Olave, Saints
TE Evan Engram, Broncos
RB Brian Robinson Jr., Commanders
TE Mark Andrews, Ravens
WR Ricky Pearsall, 49ers
RB Travis Etienne Jr., Jaguars
QB Dak Prescott, Cowboys
WR Khalil Shakir, Bills
QB Bo Nix, Broncos
WR Travis Hunter, Jaguars
RB Javonte Williams, Cowboys
WR Jauan Jennings, 49ers
TE David Njoku, Browns
WR Cooper Kupp, Seahawks
QB Jared Goff, Lions
RB Jerome Ford, Browns
RB Zach Charbonnet, Seahawks
QB Justin Herbert, Chargers
WR Jayden Reed, Packers
RB Rhamondre Stevenson, Patriots
QB C.J. Stroud, Texans
QB Justin Fields, Jets
TE Dalton Kincaid, Bills
WR Stefon Diggs, Patriots
QB J.J. McCarthy, Vikings
WR Deebo Samuel Sr., Commanders
WR Matthew Golden, Packers
TE Tucker Kraft, Packers
TE Jake Ferguson, Cowboys
QB Caleb Williams, Bears
RB Rachaad White, Buccaneers
WR Emeka Egbuka, Buccaneers
WR Jordan Addison, Vikings
RB Tank Bigsby, Jaguars
RB Jordan Mason, Vikings
QB Drake Maye, Patriots
RB Tyjae Spears, Titans
WR Josh Downs, Colts
WR Michael Pittman Jr., Colts
TE Kyle Pitts, Falcons
TE Hunter Henry, Patriots
QB Jordan Love, Packers
WR Darnell Mooney, Falcons
RB Cam Skattebo, Giants
RB Tyler Allgeier, Falcons
WR Rashid Shaheed, Saints
QB Bryce Young, Panthers
RB J.K. Dobbins, Broncos
RB Isaac Guerendo, 49ers
WR Keon Coleman, Bills
QB Trevor Lawrence, Jaguars
RB Quinshon Judkins, Browns
WR Wan'Dale Robinson, Giants
WR Rashod Bateman, Ravens
TE Tyler Warren, Colts
QB Michael Penix Jr., Falcons
WR Jayden Higgins, Texans
TE Dallas Goedert, Eagles
RB Bhayshul Tuten, Jaguars
WR Luther Burden III, Bears
RB Rico Dowdle, Panthers
TE Jonnu Smith, Steelers
RB Austin Ekeler, Commanders
RB Ray Davis, Bills
QB Tua Tagovailoa, Dolphins
RB Jaylen Wright Dolphins
WR Brandon Aiyik, 49ers
WR Adam Thielen, Panthers
DST Philadelphia Eagles
RB Trey Benson, Cardinals
QB Matthew Stafford, Rams
WR Marvin Mims Jr., Broncos
TE Isiah Likely, Ravens
RB Jaydon Blue, Cowboys
RB Braelon Allen, Jets
TE Colston Loveland, Bears
QB Aaron Rodgers, Steelers
RB Roschon Johnson, Bears
D/ST Baltimore Ravens
RB Nick Chubb, Texans
WR Tre' Harris, Chargers
RB MarShawn Lloyd, Packers
WR Christian Kirk, Texans
WR Quentin Johnston, Chargers
D/ST Denver Broncos
WR Alec Pierce, Colts
RB Blake Corum, Rams
WR DeAndre Hopkins, Ravens
D/ST Pittsburgh Steelers
D/ST Houston Texans
TE Cade Otton, Buccaneers
WR Marquise Brown, Chiefs
RB Justice Hill, Ravens
WR Jalen McMillan, Buccaneers
RB Chris Rodriguez Jr., Commanders
WR Cedric Tillman, Browns
QB Cam Ward, Titans
WR Romeo Doubs, Packers
TE Pat Freiermuth, Steelers
RB Keaton Mitchell, Ravens
D/ST Seattle Seahawks
WR Kyle Williams, Patriots
D/ST Minnesota Vikings
D/ST Buffalo Bills
K Brandon Aubrey, Cowboys
D/ST Green Bay Packers
RB Ty Johnson, Bills
RB Dylan Sampson, Browns
D/ST Detroit Lions
D/ST Kansas City Chiefs
RB Kyle Monangai, Bears
K Cameron Dicker, Chargers
K Jake Bates, Lions
DST New York Jets
WR Xavier Legette, Panthers
TE Zach Ertz, Commanders
K Chase McLaughlin, Buccaneers
WR DeMario Douglas, Patriots
WR Joshua Palmer, Bills
"""

# =========================
# Flask
# =========================
app = Flask(__name__)
CORS(app)

# =========================
# Helpers
# =========================
def now_utc_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

def american_to_prob(odds: float) -> float:
    o = float(odds)
    if o == 0:
        raise ValueError("American odds cannot be 0")
    if o < 0:
        return (-o) / ((-o) + 100.0)
    else:
        return 100.0 / (o + 100.0)

def prob_to_american(p: float) -> int:
    p = max(min(float(p), 0.999), 0.001)
    if p >= 0.5:
        return int(round(-100.0 * p / (1.0 - p)))
    else:
        return int(round(100.0 * (1.0 - p) / p))

def decimal_to_american(decimal_odds: float) -> int:
    d = float(decimal_odds)
    if d <= 1.0:
        return -1000
    if d >= 2.0:
        return int(round((d - 1.0) * 100.0))
    return int(round(-100.0 / (d - 1.0)))

def clamp_prob(p: float, lo: float = 0.01, hi: float = 0.95) -> float:
    return max(lo, min(hi, float(p)))

def normalize_name(s: str) -> str:
    # keep apostrophes; strip dots/commas/extra spaces; lowercase
    return " ".join((s or "").lower().replace(".", "").replace(",", "").split())

# -------- Parsing: build player->team from Top-200 --------
def parse_top200_blob(blob: str) -> Dict[str, str]:
    """
    Accept lines:
      - 'WR Ja'Marr Chase, Bengals'
      - 'Rashee Rice, Chiefs'   (no POS)
      - 'RB Jaylen Wright Dolphins' (no comma)
    Ignore D/ST and K lines.
    """
    if not blob:
        return {}
    flat: Dict[str, str] = {}

    # POS Name, Team
    pat_pos_comma = re.compile(r"^\s*(QB|RB|WR|TE)\s+(.+?),\s+([A-Za-z .'\-]+)\s*$", re.MULTILINE)
    # POS Name Team
    pat_pos_nocomma = re.compile(r"^\s*(QB|RB|WR|TE)\s+(.+?)\s+([A-Za-z .'\-]+)\s*$", re.MULTILINE)
    # Name, Team   (no POS)
    pat_nopos_comma = re.compile(r"^\s*([A-Za-z][A-Za-z .'\-]+?),\s+([A-Za-z .'\-]+)\s*$", re.MULTILINE)

    def add(name: str, team_label: str):
        n = " ".join(name.split())
        t = " ".join(team_label.split())
        # filter out defenses/kickers by team label patterns (DST, D/ST, etc.)
        if t.upper().startswith(("D/ST","DST")) or t.upper().startswith(("K ", "K")):
            return
        abbr = TEAM_NAME_TO_ABBR.get(t)
        if abbr:
            flat[n] = abbr

    for pos, name, team in pat_pos_comma.findall(blob):
        add(name, team)
    for pos, name, team in pat_pos_nocomma.findall(blob):
        # don't overwrite if a cleaner comma version already set
        if name not in flat:
            add(name, team)
    for name, team in pat_nopos_comma.findall(blob):
        if name not in flat:
            add(name, team)

    return flat

PLAYER_TEAM_MAP: Dict[str, str] = {
    normalize_name(k): v for k, v in parse_top200_blob(TOP200_BLOB).items()
}

# =========================
# Data fetchers
# =========================
def fetch_team_boosts() -> Dict[str, float]:
    """Load team TD projections and compute boost factors."""
    r = requests.get(TEAM_PROJECTIONS_URL, timeout=30)
    r.raise_for_status()
    data = r.json()
    boosts: Dict[str, float] = {}
    for g in data.get("games", []):
        away = g.get("away_team")
        home = g.get("home_team")
        av = g.get("away_vegas_tds", 0.0)
        ap = g.get("away_projected_tds", 0.0)
        hv = g.get("home_vegas_tds", 0.0)
        hp = g.get("home_projected_tds", 0.0)
        if away and av and av > 0:
            boosts[away] = ap / av
        if home and hv and hv > 0:
            boosts[home] = hp / hv
    return boosts

def fetch_nfl_events() -> List[Dict[str, Any]]:
    url = f"{ODDS_API_BASE()}/sports/americanfootball_nfl/events"
    r = requests.get(url, params={"apiKey": ODDS_API_KEY}, timeout=30)
    r.raise_for_status()
    return r.json()

def fetch_anytime_market_for_event(event_id: str) -> Optional[Dict[str, Any]]:
    url = f"{ODDS_API_BASE()}/sports/americanfootball_nfl/events/{event_id}/odds"
    params = {"apiKey": ODDS_API_KEY, "markets": "player_anytime_td", "regions": "us"}
    r = requests.get(url, params=params, timeout=30)
    if not r.ok:
        return None
    return r.json()

def ODDS_API_BASE() -> str:
    # small helper so we can tweak base easily if needed
    return ODDS_BASE_URL

# =========================
# Core processing
# =========================
def player_team_lookup(player_name: str) -> str:
    return PLAYER_TEAM_MAP.get(normalize_name(player_name), "TBD")

def process_anytime_for_game(game: Dict[str, Any], team_boosts: Dict[str, float]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    game_id = game.get("id")
    if not game_id:
        return out

    home_full = game.get("home_team")
    away_full = game.get("away_team")
    commence_time = game.get("commence_time")

    # Events use full city+mascot names
    home_abbr = TEAM_CITY_TO_ABBR.get(home_full, home_full or "HOME")
    away_abbr = TEAM_CITY_TO_ABBR.get(away_full, away_full or "AWAY")

    market = fetch_anytime_market_for_event(game_id)
    if not market:
        return out

    # choose bookmaker by priority
    chosen_book: Optional[Dict[str, Any]] = None
    for bk in market.get("bookmakers", []):
        if bk.get("key") in BOOKMAKER_PRIORITY:
            chosen_book = bk
            break
    if not chosen_book:
        return out

    # find player_anytime_td
    patd = None
    for m in chosen_book.get("markets", []):
        if m.get("key") == "player_anytime_td":
            patd = m
            break
    if not patd:
        return out

    lift_home = team_boosts.get(home_abbr, 1.0)
    lift_away = team_boosts.get(away_abbr, 1.0)

    for outcome in patd.get("outcomes", []):
        if outcome.get("name") != "Yes":
            continue
        player_name = (outcome.get("description") or "").strip()
        raw_price = outcome.get("price")
        if not player_name or raw_price is None:
            continue

        # odds → prob
        if isinstance(raw_price, (int, float)) and 1.0 < float(raw_price) < 10.0:
            # decimal
            book_odds_american = decimal_to_american(float(raw_price))
            book_prob = 1.0 / float(raw_price)
        else:
            # american
            book_odds_american = int(round(float(raw_price)))
            book_prob = american_to_prob(float(book_odds_american))

        # map player to team abbr
        pteam = player_team_lookup(player_name)

        # apply lifts
        if pteam == home_abbr:
            adj_prob = clamp_prob(book_prob * lift_home); used_lift = lift_home
        elif pteam == away_abbr:
            adj_prob = clamp_prob(book_prob * lift_away); used_lift = lift_away
        else:
            if UNKNOWN_TEAM_MODE == "average":
                avg = (lift_home + lift_away) / 2.0
                adj_prob = clamp_prob(book_prob * avg); used_lift = avg
            elif UNKNOWN_TEAM_MODE == "home":
                adj_prob = clamp_prob(book_prob * lift_home); used_lift = lift_home
            elif UNKNOWN_TEAM_MODE == "away":
                adj_prob = clamp_prob(book_prob * lift_away); used_lift = lift_away
            else:
                adj_prob = clamp_prob(book_prob); used_lift = 1.0

        fair_odds = prob_to_american(adj_prob)
        edge_pp = adj_prob - book_prob
        edge_rel = (edge_pp / book_prob * 100.0) if book_prob > 0 else None

        out.append({
            "player_name": player_name,
            "team": pteam,
            "game": f"{away_abbr} @ {home_abbr}",
            "commence_time": commence_time,
            "bookmaker": chosen_book.get("key"),
            "book": {
                "odds_american": book_odds_american,
                "implied_probability": round(book_prob, 4),
                "implied_probability_pct": round(book_prob * 100.0, 1)
            },
            "adjusted": {
                "team_lift": round(used_lift, 4),
                "probability": round(adj_prob, 4),
                "probability_pct": round(adj_prob * 100.0, 1),
                "fair_odds_american": fair_odds
            },
            "edge": {
                "probability_points": round(edge_pp, 4),
                "probability_points_pct": round(edge_pp * 100.0, 2),
                "relative_uplift_pct": round(edge_rel, 2) if edge_rel is not None else None
            }
        })

    return out

# =========================
# Caching orchestration
# =========================
_cache_blob: Optional[Dict[str, Any]] = None
_cache_ts: float = 0.0

def refresh_all() -> Dict[str, Any]:
    global _cache_blob, _cache_ts
    boosts = fetch_team_boosts()
    events = fetch_nfl_events()

    players: List[Dict[str, Any]] = []
    for game in events:
        try:
            players.extend(process_anytime_for_game(game, boosts))
        except Exception as e:
            players.append({"error": f"Failed game {game.get('id','?')}: {str(e)}"})

    # sort by highest positive edge
    players.sort(key=lambda p: p.get("edge", {}).get("probability_points", 0), reverse=True)

    _cache_blob = {
        "analysis_date": now_utc_str(),
        "source": {
            "team_projections_url": TEAM_PROJECTIONS_URL,
            "odds_api": "the-odds-api.com",
            "bookmaker_priority": BOOKMAKER_PRIORITY
        },
        "summary": {
            "players": len([x for x in players if "player_name" in x]),
            "teams_with_boosts": len(boosts)
        },
        "methodology": {
            "team_lift": "projected_team_TDs / vegas_team_TDs",
            "adjustment": "adjusted_prob = book_implied_prob * team_lift (clamped [1%,95%])",
            "fair_odds": "prob_to_american(adjusted_prob)"
        },
        "players": players
    }
    _cache_ts = time.time()
    return _cache_blob

def get_cached_or_refresh() -> Dict[str, Any]:
    if _cache_blob is None or (time.time() - _cache_ts > CACHE_TTL_SECS):
        return refresh_all()
    return _cache_blob

# =========================
# Routes
# =========================
@app.route("/", methods=["GET"])
def root():
    return jsonify({
        "service": "Anytime TD Adjusted Odds",
        "version": "1.0",
        "endpoints": {
            "/anytime-td-adjusted": {"GET": "Adjusted anytime TD odds (cached or refreshed if stale)."},
            "/refresh": {"POST": "Force refresh of team projections and anytime TD odds."},
            "/roster-stats": {"GET": "How many players were mapped from Top-200 blob."},
            "/health": {"GET": "Health check."}
        },
        "config": {
            "TEAM_PROJECTIONS_URL": TEAM_PROJECTIONS_URL,
            "UNKNOWN_TEAM_MODE": UNKNOWN_TEAM_MODE,
            "CACHE_TTL_SECS": CACHE_TTL_SECS
        },
        "timestamp": now_utc_str()
    })

@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "last_build": os.getenv("RAILWAY_GIT_COMMIT_SHA", None),
        "timestamp": now_utc_str()
    })

@app.route("/roster-stats", methods=["GET"])
def roster_stats():
    return jsonify({
        "players_mapped": len(PLAYER_TEAM_MAP),
        "sample": dict(list(PLAYER_TEAM_MAP.items())[:12]),  # normalized name -> team abbr
        "notes": "Names are normalized (lowercase, strip dots/commas). Parser accepts POS and no-POS lines."
    })

@app.route("/anytime-td-adjusted", methods=["GET"])
def anytime_td_adjusted():
    try:
        data = get_cached_or_refresh()
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/refresh", methods=["POST"])
def refresh():
    try:
        data = refresh_all()
        return jsonify({"status": "success", "analysis_date": data.get("analysis_date"), "summary": data.get("summary")})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# =========================
# Entrypoint
# =========================
if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
