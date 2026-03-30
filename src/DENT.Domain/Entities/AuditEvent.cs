namespace DENT.Domain.Entities;

public class AuditEvent
{
    public long Id { get; set; }
    public DateTime Timestamp { get; set; } = DateTime.UtcNow;

    // Event classification
    public string EventType { get; set; } = string.Empty;  // PageView, ApiCall, Login, LoginFailed, Register, Upload, AdminAction, Logout
    public string Category { get; set; } = string.Empty;    // navigation, api, auth, admin, upload

    // Request details
    public string? Method { get; set; }
    public string? Path { get; set; }
    public int? StatusCode { get; set; }
    public int? DurationMs { get; set; }

    // Actor identification
    public Guid? UserId { get; set; }
    public string? SessionId { get; set; }
    public string? IpAddress { get; set; }
    public string? UserAgent { get; set; }

    // Contextual metadata (JSON blob for event-specific details)
    public string? MetadataJson { get; set; }

    // Resource reference
    public Guid? ResourceId { get; set; }
    public string? ResourceType { get; set; }
}
