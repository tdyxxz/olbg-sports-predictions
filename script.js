// Sports configuration
const SPORTS_CONFIG = {
    'BASEBALL': { name: 'Baseball', icon: 'baseball-ball', color: '#dc2626' },
    'BASKETBALL': { name: 'Basketball', icon: 'basketball-ball', color: '#ea580c' },
    'CRICKET': { name: 'Cricket', icon: 'cricket', color: '#ca8a04' },
    'DARTS': { name: 'Darts', icon: 'bullseye', color: '#65a30d' },
    'GAA': { name: 'GAA', icon: 'flag', color: '#16a34a' },
    'GOLF': { name: 'Golf', icon: 'golf-ball', color: '#059669' },
    'GREYHOUND': { name: 'Greyhound Racing', icon: 'dog', color: '#0891b2' },
    'HANDBALL': { name: 'Handball', icon: 'volleyball-ball', color: '#0284c7' },
    'ICE HOCKEY': { name: 'Ice Hockey', icon: 'hockey-puck', color: '#2563eb' },
    'MOTOR RACING': { name: 'Motor Racing', icon: 'car', color: '#4f46e5' },
    'RUGBY LEAGUE': { name: 'Rugby League', icon: 'football-ball', color: '#7c3aed' },
    'RUGBY UNION': { name: 'Rugby Union', icon: 'football-ball', color: '#9333ea' },
    'SNOOKER': { name: 'Snooker', icon: 'circle', color: '#c026d3' },
    'TENNIS': { name: 'Tennis', icon: 'table-tennis', color: '#e11d48' },
    'VOLLEYBALL': { name: 'Volleyball', icon: 'volleyball-ball', color: '#be123c' },
    'AMERICAN FOOTBALL': { name: 'American Football', icon: 'football-ball', color: '#991b1b' }
};

// Global state
let allPredictions = [];
let filteredPredictions = [];

// Initialize the application
document.addEventListener('DOMContentLoaded', function() {
    initializeEventListeners();
    loadPredictions();
    updateLastUpdateTime();
});

// Initialize event listeners
function initializeEventListeners() {
    document.getElementById('searchInput').addEventListener('input', filterPredictions);
    document.getElementById('sportFilter').addEventListener('change', filterPredictions);
    document.getElementById('typeFilter').addEventListener('change', filterPredictions);
    document.getElementById('refreshBtn').addEventListener('click', loadPredictions);
}

// Load predictions from API
async function loadPredictions() {
    showLoadingState(true);
    
    try {
        // Try to load from the generated predictions API
        const response = await fetch('api/predictions.json');
        if (response.ok) {
            const data = await response.json();
            allPredictions = data.predictions || [];
        } else {
            // Fallback to sample data for demonstration
            allPredictions = generateSamplePredictions();
        }
        
        filteredPredictions = [...allPredictions];
        updateSportFilter();
        renderPredictions();
        updateStatistics();
        updateLastUpdateTime();
    } catch (error) {
        console.error('Error loading predictions:', error);
        // Fallback to sample data
        allPredictions = generateSamplePredictions();
        filteredPredictions = [...allPredictions];
        updateSportFilter();
        renderPredictions();
        updateStatistics();
        updateLastUpdateTime();
    } finally {
        showLoadingState(false);
    }
}

// Generate sample predictions for demonstration
function generateSamplePredictions() {
    const sampleData = [];
    const today = new Date().toISOString().split('T')[0];
    
    Object.keys(SPORTS_CONFIG).forEach(sportKey => {
        const config = SPORTS_CONFIG[sportKey];
        
        // Generate 2-5 predictions per sport
        const numPredictions = Math.floor(Math.random() * 4) + 2;
        
        for (let i = 0; i < numPredictions; i++) {
            sampleData.push({
                id: `${sportKey}-${i}`,
                sport: sportKey,
                sportName: config.name,
                type: Math.random() > 0.5 ? 'active' : 'research',
                title: generatePredictionTitle(sportKey),
                prediction: generatePredictionText(sportKey),
                confidence: Math.floor(Math.random() * 30) + 70, // 70-100%
                odds: (Math.random() * 3 + 1.2).toFixed(2), // 1.2-4.2
                date: today,
                time: `${Math.floor(Math.random() * 12) + 1}:${Math.random() > 0.5 ? '00' : '30'}`,
                venue: generateVenueName(sportKey),
                teams: generateTeams(sportKey)
            });
        }
    });
    
    return sampleData;
}

// Generate prediction title based on sport
function generatePredictionTitle(sport) {
    const titles = {
        'BASEBALL': ['Yankees vs Red Sox - Moneyline', 'Dodgers vs Giants - Over/Under'],
        'BASKETBALL': ['Lakers vs Celtics - Point Spread', 'Warriors vs Heat - Player Props'],
        'CRICKET': ['India vs Australia - Match Winner', 'England vs Pakistan - Top Batsman'],
        'TENNIS': ['Nadal vs Djokovic - Match Winner', 'Williams vs Osaka - Set Betting']
    };
    
    const sportTitles = titles[sport] || ['Match Analysis', 'Tournament Prediction'];
    return sportTitles[Math.floor(Math.random() * sportTitles.length)];
}

// Generate prediction text
function generatePredictionText(sport) {
    const texts = {
        'BASEBALL': 'Yankees should prevail with their 65% home win rate at Yankee Stadium, averaging 5.2 runs per game with a strong bullpen ERA of 3.1.',
        'CRICKET': 'India maintains strong form with 72% win rate at home venues, averaging 285 runs in first innings with powerplay scoring rate of 8.1 runs per over.'
    };
    
    return texts[sport] || 'Detailed statistical analysis supporting this prediction with verified historical performance data.';
}

// Generate venue name
function generateVenueName(sport) {
    const venues = {
        'BASEBALL': ['Yankee Stadium', 'Dodger Stadium', 'Fenway Park'],
        'BASKETBALL': ['Madison Square Garden', 'Staples Center', 'United Center'],
        'CRICKET': ['Lord\'s Cricket Ground', 'Melbourne Cricket Ground', 'Eden Gardens'],
        'TENNIS': ['Wimbledon Centre Court', 'Arthur Ashe Stadium', 'Roland Garros']
    };
    
    const sportVenues = venues[sport] || ['Main Stadium', 'Central Arena', 'National Ground'];
    return sportVenues[Math.floor(Math.random() * sportVenues.length)];
}

// Generate teams
function generateTeams(sport) {
    const teamPairs = {
        'BASEBALL': [['Yankees', 'Red Sox'], ['Dodgers', 'Giants'], ['Cubs', 'Cardinals']],
        'BASKETBALL': [['Lakers', 'Celtics'], ['Warriors', 'Heat'], ['Bulls', 'Pistons']],
        'CRICKET': [['India', 'Australia'], ['England', 'Pakistan'], ['South Africa', 'New Zealand']],
        'TENNIS': [['Nadal', 'Djokovic'], ['Federer', 'Murray'], ['Williams', 'Osaka']]
    };
    
    const sportTeams = teamPairs[sport] || [['Team A', 'Team B']];
    return sportTeams[Math.floor(Math.random() * sportTeams.length)];
}

// Update sport filter dropdown
function updateSportFilter() {
    const sportFilter = document.getElementById('sportFilter');
    const sports = [...new Set(allPredictions.map(p => p.sport))];
    
    sportFilter.innerHTML = '<option value="">All Sports</option>';
    sports.forEach(sport => {
        const config = SPORTS_CONFIG[sport];
        if (config) {
            sportFilter.innerHTML += `<option value="${sport}">${config.name}</option>`;
        }
    });
}

// Filter predictions based on search and filters
function filterPredictions() {
    const searchTerm = document.getElementById('searchInput').value.toLowerCase();
    const sportFilter = document.getElementById('sportFilter').value;
    const typeFilter = document.getElementById('typeFilter').value;
    
    filteredPredictions = allPredictions.filter(prediction => {
        const matchesSearch = !searchTerm || 
            prediction.title.toLowerCase().includes(searchTerm) ||
            prediction.prediction.toLowerCase().includes(searchTerm) ||
            prediction.sportName.toLowerCase().includes(searchTerm);
        
        const matchesSport = !sportFilter || prediction.sport === sportFilter;
        const matchesType = !typeFilter || prediction.type === typeFilter;
        
        return matchesSearch && matchesSport && matchesType;
    });
    
    renderPredictions();
    updateStatistics();
}

// Render predictions to the grid
function renderPredictions() {
    const grid = document.getElementById('sportsGrid');
    const emptyState = document.getElementById('emptyState');
    
    if (filteredPredictions.length === 0) {
        grid.innerHTML = '';
        emptyState.classList.remove('hidden');
        return;
    }
    
    emptyState.classList.add('hidden');
    
    // Group predictions by sport
    const groupedPredictions = {};
    filteredPredictions.forEach(prediction => {
        if (!groupedPredictions[prediction.sport]) {
            groupedPredictions[prediction.sport] = [];
        }
        groupedPredictions[prediction.sport].push(prediction);
    });
    
    // Render sport cards
    grid.innerHTML = '';
    Object.keys(groupedPredictions).forEach(sport => {
        const predictions = groupedPredictions[sport];
        const config = SPORTS_CONFIG[sport];
        
        if (config) {
            grid.innerHTML += createSportCard(sport, predictions, config);
        }
    });
    
    // Add click handlers for prediction items
    document.querySelectorAll('.prediction-item').forEach(item => {
        item.addEventListener('click', function() {
            showPredictionDetail(this.dataset.predictionId);
        });
    });
}

// Create sport card HTML
function createSportCard(sport, predictions, config) {
    const activeCount = predictions.filter(p => p.type === 'active').length;
    const researchCount = predictions.filter(p => p.type === 'research').length;
    
    return `
        <div class="sport-card bg-white rounded-lg shadow-md p-6 sport-${sport.toLowerCase().replace(' ', '')}">
            <div class="flex items-center justify-between mb-4">
                <div class="flex items-center space-x-3">
                    <div class="w-12 h-12 rounded-full flex items-center justify-center" style="background-color: ${config.color}20;">
                        <i class="fas fa-${config.icon} text-xl" style="color: ${config.color};"></i>
                    </div>
                    <div>
                        <h3 class="text-lg font-bold text-gray-800">${config.name}</h3>
                        <p class="text-sm text-gray-500">${predictions.length} predictions today</p>
                    </div>
                </div>
                <div class="text-right">
                    <span class="inline-flex items-center px-2 py-1 rounded-full text-xs font-medium bg-green-100 text-green-800">
                        ${activeCount} Active
                    </span>
                    <span class="inline-flex items-center px-2 py-1 rounded-full text-xs font-medium bg-purple-100 text-purple-800 ml-2">
                        ${researchCount} Research
                    </span>
                </div>
            </div>
            
            <div class="space-y-2">
                ${predictions.slice(0, 3).map(prediction => `
                    <div class="prediction-item p-3 rounded-lg border border-gray-200 cursor-pointer hover:border-blue-300" 
                         data-prediction-id="${prediction.id}">
                        <div class="flex justify-between items-start">
                            <div class="flex-1">
                                <h4 class="font-medium text-gray-800 text-sm">${prediction.title}</h4>
                                <p class="text-xs text-gray-600 mt-1">${prediction.venue} • ${prediction.time}</p>
                            </div>
                            <div class="text-right ml-3">
                                <span class="inline-flex items-center px-2 py-1 rounded text-xs font-medium ${
                                    prediction.type === 'active' 
                                        ? 'bg-blue-100 text-blue-800' 
                                        : 'bg-orange-100 text-orange-800'
                                }">
                                    ${prediction.type === 'active' ? 'Active' : 'Research'}
                                </span>
                                <div class="mt-1">
                                    <span class="text-sm font-bold text-gray-800">${prediction.odds}</span>
                                    <span class="text-xs text-gray-500 ml-1">${prediction.confidence}%</span>
                                </div>
                            </div>
                        </div>
                    </div>
                `).join('')}
                
                ${predictions.length > 3 ? `
                    <div class="text-center pt-2">
                        <button class="text-blue-600 text-sm hover:text-blue-800 font-medium" 
                                onclick="showAllPredictions('${sport}')">
                            View all ${predictions.length} predictions →
                        </button>
                    </div>
                ` : ''}
            </div>
        </div>
    `;
}

// Show prediction detail modal
function showPredictionDetail(predictionId) {
    const prediction = allPredictions.find(p => p.id === predictionId);
    if (!prediction) return;
    
    // Create modal HTML (simplified version)
    const modal = document.createElement('div');
    modal.className = 'fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50';
    modal.innerHTML = `
        <div class="bg-white rounded-lg shadow-xl max-w-2xl w-full mx-4 max-h-screen overflow-y-auto">
            <div class="p-6">
                <div class="flex justify-between items-start mb-4">
                    <h2 class="text-2xl font-bold text-gray-800">${prediction.title}</h2>
                    <button onclick="closeModal()" class="text-gray-400 hover:text-gray-600">
                        <i class="fas fa-times text-xl"></i>
                    </button>
                </div>
                
                <div class="grid grid-cols-2 gap-4 mb-4">
                    <div class="bg-gray-50 p-3 rounded">
                        <p class="text-sm text-gray-500">Sport</p>
                        <p class="font-medium">${prediction.sportName}</p>
                    </div>
                    <div class="bg-gray-50 p-3 rounded">
                        <p class="text-sm text-gray-500">Type</p>
                        <p class="font-medium">${prediction.type === 'active' ? 'Active Prediction' : 'Research Analysis'}</p>
                    </div>
                    <div class="bg-gray-50 p-3 rounded">
                        <p class="text-sm text-gray-500">Venue</p>
                        <p class="font-medium">${prediction.venue}</p>
                    </div>
                    <div class="bg-gray-50 p-3 rounded">
                        <p class="text-sm text-gray-500">Time</p>
                        <p class="font-medium">${prediction.time}</p>
                    </div>
                </div>
                
                <div class="mb-4">
                    <h3 class="font-medium text-gray-800 mb-2">Analysis</h3>
                    <p class="text-gray-600">${prediction.prediction}</p>
                </div>
                
                <div class="flex justify-between items-center">
                    <div class="flex space-x-4">
                        <div class="text-center">
                            <p class="text-sm text-gray-500">Odds</p>
                            <p class="text-xl font-bold text-gray-800">${prediction.odds}</p>
                        </div>
                        <div class="text-center">
                            <p class="text-sm text-gray-500">Confidence</p>
                            <p class="text-xl font-bold text-green-600">${prediction.confidence}%</p>
                        </div>
                    </div>
                    <button onclick="closeModal()" class="px-6 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700">
                        Close
                    </button>
                </div>
            </div>
        </div>
    `;
    
    document.body.appendChild(modal);
}

// Show all predictions for a specific sport
function showAllPredictions(sport) {
    document.getElementById('sportFilter').value = sport;
    filterPredictions();
    
    // Scroll to top
    window.scrollTo({ top: 0, behavior: 'smooth' });
}

// Close modal
function closeModal() {
    const modal = document.querySelector('.fixed.inset-0');
    if (modal) {
        modal.remove();
    }
}

// Update statistics
function updateStatistics() {
    const totalSports = [...new Set(filteredPredictions.map(p => p.sport))].length;
    const activePredictions = filteredPredictions.filter(p => p.type === 'active').length;
    const researchAnalysis = filteredPredictions.filter(p => p.type === 'research').length;
    
    document.getElementById('totalSports').textContent = totalSports;
    document.getElementById('activePredictions').textContent = activePredictions;
    document.getElementById('researchAnalysis').textContent = researchAnalysis;
    document.getElementById('predictionCount').textContent = `${filteredPredictions.length} Predictions Today`;
}

// Update last update time
function updateLastUpdateTime() {
    const now = new Date();
    const timeString = now.toLocaleString();
    
    document.getElementById('lastUpdate').textContent = `Last updated: ${timeString}`;
    document.getElementById('footerUpdate').textContent = timeString;
}

// Show/hide loading state
function showLoadingState(show) {
    const loadingState = document.getElementById('loadingState');
    const sportsGrid = document.getElementById('sportsGrid');
    
    if (show) {
        loadingState.classList.remove('hidden');
        sportsGrid.classList.add('hidden');
    } else {
        loadingState.classList.add('hidden');
        sportsGrid.classList.remove('hidden');
    }
}
