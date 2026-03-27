using DENT.Application.Validation;
using FluentAssertions;
using Xunit;

namespace DENT.Tests.Validation;

public class PasswordValidatorTests
{
    [Fact]
    public void Validate_TooShort_ReturnsFalse()
    {
        var (isValid, error) = PasswordValidator.Validate("Ab1!");
        isValid.Should().BeFalse();
        error.Should().Contain("8");
    }

    [Fact]
    public void Validate_NoUppercase_ReturnsFalse()
    {
        var (isValid, error) = PasswordValidator.Validate("abcdef1!");
        isValid.Should().BeFalse();
        error.Should().Contain("veliko slovo");
    }

    [Fact]
    public void Validate_NoLowercase_ReturnsFalse()
    {
        var (isValid, error) = PasswordValidator.Validate("ABCDEF1!");
        isValid.Should().BeFalse();
        error.Should().Contain("malo slovo");
    }

    [Fact]
    public void Validate_NoDigit_ReturnsFalse()
    {
        var (isValid, error) = PasswordValidator.Validate("Abcdefg!");
        isValid.Should().BeFalse();
        error.Should().Contain("znamenku");
    }

    [Fact]
    public void Validate_NoSpecialChar_ReturnsFalse()
    {
        var (isValid, error) = PasswordValidator.Validate("Abcdefg1");
        isValid.Should().BeFalse();
        error.Should().Contain("posebni znak");
    }

    [Fact]
    public void Validate_ValidPassword_ReturnsTrue()
    {
        var (isValid, error) = PasswordValidator.Validate("MyPass1!");
        isValid.Should().BeTrue();
        error.Should().BeNull();
    }

    [Fact]
    public void Validate_ComplexPassword_ReturnsTrue()
    {
        var (isValid, _) = PasswordValidator.Validate("C0mpl3x!P@ssw0rd");
        isValid.Should().BeTrue();
    }
}
