using System.Text;
using DENT.Application.Interfaces;
using DENT.Domain.Entities;
using DENT.Infrastructure;
using DENT.Infrastructure.Data;
using Microsoft.AspNetCore.Authentication.JwtBearer;
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

// JWT Authentication
var jwtSecret = builder.Configuration["Jwt:Secret"] ?? "DENT-default-secret-change-in-production-min32chars!";
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
        // Support access_token query parameter for file download links
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

// CORS - allow frontend
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
    await db.Database.MigrateAsync();

    // Seed admin user if not exists
    var adminEmail = app.Configuration["Admin:Email"] ?? "admin@dent.hr";
    var adminPassword = app.Configuration["Admin:Password"] ?? "Admin123!";
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

    // Assign orphaned inspections (UserId=NULL) to admin
    var admin = await db.Users.FirstOrDefaultAsync(u => u.Email == adminEmail);
    if (admin is not null)
    {
        var orphaned = await db.Inspections.Where(i => i.UserId == null).CountAsync();
        if (orphaned > 0)
        {
            await db.Inspections.Where(i => i.UserId == null)
                .ExecuteUpdateAsync(s => s.SetProperty(i => i.UserId, admin.Id));
        }
    }
}

if (app.Environment.IsDevelopment())
{
    app.MapOpenApi();
}

app.UseCors();
app.UseAuthentication();
app.UseAuthorization();
app.MapControllers();

// Health check
app.MapGet("/api/health", () => Results.Ok(new { status = "healthy", service = "DENT API", timestamp = DateTime.UtcNow }));

app.Run();
