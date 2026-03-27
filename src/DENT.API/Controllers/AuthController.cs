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

    public AuthController(IAuthService auth) => _auth = auth;

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
            return Ok(result);
        }
        catch (UnauthorizedAccessException ex)
        {
            return Unauthorized(new { error = ex.Message });
        }
    }

    [HttpPost("refresh")]
    public async Task<IActionResult> Refresh([FromBody] RefreshRequest request, CancellationToken ct)
    {
        if (string.IsNullOrWhiteSpace(request.RefreshToken))
            return BadRequest(new { error = "Refresh token je obavezan." });

        try
        {
            var result = await _auth.RefreshTokenAsync(request.RefreshToken, ct);
            return Ok(result);
        }
        catch (UnauthorizedAccessException)
        {
            return Unauthorized(new { error = "Nevažeći refresh token." });
        }
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
}

public record RegisterRequest(string Email, string Password, string FullName);
public record LoginRequest(string Email, string Password);
public record RefreshRequest(string RefreshToken);
