param(
    [Parameter(Mandatory = $true)]
    [string]$CsvPath,

    [double]$MinEdgePct = 4.0,
    [double]$FlatStake = 1.0,
    [string]$OutputDir = ".\output"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Get-SigmoidProbability {
    param(
        [double]$Score,
        [double]$Center = 50.0,
        [double]$Scale = 10.0
    )

    return 1.0 / (1.0 + [math]::Exp(-(($Score - $Center) / $Scale)))
}

function Get-ImpliedProbability {
    param(
        [double]$DecimalOdds
    )

    if ($DecimalOdds -le 1.0) {
        return $null
    }

    return 1.0 / $DecimalOdds
}

function Get-MatchWinnerScore {
    param(
        $Row,
        [string]$Side
    )

    $isHome = $Side -eq "HOME"
    $winRate = if ($isHome) { [double]$Row.home_recent_win_rate } else { [double]$Row.away_recent_win_rate }
    $oppWinRate = if ($isHome) { [double]$Row.away_recent_win_rate } else { [double]$Row.home_recent_win_rate }
    $margin = if ($isHome) { [double]$Row.home_recent_avg_margin } else { [double]$Row.away_recent_avg_margin }
    $oppMargin = if ($isHome) { [double]$Row.away_recent_avg_margin } else { [double]$Row.home_recent_avg_margin }
    $setPiece = if ($isHome) { [double]$Row.home_set_piece_rating } else { [double]$Row.away_set_piece_rating }
    $oppSetPiece = if ($isHome) { [double]$Row.away_set_piece_rating } else { [double]$Row.home_set_piece_rating }
    $kicking = if ($isHome) { [double]$Row.home_goal_kicking_rating } else { [double]$Row.away_goal_kicking_rating }
    $oppKicking = if ($isHome) { [double]$Row.away_goal_kicking_rating } else { [double]$Row.home_goal_kicking_rating }
    $intl = if ($isHome) { [double]$Row.international_absence_home } else { [double]$Row.international_absence_away }
    $oppIntl = if ($isHome) { [double]$Row.international_absence_away } else { [double]$Row.international_absence_home }
    $rest = if ($isHome) { [double]$Row.home_rest_days } else { [double]$Row.away_rest_days }
    $oppRest = if ($isHome) { [double]$Row.away_rest_days } else { [double]$Row.home_rest_days }
    $travelPenalty = if ($isHome) { 0.0 } else { 12.0 * [double]$Row.travel_fatigue_away }

    $score = 50.0
    $score += 18.0 * ($winRate - $oppWinRate)
    $score += 1.2 * ($margin - $oppMargin)
    $score += 0.35 * ($setPiece - $oppSetPiece)
    $score += 0.18 * ($kicking - $oppKicking)
    $score += 1.5 * ($rest - $oppRest)
    $score -= 16.0 * $intl
    $score += 10.0 * $oppIntl
    $score -= $travelPenalty

    if ($isHome) {
        $score += 4.0
    }

    return [math]::Max(0.0, [math]::Min(100.0, $score))
}

function Get-HandicapScore {
    param(
        $Row
    )

    $underdogSide = [string]$Row.handicap_team
    $isHome = $underdogSide -eq "HOME"
    $recentMargin = if ($isHome) { [double]$Row.home_recent_avg_margin } else { [double]$Row.away_recent_avg_margin }
    $setPiece = if ($isHome) { [double]$Row.home_set_piece_rating } else { [double]$Row.away_set_piece_rating }
    $oppSetPiece = if ($isHome) { [double]$Row.away_set_piece_rating } else { [double]$Row.home_set_piece_rating }
    $kicking = if ($isHome) { [double]$Row.home_goal_kicking_rating } else { [double]$Row.away_goal_kicking_rating }
    $atsRate = if ($isHome) { [double]$Row.home_ats_cover_rate } else { [double]$Row.away_ats_cover_rate }
    $intlOpp = if ($isHome) { [double]$Row.international_absence_away } else { [double]$Row.international_absence_home }
    $weather = [double]$Row.weather_severity
    $travel = if ($isHome) { 0.0 } else { [double]$Row.travel_fatigue_away }

    $baseWinScore = Get-MatchWinnerScore -Row $Row -Side $underdogSide
    $score = $baseWinScore
    $score += 20.0 * ($atsRate - 0.5)
    $score += 0.35 * ($setPiece - $oppSetPiece)
    $score += 0.22 * ($kicking - 50.0)
    $score += 10.0 * $weather
    $score += 10.0 * $intlOpp
    $score += 8.0 * $travel

    if ($recentMargin -ge 0) {
        $score += 8.0
    } elseif ($recentMargin -gt -5.0) {
        $score += 5.0
    } elseif ($recentMargin -lt -15.0) {
        $score -= 18.0
    }

    $line = [double]$Row.handicap_line
    if ($line -ge 3.5 -and $line -le 13.5) {
        $score += 6.0
    } elseif ($line -gt 16.5) {
        $score -= 10.0
    }

    return [math]::Max(0.0, [math]::Min(100.0, $score))
}

function Get-UnderScore {
    param(
        $Row
    )

    $pace = [double]$Row.competition_pace_factor
    $weather = [double]$Row.weather_severity
    $ref = [double]$Row.ref_penalty_bias
    $homeAttack = 0.45 * [double]$Row.home_set_piece_rating + 0.35 * [double]$Row.home_goal_kicking_rating + 20.0 * [double]$Row.home_recent_win_rate
    $awayAttack = 0.45 * [double]$Row.away_set_piece_rating + 0.35 * [double]$Row.away_goal_kicking_rating + 20.0 * [double]$Row.away_recent_win_rate
    $combinedAttack = ($homeAttack + $awayAttack) / 2.0
    $line = [double]$Row.total_line

    $score = 50.0
    $score += 30.0 * $weather
    $score += 10.0 * [math]::Max(0.0, $ref)
    $score -= 18.0 * [math]::Max(0.0, $pace)
    $score += 18.0 * [math]::Max(0.0, -$pace)
    $score -= 0.25 * ($combinedAttack - 60.0)

    if ($line -ge 61.0) {
        $score += 8.0
    }

    return [math]::Max(0.0, [math]::Min(100.0, $score))
}

function Get-OverScore {
    param(
        $Row
    )

    return 100.0 - (Get-UnderScore -Row $Row)
}

function Get-HandicapResult {
    param(
        $Row
    )

    $homeScore = [double]$Row.home_score
    $awayScore = [double]$Row.away_score
    $line = [double]$Row.handicap_line
    $team = [string]$Row.handicap_team
    $adjustedMargin = if ($team -eq "HOME") {
        ($homeScore + $line) - $awayScore
    } else {
        ($awayScore + $line) - $homeScore
    }

    if ($adjustedMargin -gt 0) {
        return 1
    }

    if ($adjustedMargin -eq 0) {
        return 0
    }

    return -1
}

function Get-TotalResult {
    param(
        $Row,
        [string]$Side
    )

    $total = [double]$Row.home_score + [double]$Row.away_score
    $line = [double]$Row.total_line

    if ($total -eq $line) {
        return 0
    }

    if ($Side -eq "OVER") {
        return $(if ($total -gt $line) { 1 } else { -1 })
    }

    return $(if ($total -lt $line) { 1 } else { -1 })
}

function New-BetRecord {
    param(
        [string]$Market,
        [string]$Selection,
        [double]$Score,
        [double]$ModelProbability,
        [double]$ImpliedProbability,
        [double]$Odds,
        [int]$Result,
        [double]$Stake,
        $Row
    )

    $profit = switch ($Result) {
        1 { ($Odds - 1.0) * $Stake }
        0 { 0.0 }
        default { -1.0 * $Stake }
    }

    [pscustomobject]@{
        match_date = $Row.match_date
        competition = $Row.competition
        home_team = $Row.home_team
        away_team = $Row.away_team
        market = $Market
        selection = $Selection
        score = [math]::Round($Score, 2)
        model_probability = [math]::Round($ModelProbability, 4)
        implied_probability = [math]::Round($ImpliedProbability, 4)
        edge_pct = [math]::Round((($ModelProbability - $ImpliedProbability) * 100.0), 2)
        odds = $Odds
        stake = $Stake
        result = $Result
        profit_units = [math]::Round($profit, 4)
    }
}

if (-not (Test-Path $CsvPath)) {
    throw "CSV path not found: $CsvPath"
}

if (-not (Test-Path $OutputDir)) {
    New-Item -ItemType Directory -Path $OutputDir | Out-Null
}

$rows = Import-Csv -Path $CsvPath
$bets = New-Object System.Collections.Generic.List[object]

foreach ($row in $rows) {
    $homeWinScore = Get-MatchWinnerScore -Row $row -Side "HOME"
    $awayWinScore = Get-MatchWinnerScore -Row $row -Side "AWAY"

    $selectedSide = if ($homeWinScore -ge $awayWinScore) { "HOME" } else { "AWAY" }
    $selectedScore = [math]::Max($homeWinScore, $awayWinScore)
    $selectedOdds = if ($selectedSide -eq "HOME") { [double]$row.home_moneyline_decimal } else { [double]$row.away_moneyline_decimal }
    $winModelProb = Get-SigmoidProbability -Score $selectedScore -Center 56.0 -Scale 9.0
    $winImpliedProb = Get-ImpliedProbability -DecimalOdds $selectedOdds
    $winEdgePct = ($winModelProb - $winImpliedProb) * 100.0

    $actualWinner = if ([double]$row.home_score -gt [double]$row.away_score) { "HOME" } else { "AWAY" }
    $winResult = if ([double]$row.home_score -eq [double]$row.away_score) { 0 } elseif ($selectedSide -eq $actualWinner) { 1 } else { -1 }

    if ($selectedScore -ge 63.0 -and $winEdgePct -ge $MinEdgePct -and $selectedOdds -ge 1.45) {
        $bets.Add((New-BetRecord -Market "moneyline" -Selection $selectedSide -Score $selectedScore -ModelProbability $winModelProb -ImpliedProbability $winImpliedProb -Odds $selectedOdds -Result $winResult -Stake $FlatStake -Row $row))
    }

    $handicapScore = Get-HandicapScore -Row $row
    $handicapProb = Get-SigmoidProbability -Score $handicapScore -Center 57.0 -Scale 8.0
    $handicapImplied = Get-ImpliedProbability -DecimalOdds ([double]$row.handicap_odds_decimal)
    $handicapEdgePct = ($handicapProb - $handicapImplied) * 100.0
    $handicapResult = Get-HandicapResult -Row $row

    if ($handicapScore -ge 64.0 -and $handicapEdgePct -ge $MinEdgePct) {
        $bets.Add((New-BetRecord -Market "handicap" -Selection ([string]$row.handicap_team) -Score $handicapScore -ModelProbability $handicapProb -ImpliedProbability $handicapImplied -Odds ([double]$row.handicap_odds_decimal) -Result $handicapResult -Stake $FlatStake -Row $row))
    }

    $underScore = Get-UnderScore -Row $row
    $overScore = Get-OverScore -Row $row
    $totalSide = if ($underScore -ge $overScore) { "UNDER" } else { "OVER" }
    $totalScore = [math]::Max($underScore, $overScore)
    $totalOdds = if ($totalSide -eq "UNDER") { [double]$row.under_odds_decimal } else { [double]$row.over_odds_decimal }
    $totalProb = Get-SigmoidProbability -Score $totalScore -Center 59.0 -Scale 8.0
    $totalImplied = Get-ImpliedProbability -DecimalOdds $totalOdds
    $totalEdgePct = ($totalProb - $totalImplied) * 100.0
    $totalResult = Get-TotalResult -Row $row -Side $totalSide

    if ($totalScore -ge 66.0 -and $totalEdgePct -ge ($MinEdgePct + 1.0)) {
        $bets.Add((New-BetRecord -Market "total" -Selection $totalSide -Score $totalScore -ModelProbability $totalProb -ImpliedProbability $totalImplied -Odds $totalOdds -Result $totalResult -Stake $FlatStake -Row $row))
    }
}

$betCount = $bets.Count
$totalStake = ($bets | Measure-Object -Property stake -Sum).Sum
$totalProfit = ($bets | Measure-Object -Property profit_units -Sum).Sum
$roi = if ($totalStake) { ($totalProfit / $totalStake) * 100.0 } else { 0.0 }
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$betLogPath = Join-Path $OutputDir ("bet_log_{0}.csv" -f $timestamp)
$summaryPath = Join-Path $OutputDir ("summary_{0}.json" -f $timestamp)

Write-Host ""
Write-Host "Rugby union profitability backtest"
Write-Host "--------------------------------"
Write-Host ("Rows processed : {0}" -f $rows.Count)
Write-Host ("Bets placed    : {0}" -f $betCount)
Write-Host ("Profit (units) : {0:N2}" -f $totalProfit)
Write-Host ("ROI            : {0:N2}%" -f $roi)
Write-Host ""

if ($betCount -gt 0) {
    $summary = $bets |
        Group-Object -Property market |
        ForEach-Object {
            $marketStake = ($_.Group | Measure-Object -Property stake -Sum).Sum
            $marketProfit = ($_.Group | Measure-Object -Property profit_units -Sum).Sum
            [pscustomobject]@{
                market = $_.Name
                bets = $_.Count
                profit_units = [math]::Round($marketProfit, 4)
                roi_pct = [math]::Round((($marketProfit / $marketStake) * 100.0), 2)
            }
        }

    $bets | Export-Csv -Path $betLogPath -NoTypeInformation
    [pscustomobject]@{
        generated_at = (Get-Date).ToString("s")
        csv_path = (Resolve-Path $CsvPath).Path
        rows_processed = $rows.Count
        bets_placed = $betCount
        total_stake = [math]::Round($totalStake, 4)
        total_profit_units = [math]::Round($totalProfit, 4)
        roi_pct = [math]::Round($roi, 2)
        min_edge_pct = $MinEdgePct
        flat_stake = $FlatStake
        bet_log_path = $betLogPath
        by_market = $summary
    } | ConvertTo-Json -Depth 5 | Set-Content -Path $summaryPath

    Write-Host "By market"
    $summary | Format-Table -AutoSize

    Write-Host ""
    Write-Host "Bet log"
    $bets | Sort-Object match_date, market | Format-Table -AutoSize

    Write-Host ""
    Write-Host ("Saved bet log : {0}" -f $betLogPath)
    Write-Host ("Saved summary : {0}" -f $summaryPath)
} else {
    Write-Host "No bets were placed. The current filters are intentionally conservative."
}
