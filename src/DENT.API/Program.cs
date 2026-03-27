using System.Text;
using System.Threading.RateLimiting;
using DENT.API.Middleware;
using DENT.API.Services;
using DENT.Application.Interfaces;
using DENT.Application.Services;
using DENT.Domain.Entities;
using DENT.Infrastructure;
using DENT.Infrastructure.Data;
using Microsoft.AspNetCore.Authentication.JwtBearer;
using Microsoft.AspNetCore.RateLimiting;
using Microsoft.EntityFrameworkCore;
using Microsoft.IdentityModel.Tokens;

var builder = WebApplication.CreateBuilder(args);

// Infrastructure (DB, Storage, ML Client, Auth)
builder.Services.AddInfrastructure(builder.Configuration);

// MediatR
builder.Services.AddMediatR(cfg =>
    cfg.RegisterServicesFromAssembly(typeof(DENT.Application.Commands.CreateInspection.CreateInspectionCommand).Assembly));

// Controllers
builder.Services.AddControllers();
builder.Services.AddOpenApi();

// Global exception handler
builder.Services.AddExceptionHandler<GlobalExceptionHandler>();
builder.Services.AddProblemDetails();

// Background analysis queue (fair round-robin per user) + hosted service
builder.Services.AddSingleton<IAnalysisQueue, FairAnalysisQueue>();
builder.Services.AddHostedService<BackgroundAnalysisService>();

// JWT Authentication
var jwtSecret = builder.Configuration["Jwt:Secret"];
if (string.IsNullOrWhiteSpace(jwtSecret))
{
    if (builder.Environment.IsProduction())
        throw new InvalidOperationException(
            "FATAL: Jwt:Secret is not configured. Set the JWT_SECRET environment variable.");
    jwtSecret = "DENT-development-only-secret-do-not-use-in-production!";
}

builder.Services.AddAuthentication(JwtBearerDefaults.AuthenticationScheme)
    .AddJwtBearer(options =>
    {
        options.TokenValidationParameters = new TokenValidationParameters
        {
            ValidateIssuerSigningKey = true,
            IssuerSigningKey = new SymmetricSecurityKey(Encoding.UTF8.GetBytes(jwtSecret)),
            ValidateIssuer = true,
            ValidIssuer = builder.Configuration["Jwt:Issuer"] ?? "DENT",
            ValidateAudience = true,
            ValidAudience = builder.Configuration["Jwt:Audience"] ?? "DENT",
            ValidateLifetime = true,
            ClockSkew = TimeSpan.FromMinutes(1),
        };
        options.Events = new JwtBearerEvents
        {
            OnMessageReceived = context =>
            {
                var accessToken = context.Request.Query["access_token"];
                if (!string.IsNullOrEmpty(accessToken))
                    context.Token = accessToken;
                return Task.CompletedTask;
            }
        };
    });
builder.Services.AddAuthorization();

// Rate limiting (disabled in Development/test for integration tests)
if (!builder.Environment.IsDevelopment())
{
    builder.Services.AddRateLimiter(options =>
    {
        options.RejectionStatusCode = StatusCodes.Status429TooManyRequests;

        options.AddPolicy("auth", httpContext =>
            RateLimitPartition.GetFixedWindowLimiter(
                partitionKey: httpContext.Connection.RemoteIpAddress?.ToString() ?? "unknown",
                factory: _ => new FixedWindowRateLimiterOptions
                {
                    PermitLimit = 10,
                    Window = TimeSpan.FromMinutes(5),
                    QueueLimit = 0,
                }));

        options.AddPolicy("api", httpContext =>
            RateLimitPartition.GetFixedWindowLimiter(
                partitionKey: httpContext.Connection.RemoteIpAddress?.ToString() ?? "unknown",
                factory: _ => new FixedWindowRateLimiterOptions
                {
                    PermitLimit = 60,
                    Window = TimeSpan.FromMinutes(1),
                    QueueLimit = 2,
                }));
    });
}
else
{
    // No-op rate limiter for development/test
    builder.Services.AddRateLimiter(options =>
    {
        options.AddPolicy("auth", _ =>
            RateLimitPartition.GetNoLimiter("dev"));
        options.AddPolicy("api", _ =>
            RateLimitPartition.GetNoLimiter("dev"));
    });
}

// CORS
builder.Services.AddCors(options =>
{
    options.AddDefaultPolicy(policy =>
    {
        policy.WithOrigins(
                builder.Configuration.GetSection("Cors:Origins").Get<string[]>() ?? ["http://localhost:3000"])
            .AllowAnyHeader()
            .AllowAnyMethod();
    });
});

var app = builder.Build();

// Auto-migrate database + seed admin
using (var scope = app.Services.CreateScope())
{
    var db = scope.ServiceProvider.GetRequiredService<DentDbContext>();
    // MigrateAsync only works with relational providers (not InMemory for tests)
    if (db.Database.IsRelational())
        await db.Database.MigrateAsync();
    else
        await db.Database.EnsureCreatedAsync();

    var adminEmail = app.Configuration["Admin:Email"] ?? "admin@dent.hr";
    var adminPassword = app.Configuration["Admin:Password"];
    if (string.IsNullOrWhiteSpace(adminPassword))
    {
        if (app.Environment.IsProduction())
            throw new InvalidOperationException(
                "FATAL: Admin:Password is not configured. Set the ADMIN_PASSWORD environment variable.");
        adminPassword = "Admin123!";
    }

    if (!await db.Users.AnyAsync(u => u.Email == adminEmail))
    {
        db.Users.Add(new User
        {
            Id = Guid.NewGuid(),
            Email = adminEmail,
            PasswordHash = BCrypt.Net.BCrypt.HashPassword(adminPassword),
            FullName = "Administrator",
            Role = "Admin",
            CreatedAt = DateTime.UtcNow,
            IsActive = true,
        });
        await db.SaveChangesAsync();
    }

    var admin = await db.Users.FirstOrDefaultAsync(u => u.Email == adminEmail);
    if (admin is not null)
    {
        var orphaned = await db.Inspections.Where(i => i.UserId == null).ToListAsync();
        if (orphaned.Count > 0)
        {
            foreach (var insp in orphaned)
                insp.UserId = admin.Id;
            await db.SaveChangesAsync();
        }
    }
}

if (app.Environment.IsDevelopment())
{
    app.MapOpenApi();
}

app.UseExceptionHandler();
app.UseCors();
app.UseRateLimiter();
app.UseAuthentication();
app.UseAuthorization();
app.MapControllers();

app.MapGet("/api/health", (IAnalysisQueue queue) =>
{
    return Results.Ok(new
    {
        status = "healthy",
        service = "DENT API",
        timestamp = DateTime.UtcNow,
        queue = new
        {
            pending = queue.Count,
            activeUsers = queue.ActiveUserCount,
        }
    });
});

app.Run();

// Required for WebApplicationFactory in integration tests
public partial class Program { }
