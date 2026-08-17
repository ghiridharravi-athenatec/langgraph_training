// Pragmatic email shape check (not full RFC 5322) - same spirit as every other
// "looks like an email" validator: local-part @ domain-part . tld, no whitespace.
// Registration itself is still the source of truth (backend uses Pydantic's
// EmailStr) - this only gives the user an immediate, in-form error instead of a
// round-trip to find out "not-an-email" was rejected.
export const EMAIL_REGEX = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export function isValidEmail(email) {
  return EMAIL_REGEX.test(email.trim());
}
