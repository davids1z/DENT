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

    /// <summary>Dashboard stats: visitor tracking & engagement.</summary>
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

        var pageViews = _db.AuditEvents
            .Where(e => e.Timestamp >= since && e.EventType == "PageView");

        // ── KPI Strip ──────────────────────────────────────────
        var totalVisits = await pageViews.CountAsync(ct);

        var uniqueVisitors = await pageViews
            .Where(e => e.SessionId != null)
            .Select(e => e.SessionId).Distinct().CountAsync(ct);

        var activeNow = await _db.AuditEvents
            .Where(e => e.Timestamp >= last30m && e.SessionId != null)
            .Select(e => e.SessionId).Distinct().CountAsync(ct);

        var loggedInVisits = await pageViews
            .CountAsync(e => e.UserId != null, ct);

        var anonVisits = totalVisits - loggedInVisits;

        var todayVisits = await _db.AuditEvents
            .CountAsync(e => e.Timestamp >= last24h && e.EventType == "PageView", ct);

        // ── Visits per day ─────────────────────────────────────
        var visitsPerDay = await pageViews
            .GroupBy(e => e.Timestamp.Date)
            .Select(g => new { Date = g.Key, Count = g.Count() })
            .OrderBy(x => x.Date)
            .ToListAsync(ct);

        // ── Unique visitors per day ────────────────────────────
        var uniquePerDay = await pageViews
            .Where(e => e.SessionId != null)
            .GroupBy(e => new { Date = e.Timestamp.Date, e.SessionId })
            .Select(g => g.Key)
            .GroupBy(x => x.Date)
            .Select(g => new { Date = g.Key, Count = g.Count() })
            .OrderBy(x => x.Date)
            .ToListAsync(ct);

        // ── Visits per hour of day ─────────────────────────────
        var visitsPerHour = await pageViews
            .GroupBy(e => e.Timestamp.Hour)
            .Select(g => new { Hour = g.Key, Count = g.Count() })
            .OrderBy(x => x.Hour)
            .ToListAsync(ct);

        // ── Top pages ──────────────────────────────────────────
        var topPages = await pageViews
            .Where(e => e.Path != null)
            .GroupBy(e => e.Path!)
            .Select(g => new { Path = g.Key, Count = g.Count() })
            .OrderByDescending(x => x.Count)
            .Take(10)
            .ToListAsync(ct);

        // ── Visitor heatmap (dayOfWeek x hour) ─────────────────
        var heatmap = await pageViews
            .GroupBy(e => new { Day = (int)e.Timestamp.DayOfWeek, Hour = e.Timestamp.Hour })
            .Select(g => new { g.Key.Day, g.Key.Hour, Count = g.Count() })
            .ToListAsync(ct);

        // ── Auth vs anon per day ───────────────────────────────
        var authPerDay = await pageViews
            .GroupBy(e => new { Date = e.Timestamp.Date, IsAuth = e.UserId != null })
            .Select(g => new { Date = g.Key.Date, IsAuth = g.Key.IsAuth, Count = g.Count() })
            .OrderBy(x => x.Date)
            .ToListAsync(ct);

        // ── Recent visitors (last 20 unique sessions) ──────────
        var recentVisitors = await _db.AuditEvents
            .Where(e => e.EventType == "PageView" && e.SessionId != null)
            .OrderByDescending(e => e.Timestamp)
            .Select(e => new { e.SessionId, e.UserId, e.IpAddress, e.Path, e.Timestamp })
            .Take(200) // grab recent events, then deduplicate by session
            .ToListAsync(ct);

        var recentSessions = recentVisitors
            .GroupBy(e => e.SessionId)
            .Take(15)
            .Select(g => new
            {
                sessionId = g.Key,
                userId = g.First().UserId,
                ip = g.First().IpAddress,
                lastPage = g.First().Path,
                lastSeen = g.First().Timestamp,
                pageCount = g.Count(),
            })
            .ToList();

        // resolve user names for logged-in sessions
        var sessionUserIds = recentSessions
            .Where(s => s.userId.HasValue)
            .Select(s => s.userId!.Value)
            .Distinct()
            .ToList();
        var userNames = sessionUserIds.Count > 0
            ? await _db.Users
                .Where(u => sessionUserIds.Contains(u.Id))
                .ToDictionaryAsync(u => u.Id, u => u.FullName, ct)
            : new Dictionary<Guid, string>();

        var recentVisitorList = recentSessions.Select(s => new
        {
            s.sessionId,
            userName = s.userId.HasValue && userNames.TryGetValue(s.userId.Value, out var name) ? name : null,
            s.ip,
            s.lastPage,
            s.lastSeen,
            s.pageCount,
        });

        // ── Referrers ──────────────────────────────────────────
        var referrers = await pageViews
            .Where(e => e.MetadataJson != null)
            .Select(e => e.MetadataJson!)
            .Take(500)
            .ToListAsync(ct);

        var topReferrers = referrers
            .Select(json =>
            {
                try { return JsonSerializer.Deserialize<Dictionary<string, string>>(json); }
                catch { return null; }
            })
            .Where(d => d != null && d.ContainsKey("referrer") && !string.IsNullOrWhiteSpace(d["referrer"]))
            .Select(d => {
                try { return new Uri(d!["referrer"]).Host; }
                catch { return d!["referrer"]; }
            })
            .Where(h => !h.Contains("dent.xyler") && !h.Contains("localhost"))
            .GroupBy(h => h)
            .Select(g => new { source = g.Key, count = g.Count() })
            .OrderByDescending(x => x.count)
            .Take(5)
            .ToList();

        return Ok(new
        {
            period = days,
            // KPI strip
            totalVisits,
            uniqueVisitors,
            activeNow,
            loggedInVisits,
            anonVisits,
            todayVisits,
            // Charts
            visitsPerDay = visitsPerDay.Select(d => new { date = d.Date.ToString("yyyy-MM-dd"), count = d.Count }),
            uniquePerDay = uniquePerDay.Select(d => new { date = d.Date.ToString("yyyy-MM-dd"), count = d.Count }),
            visitsPerHour = visitsPerHour.Select(h => new { hour = h.Hour, count = h.Count }),
            authPerDay = authPerDay.Select(d => new { date = d.Date.ToString("yyyy-MM-dd"), isAuth = d.IsAuth, count = d.Count }),
            // Engagement
            topPages,
            heatmap,
            topReferrers,
            // Recent visitors
            recentVisitors = recentVisitorList,
        });
    }
}

public record TrackRequest(string? EventType, string? Path, string? SessionId, string? Referrer);
