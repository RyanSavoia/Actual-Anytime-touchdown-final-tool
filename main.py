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

class AnytimeTDOddsCalculator:
    def __init__(self, team_analysis_url=None, player_usage_url=None):
        """
        Initialize Anytime TD Odds Calculator following the same pattern as working tools
        """
        self.team_analysis_url = team_analysis_url or os.getenv('TEAM_ANALYSIS_URL', 'https://nfl-team-td-projections-production.up.railway.app/team-analysis')
        self.player_usage_url = player_usage_url or os.getenv('PLAYER_USAGE_URL', 'https://nfl-player-redzone-usage-td-share-production.up.railway.app/player-usage')
        
        # GPT's calculation parameters
        self.alpha = 0.85  # heavily weight opportunity (RZ usage) over production (TD share)
        self.epsilon = 0.01  # floor for small samples
        
        try:
            logger.info(f"Successfully initialized calculator")
        except Exception as e:
            logger.error(f"Failed to initialize calculator: {str(e)}")
    
    def fetch_team_analysis(self):
        """Fetch team TD projections from team analysis service"""
        try:
            logger.info(f"Fetching team analysis from {self.team_analysis_url}")
            response = requests.get(self.team_analysis_url, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            if 'games' not in data:
                raise ValueError("No games found in team analysis data")
            
            logger.info(f"Successfully fetched {len(data['games'])} games")
            return data['games']
            
        except Exception as e:
            logger.error(f"Failed to fetch team analysis: {str(e)}")
            raise
    
    def fetch_player_usage(self):
        """Fetch player usage data from player usage service"""
        try:
            logger.info(f"Fetching player usage from {self.player_usage_url}")
            response = requests.get(self.player_usage_url, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            if 'teams' not in data:
                raise ValueError("No teams found in player usage data")
            
            logger.info(f"Successfully fetched data for {len(data['teams'])} teams")
            return data['teams']
            
        except Exception as e:
            logger.error(f"Failed to fetch player usage: {str(e)}")
            raise
    
    def calculate_player_allocation(self, players_data):
        """
        Calculate allocation weights for players using GPT's exact formula
        alloc_raw_i = alpha * rz_usage_share_i + (1 - alpha) * td_share_i
        """
        try:
            allocations = {}
            
            for player_name, stats in players_data.items():
                rz_usage = stats.get('rz_usage_share', 0.0)
                td_share = stats.get('td_share', 0.0)
                
                # GPT's formula
                alloc_raw = self.alpha * rz_usage + (1 - self.alpha) * td_share
                
                # Apply epsilon floor for small samples
                alloc_adj = max(alloc_raw, self.epsilon)
                
                allocations[player_name] = alloc_adj
            
            # Normalize across all players
            total_allocation = sum(allocations.values())
            
            if total_allocation > 0:
                for player_name in allocations:
                    allocations[player_name] = allocations[player_name] / total_allocation
            
            return allocations
            
        except Exception as e:
            logger.error(f"Error calculating player allocation: {str(e)}")
            return {}
    
    def calculate_anytime_odds(self, lambda_td):
        """
        Convert expected TDs to anytime TD probability and American odds
        p_anytime = 1 - exp(-lambda)
        """
        try:
            # Poisson probability of at least 1 TD
            p_anytime = 1 - math.exp(-lambda_td)
            
            # Convert to American odds
            if p_anytime >= 0.5:
                american_odds = -round(100 * p_anytime / (1 - p_anytime))
            else:
                american_odds = round(100 * (1 - p_anytime) / p_anytime)
            
            return {
                'expected_tds': round(lambda_td, 3),
                'anytime_probability': round(p_anytime, 3),
                'american_odds': american_odds
            }
            
        except Exception as e:
            logger.error(f"Error calculating anytime odds: {str(e)}")
            return None
    
    def process_team_players(self, team, team_td_proj, player_usage_data):
        """Process all players for a team and calculate their anytime TD odds"""
        try:
            if team not in player_usage_data:
                logger.warning(f"No player usage data found for team {team}")
                return {}
            
            team_players = player_usage_data[team].get('players', {})
            
            if not team_players:
                logger.warning(f"No players found for team {team}")
                return {}
            
            # Calculate allocation weights
            allocations = self.calculate_player_allocation(team_players)
            
            if not allocations:
                return {}
            
            # Calculate anytime odds for each player
            player_odds = {}
            
            for player_name, allocation in allocations.items():
                # Expected TDs for this player
                lambda_player = team_td_proj * allocation
                
                # Calculate anytime odds
                odds_data = self.calculate_anytime_odds(lambda_player)
                
                if odds_data:
                    player_stats = team_players[player_name]
                    player_odds[player_name] = {
                        'rz_usage_share': round(player_stats.get('rz_usage_share', 0), 4),
                        'td_share': round(player_stats.get('td_share', 0), 4),
                        'allocation_weight': round(allocation, 4),
                        'expected_tds': odds_data['expected_tds'],
                        'anytime_probability': odds_data['anytime_probability'],
                        'american_odds': odds_data['american_odds']
                    }
            
            return player_odds
            
        except Exception as e:
            logger.error(f"Error processing team {team} players: {str(e)}")
            return {}
    
    def calculate_all_anytime_odds(self):
        """Calculate anytime TD odds for all games and players"""
        try:
            # Fetch data from both services
            team_games = self.fetch_team_analysis()
            player_usage_data = self.fetch_player_usage()
            
            results = {
                'analysis_date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'methodology': {
                    'alpha': self.alpha,
                    'epsilon': self.epsilon,
                    'allocation_formula': 'alpha * rz_usage_share + (1 - alpha) * td_share',
                    'anytime_probability': '1 - exp(-expected_tds)',
                    'source_note': 'Team TD projections already include matchup advantages'
                },
                'games': []
            }
            
            logger.info(f"Processing {len(team_games)} games...")
            
            for game in team_games:
                try:
                    away_team = game['away_team']
                    home_team = game['home_team']
                    away_projected_tds = game['away_projected_tds']
                    home_projected_tds = game['home_projected_tds']
                    
                    logger.info(f"Processing {game['game']}")
                    
                    # Process away team players
                    away_players = self.process_team_players(
                        away_team, away_projected_tds, player_usage_data
                    )
                    
                    # Process home team players  
                    home_players = self.process_team_players(
                        home_team, home_projected_tds, player_usage_data
                    )
                    
                    game_result = {
                        'game': game['game'],
                        'commence_time': game.get('commence_time', 'TBD'),
                        'bookmaker': game.get('bookmaker', 'Unknown'),
                        'away_team': away_team,
                        'home_team': home_team,
                        'away_projected_tds': away_projected_tds,
                        'home_projected_tds': home_projected_tds,
                        'away_players': away_players,
                        'home_players': home_players,
                        'total_away_players': len(away_players),
                        'total_home_players': len(home_players)
                    }
                    
                    results['games'].append(game_result)
                    
                except Exception as e:
                    logger.warning(f"Error processing game {game.get('game', 'Unknown')}: {str(e)}")
                    continue
            
            # Sort by commence time
            results['games'].sort(key=lambda x: x.get('commence_time', ''))
            
            logger.info(f"Successfully calculated odds for {len(results['games'])} games")
            return results
            
        except Exception as e:
            logger.error(f"Error calculating anytime odds: {str(e)}")
            return {"error": f"Analysis failed: {str(e)}"}
    
    def generate_json_output(self, results, include_metadata=True):
        """Generate JSON output for API consumption"""
        try:
            output = {
                "results": results,
                "metadata": {
                    "generated_at": datetime.now().isoformat(),
                    "disclaimer": "For educational analysis only. Calculated using Poisson distribution for anytime touchdown probabilities."
                } if include_metadata else None
            }
            
            if not include_metadata:
                output = {"results": results}
                
            return json.dumps(output, indent=2)
            
        except Exception as e:
            logger.error(f"Error generating JSON output: {str(e)}")
            return json.dumps({"error": "Failed to generate output", "message": str(e)})

def run_analysis():
    """Run analysis function - separates logic from main() for flask integration"""
    try:
        # Configuration - can be set via environment variables
        team_analysis_url = os.getenv('TEAM_ANALYSIS_URL')
        player_usage_url = os.getenv('PLAYER_USAGE_URL')
        
        calculator = AnytimeTDOddsCalculator(
            team_analysis_url=team_analysis_url,
            player_usage_url=player_usage_url
        )
        
        # Calculate all anytime odds
        results = calculator.calculate_all_anytime_odds()
        
        if not results or "error" in results:
            logger.error("Failed to calculate anytime odds")
            return None
        
        return {
            'results': results,
            'calculator': calculator
        }
        
    except Exception as e:
        logger.error(f"Analysis execution failed: {str(e)}")
        return None

def main():
    """Main function for command-line execution"""
    analysis_data = run_analysis()
    
    if not analysis_data:
        sys.exit(1)
    
    results = analysis_data['results']
    calculator = analysis_data['calculator']
    
    # Output JSON for API consumption
    json_output = calculator.generate_json_output(results)
    print(json_output)
    
    # Human-readable summary to stderr for logging
    print(f"\n=== NFL ANYTIME TD ODDS ANALYSIS ===", file=sys.stderr)
    print(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", file=sys.stderr)
    print("="*50, file=sys.stderr)
    
    return results

# Flask Integration
try:
    from flask import Flask, jsonify, request
    from flask_cors import CORS
    
    app = Flask(__name__)
    CORS(app)  # Enable CORS for all routes
    
    @app.route('/anytime-td-odds', methods=['GET'])
    def get_anytime_td_odds():
        """Calculate anytime TD odds for all games"""
        try:
            team_analysis_url = request.args.get('team_analysis_url')
            player_usage_url = request.args.get('player_usage_url')
            
            # Set environment variables temporarily
            original_env = {}
            env_vars = {}
            
            if team_analysis_url:
                env_vars['TEAM_ANALYSIS_URL'] = team_analysis_url
            if player_usage_url:
                env_vars['PLAYER_USAGE_URL'] = player_usage_url
            
            # Store original values and set new ones
            for key, value in env_vars.items():
                original_env[key] = os.environ.get(key)
                os.environ[key] = value
            
            try:
                # Run analysis
                analysis_data = run_analysis()
                
                if not analysis_data:
                    return jsonify({
                        "error": "Analysis failed",
                        "message": "Could not complete anytime TD odds calculation",
                        "timestamp": datetime.now().isoformat()
                    }), 500
                
                # Return results
                results = analysis_data['results']
                return jsonify(results)
                
            finally:
                # Restore original environment variables
                for key, original_value in original_env.items():
                    if original_value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = original_value
        
        except Exception as e:
            logger.error(f"Error in Flask endpoint: {str(e)}")
            return jsonify({
                "error": "Unexpected error",
                "message": str(e),
                "timestamp": datetime.now().isoformat()
            }), 500
    
    @app.route('/health', methods=['GET'])
    def health_check():
        """Health check endpoint"""
        return jsonify({
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "service": "Anytime TD Odds Calculator"
        })
    
    @app.route('/', methods=['GET'])
    def root():
        """Root endpoint with API documentation"""
        return jsonify({
            "service": "Anytime TD Odds Calculator API",
            "version": "1.0",
            "endpoints": {
                "/anytime-td-odds": {
                    "method": "GET",
                    "description": "Calculate anytime TD odds for all games",
                    "parameters": {
                        "team_analysis_url": "Optional - URL for team analysis service",
                        "player_usage_url": "Optional - URL for player usage service"
                    },
                    "example": "/anytime-td-odds?team_analysis_url=http://localhost:5000/team-analysis"
                },
                "/health": {
                    "method": "GET", 
                    "description": "Health check endpoint"
                }
            },
            "methodology": {
                "allocation_formula": "alpha * rz_usage_share + (1 - alpha) * td_share",
                "alpha": 0.85,
                "weighting": "85% RZ usage (opportunity) + 15% TD share (production)",
                "epsilon": 0.01,
                "anytime_probability": "1 - exp(-expected_tds)",
                "notes": "Uses Poisson distribution for anytime touchdown probabilities"
            },
            "timestamp": datetime.now().isoformat()
        })
    
    def run_flask_app():
        """Run Flask application"""
        port = int(os.environ.get('PORT', 10000))
        debug = os.environ.get('DEBUG', 'False').lower() == 'true'
        
        logger.info(f"Starting Anytime TD Odds Calculator API on port {port}")
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
        main()
