using DENT.Application.Commands.CreateInspection;

namespace DENT.Application.Models;

public record BackgroundAnalysisData
{
    public Guid InspectionId { get; init; }
    public Guid? UserId { get; init; }
    public byte[] FirstImageData { get; init; } = [];
    public string FirstImageFileName { get; init; } = "";
    public List<ImageInput> AllImages { get; init; } = [];
    public string? CaptureSource { get; init; }
    public string? VehicleMake { get; init; }
    public string? VehicleModel { get; init; }
    public int? VehicleYear { get; init; }
    public int? Mileage { get; init; }
    public List<object> ImageHashes { get; init; } = [];
    public List<EvidenceCustodyEvent> CustodyLog { get; init; } = [];
}

public record EvidenceCustodyEvent
{
    public string Event { get; init; } = "";
    public DateTime Timestamp { get; init; }
    public string? Hash { get; init; }
    public string? Details { get; init; }
}

public record CaptureMetaItem
{
    public GpsData? Gps { get; init; }
    public DeviceData? Device { get; init; }
    public string? CapturedAt { get; init; }
}

public record GpsData
{
    public double Latitude { get; init; }
    public double Longitude { get; init; }
    public double Accuracy { get; init; }
}

public record DeviceData
{
    public string? UserAgent { get; init; }
    public string? CameraLabel { get; init; }
    public int ScreenWidth { get; init; }
    public int ScreenHeight { get; init; }
    public string? CaptureTimestamp { get; init; }
}
