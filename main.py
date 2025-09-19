import requests
import json
import math
from datetime import datetime, timedelta
import logging
import sys
import os

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class AnytimeTDOddsService:
    def __init__(self):
        """
        Initialize Anytime TD Odds Service following the same pattern as working tools
        """
        self.odds_api_key = os.getenv('ODDS_API_KEY', 'd8ba5d45eca27e710d7ef2680d8cb452')
        self.odds_base_url = 'https://api.the-odds-api.com/v4'
        self.team_projections_url = 'https://nfl-team-td-projections-production.up.railway.app/team-analysis'
        
        # Bookmaker priority (same as friend's code)
        self.bookmaker_priority = [
            'fanduel', 'betmgm', 'caesars', 'betrivers', 'williamhill_us',
            'draftkings', 'fanatics', 'windcreek', 'espnbet', 'ballybet'
        ]
        
        self.cached_data = None
        self.last_refresh = None
        
        try:
            logger.info("Successfully initialized Anytime TD Odds Service")
        except Exception as e:
            logger.error(f"Failed to initialize service: {str(e)}")
    
    def get_implied_probability(self, odds):
        """Convert American odds to implied probability"""
        try:
            if odds < 0:
                return abs(odds) / (abs(odds) + 100)
            else:
                return 100 / (odds + 100)
        except Exception as e:
            logger.error(f"Error converting odds {odds}: {str(e)}")
            return 0.5  # Default to 50% if conversion fails
    
    def probability_to_odds(self, probability):
        """Convert probability to American odds"""
        try:
            if probability >= 1.0:
                return -1000  # Cap extremely high probabilities
            elif probability <= 0.0:
                return 1000   # Cap extremely low probabilities
            elif probability >= 0.5:
                return round(-100 * probability / (1 - probability))
            else:
                return round(100 * (1 - probability) / probability)
        except Exception as e:
            logger.error(f"Error converting probability {probability}: {str(e)}")
            return -110  # Default odds
    
    def fetch_team_projections(self):
        """Fetch team TD projections from Railway service"""
        try:
            logger.info(f"Fetching team projections from {self.team_projections_url}")
            response = requests.get(self.team_projections_url, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            if 'games' not in data:
                raise ValueError("No games found in team projections")
            
            # Create lookup dictionary: team -> boost factor
            team_boosts = {}
            for game in data['games']:
                away_team = game['away_team']
                home_team = game['home_team']
                away_vegas = game['away_vegas_tds']
                home_vegas = game['home_vegas_tds']
                away_projected = game['away_projected_tds']
                home_projected = game['home_projected_tds']
                
                # Calculate boost factors
                if away_vegas > 0:
                    team_boosts[away_team] = away_projected / away_vegas
                if home_vegas > 0:
                    team_boosts[home_team] = home_projected / home_vegas
            
            logger.info(f"Successfully fetched projections for {len(team_boosts)} teams")
            return team_boosts
            
        except Exception as e:
            logger.error(f"Failed to fetch team projections: {str(e)}")
            return {}
    
    def fetch_anytime_td_odds(self):
        """Fetch anytime TD odds from the odds API"""
        try:
            # Get current NFL games
            events_url = f"{self.odds_base_url}/sports/americanfootball_nfl/events"
            params = {
                'apiKey': self.odds_api_key
            }
            
            response = requests.get(events_url, params=params, timeout=30)
            response.raise_for_status()
            games = response.json()
            
            if not games:
                logger.warning("No NFL games found")
                return []
            
            all_player_odds = []
            
            # Fetch odds for each game
            for game in games:
                try:
                    game_id = game['id']
                    home_team = game['home_team']
                    away_team = game['away_team']
                    commence_time = game['commence_time']
                    
                    # Map full team names to abbreviations
                    team_mapping = self.get_team_abbreviations()
                    home_abbr = team_mapping.get(home_team, home_team)
                    away_abbr = team_mapping.get(away_team, away_team)
                    
                    # Get anytime TD odds for this game
                    odds_url = f"{self.odds_base_url}/sports/americanfootball_nfl/events/{game_id}/odds"
                    odds_params = {
                        'apiKey': self.odds_api_key,
                        'markets': 'player_anytime_td',
                        'regions': 'us'
                    }
                    
                    odds_response = requests.get(odds_url, params=odds_params, timeout=30)
                    if not odds_response.ok:
                        continue
                    
                    game_odds = odds_response.json()
                    
                    # Process bookmakers using priority
                    for bookmaker in game_odds.get('bookmakers', []):
                        if bookmaker['key'] not in self.bookmaker_priority:
                            continue
                        
                        for market in bookmaker.get('markets', []):
                            if market['key'] != 'player_anytime_td':
                                continue
                            
                            for outcome in market.get('outcomes', []):
                                if outcome.get('name') == 'Yes':
                                    player_name = outcome.get('description', '').strip()
                                    odds = outcome.get('price')
                                    
                                    if player_name and odds:
                                        # Determine player's team
                                        player_team = self.determine_player_team(
                                            player_name, home_abbr, away_abbr
                                        )
                                        
                                        all_player_odds.append({
                                            'player_name': player_name,
                                            'team': player_team,
                                            'book_odds': odds,
                                            'bookmaker': bookmaker['key'],
                                            'game': f"{away_abbr} @ {home_abbr}",
                                            'commence_time': commence_time
                                        })
                        
                        break  # Use first available bookmaker from priority list
                
                except Exception as e:
                    logger.warning(f"Error processing game {game.get('id', 'unknown')}: {str(e)}")
                    continue
            
            logger.info(f"Successfully fetched {len(all_player_odds)} player anytime TD odds")
            return all_player_odds
            
        except Exception as e:
            logger.error(f"Failed to fetch anytime TD odds: {str(e)}")
            return []
    
    def get_team_abbreviations(self):
        """Map full team names to abbreviations"""
        return {
            "Arizona Cardinals": "ARI",
            "Atlanta Falcons": "ATL", 
            "Baltimore Ravens": "BAL",
            "Buffalo Bills": "BUF",
            "Carolina Panthers": "CAR",
            "Chicago Bears": "CHI",
            "Cincinnati Bengals": "CIN",
            "Cleveland Browns": "CLE",
            "Dallas Cowboys": "DAL",
            "Denver Broncos": "DEN",
            "Detroit Lions": "DET",
            "Green Bay Packers": "GB",
            "Houston Texans": "HOU",
            "Indianapolis Colts": "IND",
            "Jacksonville Jaguars": "JAX",
            "Kansas City Chiefs": "KC",
            "Los Angeles Rams": "LAR",
            "Miami Dolphins": "MIA",
            "Minnesota Vikings": "MIN",
            "New England Patriots": "NE",
            "New Orleans Saints": "NO",
            "New York Giants": "NYG",
            "New York Jets": "NYJ",
            "Las Vegas Raiders": "LV",
            "Philadelphia Eagles": "PHI",
            "Pittsburgh Steelers": "PIT",
            "Los Angeles Chargers": "LAC",
            "San Francisco 49ers": "SF",
            "Seattle Seahawks": "SEA",
            "Tampa Bay Buccaneers": "TB",
            "Tennessee Titans": "TEN",
            "Washington Commanders": "WAS"
        }
    
    def determine_player_team(self, player_name, home_team, away_team):
        """
        Determine which team a player belongs to
        This is a simplified approach - in production you'd want a player database
        """
        # For now, return "TBD" - this would need a player roster lookup
        # You could enhance this by maintaining a player->team mapping
        return "TBD"
    
    def calculate_adjusted_odds(self, player_odds_list, team_boosts):
        """Apply team boost factors to player odds"""
        adjusted_players = []
        
        for player in player_odds_list:
            try:
                book_odds = player['book_odds']
                team = player['team']
                
                # Get implied probability from book odds
                book_probability = self.get_implied_probability(book_odds)
                
                # Apply team boost if available
                boost_factor = team_boosts.get(team, 1.0)
                adjusted_probability = book_probability * boost_factor
                
                # Cap probability at reasonable limits
                adjusted_probability = max(0.01, min(0.95, adjusted_probability))
                
                # Convert back to odds
                adjusted_odds = self.probability_to_odds(adjusted_probability)
                
                # Calculate boost percentage
                boost_pct = ((boost_factor - 1.0) * 100) if boost_factor != 1.0 else 0
                
                adjusted_player = {
                    'player_name': player['player_name'],
                    'team': team,
                    'game': player['game'],
                    'commence_time': player['commence_time'],
                    'bookmaker': player['bookmaker'],
                    'book_odds': book_odds,
                    'book_probability': round(book_probability, 3),
                    'team_boost_factor': round(boost_factor, 3),
                    'team_boost_pct': round(boost_pct, 1),
                    'adjusted_probability': round(adjusted_probability, 3),
                    'adjusted_odds': adjusted_odds,
                    'has_boost': boost_factor != 1.0
                }
                
                adjusted_players.append(adjusted_player)
                
            except Exception as e:
                logger.error(f"Error adjusting odds for {player.get('player_name', 'unknown')}: {str(e)}")
                continue
        
        return adjusted_players
    
    def refresh_data(self):
        """Refresh all data and cache results"""
        try:
            logger.info("Starting data refresh...")
            
            # Fetch team projections and player odds
            team_boosts = self.fetch_team_projections()
            player_odds = self.fetch_anytime_td_odds()
            
            if not player_odds:
                return {"error": "No anytime TD odds available"}
            
            # Apply team boost adjustments
            adjusted_players = self.calculate_adjusted_odds(player_odds, team_boosts)
            
            # Sort by adjusted odds (best value first)
            adjusted_players.sort(key=lambda x: x.get('adjusted_odds', 0))
            
            self.cached_data = {
                'last_updated': datetime.now().isoformat(),
                'total_players': len(adjusted_players),
                'teams_with_boosts': len([p for p in adjusted_players if p['has_boost']]),
                'methodology': {
                    'boost_calculation': 'team_projected_TDs ÷ team_vegas_TDs',
                    'adjustment_formula': 'book_probability × team_boost_factor',
                    'probability_conversion': 'adjusted_probability → American odds'
                },
                'players': adjusted_players
            }
            self.last_refresh = datetime.now()
            
            logger.info(f"Data refresh complete: {len(adjusted_players)} players processed")
            return self.cached_data
            
        except Exception as e:
            logger.error(f"Error refreshing data: {str(e)}")
            return {"error": f"Data refresh failed: {str(e)}"}
    
    def get_cached_data(self):
        """Get cached data or refresh if stale/empty"""
        try:
            # Check if data needs refresh (older than 1 hour or no data)
            if (not self.cached_data or 
                not self.last_refresh or 
                (datetime.now() - self.last_refresh).seconds > 3600):
                return self.refresh_data()
            
            return self.cached_data
            
        except Exception as e:
            logger.error(f"Error getting cached data: {str(e)}")
            return {"error": f"Failed to get data: {str(e)}"}

# Initialize service
odds_service = AnytimeTDOddsService()

# Flask Integration
try:
    from flask import Flask, jsonify, request
    from flask_cors import CORS
    
    app = Flask(__name__)
    CORS(app)  # Enable CORS for all routes
    
    @app.route('/anytime-td-odds', methods=['GET'])
    def get_anytime_td_odds():
        """Get anytime TD odds with team boost adjustments"""
        try:
            data = odds_service.get_cached_data()
            return jsonify(data)
        
        except Exception as e:
            logger.error(f"Error in Flask endpoint: {str(e)}")
            return jsonify({
                "error": "Unexpected error",
                "message": str(e),
                "timestamp": datetime.now().isoformat()
            }), 500
    
    @app.route('/refresh', methods=['POST'])
    def manual_refresh():
        """Manually refresh anytime TD odds data"""
        try:
            data = odds_service.refresh_data()
            return jsonify({
                "status": "success",
                "message": "Data refreshed successfully",
                "data": data
            })
        
        except Exception as e:
            logger.error(f"Error in refresh endpoint: {str(e)}")
            return jsonify({
                "status": "error",
                "message": str(e),
                "timestamp": datetime.now().isoformat()
            }), 500
    
    @app.route('/health', methods=['GET'])
    def health_check():
        """Health check endpoint"""
        return jsonify({
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "service": "Anytime TD Odds with Team Boost",
            "last_refresh": odds_service.last_refresh.isoformat() if odds_service.last_refresh else None
        })
    
    @app.route('/', methods=['GET'])
    def root():
        """Root endpoint with API documentation"""
        return jsonify({
            "service": "Anytime TD Odds with Team Boost API",
            "version": "1.0",
            "endpoints": {
                "/anytime-td-odds": {
                    "method": "GET",
                    "description": "Get anytime TD odds with team boost adjustments",
                    "returns": "List of players with book odds and adjusted fair odds"
                },
                "/refresh": {
                    "method": "POST",
                    "description": "Manually refresh odds data"
                },
                "/health": {
                    "method": "GET", 
                    "description": "Health check endpoint"
                }
            },
            "methodology": {
                "team_boost": "projected_TDs ÷ vegas_TDs per team",
                "player_adjustment": "book_probability × team_boost_factor",
                "refresh_frequency": "Every hour (3600 seconds)",
                "data_sources": ["the-odds-api.com", "team-projections-railway-service"]
            },
            "timestamp": datetime.now().isoformat()
        })
    
    def run_flask_app():
        """Run Flask application"""
        port = int(os.environ.get('PORT', 10000))
        debug = os.environ.get('DEBUG', 'False').lower() == 'true'
        
        logger.info(f"Starting Anytime TD Odds Service on port {port}")
        app.run(host='0.0.0.0', port=port, debug=debug)

except ImportError:
    logger.info("Flask not available - running in CLI mode only")
    app = None
    def run_flask_app():
        logger.error("Flask not installed. Install with: pip install flask")
        sys.exit(1)

if __name__ == "__main__":
    # Check if Flask mode is requested
    if len(sys.argv) > 1 and sys.argv[1] == '--flask':
        if app is not None:
            run_flask_app()
        else:
            logger.error("Flask not available. Install with: pip install flask")
            sys.exit(1)
    else:
        # CLI mode - refresh data once and output
        data = odds_service.refresh_data()
        print(json.dumps(data, indent=2))
