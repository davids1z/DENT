FROM mcr.microsoft.com/dotnet/sdk:9.0 AS build
WORKDIR /src

COPY DENT.Domain/DENT.Domain.csproj DENT.Domain/
COPY DENT.Shared/DENT.Shared.csproj DENT.Shared/
COPY DENT.Application/DENT.Application.csproj DENT.Application/
COPY DENT.Infrastructure/DENT.Infrastructure.csproj DENT.Infrastructure/
COPY DENT.API/DENT.API.csproj DENT.API/
RUN dotnet restore DENT.API/DENT.API.csproj

COPY . .
RUN dotnet publish DENT.API/DENT.API.csproj -c Release -o /app/publish

FROM mcr.microsoft.com/dotnet/aspnet:9.0
WORKDIR /app

RUN adduser --disabled-password --gecos "" appuser

COPY --from=build /app/publish .

# Install curl for health checks
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

USER appuser
EXPOSE 8080
ENV ASPNETCORE_URLS=http://+:8080
ENTRYPOINT ["dotnet", "DENT.API.dll"]
