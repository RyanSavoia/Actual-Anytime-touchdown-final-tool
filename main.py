import os
import time
import json
import math
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional

import requests
from flask import Flask, jsonify, request
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

CACHE_TTL_SECS = int(os.getenv("CACHE_TTL_SECS", "3600"))  # 1 hour

TEAM_ABBR = {
    "Arizona Cardinals": "ARI", "Atlanta Falcons": "ATL", "Baltimore Ravens": "BAL",
    "Buffalo Bills": "BUF", "Carolina Panthers": "CAR", "Chicago Bears": "CHI",
    "Cincinnati Bengals": "CIN", "Cleveland Browns": "CLE", "Dallas Cowboys": "DAL",
    "Denver Broncos": "DEN", "Detroit Lions": "DET", "Green Bay Packers": "GB",
    "Houston Texans": "HOU", "Indianapolis Colts": "IND", "Jacksonville Jaguars": "JAX",
    "Kansas City Chiefs": "KC", "Los Angeles Rams": "LAR", "Miami Dolphins": "MIA",
    "Minnesota Vikings": "MIN", "New England Patriots": "NE", "New Orleans Saints": "NO",
    "New York Giants": "NYG", "New York Jets": "NYJ", "Las Vegas Raiders": "LV",
    "Philadelphia Eagles": "PHI", "Pittsburgh Steelers": "PIT", "Los Angeles Chargers": "LAC",
    "San Francisco 49ers": "SF", "Seattle Seahawks": "SEA", "Tampa Bay Buccaneers": "TB",
    "Tennessee Titans": "TEN", "Washington Commanders": "WAS",
}

# =========================
# Flask
# =========================
app = Flask(__name__)
CORS(app)

# =========================
# Helpers: time, math, odds
# =========================
def now_utc_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

def american_to_prob(odds: float) -> float:
    """Convert American odds to implied probability (0..1)."""
    o = float(odds)
    if o == 0:
        raise ValueError("American odds cannot be 0")
    if o < 0:
        return (-o) / ((-o) + 100.0)
    else:
        return 100.0 / (o + 100.0)

def prob_to_american(p: float) -> int:
    """Convert probability (0..1) to American odds, with sensible clamps."""
    p = max(min(float(p), 0.999), 0.001)
    if p >= 0.5:
        return int(round(-100.0 * p / (1.0 - p)))
    else:
        return int(round(100.0 * (1.0 - p) / p))

def decimal_to_american(decimal_odds: float) -> int:
    """Convert decimal odds to American odds."""
    d = float(decimal_odds)
    if d <= 1.0:
        return -1000
    if d >= 2.0:
        return int(round((d - 1.0) * 100.0))
    return int(round(-100.0 / (d - 1.0)))

def clamp_prob(p: float, lo: float = 0.01, hi: float = 0.95) -> float:
    return max(lo, min(hi, float(p)))

# =========================
# Data fetchers
# =========================
def fetch_team_boosts() -> Dict[str, float]:
    """
    Load your team TD projections and compute boost factors.
    boost = projected_tds / vegas_tds for both home and away teams.
    Returns { 'DAL': 1.0763, ... }
    """
    resp = requests.get(TEAM_PROJECTIONS_URL, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    games = data.get("games", [])
    boosts: Dict[str, float] = {}

    for g in games:
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
    """Pull current NFL events from The Odds API."""
    url = f"{ODDS_BASE_URL}/sports/americanfootball_nfl/events"
    params = {"apiKey": ODDS_API_KEY}
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    return r.json()

def fetch_anytime_market_for_event(event_id: str) -> Optional[Dict[str, Any]]:
    """Get the player_anytime_td market for a specific event."""
    url = f"{ODDS_BASE_URL}/sports/americanfootball_nfl/events/{event_id}/odds"
    params = {
        "apiKey": ODDS_API_KEY,
        "markets": "player_anytime_td",
        "regions": "us",
    }
    r = requests.get(url, params=params, timeout=30)
    if not r.ok:
        return None
    return r.json()

# =========================
# Core adjustment
# =========================
def determine_player_team(player_name: str, home_abbr: str, away_abbr: str) -> str:
    """
    Placeholder team inference. Without a roster DB, return 'TBD'.
    Later: wire a player -> team map and return home_abbr/away_abbr accordingly.
    """
    return "TBD"

def process_anytime_for_game(game: Dict[str, Any], team_boosts: Dict[str, float]) -> List[Dict[str, Any]]:
    """
    For one game, pull player_anytime_td odds, select first available bookmaker
    per priority, and compute adjusted fair odds via team lift.
    """
    results: List[Dict[str, Any]] = []

    game_id = game.get("id")
    if not game_id:
        return results

    home_full = game.get("home_team")
    away_full = game.get("away_team")
    commence_time = game.get("commence_time")

    home_abbr = TEAM_ABBR.get(home_full, home_full or "HOME")
    away_abbr = TEAM_ABBR.get(away_full, away_full or "AWAY")

    market_blob = fetch_anytime_market_for_event(game_id)
    if not market_blob:
        return results

    # choose top bookmaker by priority
    chosen_book: Optional[Dict[str, Any]] = None
    for bk in market_blob.get("bookmakers", []):
        if bk.get("key") in BOOKMAKER_PRIORITY:
            chosen_book = bk
            break
    if not chosen_book:
        return results

    # find player_anytime_td market
    patd_market = None
    for m in chosen_book.get("markets", []):
        if m.get("key") == "player_anytime_td":
            patd_market = m
            break
    if not patd_market:
        return results

    lift_home = team_boosts.get(home_abbr, 1.0)
    lift_away = team_boosts.get(away_abbr, 1.0)

    for outcome in patd_market.get("outcomes", []):
        # The Odds API typically structures player anytime TD as:
        # { name: 'Yes', description: '<Player Name>', price: <american or decimal> }
        if outcome.get("name") != "Yes":
            continue

        player_name = (outcome.get("description") or "").strip()
        raw_price = outcome.get("price")

        if player_name == "" or raw_price is None:
            continue

        # Figure out if price is decimal (e.g., 1.83) or American (e.g., -120)
        # Heuristic: between 1 and 10 is likely decimal
        if isinstance(raw_price, (int, float)) and 1.0 < float(raw_price) < 10.0:
            # decimal odds
            book_odds_american = decimal_to_american(float(raw_price))
            book_prob = 1.0 / float(raw_price)
        else:
            # american odds
            book_odds_american = int(round(float(raw_price)))
            book_prob = american_to_prob(float(book_odds_american))

        # Team inference
        player_team = determine_player_team(player_name, home_abbr, away_abbr)

        # Apply lift if team known
        if player_team == home_abbr:
            adj_prob = clamp_prob(book_prob * lift_home)
            used_lift = lift_home
        elif player_team == away_abbr:
            adj_prob = clamp_prob(book_prob * lift_away)
            used_lift = lift_away
        else:
            # Unknown team -> no boost (transparent)
            adj_prob = clamp_prob(book_prob)
            used_lift = 1.0

        fair_odds = prob_to_american(adj_prob)
        edge_pp = adj_prob - book_prob
        edge_rel = (edge_pp / book_prob * 100.0) if book_prob > 0 else None

        results.append({
            "player_name": player_name,
            "team": player_team,                     # "TBD" until you wire roster
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
                "probability_points": round(edge_pp, 4),                 # e.g. +0.039 = +3.9 pp
                "probability_points_pct": round(edge_pp * 100.0, 2),     # %-points
                "relative_uplift_pct": round(edge_rel, 2) if edge_rel is not None else None
            }
        })

    return results

# =========================
# Caching / Service orchestration
# =========================
_cache_blob: Optional[Dict[str, Any]] = None
_cache_ts: float = 0.0

def refresh_all() -> Dict[str, Any]:
    """Fetch team boosts, events, markets; compute adjusted fair odds; cache."""
    global _cache_blob, _cache_ts

    boosts = fetch_team_boosts()
    events = fetch_nfl_events()

    all_players: List[Dict[str, Any]] = []
    for game in events:
        try:
            all_players.extend(process_anytime_for_game(game, boosts))
        except Exception as e:
            # Continue past a single game failure
            all_players.append({
                "error": f"Failed processing game {game.get('id', 'unknown')}: {str(e)}"
            })

    # Sort best value first by fair odds difference vs book (approx via prob diff)
    all_players.sort(key=lambda p: p.get("edge", {}).get("probability_points", 0), reverse=True)

    _cache_blob = {
        "analysis_date": now_utc_str(),
        "source": {
            "team_projections_url": TEAM_PROJECTIONS_URL,
            "odds_api": "the-odds-api.com",
            "bookmaker_priority": BOOKMAKER_PRIORITY
        },
        "summary": {
            "players": len([x for x in all_players if "player_name" in x]),
            "teams_with_boosts": len(boosts),
        },
        "methodology": {
            "team_lift": "projected_team_TDs / vegas_team_TDs",
            "adjustment": "adjusted_prob = book_implied_prob * team_lift (clamped [1%,95%])",
            "fair_odds": "prob_to_american(adjusted_prob)"
        },
        "players": all_players
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
            "/anytime-td-adjusted": {
                "GET": "Return adjusted anytime TD odds (cached or refreshed if stale)."
            },
            "/refresh": {
                "POST": "Force refresh of team projections and anytime TD odds."
            },
            "/health": {
                "GET": "Health check."
            }
        },
        "config": {
            "TEAM_PROJECTIONS_URL": TEAM_PROJECTIONS_URL,
            "ODDS_BASE_URL": ODDS_BASE_URL,
            "BOOKMAKER_PRIORITY": BOOKMAKER_PRIORITY,
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
