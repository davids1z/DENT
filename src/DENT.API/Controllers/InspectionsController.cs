using DENT.Application.Commands.CreateInspection;
using DENT.Application.Commands.DeleteInspection;
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
    [RequestSizeLimit(50_000_000)] // 50MB
    public async Task<IActionResult> Create(IFormFile image, CancellationToken ct)
    {
        if (image is null || image.Length == 0)
            return BadRequest(new { error = "No image provided" });

        var allowedTypes = new[] { "image/jpeg", "image/png", "image/webp", "image/heic" };
        if (!allowedTypes.Contains(image.ContentType.ToLower()))
            return BadRequest(new { error = "Invalid image type. Supported: JPEG, PNG, WebP, HEIC" });

        using var stream = new MemoryStream();
        await image.CopyToAsync(stream, ct);
        stream.Position = 0;

        var result = await _mediator.Send(new CreateInspectionCommand
        {
            ImageStream = stream,
            FileName = image.FileName,
            ContentType = image.ContentType
        }, ct);

        return CreatedAtAction(nameof(GetById), new { id = result.Id }, result);
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
}
