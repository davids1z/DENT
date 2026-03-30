using System;
using Microsoft.EntityFrameworkCore.Migrations;
using Npgsql.EntityFrameworkCore.PostgreSQL.Metadata;

#nullable disable

namespace DENT.Infrastructure.Data.Migrations
{
    /// <inheritdoc />
    public partial class AddAuditEvents : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.CreateTable(
                name: "AuditEvents",
                columns: table => new
                {
                    Id = table.Column<long>(type: "bigint", nullable: false)
                        .Annotation("Npgsql:ValueGenerationStrategy", NpgsqlValueGenerationStrategy.IdentityAlwaysColumn),
                    Timestamp = table.Column<DateTime>(type: "timestamp with time zone", nullable: false),
                    EventType = table.Column<string>(type: "character varying(50)", maxLength: 50, nullable: false),
                    Category = table.Column<string>(type: "character varying(30)", maxLength: 30, nullable: false),
                    Method = table.Column<string>(type: "character varying(10)", maxLength: 10, nullable: true),
                    Path = table.Column<string>(type: "character varying(500)", maxLength: 500, nullable: true),
                    StatusCode = table.Column<int>(type: "integer", nullable: true),
                    DurationMs = table.Column<int>(type: "integer", nullable: true),
                    UserId = table.Column<Guid>(type: "uuid", nullable: true),
                    SessionId = table.Column<string>(type: "character varying(64)", maxLength: 64, nullable: true),
                    IpAddress = table.Column<string>(type: "character varying(45)", maxLength: 45, nullable: true),
                    UserAgent = table.Column<string>(type: "character varying(500)", maxLength: 500, nullable: true),
                    MetadataJson = table.Column<string>(type: "jsonb", nullable: true),
                    ResourceId = table.Column<Guid>(type: "uuid", nullable: true),
                    ResourceType = table.Column<string>(type: "character varying(50)", maxLength: 50, nullable: true)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_AuditEvents", x => x.Id);
                });

            migrationBuilder.CreateIndex(
                name: "IX_AuditEvents_Category_Timestamp",
                table: "AuditEvents",
                columns: new[] { "Category", "Timestamp" });

            migrationBuilder.CreateIndex(
                name: "IX_AuditEvents_EventType",
                table: "AuditEvents",
                column: "EventType");

            migrationBuilder.CreateIndex(
                name: "IX_AuditEvents_SessionId",
                table: "AuditEvents",
                column: "SessionId");

            migrationBuilder.CreateIndex(
                name: "IX_AuditEvents_Timestamp",
                table: "AuditEvents",
                column: "Timestamp");

            migrationBuilder.CreateIndex(
                name: "IX_AuditEvents_UserId",
                table: "AuditEvents",
                column: "UserId");
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropTable(
                name: "AuditEvents");
        }
    }
}
