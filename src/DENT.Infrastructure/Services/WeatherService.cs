using System.Net.Http.Json;
using System.Text.Json;
using System.Text.Json.Serialization;
using DENT.Application.Interfaces;
using Microsoft.Extensions.Logging;

namespace DENT.Infrastructure.Services;

public class WeatherService : IWeatherService
{
    private readonly HttpClient _http;
    private readonly ILogger<WeatherService> _logger;

    public WeatherService(HttpClient http, ILogger<WeatherService> logger)
    {
        _http = http;
        _logger = logger;
    }

    public async Task<WeatherData?> GetHistoricalWeatherAsync(
        double latitude, double longitude, DateTime date, CancellationToken ct = default)
    {
        try
        {
            // Open-Meteo Archive API — free, no API key required
            var dateStr = date.ToString("yyyy-MM-dd");
            var url = $"https://archive-api.open-meteo.com/v1/archive" +
                      $"?latitude={latitude:F4}&longitude={longitude:F4}" +
                      $"&start_date={dateStr}&end_date={dateStr}" +
                      $"&daily=precipitation_sum,temperature_2m_max,temperature_2m_min,weathercode" +
                      $"&timezone=auto";

            _logger.LogDebug("Weather API call: {Url}", url);

            using var response = await _http.GetAsync(url, ct);
            if (!response.IsSuccessStatusCode)
            {
                _logger.LogWarning("Weather API returned {Status}", response.StatusCode);
                return null;
            }

            var json = await response.Content.ReadFromJsonAsync<OpenMeteoResponse>(
                new JsonSerializerOptions { PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower }, ct);

            if (json?.Daily == null || json.Daily.PrecipitationSum == null || json.Daily.PrecipitationSum.Count == 0)
            {
                _logger.LogDebug("Weather API returned empty daily data");
                return null;
            }

            var precip = json.Daily.PrecipitationSum[0] ?? 0;
            var tempMax = json.Daily.Temperature2mMax?.FirstOrDefault() ?? 0;
            var tempMin = json.Daily.Temperature2mMin?.FirstOrDefault() ?? 0;
            var code = json.Daily.Weathercode?.FirstOrDefault() ?? 0;

            var description = WmoCodeToDescription(code);
            var hadPrecipitation = precip > 0.5; // > 0.5mm = meaningful precipitation
            var hadHail = code >= 96 && code <= 99; // WMO codes 96-99 = thunderstorm with hail

            _logger.LogInformation(
                "Weather for ({Lat:F2}, {Lon:F2}) on {Date}: {Desc}, {Precip}mm, {TMin}-{TMax}°C",
                latitude, longitude, dateStr, description, precip, tempMin, tempMax);

            return new WeatherData(precip, tempMax, tempMin, code, description, hadPrecipitation, hadHail);
        }
        catch (TaskCanceledException)
        {
            return null;
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Weather API call failed for ({Lat}, {Lon}) on {Date}",
                latitude, longitude, date);
            return null;
        }
    }

    private static string WmoCodeToDescription(int code) => code switch
    {
        0 => "Vedro",
        1 => "Pretežno vedro",
        2 => "Djelomično oblačno",
        3 => "Oblačno",
        45 or 48 => "Magla",
        51 or 53 or 55 => "Sitna kiša",
        56 or 57 => "Ledena sitna kiša",
        61 or 63 or 65 => "Kiša",
        66 or 67 => "Ledena kiša",
        71 or 73 or 75 => "Snijeg",
        77 => "Snježna zrna",
        80 or 81 or 82 => "Pljusak",
        85 or 86 => "Snježni pljusak",
        95 => "Grmljavina",
        96 or 99 => "Grmljavina s tučom",
        _ => $"WMO kod {code}",
    };
}

// Open-Meteo API response models
file class OpenMeteoResponse
{
    [JsonPropertyName("daily")]
    public OpenMeteoDailyData? Daily { get; set; }
}

file class OpenMeteoDailyData
{
    [JsonPropertyName("precipitation_sum")]
    public List<double?>? PrecipitationSum { get; set; }

    [JsonPropertyName("temperature_2m_max")]
    public List<double?>? Temperature2mMax { get; set; }

    [JsonPropertyName("temperature_2m_min")]
    public List<double?>? Temperature2mMin { get; set; }

    [JsonPropertyName("weathercode")]
    public List<int?>? Weathercode { get; set; }
}
