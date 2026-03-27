using Microsoft.AspNetCore.Diagnostics;

namespace DENT.API.Middleware;

public class GlobalExceptionHandler : IExceptionHandler
{
    private readonly ILogger<GlobalExceptionHandler> _logger;
    private readonly IHostEnvironment _env;

    public GlobalExceptionHandler(ILogger<GlobalExceptionHandler> logger, IHostEnvironment env)
    {
        _logger = logger;
        _env = env;
    }

    public async ValueTask<bool> TryHandleAsync(
        HttpContext httpContext, Exception exception, CancellationToken ct)
    {
        _logger.LogError(exception, "Unhandled exception: {Message}", exception.Message);

        var (statusCode, errorMessage) = exception switch
        {
            UnauthorizedAccessException => (StatusCodes.Status401Unauthorized, "Unauthorized"),
            InvalidOperationException e => (StatusCodes.Status400BadRequest, e.Message),
            ArgumentException e => (StatusCodes.Status400BadRequest, e.Message),
            KeyNotFoundException => (StatusCodes.Status404NotFound, "Resource not found"),
            _ => (StatusCodes.Status500InternalServerError, "Došlo je do interne greške.")
        };

        httpContext.Response.StatusCode = statusCode;
        httpContext.Response.ContentType = "application/json";

        var response = new
        {
            error = errorMessage,
            status = statusCode,
            traceId = httpContext.TraceIdentifier,
        };

        await httpContext.Response.WriteAsJsonAsync(response, ct);
        return true;
    }
}
