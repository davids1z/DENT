namespace DENT.Application.Interfaces;

public interface IWeatherService
{
    Task<WeatherData?> GetHistoricalWeatherAsync(double latitude, double longitude, DateTime date, CancellationToken ct = default);
}

public record WeatherData(
    double PrecipitationMm,
    double TempMax,
    double TempMin,
    int WeatherCode,
    string WeatherDescription,
    bool HadPrecipitation,
    bool HadHail
);
