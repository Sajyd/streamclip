// Display hints only: the API enforces the real rules (GET /api/v1/meta).
export const PASSWORD_MIN_LENGTH = 10;

export const SUPPORTED_TIME_ZONES = [
  "Europe/Paris",
  "Europe/Brussels",
  "Europe/Zurich",
  "Europe/Luxembourg",
  "Europe/London",
  "Europe/Madrid",
  "Europe/Berlin",
  "Europe/Rome",
  "Africa/Casablanca",
  "Africa/Tunis",
  "Africa/Algiers",
  "Africa/Dakar",
  "Africa/Abidjan",
  "America/Toronto",
  "America/New_York",
  "America/Los_Angeles",
  "America/Guadeloupe",
  "America/Martinique",
  "Indian/Reunion",
  "Pacific/Noumea",
  "Pacific/Tahiti",
  "UTC",
] as const;
