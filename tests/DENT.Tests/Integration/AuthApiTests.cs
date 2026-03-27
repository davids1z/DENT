using System.Net;
using System.Net.Http.Json;
using System.Text.Json;
using FluentAssertions;
using Xunit;

namespace DENT.Tests.Integration;

public class AuthApiTests : IClassFixture<CustomWebApplicationFactory>
{
    private readonly HttpClient _client;

    public AuthApiTests(CustomWebApplicationFactory factory)
    {
        _client = factory.CreateClient();
    }

    [Fact]
    public async Task Register_ValidCredentials_ReturnsToken()
    {
        var response = await _client.PostAsJsonAsync("/api/auth/register", new
        {
            email = $"test-{Guid.NewGuid():N}@example.com",
            password = "TestPass1!",
            fullName = "Test User"
        });

        response.StatusCode.Should().Be(HttpStatusCode.OK);
        var body = await response.Content.ReadFromJsonAsync<JsonElement>();
        body.GetProperty("token").GetString().Should().NotBeNullOrEmpty();
        body.GetProperty("refreshToken").GetString().Should().NotBeNullOrEmpty();
        body.GetProperty("user").GetProperty("email").GetString().Should().Contain("@");
    }

    [Fact]
    public async Task Register_WeakPassword_Returns400()
    {
        var response = await _client.PostAsJsonAsync("/api/auth/register", new
        {
            email = "weak@example.com",
            password = "short",
            fullName = "Test"
        });

        response.StatusCode.Should().Be(HttpStatusCode.BadRequest);
        var body = await response.Content.ReadFromJsonAsync<JsonElement>();
        body.GetProperty("error").GetString().Should().Contain("8");
    }

    [Fact]
    public async Task Register_DuplicateEmail_Returns409()
    {
        var email = $"dup-{Guid.NewGuid():N}@example.com";

        await _client.PostAsJsonAsync("/api/auth/register", new
        {
            email,
            password = "TestPass1!",
            fullName = "First"
        });

        var response = await _client.PostAsJsonAsync("/api/auth/register", new
        {
            email,
            password = "TestPass1!",
            fullName = "Second"
        });

        response.StatusCode.Should().Be(HttpStatusCode.Conflict);
    }

    [Fact]
    public async Task Login_ValidCredentials_ReturnsToken()
    {
        var email = $"login-{Guid.NewGuid():N}@example.com";
        await _client.PostAsJsonAsync("/api/auth/register", new
        {
            email,
            password = "TestPass1!",
            fullName = "Login Test"
        });

        var response = await _client.PostAsJsonAsync("/api/auth/login", new
        {
            email,
            password = "TestPass1!"
        });

        response.StatusCode.Should().Be(HttpStatusCode.OK);
        var body = await response.Content.ReadFromJsonAsync<JsonElement>();
        body.GetProperty("token").GetString().Should().NotBeNullOrEmpty();
    }

    [Fact]
    public async Task Login_WrongPassword_Returns401()
    {
        var email = $"wrong-{Guid.NewGuid():N}@example.com";
        await _client.PostAsJsonAsync("/api/auth/register", new
        {
            email,
            password = "TestPass1!",
            fullName = "Test"
        });

        var response = await _client.PostAsJsonAsync("/api/auth/login", new
        {
            email,
            password = "WrongPass1!"
        });

        response.StatusCode.Should().Be(HttpStatusCode.Unauthorized);
    }

    [Fact]
    public async Task Me_WithValidToken_ReturnsUser()
    {
        var email = $"me-{Guid.NewGuid():N}@example.com";
        var regResponse = await _client.PostAsJsonAsync("/api/auth/register", new
        {
            email,
            password = "TestPass1!",
            fullName = "Me Test"
        });
        var regBody = await regResponse.Content.ReadFromJsonAsync<JsonElement>();
        var token = regBody.GetProperty("token").GetString()!;

        var request = new HttpRequestMessage(HttpMethod.Get, "/api/auth/me");
        request.Headers.Add("Authorization", $"Bearer {token}");
        var response = await _client.SendAsync(request);

        response.StatusCode.Should().Be(HttpStatusCode.OK);
        var user = await response.Content.ReadFromJsonAsync<JsonElement>();
        user.GetProperty("email").GetString().Should().Be(email);
        user.GetProperty("fullName").GetString().Should().Be("Me Test");
    }

    [Fact]
    public async Task Me_WithoutToken_Returns401()
    {
        var response = await _client.GetAsync("/api/auth/me");
        response.StatusCode.Should().Be(HttpStatusCode.Unauthorized);
    }

    [Fact]
    public async Task Refresh_ValidToken_ReturnsNewTokens()
    {
        var email = $"refresh-{Guid.NewGuid():N}@example.com";
        var regResponse = await _client.PostAsJsonAsync("/api/auth/register", new
        {
            email,
            password = "TestPass1!",
            fullName = "Refresh Test"
        });
        var regBody = await regResponse.Content.ReadFromJsonAsync<JsonElement>();
        var refreshToken = regBody.GetProperty("refreshToken").GetString()!;

        var response = await _client.PostAsJsonAsync("/api/auth/refresh", new { refreshToken });

        response.StatusCode.Should().Be(HttpStatusCode.OK);
        var body = await response.Content.ReadFromJsonAsync<JsonElement>();
        body.GetProperty("token").GetString().Should().NotBeNullOrEmpty();
    }

    [Fact]
    public async Task HealthCheck_ReturnsHealthy()
    {
        var response = await _client.GetAsync("/api/health");
        response.StatusCode.Should().Be(HttpStatusCode.OK);
        var body = await response.Content.ReadFromJsonAsync<JsonElement>();
        body.GetProperty("status").GetString().Should().Be("healthy");
    }
}
