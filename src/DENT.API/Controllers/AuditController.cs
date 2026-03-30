using System.Security.Claims;
using System.Text.Json;
using DENT.Application.Interfaces;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.RateLimiting;
using Microsoft.EntityFrameworkCore;

namespace DENT.API.Controllers;

[ApiController]
[Route("api/[controller]")]
public class AuditController : ControllerBase
{
    private readonly IAuditService _audit;
    private readonly IDentDbContext _db;

    public AuditController(IAuditService audit, IDentDbContext db)
    {
        _audit = audit;
        _db = db;
    }

    /// <summary>Frontend page view tracking. No auth required.</summary>
    [HttpPost("track")]
    [EnableRateLimiting("api")]
    public IActionResult Track([FromBody] TrackRequest req)
    {
        if (string.IsNullOrWhiteSpace(req.Path)) return BadRequest();

        var userId = User.FindFirstValue(ClaimTypes.NameIdentifier);

        _audit.Track(new AuditEventData
        {
            EventType = req.EventType ?? "PageView",
            Category = "navigation",
            Path = req.Path?.Length > 500 ? req.Path[..500] : req.Path,
            SessionId = req.SessionId?.Length > 64 ? req.SessionId[..64] : req.SessionId,
            UserId = Guid.TryParse(userId, out var uid) ? uid : null,
            IpAddress = HttpContext.Connection.RemoteIpAddress?.ToString(),
            UserAgent = Request.Headers.UserAgent.ToString(),
            MetadataJson = req.Referrer != null
                ? JsonSerializer.Serialize(new { referrer = req.Referrer })
                : null,
        });

        return NoContent();
    }

    /// <summary>Query audit events. Admin only.</summary>
    [HttpGet("events")]
    [Authorize(Roles = "Admin")]
    [EnableRateLimiting("api")]
    public async Task<IActionResult> GetEvents(
        [FromQuery] string? eventType,
        [FromQuery] string? category,
        [FromQuery] Guid? userId,
        [FromQuery] string? sessionId,
        [FromQuery] DateTime? from,
        [FromQuery] DateTime? to,
        [FromQuery] string? path,
        [FromQuery] int page = 1,
        [FromQuery] int pageSize = 50,
        CancellationToken ct = default)
    {
        var query = _db.AuditEvents.AsNoTracking().AsQueryable();

        if (!string.IsNullOrEmpty(eventType))
            query = query.Where(e => e.EventType == eventType);
        if (!string.IsNullOrEmpty(category))
            query = query.Where(e => e.Category == category);
        if (userId.HasValue)
            query = query.Where(e => e.UserId == userId);
        if (!string.IsNullOrEmpty(sessionId))
            query = query.Where(e => e.SessionId == sessionId);
        if (from.HasValue)
            query = query.Where(e => e.Timestamp >= from.Value);
        if (to.HasValue)
            query = query.Where(e => e.Timestamp <= to.Value);
        if (!string.IsNullOrEmpty(path))
            query = query.Where(e => e.Path != null && e.Path.Contains(path));

        var total = await query.CountAsync(ct);
        var events = await query
            .OrderByDescending(e => e.Timestamp)
            .Skip((page - 1) * pageSize)
            .Take(Math.Min(pageSize, 100))
            .Select(e => new
            {
                e.Id, e.Timestamp, e.EventType, e.Category,
                e.Method, e.Path, e.StatusCode, e.DurationMs,
                e.UserId, e.SessionId, e.IpAddress, e.UserAgent,
                e.MetadataJson, e.ResourceId, e.ResourceType,
            })
            .ToListAsync(ct);

        return Ok(new { total, page, pageSize, events });
    }

    /// <summary>Dashboard stats: security, engagement, API health.</summary>
    [HttpGet("stats")]
    [Authorize(Roles = "Admin")]
    [EnableRateLimiting("api")]
    public async Task<IActionResult> GetAuditStats(
        [FromQuery] int days = 7,
        CancellationToken ct = default)
    {
        var since = DateTime.UtcNow.AddDays(-days);
        var last24h = DateTime.UtcNow.AddHours(-24);
        var last30m = DateTime.UtcNow.AddMinutes(-30);

        // ── KPI Strip ──────────────────────────────────────────
        var activeSessions = await _db.AuditEvents
            .Where(e => e.Timestamp >= last30m && e.SessionId != null)
            .Select(e => e.SessionId).Distinct().CountAsync(ct);

        var failedLogins24h = await _db.AuditEvents
            .CountAsync(e => e.Timestamp >= last24h && e.EventType == "LoginFailed", ct);

        var apiErrors24h = await _db.AuditEvents
            .CountAsync(e => e.Timestamp >= last24h && e.EventType == "ApiCall" && e.StatusCode >= 500, ct);

        var avgResponseMs = await _db.AuditEvents
            .Where(e => e.Timestamp >= last24h && e.EventType == "ApiCall" && e.DurationMs != null)
            .Select(e => (double?)e.DurationMs)
            .AverageAsync(ct) ?? 0;

        // ── Security: failed logins per day ────────────────────
        var failedLoginsByDay = await _db.AuditEvents
            .Where(e => e.Timestamp >= since && e.EventType == "LoginFailed")
            .GroupBy(e => e.Timestamp.Date)
            .Select(g => new { Date = g.Key, Count = g.Count() })
            .OrderBy(x => x.Date)
            .ToListAsync(ct);

        // ── Security: suspicious IPs (5+ failures in period) ───
        var suspiciousIps = await _db.AuditEvents
            .Where(e => e.Timestamp >= since && e.EventType == "LoginFailed" && e.IpAddress != null)
            .GroupBy(e => e.IpAddress!)
            .Select(g => new { Ip = g.Key, Count = g.Count(), Last = g.Max(e => e.Timestamp) })
            .Where(x => x.Count >= 3)
            .OrderByDescending(x => x.Count)
            .Take(10)
            .ToListAsync(ct);

        // ── Security: recent failed logins ─────────────────────
        var recentFailedLogins = await _db.AuditEvents
            .Where(e => e.Timestamp >= since && e.EventType == "LoginFailed")
            .OrderByDescending(e => e.Timestamp)
            .Take(10)
            .Select(e => new { e.Timestamp, e.IpAddress, e.MetadataJson })
            .ToListAsync(ct);

        // ── Engagement: top pages (normalized) ─────────────────
        var topPages = await _db.AuditEvents
            .Where(e => e.Timestamp >= since && e.EventType == "PageView" && e.Path != null)
            .GroupBy(e => e.Path!)
            .Select(g => new { Path = g.Key, Count = g.Count() })
            .OrderByDescending(x => x.Count)
            .Take(10)
            .ToListAsync(ct);

        // ── Engagement: activity heatmap (dayOfWeek x hour) ────
        var heatmap = await _db.AuditEvents
            .Where(e => e.Timestamp >= since && (e.EventType == "PageView" || e.EventType == "ApiCall"))
            .GroupBy(e => new { Day = (int)e.Timestamp.DayOfWeek, Hour = e.Timestamp.Hour })
            .Select(g => new { g.Key.Day, g.Key.Hour, Count = g.Count() })
            .ToListAsync(ct);

        // ── API Health: slowest endpoints ──────────────────────
        var slowEndpoints = await _db.AuditEvents
            .Where(e => e.Timestamp >= since && e.EventType == "ApiCall" && e.DurationMs != null && e.Path != null)
            .GroupBy(e => new { e.Method, e.Path })
            .Select(g => new
            {
                Method = g.Key.Method,
                Path = g.Key.Path,
                Avg = (int)g.Average(e => e.DurationMs!.Value),
                Count = g.Count(),
                Errors = g.Count(e => e.StatusCode >= 400),
            })
            .OrderByDescending(x => x.Avg)
            .Take(8)
            .ToListAsync(ct);

        // ── API Health: status code distribution ───────────────
        var statusCodes = await _db.AuditEvents
            .Where(e => e.Timestamp >= since && e.EventType == "ApiCall" && e.StatusCode != null)
            .GroupBy(e => e.StatusCode!.Value / 100) // 2, 3, 4, 5
            .Select(g => new { Group = g.Key, Count = g.Count() })
            .ToDictionaryAsync(x => $"{x.Group}xx", x => x.Count, ct);

        return Ok(new
        {
            period = days,
            // KPI strip
            activeSessions,
            failedLogins24h,
            apiErrors24h,
            avgResponseMs = (int)avgResponseMs,
            // Security
            failedLoginsByDay = failedLoginsByDay.Select(d => new { date = d.Date.ToString("yyyy-MM-dd"), count = d.Count }),
            suspiciousIps,
            recentFailedLogins,
            // Engagement
            topPages,
            heatmap,
            // API Health
            slowEndpoints,
            statusCodes,
        });
    }
}

public record TrackRequest(string? EventType, string? Path, string? SessionId, string? Referrer);
