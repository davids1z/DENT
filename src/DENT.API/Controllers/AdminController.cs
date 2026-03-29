using DENT.Application.Interfaces;
using DENT.Application.Queries.GetAdminStats;
using MediatR;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.RateLimiting;
using Microsoft.EntityFrameworkCore;

namespace DENT.API.Controllers;

[ApiController]
[Route("api/[controller]")]
[Authorize(Roles = "Admin")]
[EnableRateLimiting("api")]
public class AdminController : ControllerBase
{
    private readonly IDentDbContext _db;
    private readonly IMediator _mediator;

    public AdminController(IDentDbContext db, IMediator mediator)
    {
        _db = db;
        _mediator = mediator;
    }

    [HttpGet("stats")]
    public async Task<IActionResult> GetStats(CancellationToken ct)
    {
        var result = await _mediator.Send(new GetAdminStatsQuery(), ct);
        return Ok(result);
    }

    [HttpGet("users")]
    public async Task<IActionResult> GetUsers(CancellationToken ct)
    {
        var users = await _db.Users
            .AsNoTracking()
            .OrderByDescending(u => u.CreatedAt)
            .Select(u => new
            {
                u.Id,
                u.Email,
                u.FullName,
                u.Role,
                u.CreatedAt,
                u.LastLoginAt,
                u.IsActive,
                InspectionCount = u.Inspections.Count
            })
            .ToListAsync(ct);

        return Ok(users);
    }

    [HttpDelete("users/{id:guid}")]
    public async Task<IActionResult> DeactivateUser(Guid id, CancellationToken ct)
    {
        var user = await _db.Users.FirstOrDefaultAsync(u => u.Id == id, ct);
        if (user is null) return NotFound();
        if (user.Role == "Admin") return BadRequest(new { error = "Ne možete deaktivirati administratora." });

        user.IsActive = false;
        user.RefreshToken = null;
        await _db.SaveChangesAsync(ct);
        return NoContent();
    }

    [HttpPost("users/{id:guid}/activate")]
    public async Task<IActionResult> ActivateUser(Guid id, CancellationToken ct)
    {
        var user = await _db.Users.FirstOrDefaultAsync(u => u.Id == id, ct);
        if (user is null) return NotFound();

        user.IsActive = true;
        await _db.SaveChangesAsync(ct);
        return NoContent();
    }

    [HttpPatch("users/{id:guid}/role")]
    public async Task<IActionResult> ChangeRole(Guid id, [FromBody] ChangeRoleRequest request, CancellationToken ct)
    {
        if (request.Role is not ("Admin" or "User"))
            return BadRequest(new { error = "Uloga mora biti 'Admin' ili 'User'." });

        var user = await _db.Users.FirstOrDefaultAsync(u => u.Id == id, ct);
        if (user is null) return NotFound();

        user.Role = request.Role;
        await _db.SaveChangesAsync(ct);
        return NoContent();
    }
}

public record ChangeRoleRequest(string Role);
