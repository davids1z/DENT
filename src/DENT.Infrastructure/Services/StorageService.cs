using Amazon.S3;
using Amazon.S3.Model;
using DENT.Application.Interfaces;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.Logging;

namespace DENT.Infrastructure.Services;

public class StorageService : IStorageService
{
    private readonly IAmazonS3 _s3Client;
    private readonly string _bucketName;
    private readonly string _publicUrl;
    private readonly ILogger<StorageService> _logger;

    public StorageService(IAmazonS3 s3Client, IConfiguration config, ILogger<StorageService> logger)
    {
        _s3Client = s3Client;
        _bucketName = config["Storage:BucketName"] ?? "dent-images";
        _publicUrl = config["Storage:PublicUrl"] ?? "http://localhost:9000/dent-images";
        _logger = logger;
    }

    public async Task<string> UploadAsync(Stream stream, string fileName, string contentType, CancellationToken ct = default)
    {
        var key = $"inspections/{DateTime.UtcNow:yyyy/MM/dd}/{Guid.NewGuid()}{Path.GetExtension(fileName)}";

        var request = new PutObjectRequest
        {
            BucketName = _bucketName,
            Key = key,
            InputStream = stream,
            ContentType = contentType,
            CannedACL = S3CannedACL.PublicRead
        };

        await _s3Client.PutObjectAsync(request, ct);
        _logger.LogInformation("Uploaded {Key} to S3", key);

        return key;
    }

    public async Task DeleteAsync(string fileKey, CancellationToken ct = default)
    {
        await _s3Client.DeleteObjectAsync(_bucketName, fileKey, ct);
        _logger.LogInformation("Deleted {Key} from S3", fileKey);
    }

    public string GetPublicUrl(string key) => $"{_publicUrl.TrimEnd('/')}/{key}";
}
