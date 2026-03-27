using DENT.Shared.DTOs;
using MediatR;

namespace DENT.Application.Commands.CreateInspection;

public record CreateInspectionCommand : IRequest<InspectionDto>
{
    public required List<ImageInput> Images { get; init; }
    public Guid? UserId { get; init; }
    public string? VehicleMake { get; init; }
    public string? VehicleModel { get; init; }
    public int? VehicleYear { get; init; }
    public int? Mileage { get; init; }
    public string? CaptureMetadataJson { get; init; }
}

public record ImageInput
{
    public required byte[] Data { get; init; }
    public required string FileName { get; init; }
    public required string ContentType { get; init; }
}
