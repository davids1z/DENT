using System.Security.Claims;
using DENT.Application.Interfaces;
using DENT.Application.Validation;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.RateLimiting;

namespace DENT.API.Controllers;

[ApiController]
[Route("api/[controller]")]
[EnableRateLimiting("auth")]
public class AuthController : ControllerBase
{
    private readonly IAuthService _auth;
    private readonly IWebHostEnvironment _env;
    private readonly IConfiguration _config;

    public AuthController(IAuthService auth, IWebHostEnvironment env, IConfiguration config)
    {
        _auth = auth;
        _env = env;
        _config = config;
    }

    [HttpPost("register")]
    public async Task<IActionResult> Register([FromBody] RegisterRequest request, CancellationToken ct)
    {
        if (string.IsNullOrWhiteSpace(request.Email) || string.IsNullOrWhiteSpace(request.Password) || string.IsNullOrWhiteSpace(request.FullName))
            return BadRequest(new { error = "Sva polja su obavezna." });

        var (isValid, error) = PasswordValidator.Validate(request.Password);
        if (!isValid)
            return BadRequest(new { error });

        try
        {
            var result = await _auth.RegisterAsync(request.Email, request.Password, request.FullName, ct);
            SetAuthCookies(result.Token, result.RefreshToken);
            return Ok(result);
        }
        catch (InvalidOperationException ex)
        {
            return Conflict(new { error = ex.Message });
        }
    }

    [HttpPost("login")]
    public async Task<IActionResult> Login([FromBody] LoginRequest request, CancellationToken ct)
    {
        if (string.IsNullOrWhiteSpace(request.Email) || string.IsNullOrWhiteSpace(request.Password))
            return BadRequest(new { error = "Email i lozinka su obavezni." });

        try
        {
            var result = await _auth.LoginAsync(request.Email, request.Password, ct);
            SetAuthCookies(result.Token, result.RefreshToken);
            return Ok(result);
        }
        catch (UnauthorizedAccessException ex)
        {
            return Unauthorized(new { error = ex.Message });
        }
    }

    [HttpPost("refresh")]
    public async Task<IActionResult> Refresh(CancellationToken ct)
    {
        // Try cookie first, then request body for backward compatibility
        var refreshToken = Request.Cookies["dent_refresh"];

        if (string.IsNullOrWhiteSpace(refreshToken) && Request.ContentLength > 0)
        {
            try
            {
                var body = await Request.ReadFromJsonAsync<RefreshRequest>(ct);
                refreshToken = body?.RefreshToken;
            }
            catch { /* invalid body — ignore */ }
        }

        if (string.IsNullOrWhiteSpace(refreshToken))
            return BadRequest(new { error = "Refresh token je obavezan." });

        try
        {
            var result = await _auth.RefreshTokenAsync(refreshToken, ct);
            SetAuthCookies(result.Token, result.RefreshToken);
            return Ok(result);
        }
        catch (UnauthorizedAccessException)
        {
            ClearAuthCookies();
            return Unauthorized(new { error = "Nevažeći refresh token." });
        }
    }

    [HttpPost("logout")]
    public IActionResult Logout()
    {
        ClearAuthCookies();
        return Ok(new { message = "Odjava uspješna." });
    }

    [Authorize]
    [HttpGet("me")]
    public async Task<IActionResult> Me(CancellationToken ct)
    {
        var userId = Guid.Parse(User.FindFirstValue(ClaimTypes.NameIdentifier)!);
        var user = await _auth.GetUserAsync(userId, ct);
        if (user is null) return Unauthorized();
        return Ok(user);
    }

    /// <summary>Lightweight JWT validation for nginx auth_request subrequests (no DB call).</summary>
    [Authorize]
    [HttpGet("validate")]
    public IActionResult Validate() => Ok();

    private void SetAuthCookies(string token, string refreshToken)
    {
        var secure = !_env.IsDevelopment();
        var expiryHours = int.TryParse(_config["Jwt:ExpiryHours"], out var h) ? h : 24;

        Response.Cookies.Append("dent_auth", token, new CookieOptions
        {
            HttpOnly = true,
            Secure = secure,
            SameSite = SameSiteMode.Lax,
            Path = "/",
            MaxAge = TimeSpan.FromHours(expiryHours),
        });

        Response.Cookies.Append("dent_refresh", refreshToken, new CookieOptions
        {
            HttpOnly = true,
            Secure = secure,
            SameSite = SameSiteMode.Lax,
            Path = "/api/auth",
            MaxAge = TimeSpan.FromDays(30),
        });

        // JS-readable flag for FOUC prevention (not a secret — just "1")
        Response.Cookies.Append("dent_has_auth", "1", new CookieOptions
        {
            HttpOnly = false,
            Secure = secure,
            SameSite = SameSiteMode.Lax,
            Path = "/",
            MaxAge = TimeSpan.FromHours(expiryHours),
        });
    }

    private void ClearAuthCookies()
    {
        Response.Cookies.Delete("dent_auth", new CookieOptions { Path = "/" });
        Response.Cookies.Delete("dent_refresh", new CookieOptions { Path = "/api/auth" });
        Response.Cookies.Delete("dent_has_auth", new CookieOptions { Path = "/" });
    }
}

public record RegisterRequest(string Email, string Password, string FullName);
public record LoginRequest(string Email, string Password);
public record RefreshRequest(string RefreshToken);
