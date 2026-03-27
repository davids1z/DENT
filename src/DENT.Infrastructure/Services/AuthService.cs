using System.IdentityModel.Tokens.Jwt;
using System.Security.Claims;
using System.Security.Cryptography;
using System.Text;
using DENT.Application.Interfaces;
using DENT.Domain.Entities;
using DENT.Infrastructure.Data;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Configuration;
using Microsoft.IdentityModel.Tokens;

namespace DENT.Infrastructure.Services;

public class AuthService : IAuthService
{
    private readonly DentDbContext _db;
    private readonly IConfiguration _config;

    public AuthService(DentDbContext db, IConfiguration config)
    {
        _db = db;
        _config = config;
    }

    public async Task<AuthResult> RegisterAsync(string email, string password, string fullName, CancellationToken ct = default)
    {
        var normalizedEmail = email.Trim().ToLowerInvariant();

        if (await _db.Users.AnyAsync(u => u.Email == normalizedEmail, ct))
            throw new InvalidOperationException("Korisnik s ovim emailom već postoji.");

        var user = new User
        {
            Id = Guid.NewGuid(),
            Email = normalizedEmail,
            PasswordHash = BCrypt.Net.BCrypt.HashPassword(password),
            FullName = fullName.Trim(),
            Role = "User",
            CreatedAt = DateTime.UtcNow,
            IsActive = true,
        };

        var refreshToken = GenerateRefreshToken();
        user.RefreshToken = refreshToken;
        user.RefreshTokenExpiresAt = DateTime.UtcNow.AddDays(30);

        _db.Users.Add(user);
        await _db.SaveChangesAsync(ct);

        var token = GenerateJwt(user);
        return new AuthResult(token, refreshToken, ToUserInfo(user));
    }

    public async Task<AuthResult> LoginAsync(string email, string password, CancellationToken ct = default)
    {
        var normalizedEmail = email.Trim().ToLowerInvariant();
        var user = await _db.Users.FirstOrDefaultAsync(u => u.Email == normalizedEmail, ct);

        if (user is null || !BCrypt.Net.BCrypt.Verify(password, user.PasswordHash))
            throw new UnauthorizedAccessException("Neispravan email ili lozinka.");

        if (!user.IsActive)
            throw new UnauthorizedAccessException("Korisnički račun je deaktiviran.");

        var refreshToken = GenerateRefreshToken();
        user.RefreshToken = refreshToken;
        user.RefreshTokenExpiresAt = DateTime.UtcNow.AddDays(30);
        user.LastLoginAt = DateTime.UtcNow;
        await _db.SaveChangesAsync(ct);

        var token = GenerateJwt(user);
        return new AuthResult(token, refreshToken, ToUserInfo(user));
    }

    public async Task<AuthResult> RefreshTokenAsync(string refreshToken, CancellationToken ct = default)
    {
        var user = await _db.Users.FirstOrDefaultAsync(
            u => u.RefreshToken == refreshToken && u.RefreshTokenExpiresAt > DateTime.UtcNow, ct);

        if (user is null || !user.IsActive)
            throw new UnauthorizedAccessException("Nevažeći refresh token.");

        var newRefreshToken = GenerateRefreshToken();
        user.RefreshToken = newRefreshToken;
        user.RefreshTokenExpiresAt = DateTime.UtcNow.AddDays(30);
        await _db.SaveChangesAsync(ct);

        var token = GenerateJwt(user);
        return new AuthResult(token, newRefreshToken, ToUserInfo(user));
    }

    public async Task<AuthUserInfo?> GetUserAsync(Guid userId, CancellationToken ct = default)
    {
        var user = await _db.Users.AsNoTracking().FirstOrDefaultAsync(u => u.Id == userId && u.IsActive, ct);
        return user is null ? null : ToUserInfo(user);
    }

    private string GenerateJwt(User user)
    {
        var secret = _config["Jwt:Secret"] ?? throw new InvalidOperationException("JWT secret not configured");
        var key = new SymmetricSecurityKey(Encoding.UTF8.GetBytes(secret));
        var creds = new SigningCredentials(key, SecurityAlgorithms.HmacSha256);

        var claims = new[]
        {
            new Claim(JwtRegisteredClaimNames.Sub, user.Id.ToString()),
            new Claim(JwtRegisteredClaimNames.Email, user.Email),
            new Claim(ClaimTypes.Role, user.Role),
            new Claim("fullName", user.FullName),
        };

        var expiryHours = int.TryParse(_config["Jwt:ExpiryHours"], out var h) ? h : 24;

        var token = new JwtSecurityToken(
            issuer: _config["Jwt:Issuer"] ?? "DENT",
            audience: _config["Jwt:Audience"] ?? "DENT",
            claims: claims,
            expires: DateTime.UtcNow.AddHours(expiryHours),
            signingCredentials: creds);

        return new JwtSecurityTokenHandler().WriteToken(token);
    }

    private static string GenerateRefreshToken()
    {
        var bytes = new byte[64];
        using var rng = RandomNumberGenerator.Create();
        rng.GetBytes(bytes);
        return Convert.ToBase64String(bytes);
    }

    private static AuthUserInfo ToUserInfo(User user) =>
        new(user.Id, user.Email, user.FullName, user.Role);
}
