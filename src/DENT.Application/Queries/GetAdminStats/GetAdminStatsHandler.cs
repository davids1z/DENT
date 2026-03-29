using System.Text.Json;
using DENT.Application.Interfaces;
using DENT.Application.Services;
using DENT.Domain.Enums;
using DENT.Shared.DTOs;
using MediatR;
using Microsoft.EntityFrameworkCore;

namespace DENT.Application.Queries.GetAdminStats;

public class GetAdminStatsHandler : IRequestHandler<GetAdminStatsQuery, AdminStatsDto>
{
    private readonly IDentDbContext _db;
    private readonly IAnalysisQueue _queue;

    public GetAdminStatsHandler(IDentDbContext db, IAnalysisQueue queue)
    {
        _db = db;
        _queue = queue;
    }

    public async Task<AdminStatsDto> Handle(GetAdminStatsQuery request, CancellationToken ct)
    {
        var now = DateTime.UtcNow;
        var today = now.Date;
        var weekAgo = today.AddDays(-7);
        var thirtyDaysAgo = today.AddDays(-30);

        // --- Users ---
        var totalUsers = await _db.Users.CountAsync(ct);
        var activeUsers = await _db.Users.CountAsync(u => u.IsActive, ct);
        var usersToday = await _db.Users.CountAsync(u => u.CreatedAt >= today, ct);
        var usersThisWeek = await _db.Users.CountAsync(u => u.CreatedAt >= weekAgo, ct);

        // --- Inspections by status ---
        var statusGroups = await _db.Inspections
            .GroupBy(i => i.Status)
            .Select(g => new { Status = g.Key, Count = g.Count() })
            .ToListAsync(ct);

        var totalInspections = statusGroups.Sum(g => g.Count);
        var completedInspections = statusGroups.FirstOrDefault(g => g.Status == InspectionStatus.Completed)?.Count ?? 0;
        var pendingInspections = statusGroups.FirstOrDefault(g => g.Status == InspectionStatus.Pending)?.Count ?? 0;
        var analyzingInspections = statusGroups.FirstOrDefault(g => g.Status == InspectionStatus.Analyzing)?.Count ?? 0;
        var failedInspections = statusGroups.FirstOrDefault(g => g.Status == InspectionStatus.Failed)?.Count ?? 0;

        // --- Average processing time (completed only) ---
        var avgProcessingMs = 0.0;
        var completedWithTime = await _db.Inspections
            .Where(i => i.Status == InspectionStatus.Completed && i.CompletedAt != null)
            .Select(i => new { i.CreatedAt, CompletedAt = i.CompletedAt!.Value })
            .ToListAsync(ct);

        if (completedWithTime.Count > 0)
        {
            avgProcessingMs = completedWithTime
                .Average(i => (i.CompletedAt - i.CreatedAt).TotalMilliseconds);
        }

        // --- Daily analysis counts (last 30 days) ---
        var dailyRaw = await _db.Inspections
            .Where(i => i.CreatedAt >= thirtyDaysAgo)
            .GroupBy(i => i.CreatedAt.Date)
            .Select(g => new { Date = g.Key, Count = g.Count() })
            .OrderBy(x => x.Date)
            .ToListAsync(ct);

        // Fill in missing days with 0
        var dailyCounts = new List<DailyCountDto>();
        for (var d = thirtyDaysAgo; d <= today; d = d.AddDays(1))
        {
            var count = dailyRaw.FirstOrDefault(x => x.Date == d)?.Count ?? 0;
            dailyCounts.Add(new DailyCountDto { Date = d.ToString("yyyy-MM-dd"), Count = count });
        }

        // --- Hourly distribution (last 30 days, aggregated by hour 0-23) ---
        var hourlyRaw = await _db.Inspections
            .Where(i => i.CreatedAt >= thirtyDaysAgo)
            .GroupBy(i => i.CreatedAt.Hour)
            .Select(g => new HourlyCountDto { Hour = g.Key, Count = g.Count() })
            .OrderBy(x => x.Hour)
            .ToListAsync(ct);

        // Fill missing hours with 0
        var hourlyCounts = Enumerable.Range(0, 24)
            .Select(h => hourlyRaw.FirstOrDefault(x => x.Hour == h) ?? new HourlyCountDto { Hour = h, Count = 0 })
            .ToList();

        // --- Day-of-week distribution (last 30 days) ---
        var dowDates = await _db.Inspections
            .Where(i => i.CreatedAt >= thirtyDaysAgo)
            .Select(i => i.CreatedAt.Date)
            .ToListAsync(ct);

        var dowRaw = dowDates
            .GroupBy(d => (int)d.DayOfWeek)
            .Select(g => new DayOfWeekCountDto { Day = g.Key, Count = g.Count() })
            .OrderBy(x => x.Day)
            .ToList();

        // Fill missing days with 0
        var dowCounts = Enumerable.Range(0, 7)
            .Select(d => dowRaw.FirstOrDefault(x => x.Day == d) ?? new DayOfWeekCountDto { Day = d, Count = 0 })
            .ToList();

        // --- Risk level distribution (from ForensicResults) ---
        var riskLevels = await _db.ForensicResults
            .GroupBy(fr => fr.OverallRiskLevel)
            .Select(g => new { Level = g.Key, Count = g.Count() })
            .ToDictionaryAsync(x => x.Level, x => x.Count, ct);

        // --- Verdict distribution (from VerdictProbabilitiesJson) ---
        var verdictJsons = await _db.ForensicResults
            .Where(fr => fr.VerdictProbabilitiesJson != null)
            .Select(fr => fr.VerdictProbabilitiesJson!)
            .ToListAsync(ct);

        var verdictDistribution = new Dictionary<string, int>();
        foreach (var json in verdictJsons)
        {
            try
            {
                var probs = JsonSerializer.Deserialize<Dictionary<string, double>>(json);
                if (probs is { Count: > 0 })
                {
                    var winner = probs.MaxBy(kv => kv.Value).Key;
                    verdictDistribution[winner] = verdictDistribution.GetValueOrDefault(winner) + 1;
                }
            }
            catch { /* skip malformed */ }
        }

        // --- Decision outcomes ---
        var decisionOutcomes = await _db.Inspections
            .Where(i => i.DecisionOutcome != null)
            .GroupBy(i => i.DecisionOutcome!.Value)
            .Select(g => new { Outcome = g.Key.ToString(), Count = g.Count() })
            .ToDictionaryAsync(x => x.Outcome, x => x.Count, ct);

        // --- File type distribution ---
        var fileNames = await _db.Inspections
            .Select(i => i.OriginalFileName)
            .ToListAsync(ct);

        var fileTypeDist = fileNames
            .Select(f => Path.GetExtension(f).ToLowerInvariant().TrimStart('.'))
            .Where(ext => !string.IsNullOrEmpty(ext))
            .GroupBy(ext => ext)
            .ToDictionary(g => g.Key, g => g.Count());

        // --- Fraud risk distribution ---
        var fraudRiskRaw = await _db.Inspections
            .Where(i => i.FraudRiskLevel != null)
            .GroupBy(i => i.FraudRiskLevel!.Value)
            .Select(g => new { Level = g.Key, Count = g.Count() })
            .ToListAsync(ct);
        var fraudRiskDist = fraudRiskRaw.ToDictionary(x => x.Level.ToString(), x => x.Count);

        // --- Capture source distribution ---
        var captureSourceRaw = await _db.Inspections
            .Where(i => i.CaptureSource != null)
            .GroupBy(i => i.CaptureSource!.Value)
            .Select(g => new { Source = g.Key, Count = g.Count() })
            .ToListAsync(ct);
        var captureSourceDist = captureSourceRaw.ToDictionary(x => x.Source.ToString(), x => x.Count);

        // --- Processing time percentiles ---
        var procTimes = completedWithTime
            .Select(i => (i.CompletedAt - i.CreatedAt).TotalMilliseconds)
            .OrderBy(t => t)
            .ToList();

        double Percentile(List<double> sorted, double p) =>
            sorted.Count == 0 ? 0 : sorted[Math.Min((int)(sorted.Count * p), sorted.Count - 1)];

        // --- User registrations per day (last 30 days) ---
        var userDailyRaw = await _db.Users
            .Where(u => u.CreatedAt >= thirtyDaysAgo)
            .GroupBy(u => u.CreatedAt.Date)
            .Select(g => new { Date = g.Key, Count = g.Count() })
            .OrderBy(x => x.Date)
            .ToListAsync(ct);

        var usersPerDay = new List<DailyCountDto>();
        for (var d = thirtyDaysAgo; d <= today; d = d.AddDays(1))
        {
            var count = userDailyRaw.FirstOrDefault(x => x.Date == d)?.Count ?? 0;
            usersPerDay.Add(new DailyCountDto { Date = d.ToString("yyyy-MM-dd"), Count = count });
        }

        // --- Average fraud risk score ---
        var avgFraudScore = await _db.Inspections
            .Where(i => i.FraudRiskScore != null)
            .AverageAsync(i => (double?)i.FraudRiskScore, ct) ?? 0;

        // --- Recent failures ---
        var recentFailures = await _db.Inspections
            .Include(i => i.User)
            .Where(i => i.Status == InspectionStatus.Failed)
            .OrderByDescending(i => i.CreatedAt)
            .Take(10)
            .Select(i => new AdminFailedInspectionDto
            {
                Id = i.Id,
                OriginalFileName = i.OriginalFileName,
                ErrorMessage = i.ErrorMessage,
                UserFullName = i.User != null ? i.User.FullName : null,
                CreatedAt = i.CreatedAt
            })
            .ToListAsync(ct);

        return new AdminStatsDto
        {
            TotalUsers = totalUsers,
            ActiveUsers = activeUsers,
            UsersRegisteredToday = usersToday,
            UsersRegisteredThisWeek = usersThisWeek,
            TotalInspections = totalInspections,
            CompletedInspections = completedInspections,
            PendingInspections = pendingInspections,
            AnalyzingInspections = analyzingInspections,
            FailedInspections = failedInspections,
            AverageProcessingTimeMs = Math.Round(avgProcessingMs, 0),
            QueuePending = _queue.Count,
            QueueActiveUsers = _queue.ActiveUserCount,
            AnalysesPerDay = dailyCounts,
            AnalysesPerHour = hourlyCounts,
            AnalysesPerDayOfWeek = dowCounts,
            RiskLevelDistribution = riskLevels,
            VerdictDistribution = verdictDistribution,
            DecisionOutcomeDistribution = decisionOutcomes,
            FileTypeDistribution = fileTypeDist,
            FraudRiskDistribution = fraudRiskDist,
            CaptureSourceDistribution = captureSourceDist,
            ProcessingTimeP50 = Math.Round(Percentile(procTimes, 0.50), 0),
            ProcessingTimeP90 = Math.Round(Percentile(procTimes, 0.90), 0),
            ProcessingTimeP95 = Math.Round(Percentile(procTimes, 0.95), 0),
            ProcessingTimeP99 = Math.Round(Percentile(procTimes, 0.99), 0),
            UsersPerDay = usersPerDay,
            AverageFraudRiskScore = Math.Round(avgFraudScore * 100, 1),
            RecentFailures = recentFailures,
        };
    }
}
