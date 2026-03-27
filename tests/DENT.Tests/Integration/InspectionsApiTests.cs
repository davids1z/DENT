using System.Net;
using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Text;
using System.Text.Json;
using FluentAssertions;
using Xunit;

namespace DENT.Tests.Integration;

public class InspectionsApiTests : IClassFixture<CustomWebApplicationFactory>
{
    private readonly HttpClient _client;

    public InspectionsApiTests(CustomWebApplicationFactory factory)
    {
        _client = factory.CreateClient();
    }

    private async Task<string> GetAuthToken()
    {
        var email = $"insp-{Guid.NewGuid():N}@example.com";
        var response = await _client.PostAsJsonAsync("/api/auth/register", new
        {
            email,
            password = "TestPass1!",
            fullName = "Inspector"
        });
        var body = await response.Content.ReadFromJsonAsync<JsonElement>();
        return body.GetProperty("token").GetString()!;
    }

    private HttpRequestMessage AuthRequest(HttpMethod method, string url, string token, HttpContent? content = null)
    {
        var request = new HttpRequestMessage(method, url) { Content = content };
        request.Headers.Add("Authorization", $"Bearer {token}");
        return request;
    }

    [Fact]
    public async Task GetInspections_WithAuth_ReturnsEmptyList()
    {
        var token = await GetAuthToken();
        var request = AuthRequest(HttpMethod.Get, "/api/inspections", token);

        var response = await _client.SendAsync(request);

        response.StatusCode.Should().Be(HttpStatusCode.OK);
        var inspections = await response.Content.ReadFromJsonAsync<JsonElement>();
        inspections.GetArrayLength().Should().Be(0);
    }

    [Fact]
    public async Task GetInspections_WithoutAuth_Returns401()
    {
        var response = await _client.GetAsync("/api/inspections");
        response.StatusCode.Should().Be(HttpStatusCode.Unauthorized);
    }

    [Fact]
    public async Task CreateInspection_WithImage_ReturnsCreated()
    {
        var token = await GetAuthToken();

        // Create a minimal JPEG-like file
        var content = new MultipartFormDataContent();
        var imageBytes = new byte[] { 0xFF, 0xD8, 0xFF, 0xE0, 0x00, 0x10, 0x4A, 0x46 }; // JPEG header
        var imageContent = new ByteArrayContent(imageBytes);
        imageContent.Headers.ContentType = new MediaTypeHeaderValue("image/jpeg");
        content.Add(imageContent, "images", "test.jpg");

        var request = AuthRequest(HttpMethod.Post, "/api/inspections", token, content);
        var response = await _client.SendAsync(request);

        response.StatusCode.Should().Be(HttpStatusCode.Created);
        var inspection = await response.Content.ReadFromJsonAsync<JsonElement>();
        inspection.GetProperty("id").GetString().Should().NotBeNullOrEmpty();
        inspection.GetProperty("status").GetString().Should().Be("Analyzing");
        inspection.GetProperty("originalFileName").GetString().Should().Be("test.jpg");
    }

    [Fact]
    public async Task CreateInspection_NoImages_Returns400()
    {
        var token = await GetAuthToken();
        var content = new MultipartFormDataContent();
        var request = AuthRequest(HttpMethod.Post, "/api/inspections", token, content);

        var response = await _client.SendAsync(request);

        response.StatusCode.Should().Be(HttpStatusCode.BadRequest);
    }

    [Fact]
    public async Task CreateInspection_InvalidFileType_Returns400()
    {
        var token = await GetAuthToken();
        var content = new MultipartFormDataContent();
        var fileContent = new ByteArrayContent(Encoding.UTF8.GetBytes("not an image"));
        fileContent.Headers.ContentType = new MediaTypeHeaderValue("text/plain");
        content.Add(fileContent, "images", "test.txt");

        var request = AuthRequest(HttpMethod.Post, "/api/inspections", token, content);
        var response = await _client.SendAsync(request);

        response.StatusCode.Should().Be(HttpStatusCode.BadRequest);
        var body = await response.Content.ReadFromJsonAsync<JsonElement>();
        body.GetProperty("error").GetString().Should().Contain("Invalid file type");
    }

    [Fact]
    public async Task GetInspection_OtherUserInspection_Returns404()
    {
        // User 1 creates inspection
        var token1 = await GetAuthToken();
        var content = new MultipartFormDataContent();
        var imageContent = new ByteArrayContent(new byte[] { 0xFF, 0xD8, 0xFF, 0xE0 });
        imageContent.Headers.ContentType = new MediaTypeHeaderValue("image/jpeg");
        content.Add(imageContent, "images", "test.jpg");
        var createRequest = AuthRequest(HttpMethod.Post, "/api/inspections", token1, content);
        var createResponse = await _client.SendAsync(createRequest);
        var created = await createResponse.Content.ReadFromJsonAsync<JsonElement>();
        var inspectionId = created.GetProperty("id").GetString()!;

        // User 2 tries to access it
        var token2 = await GetAuthToken();
        var getRequest = AuthRequest(HttpMethod.Get, $"/api/inspections/{inspectionId}", token2);
        var response = await _client.SendAsync(getRequest);

        response.StatusCode.Should().Be(HttpStatusCode.NotFound);
    }

    [Fact]
    public async Task DeleteInspection_Own_ReturnsNoContent()
    {
        var token = await GetAuthToken();

        // Create
        var content = new MultipartFormDataContent();
        var imageContent = new ByteArrayContent(new byte[] { 0xFF, 0xD8, 0xFF, 0xE0 });
        imageContent.Headers.ContentType = new MediaTypeHeaderValue("image/jpeg");
        content.Add(imageContent, "images", "test.jpg");
        var createRequest = AuthRequest(HttpMethod.Post, "/api/inspections", token, content);
        var createResponse = await _client.SendAsync(createRequest);
        var created = await createResponse.Content.ReadFromJsonAsync<JsonElement>();
        var id = created.GetProperty("id").GetString()!;

        // Delete
        var deleteRequest = AuthRequest(HttpMethod.Delete, $"/api/inspections/{id}", token);
        var response = await _client.SendAsync(deleteRequest);

        response.StatusCode.Should().Be(HttpStatusCode.NoContent);
    }

    [Fact]
    public async Task DashboardStats_WithAuth_ReturnsStats()
    {
        var token = await GetAuthToken();
        var request = AuthRequest(HttpMethod.Get, "/api/dashboard/stats", token);

        var response = await _client.SendAsync(request);

        response.StatusCode.Should().Be(HttpStatusCode.OK);
        var stats = await response.Content.ReadFromJsonAsync<JsonElement>();
        stats.GetProperty("totalInspections").GetInt32().Should().BeGreaterOrEqualTo(0);
    }
}
