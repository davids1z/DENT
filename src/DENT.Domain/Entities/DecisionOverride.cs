namespace DENT.Domain.Entities;

public class DecisionOverride
{
    public Guid Id { get; set; }
    public Guid InspectionId { get; set; }
    public string OriginalOutcome { get; set; } = string.Empty;
    public string NewOutcome { get; set; } = string.Empty;
    public string Reason { get; set; } = string.Empty;
    public string OperatorName { get; set; } = string.Empty;
    public DateTime CreatedAt { get; set; } = DateTime.UtcNow;

    public Inspection Inspection { get; set; } = null!;
}
