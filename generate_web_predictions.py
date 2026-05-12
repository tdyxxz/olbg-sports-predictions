#!/usr/bin/env python3
"""
Generate web-ready predictions from OLBG system outputs
Converts prediction data to JSON format for the website
"""

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Any

# Sports configuration matching the website
SPORTS_CONFIG = {
    'BASEBALL': {'name': 'Baseball', 'icon': 'baseball-ball', 'color': '#dc2626'},
    'BASKETBALL': {'name': 'Basketball', 'icon': 'basketball-ball', 'color': '#ea580c'},
    'CRICKET': {'name': 'Cricket', 'icon': 'cricket', 'color': '#ca8a04'},
    'DARTS': {'name': 'Darts', 'icon': 'bullseye', 'color': '#65a30d'},
    'GAA': {'name': 'GAA', 'icon': 'flag', 'color': '#16a34a'},
    'GOLF': {'name': 'Golf', 'icon': 'golf-ball', 'color': '#059669'},
    'GREYHOUND': {'name': 'Greyhound Racing', 'icon': 'dog', 'color': '#0891b2'},
    'HANDBALL': {'name': 'Handball', 'icon': 'volleyball-ball', 'color': '#0284c7'},
    'ICE HOCKEY': {'name': 'Ice Hockey', 'icon': 'hockey-puck', 'color': '#2563eb'},
    'MOTOR RACING': {'name': 'Motor Racing', 'icon': 'car', 'color': '#4f46e5'},
    'RUGBY LEAGUE': {'name': 'Rugby League', 'icon': 'football-ball', 'color': '#7c3aed'},
    'RUGBY UNION': {'name': 'Rugby Union', 'icon': 'football-ball', 'color': '#9333ea'},
    'SNOOKER': {'name': 'Snooker', 'icon': 'circle', 'color': '#c026d3'},
    'TENNIS': {'name': 'Tennis', 'icon': 'table-tennis', 'color': '#e11d48'},
    'VOLLEYBALL': {'name': 'Volleyball', 'icon': 'volleyball-ball', 'color': '#be123c'},
    'AMERICAN FOOTBALL': {'name': 'American Football', 'icon': 'football-ball', 'color': '#991b1b'}
}

class WebPredictionGenerator:
    def __init__(self, base_dir: Path = None):
        self.base_dir = base_dir or Path(__file__).parent
        self.predictions = []
        
    def collect_predictions_from_files(self) -> List[Dict[str, Any]]:
        """Collect predictions from various output files"""
        predictions = []
        today = datetime.now().strftime('%Y-%m-%d')
        
        # Try to collect actual written predictions first
        predictions.extend(self._collect_actual_written_predictions(today))
        
        # If no real predictions found, fall back to other methods
        if not predictions:
            # Collect from written predictions dumps
            predictions.extend(self._collect_written_predictions(today))
            
            # Collect from research dumps
            predictions.extend(self._collect_research_predictions(today))
            
            # Collect from sport-specific outputs
            predictions.extend(self._collect_sport_outputs())
        
        return predictions
    
    def _collect_actual_written_predictions(self, date: str) -> List[Dict[str, Any]]:
        """Collect actual written predictions from text files"""
        predictions = []
        written_dir = self.base_dir / "WRITTEN PREDICTIONS" / "ARCHIVE" / date.replace('-', '-')
        
        if not written_dir.exists():
            return predictions
        
        # Look for written prediction text files
        for file_path in written_dir.glob("written_predictions_*.txt"):
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Parse the text file format
                sport = self._extract_sport_from_content(content)
                if not sport:
                    continue
                
                # Parse individual predictions
                parsed_predictions = self._parse_written_predictions_text(content, sport, date)
                predictions.extend(parsed_predictions)
                
            except Exception as e:
                print(f"Error reading {file_path}: {e}")
        
        # Also check for sport-specific prediction files
        for file_path in written_dir.glob("*_active_predictions_*.txt"):
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Extract sport from filename
                sport = self._extract_sport_from_filename(file_path.name)
                if not sport:
                    continue
                
                # Parse the text file format
                parsed_predictions = self._parse_written_predictions_text(content, sport, date)
                predictions.extend(parsed_predictions)
                
            except Exception as e:
                print(f"Error reading {file_path}: {e}")
                
        return predictions
    
    def _extract_sport_from_content(self, content: str) -> str:
        """Extract sport from the content header"""
        lines = content.split('\n')
        for line in lines[:5]:
            if 'DAILY WRITTEN PREDICTION SEARCH' in line:
                # Extract sport from line like "DAILY WRITTEN PREDICTION SEARCH — BASKETBALL"
                parts = line.split('—')
                if len(parts) > 1:
                    sport_name = parts[-1].strip().upper()
                    return self._normalize_sport_name(sport_name)
        return None
    
    def _extract_sport_from_filename(self, filename: str) -> str:
        """Extract sport from filename"""
        # Handle filenames like "handball_active_predictions_20260512_094355.txt"
        if '_active_predictions_' in filename:
            sport_part = filename.split('_active_predictions_')[0]
            return self._normalize_sport_name(sport_part)
        return None
    
    def _normalize_sport_name(self, sport_name: str) -> str:
        """Normalize sport name to match SPORTS_CONFIG keys"""
        sport_mapping = {
            'BASKETBALL': 'BASKETBALL',
            'BASEBALL': 'BASEBALL',
            'CRICKET': 'CRICKET',
            'DARTS': 'DARTS',
            'GAA': 'GAA',
            'GOLF': 'GOLF',
            'GREYHOUND': 'GREYHOUND',
            'HANDBALL': 'HANDBALL',
            'ICE HOCKEY': 'ICE HOCKEY',
            'MOTOR RACING': 'MOTOR RACING',
            'RUGBY LEAGUE': 'RUGBY LEAGUE',
            'RUGBY UNION': 'RUGBY UNION',
            'SNOOKER': 'SNOOKER',
            'TENNIS': 'TENNIS',
            'VOLLEYBALL': 'VOLLEYBALL',
            'AMERICAN FOOTBALL': 'AMERICAN FOOTBALL'
        }
        
        # Try exact match first
        if sport_name in sport_mapping:
            return sport_mapping[sport_name]
        
        # Try partial match
        for key, value in sport_mapping.items():
            if key in sport_name or sport_name in key:
                return value
        
        return sport_name.upper()
    
    def _parse_written_predictions_text(self, content: str, sport: str, date: str) -> List[Dict[str, Any]]:
        """Parse written predictions text file format"""
        predictions = []
        lines = content.split('\n')
        
        current_prediction = None
        prediction_count = 0
        in_analysis = False
        
        for i, line in enumerate(lines):
            line = line.strip()
            
            # Detect prediction start (numbered list)
            if line and line[0].isdigit() and '.' in line and len(line) < 100:
                # Save previous prediction if exists
                if current_prediction and current_prediction['prediction']:
                    predictions.append(current_prediction)
                    prediction_count += 1
                
                # Start new prediction
                current_prediction = {
                    'id': f"{sport.lower().replace(' ', '-')}-{prediction_count}",
                    'sport': sport,
                    'sportName': SPORTS_CONFIG.get(sport, {}).get('name', sport),
                    'type': 'research',  # Default to research
                    'title': line.split('.', 1)[1].strip() if '.' in line else line,
                    'prediction': '',
                    'confidence': 85,
                    'odds': '2.50',
                    'date': date,
                    'time': '12:00',
                    'venue': 'Stadium',
                    'teams': ['Team A', 'Team B']
                }
                in_analysis = False
            
            # Parse prediction details
            elif current_prediction:
                if line.startswith('Pick:'):
                    current_prediction['title'] = line.split(':', 1)[1].strip()
                    in_analysis = False
                elif line.startswith('Event Time:'):
                    time_str = line.split(':', 1)[1].strip()
                    current_prediction['time'] = self._parse_time(time_str)
                    in_analysis = False
                elif line.startswith('Competition:'):
                    in_analysis = False
                elif line.startswith('ACTIVE WRITES') or line.startswith('RESEARCH WRITES'):
                    in_analysis = False
                elif line.startswith('No active predictions'):
                    in_analysis = False
                elif line and not line.startswith('-') and not line.startswith('FINAL') and not line.startswith('VALIDATION'):
                    # This is likely the analysis text
                    if len(line) > 20:  # Only substantial text is analysis
                        if current_prediction['prediction']:
                            current_prediction['prediction'] += ' ' + line
                        else:
                            current_prediction['prediction'] = line
                            in_analysis = True
        
        # Don't forget the last prediction
        if current_prediction and current_prediction['prediction']:
            predictions.append(current_prediction)
        
        return predictions
    
    def _parse_time(self, time_str: str) -> str:
        """Parse time string to extract time"""
        # Handle formats like "May 12, 2026 3:00 PM PT"
        try:
            if ':' in time_str:
                time_part = time_str.split(':')[0]
                # Extract the time portion
                for part in time_str.split():
                    if ':' in part:
                        return part.split(':')[0] + ':' + part.split(':')[1][:2]
        except:
            pass
        return '12:00'
    
    def _collect_written_predictions(self, date: str) -> List[Dict[str, Any]]:
        """Collect from written prediction support dumps"""
        predictions = []
        written_dir = self.base_dir / "WRITTEN PREDICTIONS"
        
        # Look for today's support dump
        pattern = f"written_prediction_support_dump_{date}*.json"
        for file_path in written_dir.glob(pattern):
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    
                for item in data:
                    if isinstance(item, dict) and item.get('status') == 'written':
                        prediction = self._convert_to_web_format(item, 'active')
                        if prediction:
                            predictions.append(prediction)
                            
            except Exception as e:
                print(f"Error reading {file_path}: {e}")
                
        return predictions
    
    def _collect_research_predictions(self, date: str) -> List[Dict[str, Any]]:
        """Collect from research review dumps"""
        predictions = []
        research_dir = self.base_dir / "WRITTEN PREDICTIONS" / "RESEARCH ONLY"
        
        # Look for today's research dump
        pattern = f"research_review_dump_{date}*.json"
        for file_path in research_dir.glob(pattern):
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    
                for item in data.get('review', []):
                    if isinstance(item, dict) and item.get('status') == 'written':
                        prediction = self._convert_to_web_format(item, 'research')
                        if prediction:
                            predictions.append(prediction)
                            
            except Exception as e:
                print(f"Error reading {file_path}: {e}")
                
        return predictions
    
    def _collect_sport_outputs(self) -> List[Dict[str, Any]]:
        """Collect from sport-specific output files"""
        predictions = []
        
        sports = [
            'BASEBALL OLBG', 'BASKETBALL OLBG', 'CRICKET OLBG', 'DARTS OLBG',
            'GAA OLBG', 'GOLF OBG', 'GREYHOUND OLBG', 'HANDBALL OLBG',
            'ICE HOCKEY OLBG', 'MOTOR RACING OLBG', 'RUGBY LEAGUE OLBG',
            'RUGBY UNION OLBG', 'SNOOKER OLBG', 'TENNIS OLBG', 'VOLLEYBALL OLBG'
        ]
        
        for sport_dir in sports:
            sport_path = self.base_dir / sport_dir
            if sport_path.exists():
                predictions.extend(self._collect_from_sport_dir(sport_path))
                
        return predictions
    
    def _collect_from_sport_dir(self, sport_path: Path) -> List[Dict[str, Any]]:
        """Collect predictions from a specific sport directory"""
        predictions = []
        sport_name = sport_path.name.replace(' OLBG', '').replace(' OBG', '')
        outputs_dir = sport_path / "outputs"
        
        if not outputs_dir.exists():
            return predictions
            
        # Look for model summary files
        for file_path in outputs_dir.glob("*summary.json"):
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    
                # Convert model data to web format
                if 'lanes' in data:
                    for lane in data['lanes']:
                        if lane.get('pick_count', 0) > 0:
                            prediction = {
                                'id': f"{sport_name}-{file_path.stem}-{lane.get('label', 'unknown')}",
                                'sport': sport_name,
                                'sportName': SPORTS_CONFIG.get(sport_name, {}).get('name', sport_name),
                                'type': 'active',
                                'title': f"{lane.get('label', 'Prediction')} - {sport_name}",
                                'prediction': lane.get('description', f'Analysis for {lane.get("label", "prediction")}'),
                                'confidence': min(95, max(70, lane.get('pick_count', 5) * 10)),  # Mock confidence
                                'odds': f"{lane.get('avg_odds', 2.5):.2f}",
                                'date': datetime.now().strftime('%Y-%m-%d'),
                                'time': datetime.now().strftime('%H:%M'),
                                'venue': lane.get('venue', 'TBD'),
                                'teams': lane.get('teams', ['Team A', 'Team B'])
                            }
                            predictions.append(prediction)
                            
            except Exception as e:
                print(f"Error reading {file_path}: {e}")
                
        return predictions
    
    def _convert_to_web_format(self, item: Dict[str, Any], pred_type: str) -> Dict[str, Any]:
        """Convert prediction item to web format"""
        try:
            # Extract sport from the prediction
            sport_key = self._extract_sport_from_prediction(item)
            if not sport_key:
                return None
                
            config = SPORTS_CONFIG.get(sport_key, {'name': sport_key, 'icon': 'trophy', 'color': '#6b7280'})
            
            return {
                'id': item.get('id', f"{sport_key}-{hash(str(item)) % 10000}"),
                'sport': sport_key,
                'sportName': config['name'],
                'type': pred_type,
                'title': item.get('title', item.get('event', f'{sport_key} Prediction')),
                'prediction': item.get('prediction', item.get('analysis', 'Detailed analysis available')),
                'confidence': item.get('confidence', 85),
                'odds': str(item.get('odds', 2.5)),
                'date': item.get('date', datetime.now().strftime('%Y-%m-%d')),
                'time': item.get('time', datetime.now().strftime('%H:%M')),
                'venue': item.get('venue', 'Stadium'),
                'teams': item.get('teams', ['Team A', 'Team B'])
            }
        except Exception as e:
            print(f"Error converting prediction: {e}")
            return None
    
    def _extract_sport_from_prediction(self, item: Dict[str, Any]) -> str:
        """Extract sport key from prediction item"""
        # Check various fields for sport information
        sport_fields = ['sport', 'category', 'type', 'source']
        
        for field in sport_fields:
            if field in item:
                value = str(item[field]).upper()
                for sport_key in SPORTS_CONFIG.keys():
                    if sport_key in value:
                        return sport_key
        
        # Try to match from title/prediction text
        text_to_check = ' '.join([
            str(item.get('title', '')),
            str(item.get('prediction', '')),
            str(item.get('event', ''))
        ]).upper()
        
        for sport_key in SPORTS_CONFIG.keys():
            if sport_key in text_to_check:
                return sport_key
                
        return 'UNKNOWN'
    
    def generate_sample_predictions(self) -> List[Dict[str, Any]]:
        """Generate sample predictions when no real data is available"""
        predictions = []
        today = datetime.now().strftime('%Y-%m-%d')
        
        for sport_key, config in SPORTS_CONFIG.items():
            # Generate 2-5 predictions per sport
            num_predictions = 3
            
            for i in range(num_predictions):
                prediction = {
                    'id': f"{sport_key.lower().replace(' ', '-')}-{i}",
                    'sport': sport_key,
                    'sportName': config['name'],
                    'type': 'active' if i % 2 == 0 else 'research',
                    'title': f"{config['name']} Match Analysis {i+1}",
                    'prediction': f"Statistical analysis for {config['name']} with verified historical data and performance metrics.",
                    'confidence': 75 + (i * 5),
                    'odds': f"{2.0 + (i * 0.3):.2f}",
                    'date': today,
                    'time': f"{9 + i}:00",
                    'venue': f"{config['name']} Stadium",
                    'teams': [f"Team A{i+1}", f"Team B{i+1}"]
                }
                predictions.append(prediction)
                
        return predictions
    
    def save_predictions_json(self, predictions: List[Dict[str, Any]], output_path: Path):
        """Save predictions to JSON file for the website"""
        web_data = {
            'lastUpdated': datetime.now().isoformat(),
            'totalPredictions': len(predictions),
            'sports': list(SPORTS_CONFIG.keys()),
            'predictions': predictions
        }
        
        # Create api directory if it doesn't exist
        output_path.parent.mkdir(exist_ok=True)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(web_data, f, indent=2, ensure_ascii=False)
        
        print(f"Saved {len(predictions)} predictions to {output_path}")
    
    def update_website(self):
        """Main method to update website predictions"""
        print("Generating web predictions...")
        
        # Collect predictions
        predictions = self.collect_predictions_from_files()
        
        # If no real predictions found, log error but don't generate fake data
        if not predictions:
            print("WARNING: No real predictions found in WRITTEN PREDICTIONS folder")
            print("Website will show no predictions until predictions are generated")
        
        # Save to web format (even if empty)
        api_path = self.base_dir / "api" / "predictions.json"
        self.save_predictions_json(predictions, api_path)
        
        print(f"Website updated with {len(predictions)} predictions")
        return len(predictions)

def main():
    """Main execution function"""
    generator = WebPredictionGenerator()
    count = generator.update_website()
    return count

if __name__ == "__main__":
    main()
