/**
 * Checks for data that arrives over the network.
 *
 * TypeScript's types exist only while the code is compiled. A JSON response
 * from the server could hold anything, so its type is `unknown` until code
 * like this has checked it, field by field.
 */

export type JsonObject = Record<string, unknown>;

/** A plain JSON object: not null, and not an array. */
export function isObject(value: unknown): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** An array whose items are all strings. */
export function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}

/** An array of rows, where each row is an array of values. */
export function isRows(value: unknown): value is unknown[][] {
  return Array.isArray(value) && value.every((row) => Array.isArray(row));
}
