namespace DENT.Application.Interfaces;

public interface IImageProcessingService
{
    byte[]? GenerateThumbnail(byte[] imageData, int maxWidth, int quality);
    string DeriveForensicCategory(MlForensicResult forensicResult);
}
