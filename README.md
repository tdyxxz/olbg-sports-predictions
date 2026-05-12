# OLBG Sports Betting Prediction System

A comprehensive automated sports betting prediction system that generates daily picks across multiple sports using verified statistics and machine learning models.

## Supported Sports

- **American Football** - NFL and college football predictions
- **Baseball** - MLB betting analysis and picks
- **Basketball** - NBA and international basketball
- **Cricket** - International and T20 cricket predictions
- **Darts** - Professional darts tournament analysis
- **GAA** - Gaelic Athletic Association sports
- **Golf** - PGA and European tour predictions
- **Greyhound Racing** - UK greyhound racing analysis
- **Handball** - International handball predictions
- **Ice Hockey** - NHL and European hockey
- **Motor Racing** - F1 and motorsport betting
- **Rugby League** - Super League and international rugby
- **Rugby Union** - Premiership and international rugby
- **Snooker** - Professional snooker tournaments
- **Tennis** - ATP and WTA tour predictions
- **Volleyball** - International volleyball predictions

## Features

- **Daily Automated Runs**: Generates predictions every day at 9 AM PST
- **Verified Statistics**: All predictions based on verifiable statistical data
- **ROI Optimization**: Continuously improved models for maximum return on investment
- **Multi-Sport Coverage**: Comprehensive analysis across 15+ sports
- **Research & Active Predictions**: Both research-based and active betting picks

## Setup

### Prerequisites
- Python 3.10 or higher
- PowerShell (for Windows automation)
- Git

### Installation

1. Clone this repository:
```bash
git clone <repository-url>
cd "OLBG CODEX PROJECTS"
```

2. Install Python dependencies:
```bash
pip install -r requirements.txt
```

3. Run manual prediction cycle:
```powershell
.\run_daily_full_cycle.ps1
```

## Automation

This project uses GitHub Actions for automated daily execution:

- **Schedule**: Runs every day at 9:00 AM PST (17:00 UTC)
- **Manual Trigger**: Can be run manually via GitHub Actions tab
- **Artifact Storage**: Prediction results stored for 30 days
- **Auto-commit**: Changes automatically committed back to repository

### Workflow Steps

1. **Environment Setup**: Configures Python and dependencies
2. **Data Collection**: Fetches latest sports data and statistics
3. **Model Execution**: Runs prediction models for all sports
4. **Result Generation**: Creates written predictions and analysis
5. **Quality Control**: Validates and filters predictions
6. **Output Storage**: Saves results and commits changes

## File Structure

```
├── [SPORT] OLBG/           # Sport-specific modules
│   ├── scripts/            # Prediction scripts
│   ├── config/             # Configuration files
│   └── outputs/            # Sport-specific results
├── scripts/                # Shared utilities and pipeline scripts
├── WRITTEN PREDICTIONS/    # Generated prediction outputs
├── trained_models/         # Machine learning models
├── data/                   # Historical data and caches
└── run_daily_full_cycle.ps1 # Main automation script
```

## Daily Output

The system generates:
- **Active Predictions**: Ready-to-use betting picks
- **Research Analysis**: In-depth statistical research
- **Performance Reports**: ROI and accuracy tracking
- **Model Updates**: Retrained models with latest data

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test locally with `.\run_daily_full_cycle.ps1`
5. Submit a pull request

## Monitoring

- Check GitHub Actions tab for run status
- Review prediction artifacts in the Actions tab
- Monitor performance through generated reports
- Track ROI improvements through summary files

## License

This project is proprietary and confidential.
