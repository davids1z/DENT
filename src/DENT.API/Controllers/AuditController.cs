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

    /// <summary>Aggregate audit stats for the admin dashboard.</summary>
    [HttpGet("stats")]
    [Authorize(Roles = "Admin")]
    [EnableRateLimiting("api")]
    public async Task<IActionResult> GetAuditStats(
        [FromQuery] int days = 7,
        CancellationToken ct = default)
    {
        var since = DateTime.UtcNow.AddDays(-days);

        var eventCounts = await _db.AuditEvents
            .Where(e => e.Timestamp >= since)
            .GroupBy(e => e.EventType)
            .Select(g => new { Type = g.Key, Count = g.Count() })
            .ToDictionaryAsync(x => x.Type, x => x.Count, ct);

        var uniqueSessions = await _db.AuditEvents
            .Where(e => e.Timestamp >= since && e.SessionId != null)
            .Select(e => e.SessionId)
            .Distinct()
            .CountAsync(ct);

        var uniqueUsers = await _db.AuditEvents
            .Where(e => e.Timestamp >= since && e.UserId != null)
            .Select(e => e.UserId)
            .Distinct()
            .CountAsync(ct);

        var topPages = await _db.AuditEvents
            .Where(e => e.Timestamp >= since && e.EventType == "PageView" && e.Path != null)
            .GroupBy(e => e.Path!)
            .Select(g => new { Path = g.Key, Count = g.Count() })
            .OrderByDescending(x => x.Count)
            .Take(10)
            .ToListAsync(ct);

        var dailyEvents = await _db.AuditEvents
            .Where(e => e.Timestamp >= since)
            .GroupBy(e => e.Timestamp.Date)
            .Select(g => new { Date = g.Key, Count = g.Count() })
            .OrderBy(x => x.Date)
            .ToListAsync(ct);

        var hourlyEvents = await _db.AuditEvents
            .Where(e => e.Timestamp >= since)
            .GroupBy(e => e.Timestamp.Hour)
            .Select(g => new { Hour = g.Key, Count = g.Count() })
            .OrderBy(x => x.Hour)
            .ToListAsync(ct);

        var recentFailedLogins = await _db.AuditEvents
            .Where(e => e.Timestamp >= since && e.EventType == "LoginFailed")
            .OrderByDescending(e => e.Timestamp)
            .Take(20)
            .Select(e => new { e.Timestamp, e.IpAddress, e.MetadataJson })
            .ToListAsync(ct);

        return Ok(new
        {
            period = days,
            eventCounts,
            uniqueSessions,
            uniqueUsers,
            failedLogins = eventCounts.GetValueOrDefault("LoginFailed", 0),
            pageViews = eventCounts.GetValueOrDefault("PageView", 0),
            apiCalls = eventCounts.GetValueOrDefault("ApiCall", 0),
            logins = eventCounts.GetValueOrDefault("Login", 0),
            topPages,
            dailyEvents = dailyEvents.Select(d => new { date = d.Date.ToString("yyyy-MM-dd"), count = d.Count }),
            hourlyEvents = hourlyEvents.Select(h => new { hour = h.Hour, count = h.Count }),
            recentFailedLogins,
        });
    }
}

public record TrackRequest(string? EventType, string? Path, string? SessionId, string? Referrer);
