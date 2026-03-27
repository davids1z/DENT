using DENT.Application.Interfaces;
using SixLabors.ImageSharp;
using SixLabors.ImageSharp.Processing;

namespace DENT.Application.Services;

public class ImageProcessingService : IImageProcessingService
{
    public byte[]? GenerateThumbnail(byte[] imageData, int maxWidth, int quality)
    {
        try
        {
            using var image = Image.Load(imageData);
            if (image.Width <= maxWidth) return null;

            var ratio = (double)maxWidth / image.Width;
            var newHeight = (int)(image.Height * ratio);
            image.Mutate(x => x.Resize(maxWidth, newHeight));

            using var ms = new MemoryStream();
            image.SaveAsJpeg(ms, new SixLabors.ImageSharp.Formats.Jpeg.JpegEncoder { Quality = quality });
            return ms.ToArray();
        }
        catch
        {
            return null;
        }
    }

    public string DeriveForensicCategory(MlForensicResult forensicResult)
    {
        var categoryMap = new Dictionary<string, string>
        {
            ["ai_generation_detection"] = "AI generiranje",
            ["clip_ai_detection"] = "AI generiranje",
            ["vae_reconstruction"] = "AI generiranje",
            ["modification_detection"] = "Digitalna manipulacija",
            ["deep_modification_detection"] = "Digitalna manipulacija",
            ["spectral_forensics"] = "Spektralna anomalija",
            ["prnu_detection"] = "Sumnjiva tekstura",
            ["semantic_forensics"] = "Perspektivna anomalija",
            ["metadata_analysis"] = "Metadata anomalija",
        };

        var topModule = forensicResult.Modules
            .Where(m => m.RiskScore >= 0.40)
            .OrderByDescending(m => m.RiskScore)
            .FirstOrDefault();

        if (topModule != null && categoryMap.TryGetValue(topModule.ModuleName, out var category))
            return category;

        return "Metadata anomalija";
    }
}
