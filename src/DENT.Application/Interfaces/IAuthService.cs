namespace DENT.Application.Interfaces;

public record AuthResult(string Token, string RefreshToken, AuthUserInfo User);
public record AuthUserInfo(Guid Id, string Email, string FullName, string Role);

public interface IAuthService
{
    Task<AuthResult> RegisterAsync(string email, string password, string fullName, CancellationToken ct = default);
    Task<AuthResult> LoginAsync(string email, string password, CancellationToken ct = default);
    Task<AuthResult> RefreshTokenAsync(string refreshToken, CancellationToken ct = default);
    Task<AuthUserInfo?> GetUserAsync(Guid userId, CancellationToken ct = default);
}
