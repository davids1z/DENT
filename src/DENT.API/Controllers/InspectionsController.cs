using DENT.Application.Commands.CreateInspection;
using DENT.Application.Commands.DeleteInspection;
using DENT.Application.Commands.OverrideDecision;
using DENT.Application.Queries.GetEvidenceCertificate;
using DENT.Application.Queries.GetEvidenceReport;
using DENT.Application.Queries.GetInspection;
using DENT.Application.Queries.GetInspections;
using MediatR;
using Microsoft.AspNetCore.Mvc;

namespace DENT.API.Controllers;

[ApiController]
[Route("api/[controller]")]
public class InspectionsController : ControllerBase
{
    private readonly IMediator _mediator;

    public InspectionsController(IMediator mediator) => _mediator = mediator;

    [HttpPost]
    [RequestSizeLimit(100_000_000)] // 100MB for multi-image
    public async Task<IActionResult> Create(
        [FromForm] List<IFormFile> images,
        [FromForm] string? vehicleMake,
        [FromForm] string? vehicleModel,
        [FromForm] int? vehicleYear,
        [FromForm] int? mileage,
        [FromForm] string? captureMetadata,
        CancellationToken ct)
    {
        if (images is null || images.Count == 0)
            return BadRequest(new { error = "No images provided" });

        if (images.Count > 8)
            return BadRequest(new { error = "Maximum 8 images allowed" });

        var allowedTypes = new[] { "image/jpeg", "image/png", "image/webp", "image/heic" };
        foreach (var image in images)
        {
            if (image.Length == 0)
                return BadRequest(new { error = "Empty image file" });
            if (!allowedTypes.Contains(image.ContentType.ToLower()))
                return BadRequest(new { error = $"Invalid image type: {image.ContentType}. Supported: JPEG, PNG, WebP, HEIC" });
        }

        var imageInputs = new List<ImageInput>();
        foreach (var image in images)
        {
            using var stream = new MemoryStream();
            await image.CopyToAsync(stream, ct);
            imageInputs.Add(new ImageInput
            {
                Data = stream.ToArray(),
                FileName = image.FileName,
                ContentType = image.ContentType,
            });
        }

        var result = await _mediator.Send(new CreateInspectionCommand
        {
            Images = imageInputs,
            VehicleMake = vehicleMake,
            VehicleModel = vehicleModel,
            VehicleYear = vehicleYear,
            Mileage = mileage,
            CaptureMetadataJson = captureMetadata,
        }, ct);

        return CreatedAtAction(nameof(GetById), new { id = result.Id }, result);
    }

    [HttpPost("{id:guid}/override")]
    public async Task<IActionResult> OverrideDecision(Guid id, [FromBody] OverrideDecisionRequest body, CancellationToken ct)
    {
        var result = await _mediator.Send(new OverrideDecisionCommand
        {
            InspectionId = id,
            NewOutcome = body.NewOutcome,
            Reason = body.Reason,
            OperatorName = body.OperatorName,
        }, ct);

        if (result is null) return NotFound();
        return Ok(result);
    }

    [HttpGet]
    public async Task<IActionResult> GetAll([FromQuery] int page = 1, [FromQuery] int pageSize = 20, [FromQuery] string? status = null, CancellationToken ct = default)
    {
        var result = await _mediator.Send(new GetInspectionsQuery
        {
            Page = page,
            PageSize = pageSize,
            Status = status
        }, ct);
        return Ok(result);
    }

    [HttpGet("{id:guid}")]
    public async Task<IActionResult> GetById(Guid id, CancellationToken ct)
    {
        var result = await _mediator.Send(new GetInspectionQuery(id), ct);
        if (result is null) return NotFound();
        return Ok(result);
    }

    [HttpDelete("{id:guid}")]
    public async Task<IActionResult> Delete(Guid id, CancellationToken ct)
    {
        var deleted = await _mediator.Send(new DeleteInspectionCommand(id), ct);
        if (!deleted) return NotFound();
        return NoContent();
    }

    [HttpGet("{id:guid}/report")]
    public async Task<IActionResult> GetReport(Guid id, CancellationToken ct)
    {
        var pdf = await _mediator.Send(new GetEvidenceReportQuery(id), ct);
        if (pdf is null) return NotFound();
        return File(pdf, "application/pdf", $"dent-izvjestaj-{id.ToString()[..8]}.pdf");
    }

    [HttpGet("{id:guid}/certificate")]
    public async Task<IActionResult> GetCertificate(Guid id, CancellationToken ct)
    {
        var xml = await _mediator.Send(new GetEvidenceCertificateQuery(id), ct);
        if (xml is null) return NotFound();
        return File(xml, "application/xml", $"dent-certifikat-{id.ToString()[..8]}.xml");
    }
}

public record OverrideDecisionRequest
{
    public required string NewOutcome { get; init; }
    public required string Reason { get; init; }
    public required string OperatorName { get; init; }
}
