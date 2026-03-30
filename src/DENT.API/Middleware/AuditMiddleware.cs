using System.Diagnostics;
using System.Security.Claims;
using DENT.Application.Interfaces;

namespace DENT.API.Middleware;

public class AuditMiddleware
{
    private readonly RequestDelegate _next;
    private readonly IAuditService _audit;

    private static readonly string[] SkipPrefixes = ["/api/health", "/api/audit/track"];

    public AuditMiddleware(RequestDelegate next, IAuditService audit)
    {
        _next = next;
        _audit = audit;
    }

    public async Task InvokeAsync(HttpContext ctx)
    {
        var path = ctx.Request.Path.Value ?? "";

        if (!path.StartsWith("/api/") || SkipPrefixes.Any(p => path.StartsWith(p, StringComparison.OrdinalIgnoreCase)))
        {
            await _next(ctx);
            return;
        }

        var sw = Stopwatch.StartNew();
        await _next(ctx);
        sw.Stop();

        var userId = ctx.User.FindFirstValue(ClaimTypes.NameIdentifier);

        _audit.Track(new AuditEventData
        {
            EventType = "ApiCall",
            Category = "api",
            Method = ctx.Request.Method,
            Path = path.Length > 500 ? path[..500] : path,
            StatusCode = ctx.Response.StatusCode,
            DurationMs = (int)sw.ElapsedMilliseconds,
            UserId = Guid.TryParse(userId, out var uid) ? uid : null,
            SessionId = ctx.Request.Cookies["dent_session"],
            IpAddress = ctx.Connection.RemoteIpAddress?.ToString(),
            UserAgent = ctx.Request.Headers.UserAgent.ToString(),
        });
    }
}
