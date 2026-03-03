namespace DENT.Domain.Entities;

public class InspectionImage
{
    public Guid Id { get; set; }
    public Guid InspectionId { get; set; }
    public string ImageUrl { get; set; } = string.Empty;
    public string OriginalFileName { get; set; } = string.Empty;
    public int SortOrder { get; set; }
    public DateTime CreatedAt { get; set; } = DateTime.UtcNow;

    public Inspection Inspection { get; set; } = null!;
}
