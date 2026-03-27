using System.Text.Json;
using DENT.Application.Interfaces;
using DENT.Application.Mapping;
using DENT.Application.Models;
using DENT.Application.Services;
using DENT.Domain.Entities;
using DENT.Domain.Enums;
using DENT.Shared.DTOs;
using MediatR;
using Microsoft.Extensions.Logging;

namespace DENT.Application.Commands.CreateInspection;

public class CreateInspectionHandler : IRequestHandler<CreateInspectionCommand, InspectionDto>
{
    private readonly IDentDbContext _db;
    private readonly IStorageService _storage;
    private readonly IEvidenceService _evidence;
    private readonly IImageProcessingService _imageProcessing;
    private readonly IAnalysisQueue _analysisQueue;
    private readonly ILogger<CreateInspectionHandler> _logger;

    public CreateInspectionHandler(
        IDentDbContext db,
        IStorageService storage,
        IEvidenceService evidence,
        IImageProcessingService imageProcessing,
        IAnalysisQueue analysisQueue,
        ILogger<CreateInspectionHandler> logger)
    {
        _db = db;
        _storage = storage;
        _evidence = evidence;
        _imageProcessing = imageProcessing;
        _analysisQueue = analysisQueue;
        _logger = logger;
    }

    public async Task<InspectionDto> Handle(CreateInspectionCommand request, CancellationToken ct)
    {
        var firstImage = request.Images[0];

        var imageHashes = new List<object>();
        var custodyLog = new List<EvidenceCustodyEvent>();

        // Upload primary image + thumbnail
        string primaryImageUrl;
        string? thumbnailUrl = null;
        using (var stream = new MemoryStream(firstImage.Data))
        {
            var key = await _storage.UploadAsync(stream, firstImage.FileName, firstImage.ContentType, ct);
            primaryImageUrl = _storage.GetPublicUrl(key);
        }

        try
        {
            var thumbBytes = _imageProcessing.GenerateThumbnail(firstImage.Data, 400, 75);
            if (thumbBytes != null)
            {
                using var thumbStream = new MemoryStream(thumbBytes);
                var thumbKey = await _storage.UploadAsync(
                    thumbStream, $"thumb_{firstImage.FileName}.jpg", "image/jpeg", ct);
                thumbnailUrl = _storage.GetPublicUrl(thumbKey);
            }
        }
        catch (Exception tex)
        {
            _logger.LogDebug(tex, "Thumbnail generation failed for {FileName}", firstImage.FileName);
        }

        // Hash primary image
        var primaryHash = _evidence.ComputeSha256(firstImage.Data);
        imageHashes.Add(new { fileName = firstImage.FileName, sha256 = primaryHash });
        custodyLog.Add(_evidence.CreateCustodyEvent("image_received", primaryHash, firstImage.FileName));

        // Create inspection entity
        var inspection = new Inspection
        {
            Id = Guid.NewGuid(),
            UserId = request.UserId,
            ImageUrl = primaryImageUrl,
            ThumbnailUrl = thumbnailUrl,
            OriginalFileName = firstImage.FileName,
            Status = InspectionStatus.Analyzing,
            CreatedAt = DateTime.UtcNow,
            UserProvidedMake = request.VehicleMake,
            UserProvidedModel = request.VehicleModel,
            UserProvidedYear = request.VehicleYear,
            Mileage = request.Mileage,
        };

        // Parse capture metadata
        if (!string.IsNullOrEmpty(request.CaptureMetadataJson))
        {
            try
            {
                var meta = JsonSerializer.Deserialize<List<CaptureMetaItem>>(
                    request.CaptureMetadataJson,
                    new JsonSerializerOptions { PropertyNameCaseInsensitive = true });

                if (meta is { Count: > 0 })
                {
                    inspection.CaptureSource = CaptureSource.Camera;
                    var first = meta[0];
                    if (first.Gps is not null)
                    {
                        inspection.CaptureLatitude = first.Gps.Latitude;
                        inspection.CaptureLongitude = first.Gps.Longitude;
                        inspection.CaptureGpsAccuracy = first.Gps.Accuracy;
                    }
                    if (first.Device is not null)
                    {
                        inspection.CaptureDeviceInfo = JsonSerializer.Serialize(first.Device,
                            new JsonSerializerOptions { PropertyNamingPolicy = JsonNamingPolicy.CamelCase });
                    }
                }
            }
            catch (Exception ex)
            {
                _logger.LogWarning(ex, "Failed to parse capture metadata, continuing without");
            }
        }
        else
        {
            inspection.CaptureSource = CaptureSource.Upload;
        }

        // Upload additional images
        for (int i = 1; i < request.Images.Count; i++)
        {
            var img = request.Images[i];
            using var stream = new MemoryStream(img.Data);
            var key = await _storage.UploadAsync(stream, img.FileName, img.ContentType, ct);
            var url = _storage.GetPublicUrl(key);
            inspection.AdditionalImages.Add(new InspectionImage
            {
                Id = Guid.NewGuid(),
                InspectionId = inspection.Id,
                ImageUrl = url,
                OriginalFileName = img.FileName,
                SortOrder = i,
                CreatedAt = DateTime.UtcNow,
            });

            var imgHash = _evidence.ComputeSha256(img.Data);
            imageHashes.Add(new { fileName = img.FileName, sha256 = imgHash });
            custodyLog.Add(_evidence.CreateCustodyEvent("image_received", imgHash, img.FileName));
        }

        inspection.ImageHashesJson = JsonSerializer.Serialize(imageHashes);

        _db.Inspections.Add(inspection);
        await _db.SaveChangesAsync(CancellationToken.None);

        // Enqueue background analysis (replaces fire-and-forget Task.Run)
        var backgroundData = new BackgroundAnalysisData
        {
            InspectionId = inspection.Id,
            UserId = request.UserId,
            FirstImageData = firstImage.Data,
            FirstImageFileName = firstImage.FileName,
            AllImages = request.Images,
            CaptureSource = inspection.CaptureSource?.ToString(),
            VehicleMake = request.VehicleMake,
            VehicleModel = request.VehicleModel,
            VehicleYear = request.VehicleYear,
            Mileage = request.Mileage,
            ImageHashes = imageHashes,
            CustodyLog = custodyLog,
        };

        await _analysisQueue.EnqueueAsync(backgroundData, CancellationToken.None);

        return InspectionMapper.MapToDto(inspection);
    }
}
