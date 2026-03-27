namespace DENT.Application.Validation;

public static class PasswordValidator
{
    public const int MinLength = 8;

    public static (bool IsValid, string? Error) Validate(string password)
    {
        if (password.Length < MinLength)
            return (false, $"Lozinka mora imati najmanje {MinLength} znakova.");

        if (!password.Any(char.IsUpper))
            return (false, "Lozinka mora sadržavati barem jedno veliko slovo.");

        if (!password.Any(char.IsLower))
            return (false, "Lozinka mora sadržavati barem jedno malo slovo.");

        if (!password.Any(char.IsDigit))
            return (false, "Lozinka mora sadržavati barem jednu znamenku.");

        if (!password.Any(c => !char.IsLetterOrDigit(c)))
            return (false, "Lozinka mora sadržavati barem jedan posebni znak (!@#$%...).");

        return (true, null);
    }
}
