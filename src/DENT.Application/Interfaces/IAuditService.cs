namespace DENT.Application.Interfaces;

public interface IAuditService
{
    void Track(AuditEventData data);
}

public record AuditEventData
{
    public string EventType { get; init; } = "";
    public string Category { get; init; } = "";
    public string? Method { get; init; }
    public string? Path { get; init; }
    public int? StatusCode { get; init; }
    public int? DurationMs { get; init; }
    public Guid? UserId { get; init; }
    public string? SessionId { get; init; }
    public string? IpAddress { get; init; }
    public string? UserAgent { get; init; }
    public string? MetadataJson { get; init; }
    public Guid? ResourceId { get; init; }
    public string? ResourceType { get; init; }
}
