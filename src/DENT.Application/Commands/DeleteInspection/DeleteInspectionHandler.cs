using DENT.Application.Interfaces;
using MediatR;
using Microsoft.EntityFrameworkCore;

namespace DENT.Application.Commands.DeleteInspection;

public class DeleteInspectionHandler : IRequestHandler<DeleteInspectionCommand, bool>
{
    private readonly IDentDbContext _db;
    private readonly IStorageService _storage;

    public DeleteInspectionHandler(IDentDbContext db, IStorageService storage)
    {
        _db = db;
        _storage = storage;
    }

    public async Task<bool> Handle(DeleteInspectionCommand request, CancellationToken ct)
    {
        var inspection = await _db.Inspections.FirstOrDefaultAsync(i => i.Id == request.Id, ct);
        if (inspection is null) return false;

        if (!string.IsNullOrEmpty(inspection.ImageUrl))
        {
            try { await _storage.DeleteAsync(inspection.ImageUrl, ct); }
            catch { /* Storage cleanup is best-effort */ }
        }

        _db.Inspections.Remove(inspection);
        await _db.SaveChangesAsync(ct);
        return true;
    }
}
